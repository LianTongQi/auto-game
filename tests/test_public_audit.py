import unittest
from pathlib import Path

from verify_public import inspect_file


class PublicAuditTests(unittest.TestCase):
    def test_public_template_keeps_order_parameters_and_blank_paths(self):
        data = (Path(__file__).resolve().parents[1] / "config/tasks.json").read_bytes()
        self.assertEqual(inspect_file("config/tasks.json", data), [])

    def test_token_detection_does_not_echo_secret(self):
        token = b"ghp_" + b"A" * 32
        errors = inspect_file("settings.txt", token)
        self.assertTrue(errors)
        self.assertNotIn(token.decode(), str(errors))

    def test_rejects_absolute_paths(self):
        path = (chr(69) + ":" + "\\" + "private" + "\\file.exe").encode()
        self.assertTrue(inspect_file("settings.json", path))

    def test_rejects_runtime_logs_and_private_files(self):
        for name in ("logs/job.log", "runtime/run_status.json", "config/secrets.dpapi",
                     "config/miyoushe_checkin.json", ".env", "key.pem"):
            with self.subTest(name=name):
                self.assertTrue(inspect_file(name, b""))
        self.assertEqual(inspect_file("runtime/.gitkeep", b""), [])

    def test_rejects_private_key_header(self):
        header = b"-----BEGIN " + b"PRIVATE KEY-----"
        self.assertTrue(inspect_file("key.txt", header))

    def test_normal_https_links_are_not_absolute_windows_paths(self):
        self.assertEqual(inspect_file("README.md", b"https://github.com/LianTongQi/auto-game"), [])


if __name__ == "__main__":
    unittest.main()
