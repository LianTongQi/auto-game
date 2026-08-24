import argparse
import ctypes
import json
import logging
import os
import platform
import signal
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path
from datetime import timedelta
from logging.handlers import RotatingFileHandler

try:
    import psutil
except ImportError:
    psutil = None


BASE_DIR = Path(__file__).resolve().parent

CONFIG_DIR = BASE_DIR / "config"
LOG_DIR = BASE_DIR / "logs"
RUNTIME_DIR = BASE_DIR / "runtime"

for directory in (CONFIG_DIR, LOG_DIR, RUNTIME_DIR):
    directory.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = CONFIG_DIR / "tasks.json"
SETUP_STATE_FILE = CONFIG_DIR / "setup_state.json"
SETUP_SCRIPT = BASE_DIR / "setup_wizard.py"
LOG_FILE = LOG_DIR / "launcher.log"
LOCK_FILE = RUNTIME_DIR / "launcher.lock"
STOP_FILE = RUNTIME_DIR / "stop.request"

LOCK_HELD = False


log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler = RotatingFileHandler(
    str(LOG_FILE),
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8"
)
file_handler.setFormatter(log_formatter)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(log_formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler]
)


class StopRequested(Exception):
    """用户请求安全停止当前流程。"""


def log_info(message):
    logging.info(message)


def log_warning(message):
    logging.warning(message)


def log_error(message):
    logging.error(message)


def initial_setup_completed():
    state = load_json(SETUP_STATE_FILE, {})
    return isinstance(state, dict) and state.get("completed") is True


def run_setup_wizard():
    if not SETUP_SCRIPT.is_file():
        log_error(f"找不到首次运行向导：{SETUP_SCRIPT}")
        return False

    log_info("首次运行设置尚未完成，正在打开程序路径向导")
    try:
        result = subprocess.run(
            [sys.executable, str(SETUP_SCRIPT)],
            cwd=str(BASE_DIR),
            check=False,
        )
    except OSError as error:
        log_error(f"无法启动首次运行向导：{error}")
        return False

    if result.returncode != 0:
        log_warning("首次运行向导已取消或保存失败")
        return False

    if not initial_setup_completed():
        log_error("首次运行向导已退出，但未找到有效的完成状态")
        return False

    log_info("首次运行设置已完成")
    return True


def load_json(file_path, default):
    if not file_path.exists():
        return default

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log_error(f"读取 JSON 失败：{file_path}，原因：{e}")
        return default


def is_running_as_admin():
    if platform.system().lower() != "windows":
        return True

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as e:
        log_error(f"检测管理员权限失败：{e}")
        return False


def relaunch_as_admin():
    """使用 UAC 以管理员权限重新启动当前 Python 脚本。"""
    if platform.system().lower() != "windows":
        return False

    try:
        shell_execute = ctypes.windll.shell32.ShellExecuteW
        shell_execute.argtypes = [
            wintypes.HWND,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.c_int
        ]
        shell_execute.restype = wintypes.HINSTANCE

        parameters = subprocess.list2cmdline([
            str(Path(__file__).resolve()),
            *sys.argv[1:]
        ])

        log_info("当前不是管理员权限，正在请求 UAC 提升")
        result = shell_execute(
            None,
            "runas",
            sys.executable,
            parameters,
            str(BASE_DIR),
            1
        )

        result_code = int(result) if result else 0
        if result_code <= 32:
            log_error(f"管理员权限提升失败或被取消，ShellExecuteW={result_code}")
            return False

        return True
    except Exception as e:
        log_error(f"管理员权限提升失败：{e}")
        return False


def clear_stop_request():
    try:
        if STOP_FILE.exists():
            STOP_FILE.unlink()
    except OSError as e:
        log_warning(f"清理停止请求失败：{e}")


def check_stop_requested():
    if STOP_FILE.exists():
        raise StopRequested("用户请求停止 TimedLauncher")


def wait_interruptibly(seconds):
    seconds = float(seconds)
    if seconds < 0:
        raise ValueError("等待时间不能为负数")

    deadline = time.monotonic() + seconds
    while True:
        check_stop_requested()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.5, remaining))


