import argparse
import json
import os
import shutil
import sys
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "tasks.json"
STATE_FILE = CONFIG_DIR / "setup_state.json"
BACKUP_DIR = CONFIG_DIR / "backups"
SETUP_VERSION = 1


@dataclass(frozen=True)
class ProgramField:
    key: str
    label: str
    expected_name: str
    description: str
    github_url: str = ""


PROGRAM_FIELDS = (
    ProgramField(
        "bettergi",
        "1. BetterGI",
        "BetterGI.exe",
        "启动后等待 10 秒并按 F10",
        "https://github.com/babalae/better-genshin-impact/releases",
    ),
    ProgramField("genshin", "   原神游戏", "YuanShen.exe", "用于判断 BetterGI 任务完成"),
    ProgramField(
        "march7th",
        "2. March7th Assistant",
        "March7th Assistant.exe",
        "星穹铁道退出后按回车",
        "https://github.com/moesnow/March7thAssistant/releases",
    ),
    ProgramField("starrail", "   星穹铁道游戏", "StarRail.exe", "用于判断 March7th 任务完成"),
    ProgramField(
        "okww",
        "3. OK-WW",
        "ok-ww.exe",
        "保留参数：-t 1 -e",
        "https://github.com/ok-oldking/ok-wuthering-waves/releases",
    ),
    ProgramField(
        "wuthering_client",
        "   鸣潮游戏",
        "Client-Win64-Shipping.exe",
        "用于判断 OK-WW 任务完成",
    ),
    ProgramField(
        "onedragon",
        "4. OneDragon",
        "OneDragon-Launcher.exe",
        "保留参数：-o -c",
        "https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/releases",
    ),
    ProgramField(
        "maaend",
        "5. MaaEnd",
        "MaaEnd.exe",
        "启动后等待 10 秒并按 F10",
        "https://github.com/MaaEnd/MaaEnd/releases",
    ),
)


def read_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def iter_steps(tasks):
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for step in task.get("steps", []):
            if isinstance(step, dict):
                yield step


def load_path_values(tasks):
    values = {field.key: "" for field in PROGRAM_FIELDS}
    for step in iter_steps(tasks):
        key = step.get("setup_key")
        if key in values and step.get("path") and not values[key]:
            values[key] = step["path"]
    return values


def validate_path_values(values):
    errors = []
    for field in PROGRAM_FIELDS:
        text = (values.get(field.key) or "").strip().strip('"')
        if not text:
            continue

        path = Path(text)
        if path.name.casefold() != field.expected_name.casefold():
            errors.append(
                f"{field.label}：应选择 {field.expected_name}，当前为 {path.name or text}"
            )
        elif not path.is_file():
            errors.append(f"{field.label}：文件不存在：{path}")
    return errors


def apply_path_values(tasks, values):
    known_keys = {field.key for field in PROGRAM_FIELDS}
    found_keys = set()

    for step in iter_steps(tasks):
        key = step.get("setup_key")
        if key not in known_keys:
            continue

        text = (values.get(key) or "").strip().strip('"')
        path = str(Path(text).resolve()) if text else ""
        step["path"] = path
        found_keys.add(key)

        if step.get("type") == "launch":
            step["working_dir"] = str(Path(path).parent) if path else ""

    missing = known_keys - found_keys
    if missing:
        raise RuntimeError(f"tasks.json 缺少路径映射：{', '.join(sorted(missing))}")


