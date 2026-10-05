"""Fail-closed checks for public trees. Never prints matched secret values."""
import argparse
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SECRET_PATTERNS = (
    re.compile(rb"gh[opusr]_[A-Za-z0-9_]{20,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"(?i)(?:api_key|access_token|refresh_token|password|cookie)\s*[=:]\s*[\"'][^\"'\r\n]{12,}[\"']"),
)
PERSONAL_PATH = re.compile(rb"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]")
PRIVATE_FILES = re.compile(r"(^|/)(?:\.env(?:\..*)?|secrets(?:\..*)?|.*\.(?:pem|pfx|p12)|miyoushe_checkin\.json|setup_state\.json)$", re.I)


def inspect_file(name, data):
    findings = []
    if name.startswith(("logs/", "runtime/")) and name not in {"logs/.gitkeep", "runtime/.gitkeep"}:
        findings.append("运行数据不可公开")
    if name.startswith((".venv/", "venv/", ".tools/", ".codex/", ".agents/", "config/backups/", "dist/")) or PRIVATE_FILES.search(name):
        findings.append("本机或敏感文件不可公开")
    if b"\0" in data:
        findings.append("意外的二进制文件，需人工审查")
    if PERSONAL_PATH.search(data):
        findings.append("包含绝对 Windows 路径")
    if any(pattern.search(data) for pattern in SECRET_PATTERNS):
        findings.append("疑似登录凭据或私钥")
    if name == "config/tasks.json":
        try:
            tasks = json.loads(data.decode("utf-8-sig"))
            for task in tasks:
                for step in task["steps"]:
                    if step.get("path") or step.get("working_dir"):
                        findings.append("公开模板路径必须留空")
            launches = [s for t in tasks for s in t["steps"] if s["type"] == "launch"]
            profiles = [s.get("setup_key") for s in launches]
            if profiles != ["bettergi", "march7th", "okww", "onedragon", "maa", "maaend"]:
                findings.append("程序顺序与公开模板不一致")
            for key, args in (("okww", ["-t", "1", "-e"]), ("onedragon", ["-o", "-c"])):
                if next(s for s in launches if s.get("setup_key") == key).get("args") != args:
                    findings.append(f"{key} 原启动参数发生变化")
        except (ValueError, KeyError, TypeError, StopIteration):
            findings.append("公开流程配置格式无效")
    return findings


def git(*args):
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True)
    if result.returncode:
        raise RuntimeError("Git 审计失败，未继续发布")
    return result.stdout


def scan_tree(revision=None):
    if revision:
        names = git("ls-tree", "-r", "--name-only", "-z", revision).split(b"\0")
    else:
        names = git("ls-files", "-z").split(b"\0")
    errors = []
    for raw in filter(None, names):
        name = raw.decode("utf-8")
        data = git("show", f"{revision}:{name}") if revision else (ROOT / name).read_bytes()
        errors.extend(f"{name}: {reason}" for reason in inspect_file(name, data))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--working-tree", action="store_true")
    parser.add_argument("--base", default="origin/github-version")
    args = parser.parse_args()
    if git("branch", "--show-current").decode().strip() != "github-version":
        raise RuntimeError("只有 github-version 分支允许公开发布")
    errors = scan_tree()
    revisions = [] if args.working_tree else git("rev-list", f"{args.base}..HEAD").decode().splitlines()
    for revision in revisions:
        errors.extend(f"{revision[:8]}: {error}" for error in scan_tree(revision))
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"PUBLIC_AUDIT_OK outgoing_commits={len(revisions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
