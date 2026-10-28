"""Normalize account exports, evaluate copilot requirements, and plan deficits."""
import json
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024


def read_json(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("JSON 文件超过 8 MB，未导入")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def number(value, name, minimum=0, maximum=10**9):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须是 {minimum}～{maximum} 范围内的整数")
    return value


def label(value, name="名称"):
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError(f"{name} 必须是非空短文本")
    if any(ord(c) < 32 for c in value):
        raise ValueError(f"{name} 含控制字符")
    return value.strip()


def normalize_inventory(raw, name_map=None):
    """Whitelist fields only: credentials/account identifiers are never retained."""
    name_map = name_map or {}
    root = raw if isinstance(raw, dict) else {}
    demo = root.get("is_demo") is True
    source = root.get("source", "用户导入")
    if isinstance(raw, list):
        rows, owned_only = raw, True
    elif isinstance(root.get("operators"), list):
        rows, owned_only = root["operators"], True
    elif isinstance(root.get("own_opers"), list):
        rows, owned_only = root["own_opers"], True
    elif isinstance(root.get("all_opers"), list):
        rows, owned_only = root["all_opers"], False
    else:
        raise ValueError("需包含 operators / own_opers / all_opers 数组，或干员名称数组")
    if len(rows) > 2000:
        raise ValueError("干员数量超过支持上限")
    operators = []
    used = set()
    for row in rows:
        row = {"name": row} if isinstance(row, str) else row
        if not isinstance(row, dict):
            raise ValueError("干员条目必须是名称或对象")
        if row.get("own") is False or (not owned_only and row.get("own") is not True):
            continue
        name = row.get("name") or name_map.get(row.get("id"))
        name = label(name, "干员名称；未知 ID 需要本机 MAA 数据映射")
        role = row.get("role", "")
        if role:
            role = label(role, "干员职业").lower()
        key = (name, role)
        if key in used:
            raise ValueError(f"重复干员：{name}；请先核对导入文件")
        used.add(key)
        op = {"name": name, "role": role}
        for field, maximum in (("elite", 2), ("level", 90), ("potential", 6), ("skill_level", 7)):
            if row.get(field) is not None:
                op[field] = number(row[field], field, 0 if field == "elite" else 1, maximum)
        skills = row.get("skills", {})
        modules = row.get("modules", {})
        if not isinstance(skills, dict) or not isinstance(modules, dict):
            raise ValueError("skills/modules 请使用编号到等级的对象格式")
        op["skills"] = {str(number(int(k), "技能编号", 1, 3)): number(v, "技能等级", 1, 10)
                        for k, v in skills.items()}
        op["modules"] = {str(number(int(k), "模组编号", 1, 5)): number(v, "模组等级", 0, 3)
                         for k, v in modules.items()}
        operators.append(op)
    materials = root.get("materials", {})
    if not isinstance(materials, dict) or len(materials) > 2000:
        raise ValueError("materials 必须是材料 ID 到数量的对象")
    return {"schema_version": 1, "is_demo": demo, "source": label(source, "数据来源"),
            "operators": operators,
            "materials": {label(str(k), "材料 ID"): number(v, "库存数量") for k, v in materials.items()}}


def normalize_job(raw, source="本地作业"):
    if not isinstance(raw, dict):
        raise ValueError("作业必须是对象")
    # API content is JSON, never executable code or markup.
    if "content" in raw:
        content = raw["content"]
        if isinstance(content, str):
            content = json.loads(content)
        raw = {**content, "source_id": str(raw.get("id", ""))}
    stage = label(raw.get("stage_name"), "关卡标识")
    actions = raw.get("actions")
    if not isinstance(actions, list) or not actions or len(actions) > 5000:
        raise ValueError("不是完整的可执行 MAA 作业：缺少非空 actions 数组")
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("作业动作格式无效")
    opers, groups = raw.get("opers", []), raw.get("groups", [])
    if not isinstance(opers, list) or not isinstance(groups, list) or len(opers) + len(groups) > 30:
        raise ValueError("作业干员/替换组格式或数量无效")
    for requirement in opers:
        validate_requirement(requirement)
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("opers"), list) or not group["opers"]:
            raise ValueError("替换组不能为空")
        label(group.get("name"), "替换组名称")
        if len(group["opers"]) > 100:
            raise ValueError("替换组过大")
        for requirement in group["opers"]:
            validate_requirement(requirement)
    doc = raw.get("doc", {})
    title = doc.get("title", stage) if isinstance(doc, dict) else stage
    return {"stage_name": stage, "title": label(title or stage, "作业标题"),
            "source": source, "source_id": str(raw.get("source_id", ""))[:64],
            "is_demo": raw.get("is_demo") is True, "opers": opers, "groups": groups,
            "action_count": len(actions)}


