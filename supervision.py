"""Bounded, evidence-based supervision of a single automation stage.

No game input or process manipulation lives here. Callbacks are supplied by the
launcher, so log parsing and restart decisions can be tested without games.
"""
import json
import os
import re
import time
from pathlib import Path


LOG_PATTERNS = {
    "bettergi": ("log/better-genshin-impact*.log",),
    "march7th": ("logs/*.log",),
    "okww": ("data/apps/ok-ww/working/logs/ok-script.log",),
    "onedragon": (".log/log.txt", ".log/python_launcher_framework.log"),
    "maa": ("debug/gui.log",),
    "maaend": ("debug/*.log",),
}


def identity(process):
    return (process["pid"], process.get("create_time"))


class IncrementalLogs:
    """Ignore old records; handle new files, rotation and split UTF-8 lines."""
    def __init__(self, root, patterns):
        self.root = Path(root)
        self.patterns = patterns
        self.files = {}
        self.identities = {}
        for path in self.paths():
            try:
                with path.open("rb") as stream:
                    stat = os.fstat(stream.fileno())
                    stream.seek(max(0, stat.st_size - 512))
                    anchor = stream.read(stat.st_size - stream.tell())
                    stream.seek(0)
                    head = stream.read(min(stat.st_size, 512))
                token = self.token(stat)
                self.files[path] = token
                self.identities[token] = (stat.st_size, b"", anchor, head)
            except FileNotFoundError:
                continue

    @staticmethod
    def token(stat):
        return (stat.st_dev, stat.st_ino, getattr(stat, "st_birthtime_ns", None))

    def paths(self):
        return sorted({p for pattern in self.patterns
                       for p in self.root.glob(pattern) if p.is_file()})

    def poll(self):
        lines = []
        for path in self.paths():
            try:
                with path.open("rb") as stream:
                    stat = os.fstat(stream.fileno())
                    token = self.token(stat)
                    offset, carry, anchor, head = self.identities.get(token, (0, b"", b"", b""))
                    stream.seek(0)
                    unchanged_head = stream.read(len(head)) == head
                    stream.seek(max(0, offset - len(anchor)))
                    unchanged = stream.read(len(anchor)) == anchor
                    if stat.st_size < offset or not unchanged or not unchanged_head:
                        offset, carry = 0, b""
                    stream.seek(offset)
                    data = stream.read(512 * 1024)
                    offset = stream.tell()
                    stream.seek(max(0, offset - 512))
                    anchor = stream.read(offset - stream.tell())
                    stream.seek(0)
                    head = stream.read(min(offset, 512))
                parts = (carry + data).split(b"\n")
                carry = parts.pop()[-65536:]
                self.files[path] = token
                self.identities[token] = (offset, carry, anchor, head)
                lines.extend(p.decode("utf-8-sig", errors="replace").rstrip("\r")
                             for p in parts)
            except FileNotFoundError:
                continue  # Some tools clear debug/ while starting.
            except OSError as error:
                raise RuntimeError(f"无法读取本轮任务日志：{path.name}：{error}") from error
        return lines