def find_processes_by_path(executable_path):
    """使用 psutil 按完整可执行文件路径查找进程。"""
    if psutil is None:
        raise RuntimeError("内置运行环境缺少 psutil，请重新下载并完整解压 Release 包")

    target_path = os.path.normcase(
        os.path.realpath(os.path.abspath(str(executable_path)))
    )
    matches = []

    for process in psutil.process_iter(["pid", "exe"]):
        try:
            actual_path = process.info.get("exe")
            if not actual_path:
                continue

            actual_path = os.path.normcase(
                os.path.realpath(os.path.abspath(actual_path))
            )
            if actual_path == target_path:
                matches.append({
                    "pid": process.info["pid"],
                    "path": process.info["exe"]
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return matches


def wait_for_process_exit(
    executable_path,
    start_timeout,
    exit_timeout,
    stable_seconds
):
    """确认目标进程已启动，再等待其退出并持续保持关闭状态。"""
    if not os.path.isfile(executable_path):
        raise RuntimeError(f"等待的程序不存在：{executable_path}")

    start_deadline = time.monotonic() + start_timeout
    log_info(f"等待程序启动：{executable_path}，超时={start_timeout}s")

    while True:
        check_stop_requested()
        matches = find_processes_by_path(executable_path)
        if matches:
            pids = [item["pid"] for item in matches]
            log_info(f"已检测到目标程序启动：PID={pids}")
            break

        if time.monotonic() >= start_deadline:
            raise RuntimeError(f"等待程序启动超时：{executable_path}")
        wait_interruptibly(1)

    exit_deadline = time.monotonic() + exit_timeout
    absent_since = None
    log_info(f"等待程序退出：{executable_path}，超时={exit_timeout}s")

    while True:
        check_stop_requested()
        matches = find_processes_by_path(executable_path)
        now = time.monotonic()

        if matches:
            absent_since = None
        else:
            if absent_since is None:
                absent_since = now
                log_info(f"目标程序已经退出，开始确认 {stable_seconds}s 稳定等待")

            if now - absent_since >= stable_seconds:
                log_info(f"目标程序已连续关闭 {stable_seconds}s，继续后续流程")
                return

        if now >= exit_deadline:
            raise RuntimeError(f"等待程序退出超时：{executable_path}")
        wait_interruptibly(1)


def acquire_single_instance():
    """创建独占锁，避免重复启动同一套自动化流程。"""
    global LOCK_HELD

    for _ in range(2):
        try:
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            LOCK_HELD = True
            return True
        except FileExistsError:
            try:
                old_pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                old_pid = None

            if old_pid and is_process_running(old_pid):
                log_warning(f"TimedLauncher 已在运行，PID={old_pid}")
                return False

            try:
                LOCK_FILE.unlink()
            except OSError as e:
                log_error(f"无法清理失效锁文件：{LOCK_FILE}，原因：{e}")
                return False
        except OSError as e:
            log_error(f"创建锁文件失败：{LOCK_FILE}，原因：{e}")
            return False

    return False


def release_single_instance():
    global LOCK_HELD

    if not LOCK_HELD:
        return

    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except OSError as e:
        log_warning(f"删除锁文件失败：{LOCK_FILE}，原因：{e}")
    finally:
        LOCK_HELD = False


def parse_duration(duration_text):
    """
    支持格式：
    00:00:10
    00:05:00
    01:00:00
    """
    hour, minute, second = map(int, str(duration_text).split(":"))
    return timedelta(hours=hour, minutes=minute, seconds=second)


def launch_program(task):
    program_path = task.get("path")
    args = task.get("args", [])
    show_console = bool(task.get("show_console", False))

    if not program_path:
        log_error(f"任务缺少 path：{task.get('name')}")
        return None

    program_path = str(program_path)

    if not os.path.exists(program_path):
        log_error(f"程序不存在：{program_path}")
        return None

    if not isinstance(args, list):
        log_error(f"args 必须是数组：{task.get('name')}")
        return None
    args = [str(arg) for arg in args]

    working_dir = task.get("working_dir")
    if working_dir:
        cwd = working_dir
    else:
        cwd = str(Path(program_path).parent)

    if not os.path.isdir(cwd):
        log_error(f"工作目录不存在：{cwd}")
        return None

    try:
        log_info(f"启动任务：{task.get('name')}")
        log_info(f"程序路径：{program_path}")
        log_info(f"工作目录：{cwd}")

        creationflags = 0
        stdin_target = subprocess.DEVNULL
        stdout_target = subprocess.DEVNULL
        stderr_target = subprocess.DEVNULL

        if platform.system().lower() == "windows":
            if show_console:
                creationflags = (
                    subprocess.CREATE_NEW_PROCESS_GROUP |
                    subprocess.CREATE_NEW_CONSOLE
                )
                stdin_target = None
                stdout_target = None
                stderr_target = None
            else:
                creationflags = (
                    subprocess.CREATE_NEW_PROCESS_GROUP |
                    subprocess.DETACHED_PROCESS
                )

        process = subprocess.Popen(
            [program_path] + args,
            cwd=cwd,
            stdin=stdin_target,
            stdout=stdout_target,
            stderr=stderr_target,
            creationflags=creationflags
        )

        log_info(f"启动成功：{task.get('name')}，PID={process.pid}")
        return process

    except Exception as e:
        log_error(f"启动失败：{task.get('name')}，原因：{e}")
        return None


def get_process_pid(process_or_pid):
    if isinstance(process_or_pid, subprocess.Popen):
        return process_or_pid.pid
    return int(process_or_pid)


def is_process_running(process_or_pid):
    if isinstance(process_or_pid, subprocess.Popen):
        return process_or_pid.poll() is None

    pid = get_process_pid(process_or_pid)
    if psutil is None:
        return False

    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def close_process(process_or_pid, force=False):
    pid = get_process_pid(process_or_pid)
    system_name = platform.system().lower()

    try:
        if not is_process_running(process_or_pid):
            log_info(f"进程已经退出：PID={pid}")
            return True

        log_info(f"准备关闭进程：PID={pid}，force={force}")

        if system_name == "windows":
            cmd = ["taskkill", "/PID", str(pid), "/T"]

            if force:
                cmd.append("/F")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="gbk",
                errors="ignore"
            )

            if result.returncode == 0:
                if isinstance(process_or_pid, subprocess.Popen):
                    try:
                        process_or_pid.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                log_info(f"关闭成功：PID={pid}")
                return True

            log_warning(f"关闭失败：PID={pid}，输出：{result.stderr or result.stdout}")
            return False

        if isinstance(process_or_pid, subprocess.Popen):
            if force:
                process_or_pid.kill()
            else:
                process_or_pid.terminate()
        elif force:
            os.kill(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGTERM)

        log_info(f"关闭成功：PID={pid}")
        return True

    except Exception as e:
        log_error(f"关闭进程失败：PID={pid}，原因：{e}")
        return False


def activate_window(window_title=None, pid=None, quiet=False):
    """按 PID 和可选标题筛选窗口，并安全地将其置于前台。"""
    if not window_title and not pid:
        return True

    try:
        user32 = None

        if platform.system().lower() == "windows":
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            enum_windows_proc = ctypes.WINFUNCTYPE(
                wintypes.BOOL,
                wintypes.HWND,
                wintypes.LPARAM
            )

            user32.EnumWindows.argtypes = [enum_windows_proc, wintypes.LPARAM]
            user32.EnumWindows.restype = wintypes.BOOL
            user32.GetWindowThreadProcessId.argtypes = [
                wintypes.HWND,
                ctypes.POINTER(wintypes.DWORD)
            ]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            user32.IsWindowVisible.argtypes = [wintypes.HWND]
            user32.IsWindowVisible.restype = wintypes.BOOL
            user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [
                wintypes.HWND,
                wintypes.LPWSTR,
                ctypes.c_int
            ]
            user32.GetWindowTextW.restype = ctypes.c_int
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.BringWindowToTop.argtypes = [wintypes.HWND]
            user32.BringWindowToTop.restype = wintypes.BOOL
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = wintypes.HWND

        if pid and user32:
            found_windows = []
            title_filter = str(window_title).casefold() if window_title else None

            @enum_windows_proc
            def enum_callback(hwnd, _lparam):
                process_id = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))

                if process_id.value != int(pid) or not user32.IsWindowVisible(hwnd):
                    return True

                title_length = user32.GetWindowTextLengthW(hwnd)
                if title_length <= 0:
                    return True

                title_buffer = ctypes.create_unicode_buffer(title_length + 1)
                user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
                title = title_buffer.value

                if title_filter and title_filter not in title.casefold():
                    return True

                found_windows.append((hwnd, title))
                return False

            user32.EnumWindows(enum_callback, 0)

            if found_windows:
                hwnd, title = found_windows[0]
                user32.ShowWindow(hwnd, 9)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                wait_interruptibly(0.5)

                if user32.GetForegroundWindow() == hwnd:
                    if not quiet:
                        log_info(f"已激活进程窗口：{title}，PID={pid}")
                    return True

        if window_title:
            import pygetwindow as gw

            windows = gw.getWindowsWithTitle(window_title)
            if windows:
                window = windows[0]

                if window.isMinimized:
                    window.restore()

                window.activate()
                wait_interruptibly(0.5)

                hwnd = getattr(window, "_hWnd", None)
                if not user32 or not hwnd or user32.GetForegroundWindow() == hwnd:
                    if not quiet:
                        log_info(f"已激活窗口：{window.title}")
                    return True

    except StopRequested:
        raise
    except Exception as e:
        if not quiet:
            log_warning(f"激活窗口失败：title={window_title}, PID={pid}，原因：{e}")
        return False

    if not quiet:
        log_warning(f"没有找到或无法激活目标窗口：title={window_title}, PID={pid}")
    return False