def validate_requirement(req):
    if not isinstance(req, dict):
        raise ValueError("作业干员要求格式无效")
    label(req.get("name"), "作业干员名称")
    if req.get("role"):
        label(req["role"], "作业干员职业")
    if "skill" in req:
        number(req["skill"], "技能序号", 0, 3)
    requirements = req.get("requirements", {})
    if not isinstance(requirements, dict):
        raise ValueError("requirements 必须是对象")
    limits = {"elite": 2, "level": 90, "skill_level": 10, "module": 5, "module_level": 3, "potential": 6}
    for field, maximum in limits.items():
        if field in requirements:
            number(requirements[field], f"作业 {field}", -1, maximum)


def compare(op, req):
    unknown, failed = [], []
    if req.get("role"):
        if not op.get("role"):
            unknown.append("职业未识别")
        elif op["role"].lower() != req["role"].lower():
            return ["职业不匹配"], []
    r = req.get("requirements", {})
    supported = {"elite", "level", "potential", "skill_level", "module", "module_level"}
    unsupported = set(r) - supported
    if unsupported:
        unknown.append("未支持的练度要求：" + "、".join(sorted(unsupported)))
    if not any(isinstance(r.get(field), int) and r[field] >= 0 for field in supported):
        unknown.append("作业未声明练度要求")
    for field in ("elite", "level", "potential"):
        target = r.get(field, -1)
        if target >= 0:
            if field not in op:
                unknown.append(f"{field} 未提供")
            elif op[field] < target:
                failed.append(f"{field} {op[field]} < {target}")
    target = r.get("skill_level", -1)
    if target >= 0:
        skill = str(req.get("skill", 0))
        actual = op.get("skills", {}).get(skill)
        if actual is None and target <= 7:
            actual = op.get("skill_level")
        if actual is None:
            unknown.append(f"技能 {skill} 等级未提供")
        elif actual < target:
            failed.append(f"技能 {skill} {actual} < {target}")
    module = r.get("module", -1)
    if module > 0:
        actual = op.get("modules", {}).get(str(module))
        if actual is None:
            unknown.append(f"模组 {module} 状态未提供")
        elif actual < max(1, r.get("module_level", 1)):
            failed.append(f"模组 {module} 等级不足")
    elif r.get("module_level", -1) > 0:
        unknown.append("模组等级要求没有对应模组编号")
    return failed, unknown


def resolve_stage(stage, stage_map):
    stage = label(stage, "关卡编号")
    if stage in stage_map:
        return stage
    candidates = [key for key, value in stage_map.items() if value.upper() == stage.upper()]
    if len(candidates) > 1:
        raise ValueError(f"{stage} 在不同活动/难度中重号，请填唯一关卡 ID：" + " / ".join(candidates[:6]))
    return candidates[0] if candidates else stage


