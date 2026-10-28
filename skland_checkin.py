"""Optional, local-only Endfield attendance. No scheduler or game controls.

Protocol references (not a supported public API):
https://github.com/sjtt2/endfield_auto_sign
https://github.com/FrostN0v0/nonebot-plugin-skland
https://github.com/AEtherside/skland-daily-attendance
"""
import argparse
import contextlib
import ctypes
import getpass
import hashlib
import hmac
import http.client
import json
import os
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SETTINGS = ROOT / "config" / "skland_checkin.json"
DATA = ROOT / "runtime" / "skland"
APP_CODE = "4ca99fa6b56cc2ba"  # Public Skland client identifier, not a secret.
AUTH_HOST = "https://as.hypergryph.com"
API_HOST = "https://zonai.skland.com"
ATTENDANCE = "/web/v1/game/endfield/attendance"
ALLOWED_HOSTS = {"as.hypergryph.com", "zonai.skland.com"}
MESSAGES = {
    "AUTH_REQUIRED": "需要重新配置森空岛登录，或在官方页面完成验证。",
    "NETWORK_ERROR": "网络请求失败；未自动重复领取，请稍后重试。",
    "API_ERROR": "森空岛接口拒绝请求；可能需要设备验证或接口已变化。",
    "BAD_RESPONSE": "森空岛返回格式变化，未确认签到结果。",
    "UNVERIFIED": "签到后的状态未确认，不记作成功。",
    "NO_ROLE": "未找到已绑定的终末地角色，请先在森空岛绑定。",
    "LOCAL_ERROR": "本机配置或加密文件无法读取，请重新配置。",
    "BUSY": "另一签到或配置进程正在运行，本次未重复执行。",
}


class CheckinError(Exception):
    """Only fixed, non-sensitive errors cross the API boundary."""
    def __init__(self, kind, http_status=None):
        self.kind = kind
        self.http_status = http_status
        super().__init__(MESSAGES.get(kind, MESSAGES["LOCAL_ERROR"]))


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def today():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def dpapi(content, decrypt=False):
    """Current Windows user only; never fall back to plaintext."""
    if os.name != "nt":
        raise CheckinError("LOCAL_ERROR")

    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(content)
    source = Blob(len(content), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(Blob)]
    function.restype = ctypes.c_int
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise CheckinError("LOCAL_ERROR")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward any credential to another endpoint, even on official hosts.
        return None


class Transport:
    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method, url, body=None, headers=None):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or parsed.fragment):
            raise CheckinError("API_ERROR")
        safe_headers = {"User-Agent": "Skland/1.32.1", "Accept": "application/json",
                        "Content-Type": "application/json", **(headers or {})}
        request = urllib.request.Request(url, data=body, headers=safe_headers, method=method)
        try:
            with self.opener.open(request, timeout=15) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise CheckinError("BAD_RESPONSE")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise CheckinError("BAD_RESPONSE")
            return value
        except urllib.error.HTTPError as error:
            kind = "AUTH_REQUIRED" if error.code in (401, 403) else "API_ERROR"
            # Neither HTTP bodies nor exception text are exposed.
            raise CheckinError(kind, error.code) from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, socket.timeout, OSError):
            raise CheckinError("NETWORK_ERROR") from None
        except (ValueError, UnicodeError):
            raise CheckinError("BAD_RESPONSE") from None


def response_data(response, field="code"):
    if type(response.get(field)) is not int or response[field] != 0:
        code = response.get(field)
        raise CheckinError("AUTH_REQUIRED" if code in (10000, 10002) else "API_ERROR")
    data = response.get("data")
    if not isinstance(data, dict):
        raise CheckinError("BAD_RESPONSE")
    return data