def save_configuration(tasks, values):
    errors = validate_path_values(values)
    if errors:
        raise ValueError("\n".join(errors))

    apply_path_values(tasks, values)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_file = BACKUP_DIR / f"tasks-{timestamp}.json"
    shutil.copy2(CONFIG_FILE, backup_file)

    write_json_atomic(CONFIG_FILE, tasks)
    write_json_atomic(
        STATE_FILE,
        {
            "completed": True,
            "setup_version": SETUP_VERSION,
            "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )
    return backup_file


class SetupWizard:
    def __init__(self, root, tasks):
        self.root = root
        self.tasks = tasks
        self.result = 1
        self.variables = {
            key: tk.StringVar(value=value)
            for key, value in load_path_values(tasks).items()
        }

        root.title("TimedLauncher 首次运行设置")
        root.geometry("1160x600")
        root.minsize(1000, 520)
        root.protocol("WM_DELETE_WINDOW", self.cancel)

        self.build_ui()

    def build_ui(self):
        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="欢迎使用 TimedLauncher",
            font=("Microsoft YaHei UI", 18, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "请严格按当前流程顺序选择程序。路径可以留空，正式运行时会跳过对应阶段；"
                "已有启动参数不会被修改。"
            ),
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(6, 16))

        form = ttk.LabelFrame(outer, text="程序路径", padding=12)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)

        for row, field in enumerate(PROGRAM_FIELDS):
            label_frame = ttk.Frame(form)
            label_frame.grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            ttk.Label(label_frame, text=field.label, width=20).pack(anchor="w")
            ttk.Label(
                label_frame,
                text=field.description,
                foreground="#666666",
                font=("Microsoft YaHei UI", 8),
            ).pack(anchor="w")

            entry = ttk.Entry(form, textvariable=self.variables[field.key])
            entry.grid(row=row, column=1, sticky="ew", pady=5)
            ttk.Button(
                form,
                text="浏览…",
                width=10,
                command=lambda selected=field: self.browse(selected),
            ).grid(row=row, column=2, padx=(10, 0), pady=5)

            if field.github_url:
                ttk.Button(
                    form,
                    text="GitHub 下载",
                    width=12,
                    command=lambda selected=field: self.open_github(selected),
                ).grid(row=row, column=3, padx=(8, 0), pady=5)
            else:
                ttk.Label(
                    form,
                    text="游戏本体",
                    width=12,
                    foreground="#777777",
                    anchor="center",
                ).grid(row=row, column=3, padx=(8, 0), pady=5)

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(16, 0))
        ttk.Label(
            footer,
            text="只校验已填写的文件；留空表示跳过。保存前会备份原配置。",
            foreground="#666666",
        ).pack(side="left")
        ttk.Button(footer, text="取消", command=self.cancel).pack(side="right")
        ttk.Button(footer, text="保存并继续", command=self.save).pack(
            side="right", padx=(0, 10)
        )

    def browse(self, field):
        current = Path(self.variables[field.key].get().strip().strip('"'))
        initial_dir = current.parent if current.parent.is_dir() else BASE_DIR
        selected = filedialog.askopenfilename(
            parent=self.root,
            title=f"选择 {field.expected_name}",
            initialdir=str(initial_dir),
            filetypes=[
                (field.expected_name, field.expected_name),
                ("Windows 程序", "*.exe"),
                ("所有文件", "*.*"),
            ],
        )
        if selected:
            self.variables[field.key].set(selected)

    def open_github(self, field):
        if not field.github_url:
            return
        try:
            opened = webbrowser.open_new_tab(field.github_url)
        except Exception as error:
            messagebox.showerror(
                "无法打开网页",
                f"浏览器启动失败：\n{error}\n\n{field.github_url}",
                parent=self.root,
            )
            return

        if not opened:
            messagebox.showwarning(
                "无法打开网页",
                f"没有找到可用的浏览器，请手动打开：\n{field.github_url}",
                parent=self.root,
            )

    def save(self):
        values = {key: variable.get() for key, variable in self.variables.items()}
        try:
            backup = save_configuration(self.tasks, values)
        except ValueError as error:
            messagebox.showerror(
                "路径需要修改",
                "请处理以下问题：\n\n" + str(error),
                parent=self.root,
            )
            return
        except Exception as error:
            messagebox.showerror(
                "保存失败",
                f"无法保存配置：\n{error}",
                parent=self.root,
            )
            return

        selected_count = sum(bool(value.strip().strip('"')) for value in values.values())
        skipped_count = len(values) - selected_count
        messagebox.showinfo(
            "设置完成",
            (
                f"程序路径已保存：已填写 {selected_count} 项，留空 {skipped_count} 项。\n"
                "留空项目会在运行时自动跳过。\n\n"
                f"原配置备份：\n{backup}"
            ),
            parent=self.root,
        )
        self.result = 0
        self.root.destroy()

    def cancel(self):
        if messagebox.askyesno(
            "取消设置",
            "尚未保存程序路径。确定要退出设置向导吗？",
            parent=self.root,
        ):
            self.result = 1
            self.root.destroy()


def validate_config_mapping():
    tasks = read_json(CONFIG_FILE)
    expected = [field.key for field in PROGRAM_FIELDS]
    observed = []
    for step in iter_steps(tasks):
        key = step.get("setup_key")
        if key in expected and key not in observed:
            observed.append(key)

    missing = [key for key in expected if key not in observed]
    if missing:
        raise RuntimeError(f"缺少路径映射：{', '.join(missing)}")
    if observed != expected:
        raise RuntimeError(
            "首次设置顺序与运行流程不一致：" + " -> ".join(observed)
        )
    print("SETUP_MAPPING_OK")


def main():
    parser = argparse.ArgumentParser(description="TimedLauncher setup wizard")
    parser.add_argument(
        "--validate-mapping",
        action="store_true",
        help="只检查 tasks.json 的首次设置字段，不打开窗口",
    )
    options = parser.parse_args()

    if options.validate_mapping:
        validate_config_mapping()
        return 0

    try:
        tasks = read_json(CONFIG_FILE)
        if not isinstance(tasks, list):
            raise ValueError("tasks.json 顶层必须是数组")
    except Exception as error:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("无法启动设置", f"读取配置失败：\n{error}", parent=root)
        root.destroy()
        return 1

    root = tk.Tk()
    wizard = SetupWizard(root, tasks)
    root.mainloop()
    return wizard.result


if __name__ == "__main__":
    raise SystemExit(main())
