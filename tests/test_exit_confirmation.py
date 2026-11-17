import unittest
import hashlib
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import scheduler_launcher as launcher


class ExitConfirmationTests(unittest.TestCase):
    def run_check(self, states, deadline=100, stop=None):
        now = [0.0]
        tracker = mock.Mock()
        tracker.current.side_effect = states
        monitor = mock.Mock(deadline=deadline)
        def wait(seconds):
            now[0] += seconds
        with mock.patch.object(launcher.time, "monotonic", side_effect=lambda: now[0]), \
                mock.patch.object(launcher, "wait_interruptibly", side_effect=wait), \
                mock.patch.object(launcher, "check_stop_requested", side_effect=stop), \
                mock.patch.object(launcher, "log_info"), \
                mock.patch.object(launcher, "execute_key_action") as keys, \
                mock.patch.object(launcher, "close_process") as close:
            launcher.confirm_tool_exit("March7th", tracker, monitor)
            keys.assert_not_called()
            close.assert_not_called()
        return now[0]

    def test_already_exited_has_no_delay(self):
        self.assertEqual(self.run_check([[]]), 0)

    def test_slow_exit_is_reconciled_without_another_key_or_close(self):
        self.assertAlmostEqual(self.run_check([[{"pid": 1}]] * 18 + [[]]), 3.6)

    def test_alive_after_grace_still_blocks_next_tool(self):
        with self.assertRaisesRegex(RuntimeError, "仍未退出"):
            self.run_check([[{"pid": 1}]] * 100)

    def test_stage_budget_is_not_extended(self):
        with self.assertRaisesRegex(RuntimeError, "仍未退出"):
            self.run_check([[{"pid": 1}]] * 100, deadline=.5)

    def test_stop_is_honored(self):
        with self.assertRaisesRegex(RuntimeError, "stopped"):
            self.run_check([[{"pid": 1}]], stop=RuntimeError("stopped"))

    def test_failure_records_survivor_pid(self):
        with self.assertRaisesRegex(RuntimeError, r"PID=\[123\]"):
            self.run_check([[{"pid": 123}]] * 100, deadline=.2)

    def test_permission_error_is_not_treated_as_exit(self):
        with self.assertRaisesRegex(RuntimeError, "无法监测"):
            self.run_check([RuntimeError("无法监测进程身份")])


class WorkflowExitConfirmationTests(unittest.TestCase):
    def run_scenario(self, exit_at, budget=100):
        """Exercise the real wait-step integration, not only the helper."""
        now = [0.0]
        task = {"name": "exit regression", "steps": [
            {"type": "launch", "name": "assistant", "save_as": "March7th",
             "setup_key": "march7th", "path": "assistant.exe"},
            {"type": "key", "target": "March7th", "keys": ["enter"]},
            {"type": "wait", "duration": "00:00:05", "requires": ["March7th"]},
            {"type": "launch", "name": "next", "save_as": "next", "path": "next.exe"},
        ]}
        tracker = mock.Mock()
        tracker.current.side_effect = lambda: (
            [{"pid": 101, "create_time": 123}] if now[0] < exit_at else [])
        monitor = mock.Mock(profile="march7th", state="SUCCEEDED", deadline=budget)
        status = mock.Mock(data={"stages": {"March7th": {"state": "SUCCEEDED"}}})
        launched_at = []
        def launch(spec):
            launched_at.append((spec["name"], now[0]))
            return mock.Mock(pid=101 if spec["name"] == "assistant" else 202)
        def wait(seconds):
            now[0] += seconds
        with ExitStack() as stack:
            replacements = {
                "ToolProcesses": mock.Mock(return_value=tracker),
                "Stage": mock.Mock(return_value=monitor),
                "RunStatus": mock.Mock(return_value=status),
                "find_processes_by_path": mock.Mock(return_value=[]),
                "launch_program": mock.Mock(side_effect=launch),
                "execute_key_action": mock.Mock(return_value=True),
                "check_stop_requested": mock.Mock(),
                "wait_interruptibly": mock.Mock(side_effect=wait),
                "is_process_running": mock.Mock(return_value=False),
                "close_configured_processes": mock.Mock(),
                "log_info": mock.Mock(), "log_warning": mock.Mock(),
            }
            for name, replacement in replacements.items():
                stack.enter_context(mock.patch.object(launcher, name, replacement))
            stack.enter_context(mock.patch.object(launcher.time, "monotonic", side_effect=lambda: now[0]))
            error = None
            try:
                launcher.run_workflow(task)
            except RuntimeError as caught:
                error = caught
            replacements["execute_key_action"].assert_called_once()
        return launched_at, now[0], error

    def test_exit_just_after_five_seconds_continues_without_second_enter(self):
        launches, elapsed, error = self.run_scenario(exit_at=5.3)
        self.assertIsNone(error)
        self.assertEqual([name for name, _ in launches], ["assistant", "next"])
        self.assertGreaterEqual(launches[1][1], 5.3)
        self.assertLess(elapsed, 6)

    def test_real_survivor_blocks_next_program_after_bounded_grace(self):
        launches, elapsed, error = self.run_scenario(exit_at=50)
        self.assertRegex(str(error), "仍未退出")
        self.assertEqual([name for name, _ in launches], ["assistant"])
        self.assertAlmostEqual(elapsed, 15)

    def test_wait_step_does_not_extend_stage_budget(self):
        launches, elapsed, error = self.run_scenario(exit_at=50, budget=6)
        self.assertRegex(str(error), "仍未退出")
        self.assertEqual(len(launches), 1)
        self.assertAlmostEqual(elapsed, 6)


class RuntimeCodeIdentityTests(unittest.TestCase):
    def test_fingerprints_only_code_not_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = b"# test implementation\n"
            for name in ("scheduler_launcher.py", "supervision.py", "maaend_startup.py"):
                (root / name).write_bytes(payload)
            (root / "tasks.json").write_text("private-test-sentinel", encoding="utf-8")
            with mock.patch.object(launcher, "BASE_DIR", root), \
                    mock.patch.object(launcher, "log_info") as log:
                launcher.log_runtime_code_identity()
            messages = str(log.call_args_list)
            self.assertIn(hashlib.sha256(payload).hexdigest(), messages)
            self.assertNotIn("private-test-sentinel", messages)
            self.assertEqual(log.call_count, 4)

    def test_unavailable_code_fingerprint_is_nonfatal_and_redacted(self):
        with mock.patch.object(Path, "read_bytes", side_effect=OSError("private-path")), \
                mock.patch.object(launcher, "log_info"), \
                mock.patch.object(launcher, "log_warning") as log:
            launcher.log_runtime_code_identity()
        self.assertEqual(log.call_count, 3)
        self.assertNotIn("private-path", str(log.call_args_list))


if __name__ == "__main__":
    unittest.main()
