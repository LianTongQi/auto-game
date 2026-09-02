import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import scheduler_launcher as launcher


class FailureCleanupTests(unittest.TestCase):
    def test_cleanup_scans_configured_paths_and_forces_survivors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first_path = str(Path(temp_dir) / "tool.exe")
            second_path = str(Path(temp_dir) / "game.exe")
            steps = [
                {"path": first_path},
                {"path": second_path},
                {"path": first_path},
                {"path": ""},
            ]

            def find_processes(path):
                if path == first_path:
                    return [{"pid": 101, "path": first_path}]
                return []

            with mock.patch.object(
                launcher,
                "find_processes_by_path",
                side_effect=find_processes,
            ), mock.patch.object(
                launcher, "close_process", return_value=True
            ) as close_process, mock.patch.object(launcher.time, "sleep"):
                launcher.close_configured_processes(steps)

            self.assertEqual(
                close_process.call_args_list,
                [
                    mock.call(101, force=False),
                    mock.call(101, force=True),
                ],
            )


class FailureReportTests(unittest.TestCase):
    def test_report_launcher_uses_independent_pythonw_process(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            python_path = temp_path / "python.exe"
            pythonw_path = temp_path / "pythonw.exe"
            report_script = temp_path / "error_report.py"
            report_file = temp_path / "last_error_report.txt"
            log_file = temp_path / "launcher.log"
            for path in (python_path, pythonw_path, report_script):
                path.touch()

            with mock.patch.object(launcher.sys, "executable", str(python_path)), \
                    mock.patch.object(launcher, "ERROR_REPORT_SCRIPT", report_script), \
                    mock.patch.object(launcher, "ERROR_REPORT_FILE", report_file), \
                    mock.patch.object(launcher, "LOG_FILE", log_file), \
                    mock.patch.object(launcher.subprocess, "Popen") as popen:
                launched = launcher.launch_error_report("测试错误\n")

            self.assertTrue(launched)
            self.assertEqual(report_file.read_text(encoding="utf-8"), "测试错误\n")
            command = popen.call_args.args[0]
            self.assertEqual(command[0], str(pythonw_path))
            self.assertIn(str(report_script), command)
            self.assertIn(str(report_file), command)

    def test_main_stops_after_first_failed_workflow_and_reports(self):
        tasks = [
            {
                "name": "失败流程",
                "enabled": True,
                "run_on_start": True,
                "steps": [],
            },
            {
                "name": "不应运行",
                "enabled": True,
                "run_on_start": True,
                "steps": [],
            },
        ]

        with mock.patch.object(sys, "argv", ["scheduler_launcher.py"]), \
                mock.patch.object(launcher, "initial_setup_completed", return_value=True), \
                mock.patch.object(launcher, "is_running_as_admin", return_value=True), \
                mock.patch.object(launcher, "acquire_single_instance", return_value=True), \
                mock.patch.object(launcher, "clear_stop_request"), \
                mock.patch.object(launcher, "release_single_instance"), \
                mock.patch.object(launcher, "load_json", return_value=tasks), \
                mock.patch.object(
                    launcher,
                    "run_workflow",
                    side_effect=RuntimeError("模拟执行异常"),
                ) as run_workflow, mock.patch.object(
                    launcher, "launch_error_report", return_value=True
                ) as launch_error_report:
            exit_code = launcher.main()

        self.assertEqual(exit_code, 1)
        run_workflow.assert_called_once()
        report_text = launch_error_report.call_args.args[0]
        self.assertIn("失败流程", report_text)
        self.assertIn("RuntimeError", report_text)
        self.assertIn("模拟执行异常", report_text)


if __name__ == "__main__":
    unittest.main()
