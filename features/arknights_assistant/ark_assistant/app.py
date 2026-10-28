"""CLI and Chinese desktop interface for the isolated analysis prototype."""
import argparse
import json
import queue
import threading
from datetime import datetime
from pathlib import Path

from .maa import doctor, load_settings, resource_maps
from .maa_logs import import_operbox
from .model import analyze, normalize_inventory, normalize_job, read_json
from .network import get_public_json, search_jobs

ROOT = Path(__file__).resolve().parent.parent
STATUS_NAMES = {"CANDIDATE": "可试验候选（未验证通关）", "NEEDS_REVIEW": "需要核验练度/演示数据",
                "MISSING_REQUIREMENTS": "阵容或练度不满足", "WRONG_STAGE": "关卡不匹配"}


def demo_data():
    folder = ROOT / "examples"
    return (normalize_inventory(read_json(folder / "inventory.demo.json")),
            [normalize_job(read_json(path), "内置演示，非真实攻略") for path in sorted((folder / "jobs").glob("*.json"))],
            read_json(folder / "goals.demo.json"))


def save_report(report):
    folder = ROOT / "runtime" / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("analysis-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return path


def describe(report):
    lines = ["明日方舟助手 · 只读分析原型", "演示数据：不是你的账号" if report["is_demo"] else "用户导入数据：尚未核对游戏实况",
             f"干员 {report['operator_count']} 名；材料 {report['material_types']} 类",
             "游戏执行关闭；不消耗理智、源石、材料，不调整编队。", ""]
    if "scan_time" in report:
        lines.extend(["历史扫描时间：" + report["scan_time"], report["scan_warning"], ""])
    for row in report["matches"]:
        lines.append(f"[{STATUS_NAMES[row['status']]}] {row['title']} / {row['stage']}")
        for choice in row["assignments"]:
            lines.append(f"  {choice['slot']} → {choice['operator']}")
        for reason in row["reasons"]:
            lines.append("  注意：" + reason)
        if row.get("support_hint"):
            lines.append("  " + row["support_hint"])
        lines.append("")
    lines.append("材料需求（来自导入清单，非自动生成配方）")
    for item in report["materials"]["items"]:
        owned = "未知" if item["owned"] is None else str(item["owned"])
        deficit = "待重新识别库存" if item["deficit"] is None else str(item["deficit"])
        lines.append(f"  {item['id']}：需要 {item['required']}，已有 {owned}，缺口 {deficit}")
    if "search" in report:
        lines += ["", f"公开检索：接收 {report['search']['received']} 条；完整作业 {report['search']['accepted']} 条",
                  report["search"]["note"]]
    return "\n".join(lines)


def gui(smoke=False):
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
    settings = load_settings(ROOT)
    names, stages = resource_maps(settings["maa_dir"])
    inventory, jobs, goals = demo_data()
    root = tk.Tk()
    root.title("明日方舟助手 0.1 · 只读原型")
    root.geometry("1000x720")
    top = ttk.Frame(root, padding=12)
    top.pack(fill="x")
    ttk.Label(top, text="干员 / 库存分析与作业匹配", font=("Microsoft YaHei", 16, "bold")).pack(anchor="w")
    ttk.Label(top, text="当前只做分析，未开放自动战斗或养成。演示数据不代表你的账号。").pack(anchor="w", pady=6)
    status = tk.StringVar(value="已加载内置演示；可以导入你自己的 JSON。")
    ttk.Label(root, textvariable=status, wraplength=970).pack(fill="x", padx=12)
    bar = ttk.Frame(root, padding=12)
    bar.pack(fill="x")
    text = scrolledtext.ScrolledText(root, wrap="word", font=("Microsoft YaHei", 10))
    text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    messages = queue.Queue()
    busy = False
    current_report = None
    search_info = None
    stage_text = tk.StringVar(value="")

    def display(value):
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("1.0", value)
        text.configure(state="disabled")

    def safe(function):
        try:
            function()
        except Exception as exc:
            messagebox.showerror("未继续执行", str(exc)[:500])

    def build():
        nonlocal current_report
        current_report = analyze(inventory, jobs, goals, stage_text.get().strip() or None, stages)
        if search_info is not None:
            current_report["search"] = search_info
        display(describe(current_report))

    def restore_demo():
        nonlocal inventory, jobs, goals, search_info
        inventory, jobs, goals = demo_data()
        search_info = None
        stage_text.set("")
        status.set("内置演示，非真实账号；未操作任何游戏。")
        build()

    def import_inventory():
        nonlocal inventory
        path = filedialog.askopenfilename(title="选择干员与库存 JSON", filetypes=[("JSON", "*.json")])
        if path:
            inventory = normalize_inventory(read_json(path), names)
            status.set(f"已导入 {len(inventory['operators'])} 名干员；数据来源：{inventory['source']}")
            build()

    def import_jobs():
        nonlocal jobs, search_info
        paths = filedialog.askopenfilenames(title="选择 MAA 作业 JSON", filetypes=[("JSON", "*.json")])
        if paths:
            parsed = [normalize_job(read_json(path)) for path in paths]
            jobs = parsed
            search_info = None
            status.set(f"已导入 {len(jobs)} 份作业，仅分析不执行。")
            build()

    def import_goals():
        nonlocal goals
        path = filedialog.askopenfilename(title="选择材料需求清单", filetypes=[("JSON", "*.json")])
        if path:
            candidate = read_json(path)
            analyze(inventory, jobs, candidate)
            goals = candidate
            build()

    def background(function, handler):
        nonlocal busy
        if busy:
            messagebox.showinfo("请稍候", "已有一次查询正在运行，不重复发起。")
            return
        busy = True
        status.set("正在只读查询；不会连接游戏或发送账号数据…")

        def work():
            try:
                messages.put((handler, function(), None))
            except Exception as exc:
                messages.put((handler, None, str(exc)[:300]))
        threading.Thread(target=work, daemon=True).start()

    def search():
        stage = stage_text.get().strip()
        if not stage:
            raise ValueError("请先填写关卡编号，例如 1-7")

        def received(result):
            nonlocal jobs, search_info
            jobs, search_info = result
            status.set("公开查询已返回。已排除不完整作业，关卡和练度仍须核验。")
            # Captured requested stage, not whatever the user typed during I/O.
            stage_text.set(stage)
            build()
        background(lambda: search_jobs(stage, stage_map=stages), received)

    def inspect():
        def received(result):
            status.set("MAA 只读检查结束；没有连接游戏。")
            display(json.dumps(result, ensure_ascii=False, indent=2))
        background(lambda: doctor(settings["maa_dir"], probe=True), received)

    def export():
        build()
        path = save_report(current_report)
        status.set("分析报告已保存：" + str(path))

    for caption, function in (("加载演示", restore_demo), ("导入干员/库存", import_inventory),
                               ("导入作业", import_jobs), ("导入材料需求", import_goals),
                               ("生成分析", build), ("保存报告", export), ("检查 MAA", inspect)):
        ttk.Button(bar, text=caption, command=lambda f=function: safe(f)).pack(side="left", padx=3)
    search_bar = ttk.Frame(root, padding=(12, 0, 12, 10))
    search_bar.pack(before=text, fill="x")
    ttk.Label(search_bar, text="关卡编号/唯一 ID：").pack(side="left")
    ttk.Entry(search_bar, textvariable=stage_text, width=20).pack(side="left")
    ttk.Button(search_bar, text="检索公开作业（单页）", command=lambda: safe(search)).pack(side="left", padx=8)
    ttk.Label(search_bar, text="不会上传干员、库存或账号信息").pack(side="left")

    def poll():
        nonlocal busy
        try:
            handler, value, error = messages.get_nowait()
        except queue.Empty:
            pass
        else:
            busy = False
            if error:
                status.set("查询未完成，未重试、未操作游戏。")
                messagebox.showerror("只读查询失败", error)
            else:
                safe(lambda: handler(value))
        root.after(100, poll)
    build()
    root.after(100, poll)
    if smoke:
        root.withdraw()
        root.after(300, root.destroy)
    root.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description="明日方舟只读分析原型；未开放游戏执行")
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("gui")
    p.add_argument("--smoke", action="store_true", help="初始化界面后自动关闭；不操作游戏")
    sub.add_parser("demo")
    p = sub.add_parser("doctor")
    p.add_argument("--maa-dir")
    p.add_argument("--probe", action="store_true")
    p = sub.add_parser("analyze")
    p.add_argument("--inventory", required=True)
    p.add_argument("--jobs", nargs="+", required=True)
    p.add_argument("--goals")
    p.add_argument("--stage")
    p = sub.add_parser("search")
    p.add_argument("--stage", required=True)
    p.add_argument("--inventory", required=True)
    p.add_argument("--limit", type=int, default=10)
    p = sub.add_parser("maa-log", help="导入已完成的本机干员扫描，并可只读检索关卡作业")
    p.add_argument("--log", required=True)
    p.add_argument("--stage")
    p = sub.add_parser("probe-copilot", help="仅验证本机 MaaCore 是否接受作业，不连接/开始任务")
    job_source = p.add_mutually_exclusive_group(required=True)
    job_source.add_argument("--job")
    job_source.add_argument("--job-id", type=int, help="匿名读取一份公开作业，保存到本机检查目录")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(ROOT)
        names, stages = resource_maps(settings["maa_dir"])
        if args.command in (None, "gui"):
            gui(getattr(args, "smoke", False))
            return 0
        if args.command == "doctor":
            print(json.dumps(doctor(args.maa_dir or settings["maa_dir"], args.probe), ensure_ascii=False, indent=2))
            return 0
        if args.command == "probe-copilot":
            from .native_probe import copilot_preflight
            folder = ROOT / "runtime" / "probes" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            job_path = args.job
            if args.job_id is not None:
                if not 1 <= args.job_id <= 10**9:
                    raise ValueError("作业 ID 超出范围")
                payload = get_public_json(f"/copilot/get/{args.job_id}")
                raw = payload.get("content") if isinstance(payload, dict) else None
                raw = json.loads(raw) if isinstance(raw, str) else raw
                normalize_job(raw, "PRTS Plus 公开作业")
                cache = ROOT / "runtime" / "copilots"
                cache.mkdir(parents=True, exist_ok=True)
                job_path = cache / f"{args.job_id}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"
                with job_path.open("x", encoding="utf-8") as stream:
                    json.dump(raw, stream, ensure_ascii=False, indent=2)
            result = copilot_preflight(settings["maa_dir"], job_path, folder)
            result["evidence_time"] = datetime.now().isoformat()
            result_path = save_report(result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("\n检查报告：" + str(result_path))
            return 0 if result["status"] == "NATIVE_ACCEPTED" else 1
        if args.command == "demo":
            report = analyze(*demo_data())
        elif args.command == "analyze":
            inventory = normalize_inventory(read_json(args.inventory), names)
            jobs = [normalize_job(read_json(path)) for path in args.jobs]
            goals = read_json(args.goals) if args.goals else {}
            report = analyze(inventory, jobs, goals, args.stage, stages)
        elif args.command == "maa-log":
            inventory = import_operbox(args.log, settings["maa_dir"])
            jobs, info = search_jobs(args.stage, stage_map=stages) if args.stage else ([], None)
            report = analyze(inventory, jobs, stage=args.stage, stage_map=stages)
            report["scan_time"] = inventory["scan_time"]
            report["scan_warning"] = inventory["scan_warning"]
            if info is not None:
                report["search"] = info
        else:
            inventory = normalize_inventory(read_json(args.inventory), names)
            jobs, info = search_jobs(args.stage, args.limit, stages)
            report = analyze(inventory, jobs, stage=args.stage, stage_map=stages)
            report["search"] = info
        output = save_report(report)
        print(describe(report))
        print("\n报告：" + str(output))
        return 0
    except Exception as exc:
        print("未继续执行：" + str(exc)[:500])
        return 1
