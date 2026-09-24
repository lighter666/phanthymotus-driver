"""Deterministic meeting workflow and durable local task board."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError("截止时间必须是带时区的 ISO 8601 时间") from exc
    if result.tzinfo is None:
        raise ValueError("截止时间必须包含时区")
    return result.astimezone(timezone.utc)


def required(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}不能为空")
    return value.strip()


class MeetingStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("CREATE TABLE IF NOT EXISTS meetings (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL, data TEXT NOT NULL)")

    def close(self):
        self.db.close()

    def _load(self, table: str, item_id: str) -> dict:
        row = self.db.execute(f"SELECT data FROM {table} WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise ValueError("记录不存在")
        return json.loads(row["data"])

    def _save(self, table: str, value: dict):
        payload = json.dumps(value, ensure_ascii=False)
        with self.db:
            if table == "meetings":
                self.db.execute("INSERT OR REPLACE INTO meetings VALUES (?,?)", (value["id"], payload))
            else:
                self.db.execute("INSERT OR REPLACE INTO tasks VALUES (?,?,?)", (value["id"], value["meeting_id"], payload))

    def create(self, title: str, attendees: list[str], agenda: list[dict], equipment: list[str] | None = None) -> dict:
        title = required(title, "会议名称")
        if not isinstance(attendees, list) or not attendees:
            raise ValueError("至少填写一名参会人")
        people = [required(name, "参会人") for name in attendees]
        if len(set(people)) != len(people):
            raise ValueError("参会人不能重名")
        if not isinstance(agenda, list) or not agenda:
            raise ValueError("至少填写一个议程")
        items = []
        for item in agenda:
            minutes = item.get("minutes") if isinstance(item, dict) else None
            if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 240:
                raise ValueError("议程时长需为 1—240 分钟的整数")
            items.append({"title": required(item.get("title"), "议程名称"), "minutes": minutes})
        names = equipment if equipment is not None else ["投影", "网络"]
        if not isinstance(names, list):
            raise ValueError("设备清单格式错误")
        names = [required(name, "设备名称") for name in names]
        if len(set(names)) != len(names) or "Bumi" in names:
            raise ValueError("设备不能重名，Bumi 由健康检查单独确认")
        meeting = {
            "id": uuid.uuid4().hex, "title": title, "status": "planned",
            "attendees": [{"name": n, "confirmed": False} for n in people],
            "equipment": [{"name": n, "confirmed": False, "source": "manual"} for n in names]
            + [{"name": "Bumi", "confirmed": False, "source": "health_check", "report": None}],
            "agenda": items, "agenda_index": 0, "agenda_started_at": None,
            "warned_five": False, "warned_end": False,
            "decisions": [], "drafts": [], "created_at": iso(now_utc()),
        }
        with self.lock:
            self._save("meetings", meeting)
        return self._decorate(meeting)

    def _decorate(self, meeting: dict, at: datetime | None = None) -> dict:
        result = json.loads(json.dumps(meeting, ensure_ascii=False))
        result["preflight_ready"] = all(p["confirmed"] for p in result["attendees"] + result["equipment"])
        if result["status"] == "active":
            elapsed = max(0, int(((at or now_utc()) - parse_time(result["agenda_started_at"])).total_seconds()))
            total = result["agenda"][result["agenda_index"]]["minutes"] * 60
            result["remaining_seconds"] = max(0, total - elapsed)
        else:
            result["remaining_seconds"] = None
        return result

    def get(self, meeting_id: str, at: datetime | None = None) -> dict:
        with self.lock:
            return self._decorate(self._load("meetings", meeting_id), at)

    def list_meetings(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT data FROM meetings ORDER BY rowid DESC").fetchall()
            return [self._decorate(json.loads(row[0])) for row in rows]

    def set_check(self, meeting_id: str, kind: str, name: str, confirmed: bool) -> dict:
        if kind not in ("attendees", "equipment") or not isinstance(confirmed, bool):
            raise ValueError("确认参数无效")
        with self.lock:
            meeting = self._load("meetings", meeting_id)
            if meeting["status"] == "ended":
                raise ValueError("会议已结束")
            entry = next((x for x in meeting[kind] if x["name"] == name), None)
            if entry is None:
                raise ValueError("人员或设备不存在")
            if entry.get("source") == "health_check":
                raise ValueError("Bumi 必须通过健康检查确认")
            entry["confirmed"] = confirmed
            self._save("meetings", meeting)
            return self._decorate(meeting)

    def record_robot_health(self, meeting_id: str, report: dict) -> dict:
        if not isinstance(report, dict):
            raise ValueError("健康报告格式错误")
        overall = report.get("status", report.get("overall_status", report.get("overall")))
        with self.lock:
            meeting = self._load("meetings", meeting_id)
            if meeting["status"] == "ended":
                raise ValueError("会议已结束")
            entry = next(x for x in meeting["equipment"] if x["name"] == "Bumi")
            entry["confirmed"] = overall in ("正常", "normal")
            entry["report"] = report
            self._save("meetings", meeting)
            return self._decorate(meeting)

    def start(self, meeting_id: str, at: datetime | None = None) -> dict:
        with self.lock:
            meeting = self._load("meetings", meeting_id)
            if meeting["status"] != "planned":
                raise ValueError("会议已开始或已结束")
            meeting.update(status="active", agenda_started_at=iso(at or now_utc()))
            self._save("meetings", meeting)
            return self._decorate(meeting, at)

    def tick(self, meeting_id: str, at: datetime | None = None) -> dict:
        at = at or now_utc()
        with self.lock:
            meeting = self._load("meetings", meeting_id)
            announcements = []
            if meeting["status"] == "active":
                remaining = self._decorate(meeting, at)["remaining_seconds"]
                duration = meeting["agenda"][meeting["agenda_index"]]["minutes"] * 60
                if duration > 300 and 0 < remaining <= 300 and not meeting["warned_five"]:
                    meeting["warned_five"] = True
                    announcements.append("five_minutes")
                if remaining == 0 and not meeting["warned_end"]:
                    meeting["warned_end"] = True
                    announcements.append("time_up")
                if announcements:
                    self._save("meetings", meeting)
            return {"meeting": self._decorate(meeting, at), "announcements": announcements}

    def next_agenda(self, meeting_id: str, at: datetime | None = None) -> dict:
        with self.lock:
            meeting = self._load("meetings", meeting_id)
            if meeting["status"] != "active":
                raise ValueError("会议未进行")
            if meeting["agenda_index"] + 1 >= len(meeting["agenda"]):
                raise ValueError("已是最后一项议程")
            meeting["agenda_index"] += 1
            meeting["agenda_started_at"] = iso(at or now_utc())
            meeting["warned_five"] = meeting["warned_end"] = False
            self._save("meetings", meeting)
            return self._decorate(meeting, at)

    def add_note(self, meeting_id: str, kind: str, text: str) -> dict:
        if kind not in ("decisions", "drafts"):
            raise ValueError("记录类型错误")
        with self.lock:
            meeting = self._load("meetings", meeting_id)
            if meeting["status"] != "active":
                raise ValueError("仅进行中的会议可以记录")
            meeting[kind].append({"id": uuid.uuid4().hex, "text": required(text, "内容"), "created_at": iso(now_utc())})
            self._save("meetings", meeting)
            return self._decorate(meeting)

    def end(self, meeting_id: str) -> dict:
        with self.lock:
            meeting = self._load("meetings", meeting_id)
            if meeting["status"] != "active":
                raise ValueError("会议未进行")
            meeting["status"] = "ended"
            self._save("meetings", meeting)
            return self._decorate(meeting)

    def confirm_task(self, meeting_id: str, draft_id: str, *, owner: str, deadline: str,
                     deliverable: str, reviewer: str, acceptance: str, confirmed: bool) -> dict:
        if confirmed is not True:
            raise ValueError("主持人必须明确确认任务")
        owner, deliverable, reviewer, acceptance = (
            required(v, label) for v, label in [
                (owner, "负责人"), (deliverable, "交付物"),
                (reviewer, "验收人"), (acceptance, "验收标准")])
        due = parse_time(deadline)
        if due <= now_utc():
            raise ValueError("截止时间必须晚于当前时间")
        with self.lock:
            meeting = self._load("meetings", meeting_id)
            draft = next((d for d in meeting["drafts"] if d["id"] == draft_id), None)
            if draft is None:
                raise ValueError("行动项草稿不存在")
            if draft.get("task_id"):
                raise ValueError("此草稿已生成任务")
            if owner not in [p["name"] for p in meeting["attendees"]] or reviewer not in [p["name"] for p in meeting["attendees"]]:
                raise ValueError("负责人和验收人必须在参会名单中")
            task = {"id": uuid.uuid4().hex, "meeting_id": meeting_id, "draft_id": draft_id,
                    "title": draft["text"], "owner": owner, "deadline": iso(due),
                    "deliverable": deliverable, "reviewer": reviewer, "acceptance": acceptance,
                    "status": "open", "evidence": None, "review_note": None,
                    "created_at": iso(now_utc())}
            draft["task_id"] = task["id"]
            with self.db:
                self.db.execute("INSERT INTO tasks VALUES (?,?,?)", (task["id"], meeting_id, json.dumps(task, ensure_ascii=False)))
                self.db.execute("UPDATE meetings SET data=? WHERE id=?", (json.dumps(meeting, ensure_ascii=False), meeting_id))
            return self._task_view(task)

    def _task_view(self, task: dict, at: datetime | None = None) -> dict:
        result = dict(task)
        due = parse_time(result["deadline"])
        now = at or now_utc()
        result["attention"] = (
            "待验收" if result["status"] == "submitted" else
            "逾期" if result["status"] != "accepted" and due < now else
            "将到期" if result["status"] != "accepted" and due <= now + timedelta(hours=24) else None
        )
        return result

    def list_tasks(self, meeting_id: str | None = None, at: datetime | None = None) -> list[dict]:
        with self.lock:
            if meeting_id:
                rows = self.db.execute("SELECT data FROM tasks WHERE meeting_id=? ORDER BY rowid", (meeting_id,)).fetchall()
            else:
                rows = self.db.execute("SELECT data FROM tasks ORDER BY rowid DESC").fetchall()
            return [self._task_view(json.loads(row[0]), at) for row in rows]

    def submit_task(self, task_id: str, evidence: str, actor: str) -> dict:
        with self.lock:
            task = self._load("tasks", task_id)
            if task["status"] not in ("open", "returned"):
                raise ValueError("该任务当前不能提交")
            if required(actor, "操作人") != task["owner"]:
                raise ValueError("只有负责人可以提交")
            task.update(status="submitted", evidence=required(evidence, "完成说明或证据"), review_note=None)
            self._save("tasks", task)
            return self._task_view(task)

    def review_task(self, task_id: str, approved: bool, actor: str, note: str = "") -> dict:
        with self.lock:
            task = self._load("tasks", task_id)
            if task["status"] != "submitted" or not isinstance(approved, bool):
                raise ValueError("只有待验收任务可以验收")
            if required(actor, "操作人") != task["reviewer"]:
                raise ValueError("只有验收人可以验收")
            if not approved:
                note = required(note, "退回原因")
            task.update(status="accepted" if approved else "returned", review_note=note.strip())
            self._save("tasks", task)
            return self._task_view(task)
