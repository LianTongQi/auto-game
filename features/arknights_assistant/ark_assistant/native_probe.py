"""Native copilot parser preflight. NEVER connect, start, or run a task."""
import ctypes
import json
import os
import platform
import re
from pathlib import Path

from .model import normalize_job, read_json


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?[0-9]+\.[0-9]+\.[0-9]+", value):
        raise ValueError("最低/本机 MAA 版本不是稳定版本格式，请人工核验")
    return tuple(int(part) for part in value.lstrip("v").split("."))


def copilot_preflight(maa_dir, job_path, user_dir):
    raw = read_json(job_path)
    normalized = normalize_job(raw)
    required = version_tuple(raw.get("minimum_required"))
    if platform.system() != "Windows" or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise ValueError("原生解析检查需要 Windows 64 位 Python")
    root = Path(maa_dir).resolve()
    user_dir = Path(user_dir).resolve()
    user_dir.mkdir(parents=True, exist_ok=False)
    with os.add_dll_directory(str(root)):
        lib = ctypes.WinDLL(str(root / "MaaCore.dll"))
        signatures = {
            "AsstGetVersion": (ctypes.c_char_p, ()),
            "AsstSetUserDir": (ctypes.c_bool, (ctypes.c_char_p,)),
            "AsstLoadResource": (ctypes.c_bool, (ctypes.c_char_p,)),
            "AsstCreate": (ctypes.c_void_p, ()),
            "AsstSetInstanceOption": (ctypes.c_bool, (ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p)),
            "AsstAppendTask": (ctypes.c_int, (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p)),
            "AsstDestroy": (None, (ctypes.c_void_p,)),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(lib, name)
            function.restype, function.argtypes = result, arguments
        actual = lib.AsstGetVersion().decode("utf-8")
        if version_tuple(actual) < required:
            raise ValueError("作业要求的 MAA 版本高于本机版本")
        if not lib.AsstSetUserDir(str(user_dir).encode("utf-8")):
            raise ValueError("无法设置独立检查日志目录")
        if not lib.AsstLoadResource(str(root).encode("utf-8")):
            raise ValueError("本机 MAA 资源加载失败")
        handle = lib.AsstCreate()
        if not handle:
            raise ValueError("无法创建原生检查实例")
        try:
            if not lib.AsstSetInstanceOption(handle, 5, b"0"):
                raise ValueError("无法确保检查实例退出时保留既有 ADB 进程")
            params = {"filename": str(Path(job_path).resolve()), "loop_times": 1,
                      "formation": False, "use_sanity_potion": False, "ignore_requirements": False}
            task_id = lib.AsstAppendTask(handle, b"Copilot", json.dumps(params).encode("utf-8"))
        finally:
            lib.AsstDestroy(handle)
    return {"status": "NATIVE_ACCEPTED" if task_id > 0 else "NATIVE_REJECTED",
            "stage": normalized["stage_name"], "maa_version": actual,
            "queued_task_id": task_id, "game_connected": False, "task_started": False,
            "notice": "仅本机解析预检，队列已销毁；不是导航、编队或通关成功"}
