import hashlib
import hmac
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import skland_checkin as sk
import scheduler_launcher as launcher


ROLE = {"roleId": "12345", "serverId": "1"}


def binding():
    return {"list": [
        {"appCode": "arknights", "bindingList": [{"roles": [ROLE]}]},
        {"appCode": "endfield", "bindingList": [
            {"uid": "wrong-binding-id", "channelMasterId": "wrong-channel-id", "roles": [ROLE, ROLE]},
            {"defaultRole": ROLE},
        ]},
    ]}


class SklandProtocolTests(unittest.TestCase):
    def client(self, replies):
        transport = mock.Mock()
        transport.request.side_effect = replies
        client = sk.Skland(transport)
        client.cred, client.key = "fictional-cred", "fictional-key"
        return client, transport

    def test_signature_matches_exact_empty_body_and_order(self):
        path = sk.ATTENDANCE
        header = sk.signed_headers(path, b"", "fictional-cred", "key", ROLE, 123)
        profile = '{"platform":"3","timestamp":"123","dId":"","vName":"1.0.0"}'
        digest = hmac.new(b"key", (path + "123" + profile).encode(), hashlib.sha256).hexdigest()
        self.assertEqual(header["sign"], hashlib.md5(digest.encode()).hexdigest())
        self.assertEqual(header["sk-game-role"], "3_12345_1")

    def test_roles_are_nested_deduplicated_and_endfield_only(self):
        self.assertEqual(sk.endfield_roles(binding()), [ROLE])

    def test_wrong_role_or_other_game_is_never_signed(self):
        client, transport = self.client([{"code": 0, "data": binding()}])
        with self.assertRaises(sk.CheckinError):
            client.checkin({"roleId": "999", "serverId": "1"})
        self.assertEqual(transport.request.call_count, 1)

    def test_already_signed_uses_no_post(self):
        client, transport = self.client([
            {"code": 0, "data": binding()}, {"code": 0, "data": {"hasToday": True}},
        ])
        self.assertEqual(client.checkin(ROLE), "ALREADY_SIGNED")
        self.assertTrue(all(c.args[0] == "GET" for c in transport.request.call_args_list))

    def test_success_requires_post_check_and_empty_body(self):
        client, transport = self.client([
            {"code": 0, "data": binding()}, {"code": 0, "data": {"hasToday": False}},
            {"code": 0, "data": {}}, {"code": 0, "data": {"hasToday": True}},
        ])
        self.assertEqual(client.checkin(ROLE), "SIGNED")
        post = transport.request.call_args_list[2]
        self.assertEqual(post.args[0], "POST")
        self.assertEqual(post.args[2], b"")

    def test_api_success_without_post_verification_is_not_success(self):
        client, _ = self.client([
            {"code": 0, "data": binding()}, {"code": 0, "data": {"hasToday": False}},
            {"code": 0, "data": {}}, {"code": 0, "data": {"hasToday": False}},
        ])
        with self.assertRaises(sk.CheckinError) as caught:
            client.checkin(ROLE)
        self.assertEqual(caught.exception.kind, "UNVERIFIED")

    def test_ambiguous_10001_is_not_already_signed(self):
        client, _ = self.client([
            {"code": 0, "data": binding()}, {"code": 0, "data": {"hasToday": False}},
            {"code": 10001, "message": "设备无效，fictional-secret"},
            {"code": 0, "data": {"hasToday": False}},
        ])
        with self.assertRaises(sk.CheckinError) as caught:
            client.checkin(ROLE)
        self.assertEqual(caught.exception.kind, "API_ERROR")
        self.assertNotIn("fictional-secret", str(caught.exception))

    def test_lost_post_response_is_read_back_not_retried(self):
        client, transport = self.client([
            {"code": 0, "data": binding()}, {"code": 0, "data": {"hasToday": False}},
            sk.CheckinError("NETWORK_ERROR"), {"code": 0, "data": {"hasToday": True}},
        ])
        self.assertEqual(client.checkin(ROLE), "SIGNED")
        self.assertEqual(sum(c.args[0] == "POST" for c in transport.request.call_args_list), 1)

    def test_device_block_before_status_never_claims(self):
        client, transport = self.client([{"code": 10001, "message": "设备验证"}])
        with self.assertRaises(sk.CheckinError):
            client.checkin(ROLE)
        self.assertEqual(transport.request.call_count, 1)

    def test_status_must_be_real_boolean(self):
        client, _ = self.client([{"code": 0, "data": {"hasToday": "false"}}])
        with self.assertRaises(sk.CheckinError):
            client.has_today(ROLE)

    def test_read_only_endpoint_fallback_only_on_404(self):
        client, transport = self.client([
            sk.CheckinError("API_ERROR", 404), {"code": 0, "data": {"hasToday": True}},
        ])
        self.assertTrue(client.has_today(ROLE))
        self.assertTrue(all(c.args[0] == "GET" for c in transport.request.call_args_list))
        self.assertIn("/api/v1/", client.attendance_path)

    def test_auth_failure_never_uses_fallback(self):
        client, transport = self.client([sk.CheckinError("AUTH_REQUIRED", 403)])
        with self.assertRaises(sk.CheckinError):
            client.has_today(ROLE)
        self.assertEqual(transport.request.call_count, 1)

    def test_false_or_missing_response_code_is_not_success(self):
        for value in ({"code": False, "data": {}}, {"data": {}}):
            with self.subTest(value=value), self.assertRaises(sk.CheckinError):
                sk.response_data(value)

    def test_login_uses_only_official_hosts(self):
        client, transport = self.client([
            {"status": 0, "data": {"code": "fictional-code"}},
            {"code": 0, "data": {"cred": "fictional-cred", "token": "fictional-key"}},
        ])
        client.login("fictional-account-token")
        self.assertEqual(client.cred, "fictional-cred")
        self.assertEqual(transport.request.call_args_list[0].args[1].split("/")[2], "as.hypergryph.com")
        self.assertEqual(transport.request.call_args_list[1].args[1].split("/")[2], "zonai.skland.com")


