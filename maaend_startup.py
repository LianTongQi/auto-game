"""Official-launcher startup; guarded button-region clicks, no desktop coordinates."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time


class StartupBlocked(RuntimeError):
    pass


def compact(text):
    return re.sub(r"\s+", "", text).upper()


def discover_launcher(game_path, explicit=None):
    if explicit:
        candidate = Path(explicit)
    else:
        game = Path(game_path)
        if game.parent.parent.name.casefold() != "games":
            raise StartupBlocked("无法确定终末地官方启动器，请配置 official_launcher_path")
        candidate = game.parent.parent.parent / "Launcher.exe"
    if not candidate.is_file():
        raise StartupBlocked("未找到终末地官方启动器，请检查游戏安装目录或 official_launcher_path")
    return candidate


def validate_ocr(title_lines, button_lines):
    if not any("ENDFIELD" in compact(x["text"]) for x in title_lines):
        raise StartupBlocked("官方启动器未识别到终末地页面，未点击任何按钮")
    matches = [x for x in button_lines if compact(x["text"]) in {"开始游戏", "STARTGAME"}]
    if len(matches) != 1:
        raise StartupBlocked("未唯一识别到官方启动器的开始游戏按钮；可能正在更新或需要登录")
    item = matches[0]
    return item["x"] + item["width"] / 2, item["y"] + item["height"] / 2


def button_bounds(image):
    """Bound the yellow button in the fixed bottom-right launcher region."""
    from PIL import ImageChops
    w, h = image.size
    left, top = int(w * .70), int(h * .77)
    roi = image.crop((left, top, int(w * .97), int(h * .96))).convert("RGB")
    r, g, b = roi.split()
    mask = ImageChops.multiply(ImageChops.multiply(r.point(lambda x: 255 if x > 180 else 0),
                                                g.point(lambda x: 255 if x > 180 else 0)),
                               b.point(lambda x: 255 if x < 100 else 0))
    box = mask.getbbox()
    if not box or box[2] - box[0] < w * .08 or box[3] - box[1] < h * .025:
        raise StartupBlocked("官方启动器按钮外观未通过校验，未点击")
    x, y, x2, y2 = box
    return left + x, top + y, left + x2, top + y2


def button_crop(image):
    """Keep account information outside the label-only OCR input."""
    x, y, x2, y2 = button_bounds(image)
    bw, bh = x2 - x, y2 - y
    left, top = int(x + bw * .27), int(y + bh * .15)
    crop = image.crop((left, top, int(x + bw * .74), int(y + bh * .85)))
    return crop.convert("L").point(lambda p: 0 if p < 110 else 255), (left, top)


def button_ocr_input(button):
    """Whitespace prevents Windows OCR dropping the first glyph of a tight crop.

    Do not accept a partial label (e.g. '始游戏'): update/login buttons must
    continue to fail closed. Recognition validates state, never click position.
    """
    from PIL import Image, ImageOps
    scale = max(1, 300 / button.width)
    resized = button.resize((round(button.width * scale), round(button.height * scale)),
                            Image.Resampling.LANCZOS)
    return ImageOps.expand(resized, border=max(30, round(resized.width * .15)), fill=255)


def button_center(image):
    left, top, right, bottom = button_bounds(image)
    return (left + right) / 2, (top + bottom) / 2


class WindowsUI:
    def __init__(self, runtime_dir, deadline=None):
        if os.name != "nt":
            raise StartupBlocked("终末地官方启动仅支持 Windows")
        import psutil
        self.psutil = psutil
        self.deadline = deadline
        self.runtime = Path(runtime_dir).resolve() / "maaend-startup"
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.script = Path(__file__).with_name("windows_game_ui.ps1")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self.user.GetWindowDC.restype = wintypes.HDC
        self.user.GetWindowDC.argtypes = [wintypes.HWND]
        self.user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
        self.user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.user.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user.IsIconic.argtypes = [wintypes.HWND]
        self.user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        for name in ("CreateCompatibleDC", "CreateCompatibleBitmap", "SelectObject"):
            getattr(self.gdi, name).restype = wintypes.HANDLE
        self.gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self.gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        self.gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
        self.gdi.DeleteObject.argtypes = [wintypes.HANDLE]
        self.gdi.DeleteDC.argtypes = [wintypes.HDC]
        self.gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HANDLE, wintypes.UINT,
                                     wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except OSError:
            pass

    def windows(self):
        result = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _):
            pid = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            rect = wintypes.RECT()
            self.user.GetWindowRect(hwnd, ctypes.byref(rect))
            if self.user.IsWindowVisible(hwnd):
                result.append({"hwnd": hwnd, "pid": pid.value,
                               "rect": (rect.left, rect.top, rect.right, rect.bottom)})
            return True
        self.user.EnumWindows(callback_type(visit), 0)
        return result

    def native(self, action, pid):
        shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        quote = lambda s: "'" + str(s).replace("'", "''") + "'"
        command = "& ([scriptblock]::Create([IO.File]::ReadAllText(" + quote(self.script) + ",[Text.Encoding]::UTF8)))"
        command += " -Action " + quote(action) if isinstance(action, str) else ""
        if action == "Ocr":
            path, language = pid
            command += " -ImagePath " + quote(path) + " -Language " + quote(language)
        else:
            command += " -OwnedPid " + str(int(pid))
        try:
            remaining = self.deadline - time.monotonic() if self.deadline is not None else 20
            if remaining <= 0:
                raise StartupBlocked("启动阶段预算已用完")
            p = subprocess.run([str(shell), "-NoProfile", "-Command", command], capture_output=True,
                               timeout=min(20, remaining), creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired as error:
            raise StartupBlocked("Windows 窗口识别超时，未盲目操作") from error
        if p.returncode:
            raise StartupBlocked("Windows 文字或控件识别失败，请检查 OCR 语言包及程序界面")
        return p.stdout.decode("utf-8-sig").strip()

    def maaend(self, action, tools):
        allowed = {p["pid"]: p["create_time"] for p in tools}
        for win in self.windows():
            if win["pid"] not in allowed:
                continue
            p = self.psutil.Process(win["pid"])
            if p.name().casefold() == "maaend.exe" and p.create_time() == allowed[p.pid]:
                if self.user.IsIconic(win["hwnd"]):
                    self.user.ShowWindowAsync(win["hwnd"], 9)
                    time.sleep(.3)
                return self.native(action, p.pid)
        raise StartupBlocked("未找到本轮 MaaEnd 窗口")

    def official(self, launcher_path):
        root = Path(launcher_path).parent.resolve()
        for win in self.windows():
            try:
                p = self.psutil.Process(win["pid"])
                if p.name().casefold() not in {"games.exe", "launcher.exe"}:
                    continue
                if not Path(p.exe()).resolve().is_relative_to(root):
                    continue
                if self.user.IsIconic(win["hwnd"]):
                    self.user.ShowWindowAsync(win["hwnd"], 9)
                    return None
                win.update(created=p.create_time(), exe=p.exe())
                return win
            except self.psutil.NoSuchProcess:
                continue
        return None

    def capture(self, win):
        results = []
        def read():
            try:
                results.append(self._capture(win))
            except Exception as error:
                results.append(error)
        remaining = self.deadline - time.monotonic() if self.deadline is not None else 5
        if remaining <= 0:
            raise StartupBlocked("启动阶段预算已用完")
        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        thread.join(min(5, remaining))
        if thread.is_alive() or not results:
            raise StartupBlocked("官方启动器截图超时，未点击")
        if isinstance(results[0], Exception):
            raise results[0]
        return results[0]

    def _capture(self, win):
        from PIL import Image
        hwnd = win["hwnd"]
        rect = wintypes.RECT()
        self.user.GetWindowRect(hwnd, ctypes.byref(rect))
        if (rect.left, rect.top, rect.right, rect.bottom) != win["rect"]:
            raise StartupBlocked("启动器窗口位置已变化，请重新识别")
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if not (600 <= width <= 8000 and 400 <= height <= 5000):
            raise StartupBlocked("启动器窗口尺寸异常")
        dc = self.user.GetWindowDC(hwnd)
        memory = self.gdi.CreateCompatibleDC(dc)
        bitmap = self.gdi.CreateCompatibleBitmap(dc, width, height)
        old = self.gdi.SelectObject(memory, bitmap)
        try:
            if not self.user.PrintWindow(hwnd, memory, 2):
                raise StartupBlocked("无法读取官方启动器画面")
            self.gdi.SelectObject(memory, old)
            header = (ctypes.c_int32 * 10)(40, width, -height, 1 | (32 << 16), 0,
                                           width * height * 4, 0, 0, 0, 0)
            pixels = ctypes.create_string_buffer(width * height * 4)
            if not self.gdi.GetDIBits(memory, bitmap, 0, height, pixels, header, 0):
                raise StartupBlocked("官方启动器截图读取失败")
            return Image.frombytes("RGB", (width, height), pixels.raw, "raw", "BGRX")
        finally:
            self.gdi.SelectObject(memory, old)
            self.gdi.DeleteObject(bitmap)
            self.gdi.DeleteDC(memory)
            self.user.ReleaseDC(hwnd, dc)

    def start_point(self, win):
        image = self.capture(win)
        w, h = image.size
        logo = image.crop((int(w * .02), int(h * .04), int(w * .27), int(h * .28)))
        logo = logo.resize((1640, max(1, round(logo.height * 1640 / logo.width))))
        button, _ = button_crop(image)
        point = button_center(image)
        button = button_ocr_input(button)
        title_path, button_path = self.runtime / "game-title.png", self.runtime / "start-button.png"
        logo.save(title_path)
        button.save(button_path)
        titles = json.loads(self.native("Ocr", (title_path, "en-US")))
        buttons = json.loads(self.native("Ocr", (button_path, "zh-Hans-CN")))
        # Only our two small, non-account crops are included in this diagnostic.
        (self.runtime / "recognition.json").write_text(json.dumps({
            "strategy": "fixed-button-region-center",
            "window_size": [w, h], "candidate_point": point,
            "game_text": [x["text"] for x in titles],
            "button_text": [x["text"] for x in buttons],
        }, ensure_ascii=False), encoding="utf-8")
        validate_ocr(titles, buttons)
        return point

    def click(self, win, point):
        p = self.psutil.Process(win["pid"])
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(win["hwnd"], ctypes.byref(pid))
        rect = wintypes.RECT()
        self.user.GetWindowRect(win["hwnd"], ctypes.byref(rect))
        if (pid.value != p.pid or p.create_time() != win["created"] or p.exe() != win["exe"]
                or (rect.left, rect.top, rect.right, rect.bottom) != win["rect"]):
            raise StartupBlocked("启动器身份或位置已变化，未点击")
        origin = wintypes.POINT(0, 0)
        self.user.ClientToScreen(win["hwnd"], ctypes.byref(origin))
        x, y = int(rect.left + point[0] - origin.x), int(rect.top + point[1] - origin.y)
        client = wintypes.RECT()
        self.user.GetClientRect(win["hwnd"], ctypes.byref(client))
        if not (0 < x < client.right and 0 < y < client.bottom):
            raise StartupBlocked("识别出的按钮不在启动器内")
        position = (y << 16) | x
        for message, flags in ((0x200, 0), (0x201, 1), (0x202, 0)):
            self.user.PostMessageW(win["hwnd"], message, flags, position)

    def game_window(self, processes):
        allowed = {p["pid"]: p["create_time"] for p in processes}
        for win in self.windows():
            if win["pid"] in allowed:
                p = self.psutil.Process(win["pid"])
                if p.create_time() == allowed[p.pid]:
                    if self.user.IsIconic(win["hwnd"]):
                        self.user.ShowWindowAsync(win["hwnd"], 9)
                        return False
                    return win["rect"][2] - win["rect"][0] >= 600
        return False


def prepare(stage, runtime_dir, launch, explicit_launcher=None, ui=None):
    """Called after MaaEnd launch but before its start key; one official click."""
    stage.poll()
    if stage.signals.started or stage.signals.success:
        return
    game_path = stage.cb.get("game_path")
    if not game_path:
        raise StartupBlocked("请先在 MaaEnd 当前实例配置终末地游戏路径")
    limit = min(stage.deadline, time.monotonic() + 180)
    ui = ui or WindowsUI(runtime_dir, deadline=limit)
    ui.maaend("DismissNews", stage.cb["tools"]())
    official = None
    click_sent = False
    game_seen = None
    official_started = None
    while time.monotonic() < limit:
        stage.poll()
        stage.check_deadline()
        if stage.signals.started or stage.signals.success:
            return
        games = stage.cb["scan"](game_path)
        if games:
            if ui.game_window(games):
                game_seen = game_seen or time.monotonic()
                if time.monotonic() - game_seen >= 12:
                    return
            else:
                game_seen = None
        else:
            if official is None:
                official = discover_launcher(game_path, explicit_launcher)
                if launch({"name":"终末地官方启动器", "path":str(official), "args":[],
                           "working_dir":str(official.parent)}) is None:
                    raise StartupBlocked("官方启动器未能打开")
                stage.cb["info"]("MaaEnd 已打开，正在通过官方启动器启动终末地")
                official_started = time.monotonic()
            if not click_sent:
                window = ui.official(official)
                if window:
                    try:
                        point = ui.start_point(window)
                    except StartupBlocked:
                        if time.monotonic() - official_started < 20:
                            stage.cb["wait"](1)
                            continue
                        raise
                    stage.poll()
                    if stage.signals.started or stage.cb["scan"](game_path):
                        continue
                    ui.click(window, point)
                    click_sent = True
                    stage.cb["info"]("已校验终末地页面及开始状态，点击右下角按钮区域中心一次")
        stage.cb["wait"](1)
    raise StartupBlocked("官方启动器启动终末地超时；不直接运行游戏 EXE，也不重复点击")