class Signals:
    def __init__(self, profile):
        self.profile = profile
        self.started = False
        self.success = False
        self.failure = ""
        self.updating = False
        self.update_ready = False
        self.game_restart = False
        self.expected = set()
        self.succeeded = set()
        self.exit_group = False
        self.completion_banner = False
        self.last_evidence = ""

    def new_generation(self):
        self.started = self.success = False
        self.failure = ""
        self.expected.clear()
        self.succeeded.clear()
        self.exit_group = False
        self.completion_banner = False

    def consume(self, line):
        p = self.profile
        # A version CHECK is not an update; an OCR miss is not a failed task.
        if not re.search(r"更新检查|检查更新|有更新=false|check.*update", line, re.I):
            update_failed = re.search(r"更新失败|更新未成功|update failed|failed to update", line, re.I)
            if update_failed and self.updating:
                self.failure = f"更新失败：{line[-180:]}"
            if re.search(r"开始更新|正在更新|正在安装更新|installing update", line, re.I):
                if not self.updating:
                    self.started = False
                self.updating = True
            if (not update_failed and not re.search(r"更新成功=false|没有.*更新成功", line, re.I)
                    and re.search(r"更新成功|更新完成|update (?:completed|successful)", line, re.I)):
                if not self.updating:
                    self.started = False
                self.updating = self.update_ready = True
                if "游戏" in line and "重启" in line:
                    self.game_restart = True
        if p == "maaend":
            if "开始执行任务" in line:
                self.started = True
            match = re.search(r"任务已提交.*task[Ii]ds\s*:\s*(\[[^\]]*\])", line)
            if not match:
                match = re.search(r"任务已提交.*task_ids\s*:\s*(\[[^\]]*\])", line)
            if match:
                ids = json.loads(match.group(1))
                self.expected = {int(i) for i in ids}
                self.started = bool(self.expected)
            event = re.search(r"Tasker\.Task\.(Starting|Succeeded|Failed).*?\"task_id\"\s*:\s*(\d+)", line)
            if event:
                state, task_id = event.group(1), int(event.group(2))
                if state == "Starting":
                    self.started = True
                elif state == "Succeeded":
                    self.succeeded.add(task_id)
                else:
                    self.failure = f"MaaEnd 根任务 {task_id} 执行失败"
            self.success = bool(self.expected) and self.expected <= self.succeeded
        elif p == "onedragon":
            if re.search(r"指令\[\s*一条龙\s*\].*节点", line):
                self.started = True
            if re.search(r"指令\[\s*一条龙\s*\]\s*执行成功\s*返回状态\s*全部结束", line):
                self.success = True
            if re.search(r"指令\[\s*一条龙\s*\]\s*执行失败", line):
                self.failure = "OneDragon 一条龙执行失败"
        elif p == "okww":
            if "TaskExecutor" in line and ("Executing" in line or "开始" in line):
                self.started = True
            if "TaskExecutor:Successfully Executed Task, Exiting Game and App!" in line:
                self.success = True
        elif p == "maa":
            if "完成任务:" in line or "开始任务:" in line:
                self.started = True
            if "任务已全部完成" in line:
                self.success = True
        elif p == "march7th":
            if "当前界面" in line:
                self.started = True
            # Game termination alone is not proof that every daily succeeded.
            if re.fullmatch(r"-+\s*完成\s*-+", line.strip()):
                self.completion_banner = True
            if self.completion_banner and "游戏终止：StarRail" in line:
                self.success = True
        elif p == "bettergi":
            if "一条龙任务执行:" in line:
                self.started = True
            if '配置组 "退出" 执行结束' in line:
                self.exit_group = True
            if "一条龙任务全部完成" in line:
                self.success = True
            # Intentional exit scripts can cancel themselves when the game closes.
            # This is recorded as unverified, NOT misreported as a full success.
        if self.started or self.updating or self.success or self.failure:
            self.last_evidence = line[-180:]


class RunStatus:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {"started_at": time.time(), "state": "RUNNING", "stages": {}}
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        finally:
            if tmp.exists():
                tmp.unlink()

    def stage(self, alias, state, **details):
        item = self.data["stages"].setdefault(alias, {})
        changed = item.get("state") != state
        item.update(state=state, **details)
        self.data["current_stage"] = alias
        if state == "SUCCEEDED":
            self.data["last_verified_stage"] = alias
        if changed:
            self.save()

    def finish(self, state, reason=""):
        alias = self.data.get("current_stage")
        stage = self.data["stages"].get(alias)
        if state in {"FAILED", "STOPPED"} and stage and stage["state"] in {"STARTING", "RUNNING", "UPDATING"}:
            stage.update(state=state, note=str(reason))
        self.data.update(state=state, reason=str(reason), finished_at=time.time())
        self.save()

    def step(self, index, total, kind, alias=None):
        self.data["current_step"] = {"index": index, "total": total, "type": kind}
        if alias:
            self.data["current_stage"] = alias
        self.save()


