import subprocess
import unittest
from unittest import mock

import scheduler_launcher as launcher


class WindowsExitTests(unittest.TestCase):
    def setUp(self):
        self.kernel = mock.Mock()
        self.kernel.OpenProcess.return_value = 123
        self.windows = mock.patch.object(launcher.platform, "system", return_value="Windows")
        self.dll = mock.patch.object(launcher.ctypes, "WinDLL", return_value=self.kernel, create=True)
        self.windows.start()
        self.dll.start()
        self.addCleanup(self.windows.stop)
        self.addCleanup(self.dll.stop)

    def test_signalled_process_is_exited_even_if_pid_still_exists(self):
        self.kernel.WaitForSingleObject.return_value = 0
        with mock.patch.object(launcher.psutil, "pid_exists", return_value=True):
            self.assertTrue(launcher.wait_pid_termination(42, timeout=0))
            self.assertFalse(launcher.is_process_running(42))
        self.kernel.CloseHandle.assert_has_calls([mock.call(123), mock.call(123)])

    def test_live_process_wait_is_bounded(self):
        self.kernel.WaitForSingleObject.return_value = 258
        self.assertFalse(launcher.wait_pid_termination(42, timeout=10))
        self.kernel.WaitForSingleObject.assert_called_once_with(123, 10000)
        self.kernel.CloseHandle.assert_called_once_with(123)

    def test_missing_pid_is_exited(self):
        self.kernel.OpenProcess.return_value = None
        with mock.patch.object(launcher.ctypes, "get_last_error", return_value=87, create=True):
            self.assertTrue(launcher.wait_pid_termination(42, timeout=0))
        self.kernel.CloseHandle.assert_not_called()

    def test_access_denied_is_not_mistaken_for_exit(self):
        self.kernel.OpenProcess.return_value = None
        with mock.patch.object(launcher.ctypes, "get_last_error", return_value=5, create=True):
            with self.assertRaisesRegex(RuntimeError, "无法确认进程退出"):
                launcher.is_process_running(42)

    def test_failed_wait_releases_handle_and_reports_error(self):
        self.kernel.WaitForSingleObject.return_value = 0xFFFFFFFF
        with mock.patch.object(launcher.ctypes, "get_last_error", return_value=6, create=True):
            with self.assertRaisesRegex(RuntimeError, "等待进程退出失败"):
                launcher.wait_pid_termination(42)
        self.kernel.CloseHandle.assert_called_once_with(123)


class CloseTests(unittest.TestCase):
    def setUp(self):
        self.windows = mock.patch.object(launcher.platform, "system", return_value="Windows")
        self.running = mock.patch.object(launcher, "is_process_running", return_value=True)
        self.windows.start()
        self.running.start()
        self.addCleanup(self.windows.stop)
        self.addCleanup(self.running.stop)

    def test_pid_close_waits_for_actual_exit_before_success(self):
        result = mock.Mock(returncode=0)
        with mock.patch.object(launcher.subprocess, "run", return_value=result) as kill, \
             mock.patch.object(launcher, "wait_pid_termination", return_value=True) as wait:
            self.assertTrue(launcher.close_process(42, force=True))
        self.assertEqual(kill.call_args.args[0], ["taskkill", "/PID", "42", "/T", "/F"])
        wait.assert_called_once_with(42, timeout=10)

    def test_successful_command_without_exit_is_still_failure(self):
        with mock.patch.object(launcher.subprocess, "run", return_value=mock.Mock(returncode=0)), \
             mock.patch.object(launcher, "wait_pid_termination", return_value=False) as wait:
            self.assertFalse(launcher.close_process(42, force=True))
        wait.assert_called_once_with(42, timeout=10)

    def test_process_exiting_during_failed_command_is_not_false_alarm(self):
        result = mock.Mock(returncode=1, stderr="not found", stdout="")
        with mock.patch.object(launcher.subprocess, "run", return_value=result), \
             mock.patch.object(launcher, "wait_pid_termination", return_value=True) as wait:
            self.assertTrue(launcher.close_process(42))
        wait.assert_called_once_with(42, timeout=10)

    def test_partial_tree_error_still_waits_for_delayed_root_exit(self):
        result = mock.Mock(returncode=1, stderr="child no longer exists", stdout="")
        def delayed_exit(_pid, timeout):
            return timeout >= 0.2
        with mock.patch.object(launcher.subprocess, "run", return_value=result), \
             mock.patch.object(launcher, "wait_pid_termination", side_effect=delayed_exit) as wait:
            self.assertTrue(launcher.close_process(42, force=True))
        wait.assert_called_once_with(42, timeout=10)

    def test_failed_command_and_live_process_remains_failure(self):
        result = mock.Mock(returncode=1, stderr="access denied", stdout="")
        with mock.patch.object(launcher.subprocess, "run", return_value=result), \
             mock.patch.object(launcher, "wait_pid_termination", return_value=False):
            self.assertFalse(launcher.close_process(42))


class TrackerExitTests(unittest.TestCase):
    def test_retained_terminated_pid_is_not_a_live_tool(self):
        process = mock.Mock(pid=42)
        process.create_time.return_value = 100
        process.is_running.return_value = True
        tracker = launcher.ToolProcesses("tool.exe")
        tracker.known = {42: 100}
        with mock.patch.object(launcher, "find_processes_by_path", return_value=[]), \
             mock.patch.object(launcher.psutil, "Process", return_value=process), \
             mock.patch.object(launcher, "is_process_running", return_value=False):
            self.assertEqual(tracker.current(include_games=True), [])
        process.children.assert_not_called()

    def test_reused_pid_is_not_closed(self):
        process = mock.Mock(pid=42)
        process.create_time.return_value = 200
        tracker = launcher.ToolProcesses("tool.exe")
        tracker.known = {42: 100}
        with mock.patch.object(tracker, "current", side_effect=[[{"pid": 42, "create_time": 100}], []]), \
             mock.patch.object(launcher.psutil, "Process", return_value=process), \
             mock.patch.object(launcher, "close_process") as close:
            tracker.close()
        close.assert_not_called()

    def test_genuine_survivor_still_stops_workflow(self):
        process = mock.Mock(pid=42)
        process.create_time.return_value = 100
        tracker = launcher.ToolProcesses("tool.exe")
        with mock.patch.object(tracker, "current", return_value=[{"pid": 42, "create_time": 100}]), \
             mock.patch.object(launcher.psutil, "Process", return_value=process), \
             mock.patch.object(launcher, "close_process", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "关闭后仍存活"):
                tracker.close()


if __name__ == "__main__":
    unittest.main()
