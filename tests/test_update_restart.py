import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import scheduler_launcher as launcher


class AppendedLogMarkerWatcherTests(unittest.TestCase):
    def test_ignores_existing_marker_and_detects_fragmented_append(self):
        marker = "游戏更新成功, 游戏即将重启"
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "ok-script.log"
            log_path.write_text(marker + "\n", encoding="utf-8")
            watcher = launcher.AppendedLogMarkerWatcher(log_path, marker)

            self.assertFalse(watcher.poll())
            marker_bytes = marker.encode("utf-8")
            with log_path.open("ab") as log_file:
                log_file.write(marker_bytes[:9])
            self.assertFalse(watcher.poll())
            with log_path.open("ab") as log_file:
                log_file.write(marker_bytes[9:] + b"\n")
            self.assertTrue(watcher.poll())

    def test_detects_marker_after_log_rotation(self):
        marker = "游戏更新成功, 游戏即将重启"
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "ok-script.log"
            rotated_path = Path(temp_dir) / "ok-script.log.1"
            log_path.write_text("旧日志内容足够长\n" * 10, encoding="utf-8")
            watcher = launcher.AppendedLogMarkerWatcher(log_path, marker)

            log_path.replace(rotated_path)
            log_path.write_text(marker + "\n", encoding="utf-8")

            self.assertTrue(watcher.poll())


