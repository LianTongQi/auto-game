"""Configure an optional external check-in adapter; never reads login secrets."""
import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from skland_checkin import atomic_write


ROOT = Path(__file__).resolve().parent


def make_settings(executable, script, enabled=True):
    if not enabled:
        return {"enabled": False}
    python, entry = Path(executable), Path(script)
    if (not python.is_absolute() or not entry.is_absolute()
            or not python.is_file() or not entry.is_file()
            or python.name.casefold() not in {"python.exe", "pythonw.exe"}
            or entry.name != "miyoushe_accounts.py"):
        raise ValueError("请选择已安装签到工具的 Python 和 miyoushe_accounts.py 文件。")
    return {"enabled": True, "pythonw_path": str(python),
            "script_path": str(entry), "working_dir": str(entry.parent)}


def save_settings(path, settings):
    path = Path(path)
    if path.is_file():
        backup = path.parent / "backups" / (path.name + "." + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
    atomic_write(path, (json.dumps(settings, ensure_ascii=False, indent=2) + "\n").encode())


def main(argv=None):
    parser = argparse.ArgumentParser(description="可选米游社签到连接设置（不包含第三方签到本体）")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        print("CHECKIN_SETUP_OK")
        return 0
    import tkinter as tk
    from tkinter import filedialog, messagebox
    window = tk.Tk()
    window.title("米游社签到连接设置")
    window.resizable(False, False)
    tk.Label(window, text="仅连接你已安装、已自行登录的兼容工具。\n不收集 Cookie，不登录、不领取、不创建定时任务。",
             justify="left").grid(row=0, column=0, columnspan=3, padx=15, pady=15)
    executable, script = tk.StringVar(), tk.StringVar()
    enabled = tk.BooleanVar(value=True)
    for row, (label, value, extensions) in enumerate([
            ("签到工具 Python", executable, [("Python", "*.exe")]),
            ("miyoushe_accounts.py", script, [("Python script", "*.py")])], 1):
        tk.Label(window, text=label).grid(row=row, column=0, padx=10, pady=6)
        tk.Entry(window, textvariable=value, width=48).grid(row=row, column=1)
        tk.Button(window, text="选择", command=lambda v=value, e=extensions: v.set(
            filedialog.askopenfilename(parent=window, filetypes=e))).grid(row=row, column=2, padx=10)
    tk.Checkbutton(window, text="随日常启动时后台尝试签到", variable=enabled).grid(row=3, column=1, pady=8)

    def save():
        try:
            settings = make_settings(executable.get(), script.get(), enabled.get())
            save_settings(ROOT / "config" / "miyoushe_checkin.json", settings)
        except ValueError as error:
            messagebox.showerror("设置无效", str(error), parent=window)
            return
        except Exception:
            messagebox.showerror("无法保存", "请检查文件夹权限；未显示本机路径或异常详情。", parent=window)
            return
        messagebox.showinfo("已保存", "连接设置只保存在本机；尚未执行签到。", parent=window)
        window.destroy()

    tk.Button(window, text="保存本机设置", command=save).grid(row=4, column=1, pady=12)
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