def execute_key_action(action, target_pid=None):
    """
    mode = press  ：普通按键，可以逐个按 keys
    mode = hotkey ：组合键，例如 ctrl+s
    mode = write  ：输入文本，使用 text 字段
    """
    try:
        import pyautogui

        window_title = action.get("window_title")
        if not target_pid and not window_title:
            log_error("按键动作缺少 target 或 window_title，已跳过")
            return False

        mode = action.get("mode", "press")
        keys = action.get("keys", [])
        repeat = int(action.get("repeat", 1))
        interval = float(action.get("interval", 0.2))
        window_timeout = float(action.get("window_timeout", 15))

        if repeat < 1:
            log_error("repeat 必须大于等于 1")
            return False
        if interval < 0 or window_timeout < 0:
            log_error("interval 和 window_timeout 不能为负数")
            return False

        deadline = time.monotonic() + window_timeout
        while not activate_window(
            window_title=window_title,
            pid=target_pid,
            quiet=True
        ):
            check_stop_requested()
            if time.monotonic() >= deadline:
                log_error(
                    f"等待目标窗口超时，跳过按键：PID={target_pid}, "
                    f"title={window_title}, timeout={window_timeout}s"
                )
                return False
            wait_interruptibly(0.5)

        log_info(f"目标窗口已激活：PID={target_pid}, title={window_title}")

        log_info(f"执行按键动作：mode={mode}，keys={keys}，repeat={repeat}")

        for i in range(repeat):
            check_stop_requested()

            if mode == "hotkey":
                if not keys:
                    log_warning("hotkey 模式缺少 keys")
                    return False
                pyautogui.hotkey(*keys)

            elif mode == "press":
                if not keys:
                    log_warning("press 模式缺少 keys")
                    return False
                for key in keys:
                    pyautogui.press(key)

            elif mode == "write":
                text = action.get("text", "")
                write_interval = float(action.get("write_interval", 0.02))
                if write_interval < 0:
                    log_warning("write_interval 不能为负数")
                    return False
                pyautogui.write(text, interval=write_interval)

            else:
                log_warning(f"未知按键模式：{mode}")
                return False

            if i < repeat - 1:
                wait_interruptibly(interval)

        log_info("按键动作执行完成")
        return True

    except StopRequested:
        raise
    except ImportError:
        log_error("缺少依赖：请安装 pyautogui 和 pygetwindow")
        return False

    except Exception as e:
        log_error(f"按键动作执行失败：{e}")
        return False


