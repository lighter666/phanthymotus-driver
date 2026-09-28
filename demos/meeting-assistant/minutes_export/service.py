"""Validate a meeting draft and save an immutable UTF-8 TXT file."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


FIELDS = ("item", "owner", "deadline", "deliverable", "reviewer", "acceptance")
ALLOWED = {"action", "title", "attendees", "robot_status", "decisions", "tasks", "pending"}


def _line(value, label):
    if value is None or value == "":
        return "待确认"
    if not isinstance(value, str) or len(value) > 4000 or any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        raise ValueError(f"{label} 必须是长度不超过 4000 的文本")
    return re.sub(r"\s+", " ", value).strip() or "待确认"


def _list(value, label):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 200:
        raise ValueError(f"{label} 必须是最多 200 项的列表")
    return [_line(item, label) for item in value]


def normalize(args):
    if not isinstance(args, dict) or args.get("action") != "save" or set(args) - ALLOWED:
        raise ValueError("只支持 action=save，且不接受自定义路径或未知字段")
    tasks = args.get("tasks", [])
    if not isinstance(tasks, list) or len(tasks) > 200:
        raise ValueError("tasks 必须是最多 200 项的列表")
    normalized_tasks = []
    for index, task in enumerate(tasks, 1):
        if not isinstance(task, dict) or set(task) - set(FIELDS):
            raise ValueError(f"任务 {index} 格式错误")
        normalized_tasks.append({key: _line(task.get(key), f"任务 {index}.{key}") for key in FIELDS})
    data = {
        "title": _line(args.get("title"), "title"),
        "attendees": _list(args.get("attendees"), "attendees"),
        "robot_status": _line(args.get("robot_status"), "robot_status"),
        "decisions": _list(args.get("decisions"), "decisions"),
        "tasks": normalized_tasks,
        "pending": _list(args.get("pending"), "pending"),
    }
    if not any((data["title"] != "待确认", data["attendees"], data["decisions"], data["tasks"], data["pending"])):
        raise ValueError("空纪要不能保存")
    return data


def render(data):
    lines = [
        "会议纪要草稿", "", f"会议主题：{data['title']}",
        f"参会人：{'、'.join(data['attendees']) if data['attendees'] else '待确认'}",
        "纪要状态：草稿", f"Bumi 健康检查：{data['robot_status']}", "",
        "关键决策：",
    ]
    lines.extend(f"{index}. {item}" for index, item in enumerate(data["decisions"], 1))
    if not data["decisions"]:
        lines.append("待确认")
    lines.extend(("", "行动项："))
    for index, task in enumerate(data["tasks"], 1):
        lines.extend((
            f"{index}. 事项：{task['item']}",
            f"   负责人：{task['owner']}",
            f"   截止时间：{task['deadline']}",
            f"   交付物：{task['deliverable']}",
            f"   验收人：{task['reviewer']}",
            f"   验收标准：{task['acceptance']}",
        ))
    if not data["tasks"]:
        lines.append("待确认")
    lines.extend(("", "待确认问题："))
    for task in data["tasks"]:
        missing = [name for key, name in (
            ("owner", "负责人"), ("deadline", "截止时间"), ("deliverable", "交付物"),
            ("reviewer", "验收人"), ("acceptance", "验收标准")) if task[key] == "待确认"]
        if missing:
            lines.append(f"- {task['item']}：{', '.join(missing)}待确认")
    lines.extend(f"- {item}" for item in data["pending"])
    if lines[-1] == "待确认问题：":
        lines.append("无")
    lines.extend(("", "此文件为草稿；不代表任务已派发或已通知参会人。", ""))
    return "\n".join(lines)


class MinutesStore:
    def __init__(self, directory: Path, public_directory: Path | None = None):
        self.directory = Path(directory)
        self.public_directory = Path(public_directory) if public_directory else self.directory
        self.active = True

    def dispatch(self, args):
        action = args.get("action")
        if action == "start":
            self.active = True
            return {"state": "ready"}
        if action == "stop":
            self.active = False
            return {"state": "idle"}
        if action == "info":
            return {"state": "ready" if self.active else "idle"}
        return self.save(args)

    def save(self, args):
        if not self.active:
            raise ValueError("导出卡片未启动")
        data = normalize(args)
        canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        filename = f"meeting-minutes-{digest[:20]}.txt"
        target = self.directory / filename
        content = render(data).encode("utf-8")
        self.directory.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            self.directory.chmod(0o700)
        if target.exists():
            if target.read_bytes() != content:
                raise RuntimeError("目标文件已存在且内容不符，未覆盖")
            return self._result("existing", filename, digest)
        fd, temporary = tempfile.mkstemp(prefix=".minutes-", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
                status = "saved"
            except FileExistsError:
                if target.read_bytes() != content:
                    raise RuntimeError("目标文件已存在且内容不符，未覆盖")
                status = "existing"
        finally:
            os.unlink(temporary)
        return self._result(status, filename, digest)

    def _result(self, status, filename, digest):
        return {"status": status, "path": str(self.public_directory / filename),
                "sha256": digest, "draft": True}