def match_job(inventory, job, stage=None, stage_map=None):
    stage_map = stage_map or {}
    actual_stage = stage_map.get(job["stage_name"], job["stage_name"])
    if stage:
        target = resolve_stage(stage, stage_map)
        try:
            job_id = resolve_stage(job["stage_name"], stage_map)
        except ValueError:
            job_id = ""
    if stage and job_id.upper() != target.upper():
        return {"title": job["title"], "stage": actual_stage, "status": "WRONG_STAGE",
                "reasons": ["关卡不匹配，未纳入候选"], "assignments": [], "missing_slots": []}
    slots = [(op["name"], [op]) for op in job["opers"]]
    slots += [(group["name"], group["opers"]) for group in job["groups"]]
    options, failures = [], []
    for title, reqs in slots:
        choices, blocked = {}, []
        for req in reqs:
            found = False
            for index, op in enumerate(inventory["operators"]):
                if op["name"] != req["name"]:
                    continue
                found = True
                bad, unknown = compare(op, req)
                if bad:
                    blocked.append(f"{op['name']}：" + "、".join(bad))
                elif index not in choices or len(unknown) < len(choices[index]):
                    choices[index] = unknown
            if not found:
                blocked.append(f"未拥有 {req['name']}")
        options.append(choices)
        failures.append(blocked)
    # Bipartite assignment prevents assigning the same operator to two slots.
    assigned, owners = {}, {}

    def augment(slot, visited, include_unknown):
        for index in sorted(options[slot], key=lambda i: len(options[slot][i])):
            if index in visited or (options[slot][index] and not include_unknown):
                continue
            visited.add(index)
            previous = owners.get(index)
            if previous is None or augment(previous, visited, include_unknown):
                owners[index] = slot
                assigned[slot] = index
                return True
        return False

    order = sorted(range(len(slots)), key=lambda slot: len(options[slot]))
    for slot in order:
        augment(slot, set(), False)
    for slot in order:
        if slot not in assigned:
            augment(slot, set(), True)
    missing, warnings, selections = [], [], []
    for slot, (title, reqs) in enumerate(slots):
        if slot not in assigned:
            missing.append(title)
            warnings.extend(failures[slot] or [f"{title} 与其他位置争用同一干员"])
        else:
            index = assigned[slot]
            op = inventory["operators"][index]
            selections.append({"slot": title, "operator": op["name"], "unknown": options[slot][index]})
            warnings.extend(f"{op['name']}：{reason}" for reason in options[slot][index])
    if not slots:
        warnings.append("作业没有声明编队，必须人工核验")
    if inventory["is_demo"] or job["is_demo"]:
        warnings.append("演示数据，不代表真实账号或实测通关")
    status = "MISSING_REQUIREMENTS" if missing else "NEEDS_REVIEW" if warnings else "CANDIDATE"
    return {"title": job["title"], "stage": actual_stage, "status": status,
            "source_id": job["source_id"], "assignments": selections, "missing_slots": missing,
            "support_hint": "缺一个位置，可人工核对助战" if len(missing) == 1 else "",
            "reasons": warnings,
            "notice": "仅匹配候选，尚未演习或验证通关；不允许自动执行"}


def material_plan(inventory, goals):
    """Goals contain an explicit bill of materials, not guessed game recipes."""
    if not isinstance(goals, dict) or not isinstance(goals.get("materials", {}), dict):
        raise ValueError("养成需求须包含 materials 对象")
    targets = goals.get("targets", [])
    if not isinstance(targets, list) or len(targets) > 100:
        raise ValueError("养成目标须为数组，最多 100 项")
    clean_targets = []
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("养成目标条目格式无效")
        clean = {"name": label(target.get("name"), "目标干员名称")}
        for field, maximum in (("elite", 2), ("level", 90), ("skill", 3), ("skill_level", 10)):
            if field in target:
                clean[field] = number(target[field], field, 0, maximum)
        clean_targets.append(clean)
    rows = []
    for material, count in goals.get("materials", {}).items():
        material = label(str(material), "材料 ID")
        need = number(count, "目标材料数量")
        have = inventory["materials"].get(material)
        rows.append({"id": material, "required": need, "owned": have,
                     "deficit": None if have is None else max(0, need - have),
                     "status": "UNKNOWN_STOCK" if have is None else "SHORTAGE" if have < need else "ENOUGH"})
    return {"items": rows, "targets": clean_targets, "is_demo": goals.get("is_demo") is True,
            "note": "仅根据导入的需求清单计算缺口；未自动生成升级配方，也不会消耗材料"}


def analyze(inventory, jobs, goals=None, stage=None, stage_map=None):
    matches = [match_job(inventory, job, stage, stage_map) for job in jobs]
    rank = {"CANDIDATE": 0, "NEEDS_REVIEW": 1, "MISSING_REQUIREMENTS": 2, "WRONG_STAGE": 3}
    matches.sort(key=lambda row: (rank[row["status"]], len(row["missing_slots"])))
    return {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": "ANALYSIS_ONLY", "execution_enabled": False,
            "is_demo": inventory["is_demo"] or any(job["is_demo"] for job in jobs) or (goals or {}).get("is_demo") is True,
            "operator_count": len(inventory["operators"]), "material_types": len(inventory["materials"]),
            "matches": matches, "materials": material_plan(inventory, goals or {}),
            "policy": {"use_originite": False, "use_sanity_potions": False, "automatic_training": False,
                       "purchase_or_recruit": False, "modify_daily_workflow": False}}
