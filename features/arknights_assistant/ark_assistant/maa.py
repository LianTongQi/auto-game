"""Inspect installed MAA files or load its version export; NEVER connect ADB."""
import ctypes
import json
import os
import platform
from pathlib import Path

from .model import read_json


def load_settings(root):
    path = Path(root) / "config" / "local.json"
    settings = {"analysis_only": True, "maa_dir": "", "python_path": ""}
    if path.exists():
        if path.stat().st_size > 16384:
            raise ValueError("本地配置文件过大")
        data = read_json(path)
        if not isinstance(data, dict):
            raise ValueError("本地配置格式无效")
        settings.update({key: data[key] for key in settings if key in data})
    if settings["analysis_only"] is not True:
        raise ValueError("本原型只支持 analysis_only=true，不允许开启游戏执行")
    return settings


def resource_maps(maa_dir):
    names, stages = {}, {}
    if not maa_dir:
        return names, stages
    root = Path(maa_dir) / "resource"
    battle = root / "battle_data.json"
    if battle.exists():
        data = read_json(battle)
        chars = data.get("chars", {})
        if isinstance(chars, dict):
            names = {key: value["name"] for key, value in chars.items()
                     if isinstance(value, dict) and isinstance(value.get("name"), str)}
    index = root / "stages.json"
    if index.exists():
        rows = read_json(index)
        if not isinstance(rows, list):
            raise ValueError("MAA 关卡资源格式已变化，停止关卡别名映射")
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("stageId"), str) and isinstance(row.get("code"), str):
                stages[row["stageId"]] = row["code"]
    overview = root / "Arknights-Tile-Pos" / "overview.json"
    if overview.exists():
        data = read_json(overview)
        if not isinstance(data, dict):
            raise ValueError("MAA 地图总览格式已变化")
        for row in data.values():
            if isinstance(row, dict) and isinstance(row.get("stageId"), str) and isinstance(row.get("code"), str):
                stages[row["stageId"]] = row["code"]
    return names, stages


def doctor(maa_dir, probe=False):
    if not maa_dir:
        return {"status": "NOT_CONFIGURED", "game_connected": False,
                "note": "尚未配置 MAA 路径；演示和本地 JSON 分析仍可使用"}
    root = Path(maa_dir).resolve()
    required = ["MaaCore.dll", "resource/battle_data.json", "resource/stages.json", "Python/asst/asst.py"]
    missing = [name for name in required if not (root / name).is_file()]
    result = {"status": "FILES_OK" if not missing else "MISSING_FILES", "missing": missing,
              "game_connected": False, "task_submitted": False, "version_probed": False,
              "note": "只检查文件；未启动 MAA、模拟器或游戏，未连接 ADB"}
    if probe and not missing:
        if platform.system() != "Windows" or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise ValueError("本机 MaaCore 探测需要 Windows 64 位 Python")
        # Exact installed DLL + exact dependency directory. Do not fallback to
        # global DLL search, import sample.py, run its updater, or load resources.
        with os.add_dll_directory(str(root)):
            lib = ctypes.WinDLL(str(root / "MaaCore.dll"))
            lib.AsstGetVersion.restype = ctypes.c_char_p
            lib.AsstGetVersion.argtypes = ()
            version = lib.AsstGetVersion()
            if not version:
                raise ValueError("MaaCore 未返回版本")
            result.update(status="VERSION_PROBE_OK", version=version.decode("utf-8"), version_probed=True)
            result["note"] = "原生 MaaCore 版本接口已验证；未创建实例、未连接设备、未提交任务"
    return result
