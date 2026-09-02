import argparse
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk


def read_report(path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception as error:
        return f"无法读取错误报告：{path}\n\n{type(error).__name__}: {error}"


def show_report(report_text, log_file):
    root = tk.Tk()
    root.title("TimedLauncher 运行失败")
    root.geometry("860x560")
    root.minsize(680, 420)
    root.attributes("-topmost", True)

    outer = ttk.Frame(root, padding=18)
    outer.pack(fill="both", expand=True)

    ttk.Label(
        outer,
        text="TimedLauncher 已停止运行",
        font=("Microsoft YaHei UI", 17, "bold"),
        foreground="#b42318",
    ).pack(anchor="w")
    ttk.Label(
        outer,
        text="下方报告会一直保留，直到你手动关闭此窗口。",
        font=("Microsoft YaHei UI", 10),
    ).pack(anchor="w", pady=(5, 12))

    report_box = scrolledtext.ScrolledText(
        outer,
        wrap="word",
        font=("Consolas", 10),
        padx=10,
        pady=10,
    )
    report_box.pack(fill="both", expand=True)
    report_box.insert("1.0", report_text)
    report_box.configure(state="disabled")

    buttons = ttk.Frame(outer)
    buttons.pack(fill="x", pady=(12, 0))

    def copy_report():
        root.clipboard_clear()
        root.clipboard_append(report_text)
        root.update()

    def open_log_folder():
        try:
            os.startfile(str(log_file.parent))
        except Exception as error:
            messagebox.showerror(
                "无法打开日志目录",
                str(error),
                parent=root,
            )

    ttk.Button(buttons, text="复制错误报告", command=copy_report).pack(side="left")
    ttk.Button(buttons, text="打开日志目录", command=open_log_folder).pack(
        side="left", padx=(8, 0)
    )
    ttk.Button(buttons, text="关闭", command=root.destroy).pack(side="right")

    root.after(1200, lambda: root.attributes("-topmost", False))
    root.lift()
    root.focus_force()
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="TimedLauncher error report")
    parser.add_argument("--report-file")
    parser.add_argument("--log-file")
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()

    if options.check:
        print("ERROR_REPORT_UI_CHECK_OK")
        return 0
    if not options.report_file or not options.log_file:
        parser.error("--report-file and --log-file are required")

    report_file = Path(options.report_file)
    log_file = Path(options.log_file)
    show_report(read_report(report_file), log_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