class WaitForProcessExitTests(unittest.TestCase):
    def test_early_exit_still_observes_minimum_wait(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executable_path = Path(temp_dir) / "MAA.exe"
            executable_path.touch()
            current_time = 0.0
            process_checks = 0

            def monotonic():
                return current_time

            def wait_interruptibly(seconds):
                nonlocal current_time
                current_time += seconds

            def find_processes(_path):
                nonlocal process_checks
                process_checks += 1
                if process_checks == 1:
                    return [{"pid": 101, "path": str(executable_path)}]
                return []

            with mock.patch.object(
                launcher, "find_processes_by_path", side_effect=find_processes
            ), mock.patch.object(
                launcher, "wait_interruptibly", side_effect=wait_interruptibly
            ), mock.patch.object(
                launcher.time, "monotonic", side_effect=monotonic
            ), mock.patch.object(launcher, "check_stop_requested"):
                completed = launcher.wait_for_process_exit(
                    executable_path=str(executable_path),
                    start_timeout=60,
                    exit_timeout=900,
                    stable_seconds=0,
                    minimum_wait=60,
                    timeout_is_error=False,
                )

            self.assertTrue(completed)
            self.assertEqual(current_time, 60)

    def test_non_error_timeout_allows_following_close_step(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executable_path = Path(temp_dir) / "MAA.exe"
            executable_path.touch()
            current_time = 0.0

            def monotonic():
                return current_time

            def wait_interruptibly(seconds):
                nonlocal current_time
                current_time += seconds

            running_process = [{"pid": 101, "path": str(executable_path)}]
            with mock.patch.object(
                launcher,
                "find_processes_by_path",
                return_value=running_process,
            ), mock.patch.object(
                launcher, "wait_interruptibly", side_effect=wait_interruptibly
            ), mock.patch.object(
                launcher.time, "monotonic", side_effect=monotonic
            ), mock.patch.object(launcher, "check_stop_requested"):
                completed = launcher.wait_for_process_exit(
                    executable_path=str(executable_path),
                    start_timeout=60,
                    exit_timeout=15,
                    stable_seconds=0,
                    minimum_wait=1,
                    timeout_is_error=False,
                )

            self.assertFalse(completed)
            self.assertEqual(current_time, 15)

    def test_update_restart_relaunches_once_then_waits_for_final_exit(self):
        marker = "游戏更新成功, 游戏即将重启"
        with tempfile.TemporaryDirectory() as temp_dir:
            executable_path = Path(temp_dir) / "Client-Win64-Shipping.exe"
            executable_path.touch()
            log_path = Path(temp_dir) / "ok-script.log"
            log_path.write_text(marker + "\n", encoding="utf-8")

            process_states = [
                [{"pid": 101, "path": str(executable_path)}],
                [{"pid": 101, "path": str(executable_path)}],
                [],
                [{"pid": 202, "path": str(executable_path)}],
                [{"pid": 202, "path": str(executable_path)}],
                [],
            ]
            call_count = 0

            def find_processes(_path):
                nonlocal call_count
                state = process_states[call_count]
                call_count += 1
                if call_count == 2:
                    with log_path.open("a", encoding="utf-8") as log_file:
                        log_file.write(marker + "\n")
                return state

            restarted = []

            def restart_callback():
                restarted.append(True)
                return mock.Mock(pid=303)

            with mock.patch.object(
                launcher, "find_processes_by_path", side_effect=find_processes
            ), mock.patch.object(launcher, "wait_interruptibly"), mock.patch.object(
                launcher, "check_stop_requested"
            ):
                launcher.wait_for_process_exit(
                    executable_path=str(executable_path),
                    start_timeout=60,
                    exit_timeout=60,
                    stable_seconds=0,
                    restart_policy={
                        "log_path": log_path,
                        "marker": marker,
                        "max_restarts": 1,
                        "restart_timeout": 30,
                        "restart_stable": 0,
                    },
                    restart_callback=restart_callback,
                )

            self.assertEqual(len(restarted), 1)
            self.assertEqual(call_count, len(process_states))

    def test_normal_exit_does_not_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executable_path = Path(temp_dir) / "Client-Win64-Shipping.exe"
            executable_path.touch()
            log_path = Path(temp_dir) / "ok-script.log"
            log_path.touch()
            process_states = [
                [{"pid": 101, "path": str(executable_path)}],
                [],
            ]

            with mock.patch.object(
                launcher,
                "find_processes_by_path",
                side_effect=process_states,
            ), mock.patch.object(launcher, "wait_interruptibly"), mock.patch.object(
                launcher, "check_stop_requested"
            ):
                restart_callback = mock.Mock()
                launcher.wait_for_process_exit(
                    executable_path=str(executable_path),
                    start_timeout=60,
                    exit_timeout=60,
                    stable_seconds=0,
                    restart_policy={
                        "log_path": log_path,
                        "marker": "游戏更新成功, 游戏即将重启",
                        "max_restarts": 1,
                        "restart_timeout": 30,
                        "restart_stable": 0,
                    },
                    restart_callback=restart_callback,
                )

            restart_callback.assert_not_called()


class WorkflowRestartConfigurationTests(unittest.TestCase):
    def test_restart_callback_reuses_original_arguments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            okww_path = temp_path / "ok-ww.exe"
            client_path = temp_path / "Client-Win64-Shipping.exe"
            okww_path.touch()
            client_path.touch()

            task = {
                "name": "测试流程",
                "steps": [
                    {
                        "type": "launch",
                        "name": "ok-ww",
                        "path": str(okww_path),
                        "args": ["-t", "1", "-e"],
                        "working_dir": str(temp_path),
                        "save_as": "OKWW",
                    },
                    {
                        "type": "wait_process_exit",
                        "path": str(client_path),
                        "requires": ["OKWW"],
                        "start_timeout": "00:10:00",
                        "exit_timeout": "00:30:00",
                        "after_exit": "00:00:10",
                        "restart_on_log": {
                            "target": "OKWW",
                            "relative_log_path": "data\\apps\\ok-ww\\working\\logs\\ok-script.log",
                            "marker": "游戏更新成功, 游戏即将重启",
                            "max_restarts": 1,
                            "restart_timeout": "00:05:00",
                            "restart_stable": "00:00:05",
                        },
                    },
                ],
            }
            launched_tasks = []

            def launch_program(launch_task):
                launched_tasks.append(dict(launch_task))
                return mock.Mock(pid=100 + len(launched_tasks))

            captured_policy = {}

            def wait_for_process_exit(**kwargs):
                captured_policy.update(kwargs["restart_policy"])
                self.assertIsNotNone(kwargs["restart_callback"]())

            with mock.patch.object(
                launcher, "launch_program", side_effect=launch_program
            ), mock.patch.object(
                launcher,
                "wait_for_process_exit",
                side_effect=wait_for_process_exit,
            ), mock.patch.object(launcher, "check_stop_requested"):
                launcher.run_workflow(task)

            self.assertEqual(len(launched_tasks), 2)
            self.assertEqual(launched_tasks[0], launched_tasks[1])
            self.assertEqual(launched_tasks[1]["args"], ["-t", "1", "-e"])
            self.assertEqual(captured_policy["max_restarts"], 1)
            self.assertEqual(captured_policy["restart_timeout"], 300)
            self.assertEqual(captured_policy["restart_stable"], 5)
            self.assertEqual(
                captured_policy["log_path"],
                (
                    temp_path
                    / "data"
                    / "apps"
                    / "ok-ww"
                    / "working"
                    / "logs"
                    / "ok-script.log"
                ).resolve(),
            )

    def test_close_step_uses_configured_path_for_remaining_instances(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executable_path = Path(temp_dir) / "MAA.exe"
            executable_path.touch()
            task = {
                "name": "MAA 关闭测试",
                "steps": [
                    {
                        "type": "launch",
                        "name": "MAA",
                        "path": str(executable_path),
                        "args": [],
                        "working_dir": str(executable_path.parent),
                        "save_as": "MAA",
                    },
                    {
                        "type": "close",
                        "target": "MAA",
                        "path": str(executable_path),
                        "force_close": True,
                    },
                ],
            }
            launched = mock.Mock(pid=101)

            with mock.patch.object(
                launcher, "launch_program", return_value=launched
            ), mock.patch.object(
                launcher,
                "find_processes_by_path",
                return_value=[{"pid": 202, "path": str(executable_path)}],
            ), mock.patch.object(
                launcher, "close_process", return_value=True
            ) as close_process, mock.patch.object(
                launcher, "check_stop_requested"
            ):
                launcher.run_workflow(task)

            close_process.assert_called_once_with(202, force=True)


if __name__ == "__main__":
    unittest.main()