class SklandSecurityTests(unittest.TestCase):
    def test_disallowed_urls_never_reach_network(self):
        transport = sk.Transport()
        transport.opener = mock.Mock()
        for url in ("http://zonai.skland.com/x", "https://evil.example/x",
                    "https://zonai.skland.com.evil.example/x", "https://u:p" + "@" + "zonai.skland.com/x",
                    "https://zonai.skland.com:123/x"):
            with self.subTest(url=url), self.assertRaises(sk.CheckinError):
                transport.request("POST", url)
        transport.opener.open.assert_not_called()

    def test_redirect_is_never_followed(self):
        self.assertIsNone(sk.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example"))

    def test_raw_http_error_is_not_exposed(self):
        transport = sk.Transport()
        transport.opener = mock.Mock()
        transport.opener.open.side_effect = sk.urllib.error.HTTPError(
            sk.API_HOST, 403, "fictional-secret-value", {}, None)
        with self.assertRaises(sk.CheckinError) as caught:
            transport.request("GET", sk.API_HOST)
        self.assertNotIn("fictional-secret-value", str(caught.exception))

    def test_truncated_http_body_becomes_redacted_network_error(self):
        transport = sk.Transport()
        transport.opener = mock.MagicMock()
        response = transport.opener.open.return_value.__enter__.return_value
        response.read.side_effect = sk.http.client.IncompleteRead(b"fictional-secret", 20)
        with self.assertRaises(sk.CheckinError) as caught:
            transport.request("POST", sk.API_HOST, b"")
        self.assertEqual(caught.exception.kind, "NETWORK_ERROR")
        self.assertNotIn("fictional-secret", str(caught.exception))

    def test_total_deadline_is_daemon_and_cancelled(self):
        with mock.patch.object(sk.threading, "Timer") as factory:
            with sk.worker_deadline(Path("unused")):
                factory.return_value.start.assert_called_once()
                self.assertTrue(factory.return_value.daemon)
            factory.return_value.cancel.assert_called_once()
        self.assertEqual(factory.call_args.args[0], 120)

    def test_deadline_writes_unverified_and_exits_only_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with mock.patch.object(sk.os, "_exit") as terminate:
                sk.deadline_expired(path)
            terminate.assert_called_once_with(1)
            result = json.loads((path / "last_result.json").read_bytes())
            self.assertEqual(result["state"], "UNVERIFIED")
            self.assertEqual(result["reason"], "TIME_LIMIT")

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_real_windows_dpapi_roundtrip_not_plaintext(self):
        plain = b"synthetic credential for testing, not a real secret"
        encrypted = sk.dpapi(plain)
        self.assertNotIn(plain, encrypted)
        self.assertEqual(sk.dpapi(encrypted, decrypt=True), plain)

    def test_save_excludes_original_account_token_and_signing_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            client = sk.Skland(mock.Mock())
            client.cred, client.key = "fictional-cred", "fictional-key"
            with mock.patch.object(sk, "dpapi", side_effect=lambda value, decrypt=False: value):
                sk.save_login(client, ROLE, path, path / "settings.json")
            value = json.loads((path / "secrets.dpapi").read_bytes())
            self.assertEqual(set(value), {"cred", "role"})
            self.assertNotIn("fictional-key", json.dumps(value))
            self.assertEqual(json.loads((path / "settings.json").read_bytes()), {"enabled": True, "game": "endfield"})

    def test_unconfigured_or_disabled_never_creates_client(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            factory = mock.Mock()
            self.assertEqual(sk.run_checkin(path, path / "settings.json", factory)["state"], "NOT_CONFIGURED")
            sk.write_json(path / "settings.json", {"enabled": False})
            self.assertEqual(sk.run_checkin(path, path / "settings.json", factory)["state"], "DISABLED")
            factory.assert_not_called()

    def test_saved_cred_refreshes_and_roundtrip_verifies(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            sk.write_json(path / "settings.json", {"enabled": True, "game": "endfield"})
            (path / "secrets.dpapi").write_bytes(b"synthetic-ciphertext")
            client = mock.Mock()
            client.checkin.return_value = "SIGNED"
            plain = sk.compact({"cred": "fictional-cred", "role": ROLE}).encode()
            with mock.patch.object(sk, "dpapi", return_value=plain):
                result = sk.run_checkin(path, path / "settings.json", lambda: client)
            client.refresh.assert_called_once_with("fictional-cred")
            client.checkin.assert_called_once_with(ROLE)
            self.assertEqual(result["state"], "SIGNED")
            self.assertEqual(result["date"], sk.today())
            self.assertNotIn("fictional-cred", str(result))

    def test_midnight_crossing_is_unverified_not_wrong_day_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            sk.write_json(path / "settings.json", {"enabled": True, "game": "endfield"})
            (path / "secrets.dpapi").write_bytes(b"synthetic-ciphertext")
            client = mock.Mock()
            client.checkin.return_value = "ALREADY_SIGNED"
            plain = sk.compact({"cred": "fictional-cred", "role": ROLE}).encode()
            with mock.patch.object(sk, "dpapi", return_value=plain), \
                    mock.patch.object(sk, "today", side_effect=["2026-10-19", "2026-10-20"]):
                with self.assertRaises(sk.CheckinError) as caught:
                    sk.run_checkin(path, path / "settings.json", lambda: client)
            self.assertEqual(caught.exception.kind, "UNVERIFIED")

    def test_duplicate_worker_is_refused_and_lock_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with sk.exclusive(path):
                with self.assertRaises(sk.CheckinError):
                    with sk.exclusive(path):
                        self.fail("duplicate lock")
            with sk.exclusive(path):
                pass

    def test_main_redacts_unexpected_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with mock.patch.object(sk, "DATA", path), mock.patch.object(sk, "run_checkin",
                    side_effect=ValueError("fictional-secret")), mock.patch("builtins.print") as output:
                self.assertEqual(sk.main(["checkin"]), 1)
            raw = (path / "last_result.json").read_text(encoding="utf-8")
            self.assertNotIn("fictional-secret", raw)
            self.assertNotIn("fictional-secret", str(output.call_args_list))
            self.assertEqual(json.loads(raw)["state"], "LOCAL_ERROR")


class SklandLauncherTests(unittest.TestCase):
    def test_missing_configuration_is_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(launcher, "CONFIG_DIR", Path(directory)), mock.patch.object(launcher.subprocess, "Popen") as popen:
                self.assertIsNone(launcher.start_skland_checkin_background())
                popen.assert_not_called()

    def test_launch_has_no_credentials_and_keeps_relative_install(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            sk.write_json(path / "skland_checkin.json", {"enabled": True})
            (path / "skland_checkin.py").touch()
            with mock.patch.object(launcher, "CONFIG_DIR", path), mock.patch.object(launcher, "BASE_DIR", path), \
                    mock.patch.object(launcher.subprocess, "Popen") as popen:
                launcher.start_skland_checkin_background()
            command = popen.call_args.args[0]
            self.assertEqual(command, [launcher.sys.executable, "-B", str(path / "skland_checkin.py"), "auto-checkin"])
            self.assertEqual(popen.call_args.kwargs["stdin"], launcher.subprocess.DEVNULL)

    def test_failure_does_not_stop_games_or_echo_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            sk.write_json(path / "skland_checkin.json", {"enabled": True})
            with mock.patch.object(launcher, "CONFIG_DIR", path), mock.patch.object(launcher, "BASE_DIR", path), \
                    mock.patch.object(launcher, "log_warning") as warning:
                self.assertIsNone(launcher.start_skland_checkin_background())
            self.assertIn("继续游戏自动化", warning.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
