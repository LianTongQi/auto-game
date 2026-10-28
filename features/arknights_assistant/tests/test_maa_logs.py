import json
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ark_assistant.maa_logs import completed_operbox, import_operbox
from ark_assistant.native_probe import copilot_preflight, version_tuple


def event(kind, payload, pid="Px1", hour="12:00:00.000"):
    return f'[2026-10-06 {hour}][INF][{pid}][Tx1] Assistant::append_callback | {kind} ' + json.dumps(payload, separators=(",", ":")) + "\n"


class MaaLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / "test.log"
        self.scan = {"taskchain": "OperBox", "taskid": 7, "what": "OperBoxInfo",
                     "uuid": "discard", "details": {"done": True, "own_opers": [
                         {"id": "example", "own": True, "elite": 2, "level": 60}]}}
        self.done = {"taskchain": "OperBox", "taskid": 7}
        self.now = datetime(2026, 10, 6, 13)

    def write(self, suffix="", pid="Px1"):
        self.log.write_text(event("SubTaskExtraInfo", self.scan) + suffix, encoding="utf-8")

    def test_completed_scan_required(self):
        self.write()
        with self.assertRaises(ValueError):
            completed_operbox(self.log, self.now)

    def test_task_id_and_process_must_match(self):
        for done in (event("TaskChainCompleted", {**self.done, "taskid": 8}),
                     event("TaskChainCompleted", self.done, "Px2")):
            self.write(done)
            with self.assertRaises(ValueError):
                completed_operbox(self.log, self.now)

    def test_done_flag_required(self):
        self.scan["details"]["done"] = False
        self.write(event("TaskChainCompleted", self.done))
        with self.assertRaises(ValueError):
            completed_operbox(self.log, self.now)

    def test_stopped_scan_rejected(self):
        self.write(event("TaskChainStopped", self.done) + event("TaskChainCompleted", self.done))
        with self.assertRaises(ValueError):
            completed_operbox(self.log, self.now)

    def test_old_scan_rejected(self):
        self.write(event("TaskChainCompleted", self.done))
        with self.assertRaises(ValueError):
            completed_operbox(self.log, datetime(2026, 10, 8, 13))

    def test_import_whitelist_and_unknown_mastery(self):
        self.write(event("TaskChainCompleted", self.done))
        (self.root / "resource").mkdir()
        (self.root / "resource/battle_data.json").write_text(json.dumps({"chars": {
            "example": {"name": "Example", "profession": "WARRIOR"}}}), encoding="utf-8")
        inventory = import_operbox(self.log, self.root, self.now)
        self.assertEqual(inventory["operators"][0]["role"], "guard")
        self.assertEqual(inventory["operators"][0]["level"], 60)
        self.assertEqual(inventory["operators"][0]["skills"], {})
        self.assertEqual(inventory["operators"][0]["modules"], {})
        self.assertNotIn("uuid", json.dumps(inventory))

    def test_stable_minimum_version(self):
        self.assertGreater(version_tuple("v6.18.0"), version_tuple("v6.0.0"))
        for value in (None, "v6.18.0-beta.1", "evil", "6.18"):
            with self.assertRaises(ValueError):
                version_tuple(value)

    def test_native_probe_never_connects_or_starts(self):
        job = self.root / "copilot.json"
        job.write_text(json.dumps({"stage_name": "1-7", "minimum_required": "v6.0.0",
                                   "actions": [{"type": "Output"}]}), encoding="utf-8")
        lib = MagicMock()
        lib.AsstGetVersion.return_value = b"v6.18.0"
        lib.AsstCreate.return_value = 123
        lib.AsstAppendTask.return_value = 7
        with patch("ark_assistant.native_probe.platform.system", return_value="Windows"), \
                patch("ark_assistant.native_probe.os.add_dll_directory", create=True), \
                patch("ark_assistant.native_probe.ctypes.WinDLL", return_value=lib, create=True):
            report = copilot_preflight(self.root, job, self.root / "probe")
        self.assertEqual(report["status"], "NATIVE_ACCEPTED")
        self.assertFalse(report["game_connected"])
        self.assertFalse(report["task_started"])
        lib.AsstConnect.assert_not_called()
        lib.AsstStart.assert_not_called()
        lib.AsstDestroy.assert_called_once_with(123)
        lib.AsstSetInstanceOption.assert_called_once_with(123, 5, b"0")

    def test_native_rejection_still_destroys_queue(self):
        job = self.root / "copilot.json"
        job.write_text(json.dumps({"stage_name": "1-7", "minimum_required": "v6.0.0",
                                   "actions": [{"type": "Output"}]}), encoding="utf-8")
        lib = MagicMock()
        lib.AsstGetVersion.return_value = b"v6.18.0"
        lib.AsstCreate.return_value = 123
        lib.AsstAppendTask.return_value = 0
        with patch("ark_assistant.native_probe.platform.system", return_value="Windows"), \
                patch("ark_assistant.native_probe.os.add_dll_directory", create=True), \
                patch("ark_assistant.native_probe.ctypes.WinDLL", return_value=lib, create=True):
            report = copilot_preflight(self.root, job, self.root / "probe")
        self.assertEqual(report["status"], "NATIVE_REJECTED")
        lib.AsstDestroy.assert_called_once_with(123)
        lib.AsstStart.assert_not_called()


if __name__ == "__main__":
    unittest.main()