class Stage:
    def __init__(self, alias, profile, spec, budget, status, callbacks):
        self.alias, self.profile, self.spec = alias, profile, spec
        self.status, self.cb = status, callbacks
        self.began = time.monotonic()
        self.deadline = self.began + min(float(budget), 1800)
        root = spec.get("working_dir") or str(Path(spec["path"]).parent)
        self.logs = IncrementalLogs(root, LOG_PATTERNS[profile])
        self.signals = Signals(profile)
        self.tool_ids = set()
        self.last_game_ids = set()
        self.update_origins = None
        self.game_replacement_since = None
        self.game_replacement_ids = set()
        self.missing_since = None
        self.update_since = None
        self.handover_since = None
        self.update_serial = 0
        self.recoveries = 0
        self.key_generations = set()
        self.key_action = None
        self.handover_completed = False
        self.state = "STARTING"
        self.status.stage(alias, self.state, profile=profile, budget_seconds=min(budget, 1800))

    def record(self, state, note=""):
        self.state = state
        self.status.stage(self.alias, state, note=note, recoveries=self.recoveries,
                          last_evidence=self.signals.last_evidence)

    def poll(self, game_path=None):
        self.cb["check"]()
        game_path = game_path or self.cb.get("game_path")
        now = time.monotonic()
        tools = self.cb["tools"]()
        current = {identity(p) for p in tools}
        # Reset old generation BEFORE consuming this poll's fresh start markers.
        # Otherwise a self-updater's new job could be toggled off with a second F10.
        if current:
            self.missing_since = None
            if (now < self.deadline and not self.signals.success and self.tool_ids
                    and current.isdisjoint(self.tool_ids)):
                self.accept_replacement()
            self.tool_ids = current
        elif self.missing_since is None:
            self.missing_since = now
        for line in self.logs.poll():
            self.signals.consume(line)
        if self.signals.failure:
            self.record("FAILED", self.signals.failure)
            raise RuntimeError(self.signals.failure)
        games = self.cb["scan"](game_path) if game_path else []
        game_ids = {identity(p) for p in games}
        if now >= self.deadline:
            return tools, games  # Never relaunch once the hard budget has expired.
        if self.signals.success and self.signals.updating:
            self.finish_update()
        if self.signals.updating and not self.signals.success:
            if self.update_since is None:
                self.update_since = now
                self.record("UPDATING", "等待更新及进程交接，不延长总预算")
                self.cb["info"](f"{self.alias} 检测到更新，等待进程交接")
            if self.signals.update_ready and self.handover_since is None:
                self.handover_since = now
            if self.handover_since is not None and now - self.handover_since >= 300:
                raise RuntimeError(f"{self.alias} 更新交接超过 5 分钟")
        if self.signals.game_restart and self.update_origins is None:
            self.update_origins = set(self.last_game_ids)
        game_ready = not self.signals.game_restart
        if self.signals.game_restart:
            if game_ids and game_ids != self.update_origins:
                if self.game_replacement_since is None or game_ids != self.game_replacement_ids:
                    self.game_replacement_since = now
                    self.game_replacement_ids = set(game_ids)
                game_ready = now - self.game_replacement_since >= 5
            else:
                self.game_replacement_since = None
                self.game_replacement_ids = set()
        # Never relaunch for an ordinary crash, nor while an old instance exists.
        if (not current and self.signals.update_ready and game_ready
                and not self.signals.success and now - self.missing_since >= 15):
            self.accept_replacement()
            process = self.cb["relaunch"]()
            if process is None:
                raise RuntimeError(f"{self.alias} 更新后重新启动失败")
            self.tool_ids = set()  # Next scan supplies PID + creation time.
            self.missing_since = now
        if (current and game_ready and self.signals.update_ready
                and (self.handover_completed or self.signals.started
                     or (not self.signals.game_restart and self.update_since is not None
                         and now - self.update_since >= 5))):
            self.finish_update()
            self.record("RUNNING", "更新交接完成")
        elif current and game_ready and self.signals.updating and self.signals.started:
            self.finish_update()
            self.record("RUNNING", "本轮日志已确认更新后任务继续执行")
        self.last_game_ids = game_ids
        if self.signals.started and self.state == "STARTING":
            self.record("RUNNING")
        return tools, games

    def finish_update(self):
        self.signals.updating = self.signals.update_ready = False
        self.signals.game_restart = False
        self.update_since = self.update_origins = self.handover_since = None
        self.game_replacement_since = None
        self.game_replacement_ids = set()
        self.handover_completed = False
        self.update_serial += 1

    def accept_replacement(self):
        if self.recoveries >= 1:
            raise RuntimeError(f"{self.alias} 已达到本轮更新恢复上限 1 次")
        self.recoveries += 1
        self.signals.new_generation()
        self.handover_completed = True
        self.cb["info"](f"{self.alias} 接管新的工具进程，保留原启动参数和原截止时间")

    def check_deadline(self):
        if time.monotonic() >= self.deadline:
            self.record("TIMED_OUT", "本阶段总运行预算已用完")
            raise RuntimeError(f"{self.alias} 达到本阶段总运行上限（更新、重启不重置计时）")

    def send_start_key(self, action):
        self.key_action = action
        deadline = min(self.deadline, time.monotonic() + 120)
        while True:
            tools, _ = self.poll()
            self.check_deadline()
            if self.signals.started or self.signals.success:
                return  # F10 is a toggle: never send it to an already running job.
            if self.signals.updating and self.update_since is not None:
                deadline = self.deadline  # Downloads use the same total budget.
            generation = self.recoveries  # Child-process churn is NOT a new task run.
            if tools and not self.signals.updating and generation not in self.key_generations:
                bounded_action = dict(action)
                bounded_action["window_timeout"] = min(float(action.get("window_timeout", 30)),
                                                       max(0, self.deadline - time.monotonic()))
                if not self.cb["key"](bounded_action, tools):
                    raise RuntimeError(f"{self.alias} 无法激活已验证身份的目标窗口")
                self.key_generations.add(generation)
                deadline = min(self.deadline, time.monotonic() + 120)
            if time.monotonic() >= deadline:
                raise RuntimeError(f"{self.alias} 按键后 120 秒内未确认任务开始；不重复发送 F10")
            self.cb["wait"](1)

    def wait_exit(self, game_path, start_timeout, stable_seconds, minimum_wait=0,
                  timeout_is_error=True):
        start_deadline = min(self.deadline, time.monotonic() + start_timeout)
        seen = False
        absent_since = None
        minimum_deadline = None
        update_serial = self.update_serial
        while True:
            tools, games = self.poll(game_path)
            # For launcher-wrapped tools (OneDragon), include tracked descendants.
            target = tools if Path(game_path).resolve() == Path(self.spec["path"]).resolve() else games
            now = time.monotonic()
            if update_serial != self.update_serial:
                start_deadline = min(self.deadline, now + start_timeout)
                update_serial = self.update_serial
            if now >= self.deadline:
                self.record("TIMED_OUT", "总运行预算耗尽")
                if timeout_is_error:
                    self.check_deadline()
                return False
            if (not tools and not self.signals.updating and not self.signals.success
                    and now - self.missing_since >= 30):
                raise RuntimeError(f"{self.alias} 工具在任务完成前退出，未发现更新交接证据")
            if self.key_action and tools and not self.signals.started and not self.signals.updating:
                self.send_start_key(self.key_action)
                continue  # Refresh process snapshots after a potentially long key wait.
            if target:
                seen = True
                minimum_deadline = minimum_deadline or now + minimum_wait
                absent_since = None
            elif (seen or self.signals.success) and not self.signals.updating:
                minimum_deadline = minimum_deadline or self.began + minimum_wait
                absent_since = now if absent_since is None else absent_since
                if now - absent_since >= stable_seconds and now >= minimum_deadline:
                    state = "SUCCEEDED" if self.signals.success else "UNVERIFIED_EXIT"
                    self.record(state, "目标已退出" if self.signals.success else "目标已退出，但缺少整轮成功标记")
                    if not self.signals.success:
                        self.cb["warn"](f"{self.alias} 已退出，但本轮日常结果未确认；保留原顺序继续")
                    return True
            if not seen and now >= start_deadline and not self.signals.updating:
                if self.signals.success:
                    self.cb["wait"](1)
                    continue  # Still observe stable exit / minimum wait for short tasks.
                raise RuntimeError(f"{self.alias} 等待目标启动超时")
            self.cb["wait"](1)

    def wait_completion(self):
        while True:
            tools, _ = self.poll()
            self.check_deadline()
            if self.signals.success:
                self.record("SUCCEEDED", f"已确认 {len(self.signals.expected)} 个提交任务全部成功")
                return
            if not tools and not self.signals.updating and time.monotonic() - self.missing_since >= 30:
                raise RuntimeError(f"{self.alias} 在任务完成前退出，未发现更新交接证据")
            if tools and not self.signals.started and not self.signals.updating and self.key_action:
                self.send_start_key(self.key_action)
            self.cb["wait"](1)


def maaend_game_paths(root):
    """Read enabled native launch actions; never alter the user's MaaEnd config."""
    path = Path(root) / "config" / "mxu-MaaEnd.json"
    if not path.is_file():
        return []
    settings = json.loads(path.read_text(encoding="utf-8-sig"))
    paths = []
    for instance in settings.get("instances", []):
        if instance.get("id") != settings.get("lastActiveInstanceId"):
            continue
        for action in instance.get("preActions", []):
            program = action.get("program", "")
            if action.get("enabled") and program and Path(program).is_file():
                paths.append(program)
    return paths


def onedragon_game_paths(root):
    """Only extract game_path from native account configs, not account secrets."""
    paths = []
    for path in (Path(root) / "config").glob("*/game_account.yml"):
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"^game_path:\s*(.+?)\s*$", line)
            if match:
                value = match.group(1).strip("\"'")
                if Path(value).name.casefold() == "zenlesszonezero.exe" and Path(value).is_file():
                    paths.append(value)
    return list(dict.fromkeys(paths))