def required_text(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value or len(value) > 8192 or any(c in value for c in "\r\n"):
        raise CheckinError("BAD_RESPONSE")
    return value


def signed_headers(path, body, cred, key, role=None, timestamp=None):
    timestamp = str(int(time.time()) - 1) if timestamp is None else str(timestamp)
    profile = {"platform": "3", "timestamp": timestamp, "dId": "", "vName": "1.0.0"}
    message = path + body.decode("utf-8") + timestamp + compact(profile)
    digest = hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()
    signature = hashlib.md5(digest.encode()).hexdigest()
    headers = {"cred": cred, **profile, "sign": signature}
    if role:
        headers["sk-game-role"] = "3_" + role["roleId"] + "_" + role["serverId"]
    return headers


def endfield_roles(binding):
    """Nested role IDs, not the binding UID/channel ID. Do not sign other games."""
    apps = binding.get("list")
    if not isinstance(apps, list):
        raise CheckinError("BAD_RESPONSE")
    found = {}
    for app in apps:
        if not isinstance(app, dict) or app.get("appCode") != "endfield":
            continue
        bindings = app.get("bindingList", [])
        if not isinstance(bindings, list):
            raise CheckinError("BAD_RESPONSE")
        for item in bindings:
            if not isinstance(item, dict):
                raise CheckinError("BAD_RESPONSE")
            roles = item.get("roles") or [item.get("defaultRole")]
            if not isinstance(roles, list):
                raise CheckinError("BAD_RESPONSE")
            for role in roles:
                if not isinstance(role, dict):
                    continue
                role_id = str(role.get("roleId", ""))
                server_id = str(role.get("serverId", ""))
                if (not role_id or not server_id or not role_id.isdecimal()
                        or not server_id.isdecimal() or len(role_id) > 40 or len(server_id) > 40):
                    raise CheckinError("BAD_RESPONSE")
                found[(role_id, server_id)] = {"roleId": role_id, "serverId": server_id}
    if not found:
        raise CheckinError("NO_ROLE")
    if len(found) > 20:
        raise CheckinError("BAD_RESPONSE")
    return list(found.values())


class Skland:
    def __init__(self, transport=None):
        self.transport = transport or Transport()
        self.cred = None
        self.key = None
        self.attendance_path = ATTENDANCE

    def login(self, account_token):
        grant = self.transport.request("POST", AUTH_HOST + "/user/oauth2/v2/grant",
            compact({"appCode": APP_CODE, "token": account_token, "type": 0}).encode())
        code = required_text(response_data(grant, "status"), "code")
        response = self.transport.request("POST", API_HOST + "/api/v1/user/auth/generate_cred_by_code",
            compact({"code": code, "kind": 1}).encode())
        data = response_data(response)
        self.cred, self.key = required_text(data, "cred"), required_text(data, "token")

    def refresh(self, cred):
        data = response_data(self.transport.request("GET", API_HOST + "/api/v1/auth/refresh",
                                                  headers={"cred": cred}))
        self.cred, self.key = cred, required_text(data, "token")

    def signed(self, method, path, role=None):
        # Attendance POST has a zero-byte body, NOT {} or null.
        headers = signed_headers(path, b"", self.cred, self.key, role)
        return self.transport.request(method, API_HOST + path,
                                      b"" if method == "POST" else None, headers)

    def roles(self):
        return endfield_roles(response_data(self.signed("GET", "/api/v1/game/player/binding")))

    def has_today(self, role):
        try:
            response = self.signed("GET", self.attendance_path, role)
        except CheckinError as error:
            # Endpoint compatibility is read-only. Never blindly retry a POST.
            if error.http_status != 404 or self.attendance_path != ATTENDANCE:
                raise
            self.attendance_path = "/api/v1/game/endfield/attendance"
            response = self.signed("GET", self.attendance_path, role)
        data = response_data(response)
        if not isinstance(data.get("hasToday"), bool):
            raise CheckinError("BAD_RESPONSE")
        return data["hasToday"]

    def checkin(self, role):
        if role not in self.roles():
            raise CheckinError("NO_ROLE")
        if self.has_today(role):
            return "ALREADY_SIGNED"
        error = None
        try:
            # Even code=10001 is NOT proof of a duplicate/success.
            response_data(self.signed("POST", self.attendance_path, role))
        except CheckinError as caught:
            error = caught
        # A lost POST response is resolved by a read, never by another claim.
        try:
            verified = self.has_today(role)
        except CheckinError:
            raise CheckinError("UNVERIFIED") from None
        if verified:
            return "SIGNED"
        if error:
            raise error
        raise CheckinError("UNVERIFIED")


@contextlib.contextmanager
def exclusive(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / "checkin.lock").open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise CheckinError("BUSY") from None
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise CheckinError("BUSY") from None
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def save_login(client, role, data_dir=DATA, settings_file=SETTINGS):
    # Discard accountToken and the short-lived signing key; retain only Skland cred.
    plain = compact({"cred": client.cred, "role": role}).encode()
    encrypted = dpapi(plain)
    if dpapi(encrypted, decrypt=True) != plain:
        raise CheckinError("LOCAL_ERROR")
    atomic_write(data_dir / "secrets.dpapi", encrypted)
    write_json(settings_file, {"enabled": True, "game": "endfield"})


def deadline_expired(data_dir):
    # This terminates only this isolated check-in worker, never the launcher/games.
    try:
        write_json(data_dir / "last_result.json", {
            "date": today(), "state": "UNVERIFIED", "reason": "TIME_LIMIT",
            "summary": "签到超过 120 秒，结果未确认；未自动重复领取。",
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
    finally:
        os._exit(1)


@contextlib.contextmanager
def worker_deadline(data_dir):
    timer = threading.Timer(120, deadline_expired, args=(data_dir,))
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()


def setup():
    print("森空岛 · 终末地签到配置（只保存在本机）")
    print("请先在 https://www.skland.com/ 登录自己的账号。")
    print("登录后打开 https://web-api.skland.com/account/info/hg")
    print("只复制 data.content 的值。该值是敏感登录令牌，不要发到聊天、截图或仓库。")
    print("本程序只向鹰角/森空岛官方服务器换取签到凭据；不保存原始令牌。")
    print("设备验证/验证码不会被自动绕过。取消请按 Ctrl+C。")
    if input("输入 Y 打开官方登录页，或直接回车继续：").strip().lower() == "y":
        webbrowser.open("https://www.skland.com/")
    if not __import__("sys").stdin.isatty():
        raise CheckinError("LOCAL_ERROR")  # Do not fall back to echoed credential input.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        account_token = getpass.getpass("粘贴 data.content（输入不显示）：").strip()
    if not account_token or len(account_token) > 8192 or any(c.isspace() for c in account_token):
        raise CheckinError("AUTH_REQUIRED")
    client = Skland()
    try:
        client.login(account_token)
    finally:
        account_token = None
    roles = client.roles()
    chosen = 0
    if len(roles) > 1:
        print("发现多个终末地角色，请选择一个；编号按森空岛绑定顺序，不显示 UID。")
        for index in range(len(roles)):
            print(f"  {index + 1}. 终末地角色 {index + 1}")
        try:
            chosen = int(input("选择编号：")) - 1
        except ValueError:
            raise CheckinError("LOCAL_ERROR") from None
        if not 0 <= chosen < len(roles):
            raise CheckinError("LOCAL_ERROR")
    role = roles[chosen]
    # Validate the status endpoint before enabling the integration. No claim yet.
    signed = client.has_today(role)
    save_login(client, role)
    print("配置完成。当前状态：" + ("今日已签到。" if signed else "今日未签到。"))
    print("以后启动日常时会后台签到。也可使用 skland_checkin.bat checkin 立即签到。")


def run_checkin(data_dir=DATA, settings_file=SETTINGS, client_factory=Skland):
    if not settings_file.is_file():
        return {"state": "NOT_CONFIGURED", "summary": "尚未配置森空岛签到。"}
    settings = json.loads(settings_file.read_text(encoding="utf-8-sig"))
    if settings.get("enabled") is not True:
        return {"state": "DISABLED", "summary": "森空岛签到未启用。"}
    if settings.get("game") != "endfield":
        raise CheckinError("LOCAL_ERROR")
    saved = json.loads(dpapi((data_dir / "secrets.dpapi").read_bytes(), decrypt=True))
    cred = required_text(saved, "cred")
    role = saved.get("role")
    if not isinstance(role, dict) or set(role) != {"roleId", "serverId"}:
        raise CheckinError("LOCAL_ERROR")
    if not all(isinstance(v, str) and v.isdecimal() and len(v) <= 40 for v in role.values()):
        raise CheckinError("LOCAL_ERROR")
    check_date = today()
    client = client_factory()
    client.refresh(cred)
    outcome = client.checkin(role)
    if outcome not in {"SIGNED", "ALREADY_SIGNED"} or today() != check_date:
        raise CheckinError("UNVERIFIED")
    return {"date": check_date, "state": outcome,
            "summary": "今日签到已核实。" if outcome == "SIGNED" else "今日已签到，无需重复领取。"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="森空岛终末地本机签到")
    parser.add_argument("action", choices=("setup", "checkin", "auto-checkin", "status", "disable"))
    args = parser.parse_args(argv)
    if args.action == "status":
        result_file = DATA / "last_result.json"
        if result_file.is_file():
            result = json.loads(result_file.read_text(encoding="utf-8"))
            # Whitelist only locally generated, non-sensitive fields.
            print(json.dumps({k: result.get(k) for k in ("date", "state", "summary")}, ensure_ascii=False))
        else:
            print("尚无签到结果；请先运行 skland_checkin.bat setup。")
        return 0
    try:
        with exclusive(DATA):
            if args.action == "setup":
                setup()
                return 0
            if args.action == "disable":
                write_json(SETTINGS, {"enabled": False, "game": "endfield"})
                print("已停用后台签到；加密凭据仍保留在本机。")
                return 0
            with worker_deadline(DATA):
                try:
                    result = run_checkin()
                except CheckinError as error:
                    result = {"state": error.kind, "summary": str(error)}
                except Exception:
                    # Never print traceback/exception strings that may contain credentials.
                    result = {"state": "LOCAL_ERROR", "summary": MESSAGES["LOCAL_ERROR"]}
            result.setdefault("date", today())
            result["checked_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            write_json(DATA / "last_result.json", result)
            print(result["summary"])
            return 0 if result["state"] in {"SIGNED", "ALREADY_SIGNED", "DISABLED", "NOT_CONFIGURED"} else 1
    except KeyboardInterrupt:
        print("已取消；不会开始新的签到请求。")
        return 1
    except Exception as error:
        print(str(error) if isinstance(error, CheckinError) else MESSAGES["LOCAL_ERROR"])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