def run_workflow(task, start_at=None):
    """
    顺序执行 steps。
    每一步执行完，才进入下一步。
    """
    log_info(f"开始执行流程：{task.get('name')}")

    process_map = {}
    skipped_processes = set()

    all_steps = task.get("steps", [])
    setup_paths = {}
    for configured_step in all_steps:
        if not isinstance(configured_step, dict):
            continue
        setup_key = configured_step.get("setup_key")
        if setup_key and setup_key not in setup_paths:
            setup_paths[setup_key] = str(configured_step.get("path") or "").strip()

    steps = all_steps

    if start_at:
        start_index = None
        for index, step in enumerate(steps):
            if not isinstance(step, dict) or step.get("type") != "launch":
                continue
            alias = step.get("save_as") or step.get("name")
            if alias == start_at or step.get("name") == start_at:
                start_index = index
                break

        if start_index is None:
            raise RuntimeError(f"没有找到启动起点：{start_at}")

        steps = steps[start_index:]
        log_info(f"本次从指定步骤开始：{start_at}")

    completed = False

    try:
        for index, step in enumerate(steps, start=1):
            check_stop_requested()

            if not isinstance(step, dict):
                raise RuntimeError(f"第 {index} 步必须是 JSON 对象")

            step_type = step.get("type")

            required_aliases = step.get("requires", [])
            if isinstance(required_aliases, str):
                required_aliases = [required_aliases]
            if not isinstance(required_aliases, list):
                raise RuntimeError("requires 必须是字符串或数组")

            skipped_requirements = [
                alias for alias in required_aliases if alias in skipped_processes
            ]
            if skipped_requirements:
                log_info(
                    f"跳过第 {index} 步：依赖程序未配置 "
                    f"({', '.join(skipped_requirements)})"
                )
                continue

            log_info(f"执行第 {index} 步：{step_type}")

            if step_type == "launch":
                launch_task = {
                    "name": step.get("name"),
                    "path": step.get("path"),
                    "args": step.get("args", []),
                    "working_dir": step.get("working_dir", ""),
                    "show_console": step.get("show_console", False)
                }
                save_as = step.get("save_as") or step.get("name")
                if not save_as:
                    raise RuntimeError("launch 步骤缺少 save_as 或 name")
                if save_as in process_map or save_as in skipped_processes:
                    raise RuntimeError(f"重复的进程别名：{save_as}")

                required_setup_keys = step.get("requires_setup_keys", [])
                if isinstance(required_setup_keys, str):
                    required_setup_keys = [required_setup_keys]
                if not isinstance(required_setup_keys, list):
                    raise RuntimeError("requires_setup_keys 必须是字符串或数组")

                missing_setup_keys = [
                    key for key in required_setup_keys if not setup_paths.get(key)
                ]
                if not str(step.get("path") or "").strip() or missing_setup_keys:
                    skipped_processes.add(save_as)
                    missing_text = ", ".join(missing_setup_keys) or "程序路径"
                    log_info(
                        f"未配置完整路径，跳过程序及其关联步骤："
                        f"{step.get('name')}（缺少：{missing_text}）"
                    )
                    continue

                process = launch_program(launch_task)
                if process is None:
                    raise RuntimeError(f"启动失败：{step.get('name')}")

                process_map[save_as] = process
                log_info(f"已记录进程：{save_as}，PID={process.pid}")

            elif step_type == "wait":
                duration_text = step.get("duration", "00:00:00")
                wait_seconds = parse_duration(duration_text).total_seconds()

                log_info(f"等待 {duration_text}")
                wait_interruptibly(wait_seconds)

            elif step_type == "wait_process_exit":
                executable_path = step.get("path")
                if not executable_path:
                    log_info("监测程序路径未配置，已跳过该等待步骤")
                    continue

                start_timeout = parse_duration(
                    step.get("start_timeout", "00:05:00")
                ).total_seconds()
                exit_timeout = parse_duration(
                    step.get("exit_timeout", "04:00:00")
                ).total_seconds()
                stable_seconds = parse_duration(
                    step.get("after_exit", "00:00:10")
                ).total_seconds()

                wait_for_process_exit(
                    executable_path=executable_path,
                    start_timeout=start_timeout,
                    exit_timeout=exit_timeout,
                    stable_seconds=stable_seconds
                )

            elif step_type == "key":
                target = step.get("target")
                if target in skipped_processes:
                    log_info(f"目标程序未配置，已跳过按键：{target}")
                    continue
                if target and target not in process_map:
                    raise RuntimeError(f"按键目标不存在：{target}")
                target_process = process_map.get(target) if target else None
                target_pid = target_process.pid if target_process else None
                action = {
                    "mode": step.get("mode", "press"),
                    "keys": step.get("keys", []),
                    "text": step.get("text", ""),
                    "repeat": step.get("repeat", 1),
                    "interval": step.get("interval", 0.2),
                    "window_title": step.get("window_title", ""),
                    "window_timeout": step.get("window_timeout", 15)
                }

                log_info(f"执行按键：target={target}, action={action}")
                if not execute_key_action(action, target_pid=target_pid):
                    raise RuntimeError(f"按键执行失败：target={target}")

            elif step_type == "close":
                target = step.get("target")
                if target in skipped_processes:
                    log_info(f"目标程序未配置，已跳过关闭动作：{target}")
                    continue
                force_close = step.get("force_close", False)
                process = process_map.get(target)

                if process is None:
                    raise RuntimeError(f"没有找到要关闭的目标：{target}")

                if is_process_running(process):
                    if not close_process(process, force=force_close):
                        raise RuntimeError(f"关闭失败：{target}，PID={process.pid}")
                else:
                    log_info(f"目标程序已经退出：{target}，PID={process.pid}")

            else:
                raise RuntimeError(f"未知步骤类型：{step_type}")

        completed = True
        log_info(f"流程执行完成：{task.get('name')}")
    finally:
        if not completed:
            log_warning(f"流程异常，清理已启动的程序：{task.get('name')}")
            for name, process in process_map.items():
                if not is_process_running(process):
                    continue

                log_warning(f"清理异常流程中的进程：{name}，PID={process.pid}")
                close_process(process, force=False)
                time.sleep(0.5)
                if is_process_running(process):
                    close_process(process, force=True)


