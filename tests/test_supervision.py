import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from supervision import IncrementalLogs, RunStatus, Signals, Stage, identity
import scheduler_launcher as launcher


class LogTests(unittest.TestCase):
    def test_old_success_ignored_split_utf8_and_new_log_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = root / "old.log"
            old.write_text("任务已全部完成！\n", encoding="utf-8")
            logs = IncrementalLogs(root, ("*.log",))
            self.assertEqual(logs.poll(), [])
            data = "任务已全部完成！\n".encode()
            with old.open("ab") as f:
                f.write(data[:5])
            self.assertEqual(logs.poll(), [])
            with old.open("ab") as f:
                f.write(data[5:])
            self.assertEqual(logs.poll(), ["任务已全部完成！"])
            old.unlink()
            (root / "new.log").write_text("本轮开始\n", encoding="utf-8")
            self.assertEqual(logs.poll(), ["本轮开始"])

    def test_rotation_and_truncation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "current.log"
            path.write_text("old\n" * 20, encoding="utf-8")
            logs = IncrementalLogs(root, ("*.log",))
            path.replace(root / "current.bak")
            path.write_text("new\n", encoding="utf-8")
            self.assertEqual(logs.poll(), ["new"])
            path.write_text("x\n", encoding="utf-8")
            self.assertEqual(logs.poll(), ["x"])

    def test_renamed_old_log_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "current.log"
            path.write_text("old success\n", encoding="utf-8")
            logs = IncrementalLogs(root, ("*.log",))
            path.replace(root / "rotated.log")
            path.write_text("new run\n", encoding="utf-8")
            self.assertEqual(logs.poll(), ["new run"])


class SignalTests(unittest.TestCase):
    def test_maaend_requires_all_submitted_root_tasks(self):
        s = Signals("maaend")
        s.consume("任务已提交, taskIds: [1, 2]")
        s.consume('[msg=Node.Recognition.Failed] [details={"task_id":1}]')
        self.assertFalse(s.failure)
        s.consume('[msg=Tasker.Task.Succeeded] [details={"task_id":1}]')
        s.consume('[msg=Tasker.Task.Succeeded] [details={"task_id":1}]')
        self.assertFalse(s.success)
        s.consume('[msg=Tasker.Task.Succeeded] [details={"task_id":2}]')
        self.assertTrue(s.success)

    def test_maaend_failed_root_is_not_success(self):
        s = Signals("maaend")
        s.consume("任务已提交, task_ids: [3]")
        s.consume('[msg=Tasker.Task.Failed] [details={"task_id":3}]')
        self.assertTrue(s.failure)

    def test_one_dragon_subgroup_not_entire_multi_account_success(self):
        s = Signals("onedragon")
        s.consume("指令[ 执行应用组 one_dragon ] 执行成功 返回状态 全部结束")
        self.assertFalse(s.success)
        s.consume("指令[ 一条龙 ] 执行成功 返回状态 全部结束")
        self.assertTrue(s.success)

    def test_checking_updates_is_not_updating(self):
        s = Signals("maaend")
        s.consume("更新检查完成: 有更新=false")
        self.assertFalse(s.updating)

    def test_bettergi_intentional_exit_not_false_full_success(self):
        s = Signals("bettergi")
        s.consume('配置组 "退出" 执行结束')
        s.consume("任务被取消，退出执行")
        self.assertFalse(s.failure)
        self.assertFalse(s.success)

    def test_march7th_requires_full_banner_and_game_termination(self):
        s = Signals("march7th")
        s.consume("--- 邮件奖励完成 ---")
        s.consume("游戏终止：StarRail")
        self.assertFalse(s.success)
        s.consume("------ 完成 ------")
        s.consume("游戏终止：StarRail")
        self.assertTrue(s.success)


class StageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = 0
        self.tools = [{"pid": 1, "create_time": 1}]
        self.games = [{"pid": 10, "create_time": 10}]
        self.relaunches = 0
        self.key_calls = 0
        self.clock = mock.patch("supervision.time.monotonic", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.status = RunStatus(self.root / "status.json")

    def stage(self, profile="okww", budget=100):
        def relaunch():
            self.relaunches += 1
            self.tools = [{"pid": 2, "create_time": 2}]
            return mock.Mock(pid=2)

        def key(_action, _tools):
            self.key_calls += 1
            return True

        return Stage("test", profile, {"path": str(self.root / "tool.exe"),
                    "working_dir": str(self.root), "args": ["-t", "1", "-e"]},
                    budget, self.status, {
                        "tools": lambda: self.tools, "scan": lambda _p: self.games,
                        "relaunch": relaunch, "key": key, "wait": self.wait,
                        "check": lambda: None, "info": lambda _: None,
                        "warn": lambda _: None})

    def wait(self, seconds):
        self.now += seconds

    def test_game_update_restart_preserves_hard_deadline(self):
        s = self.stage()
        s.poll("game.exe")
        s.signals.consume("游戏更新成功, 游戏即将重启")
        self.tools = []
        self.games = []
        self.now = 10
        s.poll("game.exe")
        self.games = [{"pid": 11, "create_time": 11}]
        self.now = 15
        s.poll("game.exe")
        self.now = 25
        s.poll("game.exe")
        self.assertEqual(self.relaunches, 1)
        self.assertEqual(s.deadline, 100)
        self.now = 26
        s.poll("game.exe")
        self.assertFalse(s.signals.updating)
        self.assertEqual(s.recoveries, 1)

    def test_update_not_relaunched_while_old_tool_still_running(self):
        s = self.stage()
        s.poll("game.exe")
        s.signals.consume("游戏更新成功, 游戏即将重启")
        self.games = [{"pid": 11, "create_time": 11}]
        s.poll("game.exe")
        self.now = 20
        s.poll("game.exe")
        self.assertEqual(self.relaunches, 0)

    def test_game_replacement_stability_resets_for_another_pid(self):
        s = self.stage()
        s.poll("game.exe")
        s.signals.consume("游戏更新成功, 游戏即将重启")
        self.tools = []
        s.poll("game.exe")
        self.now = 15
        self.games = [{"pid": 11, "create_time": 11}]
        s.poll("game.exe")
        self.now = 19
        self.games = [{"pid": 12, "create_time": 12}]
        s.poll("game.exe")
        self.now = 20
        s.poll("game.exe")
        self.assertEqual(self.relaunches, 0)
        self.now = 24
        s.poll("game.exe")
        self.assertEqual(self.relaunches, 1)

    def test_self_update_adopts_new_tool_without_duplicate_launch(self):
        s = self.stage("maaend")
        s.poll()
        s.signals.consume("更新完成")
        self.tools = [{"pid": 2, "create_time": 2}]
        self.now = 5
        s.poll()
        self.assertEqual(s.recoveries, 1)
        self.assertEqual(self.relaunches, 0)
        self.assertEqual(s.deadline, 100)
        self.tools = [{"pid": 3, "create_time": 3}]
        with self.assertRaisesRegex(RuntimeError, "上限"):
            s.poll()

    def test_new_generation_start_marker_not_lost_in_same_poll(self):
        s = self.stage("maaend")
        s.poll()
        self.tools = [{"pid": 2, "create_time": 2}]
        with mock.patch.object(s.logs, "poll", return_value=["任务已提交, taskIds: [10]"]):
            s.poll()
        self.assertEqual(s.signals.expected, {10})
        s.send_start_key({"keys": ["f10"]})
        self.assertEqual(self.key_calls, 0)

    def test_expired_budget_never_relaunches_tool(self):
        s = self.stage(budget=20)
        s.poll()
        s.signals.consume("更新完成")
        self.tools = []
        self.now = 1
        s.poll()
        self.now = 25
        s.poll()
        self.assertEqual(self.relaunches, 0)

    def test_in_place_resource_update_does_not_require_process_restart(self):
        s = self.stage("maaend")
        s.signals.consume("资源更新完成")
        s.poll()
        self.assertTrue(s.signals.updating)
        self.now = 5
        s.poll()
        self.assertFalse(s.signals.updating)
        self.assertEqual(self.relaunches, 0)
        self.assertEqual(s.recoveries, 0)

    def test_crash_is_not_automatically_restarted(self):
        s = self.stage("maaend")
        s.poll()
        self.tools = []
        self.now = 1
        s.poll()
        self.now = 32
        with self.assertRaisesRegex(RuntimeError, "完成前退出"):
            s.wait_completion()
        self.assertEqual(self.relaunches, 0)

    def test_f10_not_sent_again_when_task_already_started(self):
        s = self.stage("maaend")
        s.signals.started = True
        s.send_start_key({"keys": ["f10"]})
        self.assertEqual(self.key_calls, 0)

    def test_f10_without_start_confirmation_not_repeated(self):
        s = self.stage("maaend", budget=1800)
        with self.assertRaisesRegex(RuntimeError, "120 秒"):
            s.send_start_key({"keys": ["f10"]})
        self.assertEqual(self.key_calls, 1)

    def test_initial_tool_update_can_take_longer_than_key_confirmation_timeout(self):
        s = self.stage("maaend", budget=1800)
        s.signals.consume("正在更新")
        def wait(seconds):
            self.now += seconds
            if self.now == 200:
                self.tools = [{"pid": 2, "create_time": 2}]
                s.signals.update_ready = True
            elif self.now == 201:
                s.signals.consume("任务已提交, taskIds: [10]")
        s.cb["wait"] = wait
        s.send_start_key({"keys": ["f10"]})
        self.assertEqual(self.now, 201)
        self.assertEqual(self.key_calls, 1)

    def test_timeout_during_update_does_not_reset_budget(self):
        s = self.stage(budget=20)
        s.signals.consume("正在更新")
        with self.assertRaisesRegex(RuntimeError, "总运行上限"):
            s.wait_exit("game.exe", 60, 10)
        self.assertEqual(self.now, 20)

    def test_maa_timeout_reported_not_succeeded(self):
        s = self.stage("maa", budget=5)
        self.assertFalse(s.wait_exit(str(self.root / "tool.exe"), 60, 0,
                                     timeout_is_error=False))
        self.assertEqual(s.state, "TIMED_OUT")

    def test_game_exit_without_marker_is_unverified(self):
        s = self.stage()
        def wait(seconds):
            self.now += seconds
            self.games = []
        s.cb["wait"] = wait
        self.assertTrue(s.wait_exit("game.exe", 60, 10))
        self.assertEqual(s.state, "UNVERIFIED_EXIT")
        self.assertEqual(self.now, 11)

    def test_maaend_waits_for_completion_not_just_task_submission(self):
        s = self.stage("maaend")
        s.signals.consume("任务已提交, task_ids: [1, 2]")
        def wait(seconds):
            self.now += seconds
            s.signals.consume('[msg=Tasker.Task.Succeeded] [details={"task_id":%d}]' % self.now)
        s.cb["wait"] = wait
        s.wait_completion()
        self.assertEqual(self.now, 2)
        self.assertEqual(s.state, "SUCCEEDED")


class CleanupTests(unittest.TestCase):
    def test_spawned_game_is_not_treated_as_still_running_tool(self):
        tool, game, crash = (mock.Mock() for _ in range(3))
        for pid, process, name in ((1, tool, "ok-ww.exe"),
                                  (2, game, "Client-Win64-Shipping.exe"),
                                  (3, crash, "CrashReporter.exe")):
            process.pid = pid
            process.create_time.return_value = pid
            process.name.return_value = name
            process.is_running.return_value = True
        tool.children.return_value = [game, crash]
        game.children.return_value = [crash]
        crash.children.return_value = []
        tracker = launcher.ToolProcesses("ok-ww.exe")
        tracker.known = {1: 1}
        with mock.patch.object(launcher, "find_processes_by_path", return_value=[]), \
             mock.patch.object(launcher.psutil, "Process", side_effect=lambda pid: {1: tool, 2: game, 3: crash}[pid]):
            self.assertEqual([p["pid"] for p in tracker.current()], [1])
            self.assertEqual({p["pid"] for p in tracker.current(include_games=True)}, {1, 2, 3})

    def test_preexisting_process_is_preserved(self):
        path = str(Path("old.exe").resolve())
        matches = [{"pid": 1, "create_time": 100}, {"pid": 2, "create_time": 200}]
        calls = 0
        def scan(_path):
            nonlocal calls
            calls += 1
            return matches if calls < 3 else matches[:1]
        with mock.patch.object(launcher, "find_processes_by_path", side_effect=scan), \
             mock.patch.object(launcher, "close_process", return_value=True) as close, \
             mock.patch.object(launcher.time, "sleep"):
            launcher.close_configured_processes([{"path": path}], {path: {(1, 100)}})
        self.assertEqual([c.args[0] for c in close.call_args_list], [2, 2])

    def test_pid_reuse_is_not_old_process(self):
        self.assertNotEqual(identity({"pid": 1, "create_time": 100}),
                            identity({"pid": 1, "create_time": 200}))


class WorkflowTests(unittest.TestCase):
    def test_local_maaend_configuration_automatically_gets_completion_supervision(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "MaaEnd.exe"
            path.touch()
            task = {"name": "test", "steps": [
                {"type": "launch", "setup_key": "maaend", "path": str(path), "save_as": "C"},
                {"type": "key", "target": "C", "keys": ["f10"]}]}
            with mock.patch.object(launcher, "find_processes_by_path", return_value=[]), \
                 mock.patch.object(launcher, "launch_program", return_value=mock.Mock(pid=1)), \
                 mock.patch.object(launcher, "ToolProcesses"), \
                 mock.patch.object(launcher, "Stage") as stage_class, \
                 mock.patch.object(launcher, "RunStatus") as status_class, \
                 mock.patch.object(launcher, "check_stop_requested"):
                stage = stage_class.return_value
                stage.profile = "maaend"
                stage.state = "RUNNING"
                stage.deadline = launcher.time.monotonic() + 1800
                status_class.return_value.data = {"stages": {}}
                launcher.run_workflow(task)
            stage.send_start_key.assert_called_once()
            stage.wait_completion.assert_called_once()

    def test_original_arguments_preserved_by_supervised_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ok-ww.exe"
            path.touch()
            task = {"name": "test", "steps": [
                {"type": "launch", "setup_key": "okww", "path": str(path),
                 "args": ["-t", "1", "-e"], "save_as": "OKWW"}]}
            with mock.patch.object(launcher, "find_processes_by_path", return_value=[]), \
                 mock.patch.object(launcher, "launch_program", return_value=mock.Mock(pid=1)) as launch, \
                 mock.patch.object(launcher, "ToolProcesses") as trackers, \
                 mock.patch.object(launcher, "Stage") as stage_class, \
                 mock.patch.object(launcher, "RunStatus") as statuses, \
                 mock.patch.object(launcher, "check_stop_requested"):
                trackers.return_value.current.return_value = []
                statuses.return_value.data = {"stages": {}}
                stage_class.return_value.profile = "okww"
                launcher.run_workflow(task)
                callbacks = stage_class.call_args.args[-1]
                callbacks["relaunch"]()
            self.assertEqual(launch.call_args_list[0], launch.call_args_list[1])
            self.assertEqual(launch.call_args.args[0]["args"], ["-t", "1", "-e"])


if __name__ == "__main__":
    unittest.main()
