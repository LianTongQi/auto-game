"""Import a completed local MAA OperBox scan without connecting to a game."""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from .model import normalize_inventory, read_json

HEADER = re.compile(r"^\[([0-9 :.-]+)\].*?\[(Px[0-9]+)\].*?Assistant::append_callback \| (\w+) (\{.*\})$")
ROLES = {"PIONEER": "vanguard", "WARRIOR": "guard", "TANK": "defender", "SNIPER": "sniper",
         "CASTER": "caster", "MEDIC": "medic", "SUPPORT": "supporter", "SPECIAL": "specialist"}


def completed_operbox(path, now=None, max_age_hours=24):
    path = Path(path)
    if path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError("日志超过读取上限，请先选择较小的本轮日志")
    snapshots, latest = {}, None
    with path.open(encoding="utf-8-sig", errors="replace") as stream:
        for line in stream:
            if "Assistant::append_callback" not in line or '"taskchain":"OperBox"' not in line:
                continue
            match = HEADER.fullmatch(line.rstrip("\r\n"))
            if not match:
                continue
            stamp, pid, kind, body = match.groups()
            try:
                event = json.loads(body)
                task_id = event["taskid"]
                if isinstance(task_id, bool) or not isinstance(task_id, int):
                    continue
                key = (pid, task_id)
                timestamp = datetime.fromisoformat(stamp)
            except (ValueError, KeyError, TypeError):
                continue
            if kind == "SubTaskExtraInfo" and event.get("what") == "OperBoxInfo":
                details = event.get("details", {})
                if details.get("done") is True:
                    snapshots[key] = (timestamp, details)
            elif kind in ("TaskChainError", "TaskChainStopped"):
                snapshots.pop(key, None)
            elif kind == "TaskChainCompleted" and key in snapshots:
                candidate = snapshots.pop(key)
                if latest is None or candidate[0] > latest[0]:
                    latest = candidate
    if latest is None:
        raise ValueError("没有找到 done=true 且对应任务最终完成的干员扫描")
    now = now or datetime.now()
    if now - latest[0] > timedelta(hours=max_age_hours) or latest[0] > now + timedelta(minutes=5):
        raise ValueError("干员扫描已过期或时间异常；不能当成当前账号状态")
    return latest


def import_operbox(path, maa_dir, now=None):
    stamp, details = completed_operbox(path, now=now)
    battle = read_json(Path(maa_dir) / "resource" / "battle_data.json")
    chars = battle.get("chars", {})
    if not isinstance(chars, dict):
        raise ValueError("MAA 干员资源格式已变化")
    rows = details.get("own_opers")
    if not isinstance(rows, list) or not rows:
        raise ValueError("完成的扫描缺少 own_opers 练度列表")
    clean = []
    for row in rows:
        if not isinstance(row, dict) or row.get("own") is not True:
            continue
        metadata = chars.get(row.get("id"))
        if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str):
            raise ValueError("扫描中存在本机资源不认识的干员 ID，停止导入")
        role = ROLES.get(metadata.get("profession"))
        if role is None:
            raise ValueError("本机资源中存在未支持的干员职业，停止导入")
        item = {"name": metadata["name"], "role": role}
        for field in ("elite", "level", "potential"):
            if field in row:
                item[field] = row[field]
        # OperBox does NOT prove mastery/module state. Never fill defaults.
        clean.append(item)
    inventory = normalize_inventory({"source": "本机 MAA 已完成扫描", "operators": clean})
    inventory["scan_time"] = stamp.isoformat()
    inventory["scan_warning"] = "仅复用已识别练度；专精、模组、活动解锁和当前账号仍未核验"
    return inventory
