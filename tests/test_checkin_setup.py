import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import checkin_setup as setup
import scheduler_launcher as launcher


class CheckinSetupTests(unittest.TestCase):
    def test_disabled_settings_have_no_paths(self):
        self.assertEqual(setup.make_settings("", "", False), {"enabled": False})

    def test_only_expected_local_executable_and_script(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            python, script = root / "pythonw.exe", root / "miyoushe_accounts.py"
            python.touch()
            script.touch()
            result = setup.make_settings(str(python), str(script))
            self.assertEqual(set(result), {"enabled", "pythonw_path", "script_path", "working_dir"})
            self.assertEqual(result["working_dir"], str(root))
            for bad in ("python.exe", str(root / "cmd.exe")):
                with self.assertRaises(ValueError):
                    setup.make_settings(bad, str(script))

    def test_settings_save_keeps_original_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"enabled": true}', encoding="utf-8")
            setup.save_settings(path, {"enabled": False})
            backups = list((path.parent / "backups").iterdir())
            self.assertEqual(len(backups), 1)
            self.assertTrue(json.loads(backups[0].read_text())["enabled"])
            self.assertFalse(json.loads(path.read_text())["enabled"])

    def test_invalid_external_config_does_not_echo_values(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "miyoushe_checkin.json").write_text('{"enabled":true}', encoding="utf-8")
            with mock.patch.object(launcher, "CONFIG_DIR", root), \
                    mock.patch.object(launcher, "load_json", side_effect=ValueError("synthetic-private-value")), \
                    mock.patch.object(launcher, "log_warning") as log:
                self.assertIsNone(launcher.start_miyoushe_checkin_background())
            self.assertNotIn("synthetic-private-value", str(log.call_args))