def main():
    parser = argparse.ArgumentParser(description="TimedLauncher")
    parser.add_argument(
        "--start-at",
        help="从指定 launch 步骤的 save_as 或 name 开始执行"
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="打开程序路径设置向导后退出"
    )
    options = parser.parse_args()

    if options.setup:
        return 0 if run_setup_wizard() else 1

    if not initial_setup_completed() and not run_setup_wizard():
        return 1

    if not is_running_as_admin():
        if relaunch_as_admin():
            return
        raise SystemExit(1)

    if not acquire_single_instance():
        return 1

    clear_stop_request()

    try:
        log_info("TimedLauncher 已启动：打开即执行模式")
        log_info("管理员权限：已启用")
        log_info(f"项目目录：{BASE_DIR}")
        log_info(f"配置文件：{CONFIG_FILE}")

        tasks = load_json(CONFIG_FILE, [])
        if not isinstance(tasks, list):
            log_error("tasks.json 顶层必须是数组")
            return 1

        stopped = False
        failed = False

        for task in tasks:
            if not isinstance(task, dict):
                log_error("tasks.json 中存在非对象任务，已跳过")
                continue

            try:
                if not task.get("enabled", True):
                    continue

                if not task.get("run_on_start", False):
                    continue

                if "steps" not in task or not isinstance(task["steps"], list):
                    log_warning(f"任务缺少有效 steps，已跳过：{task.get('name')}")
                    continue

                run_workflow(task, start_at=options.start_at)

            except StopRequested as e:
                log_info(str(e))
                stopped = True
                break
            except Exception as e:
                log_error(f"流程执行失败：{task.get('name')}，原因：{e}")
                failed = True

        if stopped:
            log_info("TimedLauncher 已按用户请求安全停止")
        elif failed:
            log_error("一个或多个流程执行失败，TimedLauncher 以错误状态退出")
        else:
            log_info("所有启动即执行流程已完成，TimedLauncher 自动退出")
        return 1 if failed else 0
    finally:
        clear_stop_request()
        release_single_instance()


if __name__ == "__main__":
    raise SystemExit(main())
