import unittest
from pathlib import Path

from verify_public import inspect_file, scan_tree
from unittest import mock


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
                     "config/miyoushe_checkin.json", "config/skland_checkin.json",
                     "other.dpapi", ".env", "key.pem"):
            with self.subTest(name=name):
                self.assertTrue(inspect_file(name, b""))
        self.assertEqual(inspect_file("runtime/.gitkeep", b""), [])

    def test_rejects_private_key_header(self):
        header = b"-----BEGIN " + b"PRIVATE KEY-----"
        self.assertTrue(inspect_file("key.txt", header))

    def test_normal_https_links_are_not_absolute_windows_paths(self):
        self.assertEqual(inspect_file("README.md", b"https://github.com/LianTongQi/auto-game"), [])

    def test_rejects_private_collaboration_and_email(self):
        for name in ("AGENTS.md", "docs/STATUS.md", "docs/DECISIONS.md", "debug/app.log"):
            self.assertTrue(inspect_file(name, b""))
        address = b"private-user" + b"@mail.test"
        errors = inspect_file("README.md", address)
        self.assertTrue(errors)
        self.assertNotIn(address.decode(), str(errors))

    def test_examples_and_anonymous_email_allowed(self):
        self.assertEqual(inspect_file("template.txt", b"user@example.com"), [])
        self.assertEqual(inspect_file("metadata.txt", b"user@users.noreply.github.com"), [])

    def test_index_audit_reads_staged_content_not_dirty_worktree(self):
        with mock.patch("verify_public.git", side_effect=[b"README.md\0", b"safe public text"]) as git:
            self.assertEqual(scan_tree(staged=True), [])
        self.assertEqual(git.call_args_list[-1], mock.call("show", ":README.md"))


if __name__ == "__main__":
    unittest.main()
