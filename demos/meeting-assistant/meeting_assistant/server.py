"""Headless MCP meeting cards with durable local storage."""

from __future__ import annotations

import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .audio import AnnouncementPublisher, TOPIC
from .core import MeetingStore

ROOT = Path(__file__).resolve().parent
MCP_NAME = "Bumi Meeting Assistant"


def call_mcp(url: str, name: str, arguments: dict, timeout: float = 3) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": arguments}}).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if "error" in payload:
        raise RuntimeError(payload["error"].get("message", "MCP 调用失败"))
    content = payload.get("result", {}).get("content", [])
    if not content:
        raise RuntimeError("MCP 未返回结果")
    return json.loads(content[0]["text"])


class MeetingService:
    def __init__(self, db_path: str | Path, *, audio: AnnouncementPublisher | None = None,
                 bumi_url: str = "http://localhost:15704/mcp", enable_health_check: bool = False):
        self.store = MeetingStore(db_path)
        self.audio = audio or AnnouncementPublisher(ROOT.parent / "assets", enabled=False)
        self.bumi_url = bumi_url
        self.enable_health_check = enable_health_check
        self.audio_started = False
        self.last_audio_status = "画布音频卡片尚未启动"
        self._stop = threading.Event()
        self._timer = None

    def start_timer(self):
        if self._timer is None:
            self._timer = threading.Thread(target=self._timer_loop, daemon=True, name="meeting-timer")
            self._timer.start()

    def _timer_loop(self):
        while not self._stop.wait(1):
            for meeting in self.store.list_meetings():
                if meeting["status"] != "active":
                    continue
                try:
                    for cue in self.store.tick(meeting["id"])["announcements"]:
                        self._announce(cue)
                except Exception as exc:
                    self.last_audio_status = f"计时失败：{exc}"

    def _announce(self, cue: str):
        if not self.audio_started or not self.audio.available:
            self.last_audio_status = self.audio.error or "画布音频卡片尚未启动"
            return
        try:
            if not self.audio.announce(cue):
                raise RuntimeError(self.audio.error or "提醒发布失败")
            self.last_audio_status = f"已向 TTS 发布提示：{cue}（扬声器实际发声需真机确认）"
        except Exception as exc:
            self.last_audio_status = f"播报失败：{exc}"

    def action(self, args: dict) -> object:
        action = args.get("action")
        mid = args.get("meeting_id", "")
        if action == "create":
            return self.store.create(args.get("title"), args.get("attendees"), args.get("agenda"), args.get("equipment"))
        if action == "list":
            return self.store.list_meetings()
        if action == "get":
            return {"meeting": self.store.get(mid), "tasks": self.store.list_tasks(mid),
                    "audio_status": self.audio.error or self.last_audio_status,
                    "health_check_enabled": self.enable_health_check}
        if action == "brief":
            return self.store.brief(mid)
        if action in ("check_person", "check_equipment"):
            return self.store.set_check(mid, "attendees" if action == "check_person" else "equipment",
                                        args.get("name"), args.get("confirmed"))
        if action == "check_robot":
            if not self.enable_health_check:
                raise ValueError("Bumi 健康检查已暂停；未调用机器人")
            try:
                report = call_mcp(self.bumi_url, "health_check", {"action": "check"})
            except Exception as exc:
                report = {"status": "数据不足", "summary": f"Bumi 健康检查不可用：{exc}"}
            return self.store.record_robot_health(mid, report)
        if action == "begin_meeting":
            return self.store.start(mid)
        if action == "next_agenda":
            return self.store.next_agenda(mid)
        if action == "record_decision":
            return self.store.add_note(mid, "decisions", args.get("text"))
        if action == "record_draft":
            return self.store.add_note(mid, "drafts", args.get("text"), args)
        if action == "record_report":
            return self.store.add_report(mid, args.get("text"), args.get("speaker", ""))
        if action == "end_meeting":
            return self.store.end(mid)
        if action == "cancel_meeting":
            return self.store.cancel(mid)
        if action == "confirm_task":
            return self.store.confirm_task(mid, args.get("draft_id"), owner=args.get("owner"),
                                           deadline=args.get("deadline"), deliverable=args.get("deliverable"),
                                           reviewer=args.get("reviewer"), acceptance=args.get("acceptance"),
                                           confirmed=args.get("confirmed"))
        if action == "list_tasks":
            return self.store.list_tasks(mid or None)
        if action == "submit_task":
            return self.store.submit_task(args.get("task_id"), args.get("evidence"), args.get("actor"))
        if action == "review_task":
            return self.store.review_task(args.get("task_id"), args.get("approved"),
                                          args.get("actor"), args.get("note", ""))
        raise ValueError(f"未知操作：{action}")

    def close(self):
        self._stop.set()
        if self._timer:
            self._timer.join(timeout=2)
        self.audio.close()
        self.store.close()


ACTIONS = ["create", "list", "get", "brief", "check_person", "check_equipment", "check_robot",
           "begin_meeting", "next_agenda", "record_report", "record_decision", "record_draft", "end_meeting", "cancel_meeting",
           "confirm_task", "list_tasks", "submit_task", "review_task"]


def tools_list() -> list[dict]:
    return [
        {"name": "meeting_manager", "type": "actuator", "multiInstance": False,
         "description": "Manage meeting preflight, agenda, decisions, confirmed action items and acceptance. Never create a formal task without host confirmation.",
         "inputSchema": {"type": "object", "properties": {
             "action": {"type": "string", "enum": ACTIONS + ["start", "stop", "info"]},
             "meeting_id": {"type": "string"}, "title": {"type": "string"},
             "attendees": {"type": "array", "items": {"type": "string"}},
             "agenda": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "minutes": {"type": "integer"}}}},
             "equipment": {"type": "array", "items": {"type": "string"}},
             "name": {"type": "string"}, "confirmed": {"type": "boolean"},
             "text": {"type": "string"}, "speaker": {"type": "string"}, "draft_id": {"type": "string"},
             "owner": {"type": "string"}, "deadline": {"type": "string"},
             "deliverable": {"type": "string"}, "reviewer": {"type": "string"},
             "acceptance": {"type": "string"}, "task_id": {"type": "string"},
             "evidence": {"type": "string"}, "actor": {"type": "string"},
             "approved": {"type": "boolean"}, "note": {"type": "string"}},
             "required": ["action"], "x-action-params": {
                 "create": {"params": ["title", "attendees", "agenda", "equipment"]},
                 "get": {"params": ["meeting_id"]},
                 "brief": {"params": ["meeting_id"]},
                 "check_person": {"params": ["meeting_id", "name", "confirmed"]},
                 "check_equipment": {"params": ["meeting_id", "name", "confirmed"]},
                 "check_robot": {"params": ["meeting_id"]},
                 "begin_meeting": {"params": ["meeting_id"]},
                 "next_agenda": {"params": ["meeting_id"]},
                 "record_decision": {"params": ["meeting_id", "text"]},
                 "record_report": {"params": ["meeting_id", "text", "speaker"]},
                 "record_draft": {"params": ["meeting_id", "text", "owner", "deadline", "deliverable", "reviewer", "acceptance"]},
                 "end_meeting": {"params": ["meeting_id"]},
                 "cancel_meeting": {"params": ["meeting_id"]},
                 "confirm_task": {"params": ["meeting_id", "draft_id", "owner", "deadline", "deliverable", "reviewer", "acceptance", "confirmed"]},
                 "list_tasks": {"params": ["meeting_id"]},
                 "submit_task": {"params": ["task_id", "actor", "evidence"]},
                 "review_task": {"params": ["task_id", "actor", "approved", "note"]},
                 "list": {"params": []}, "start": {"params": []}, "stop": {"params": []}, "info": {"params": []}}}},
        {"name": "meeting_audio", "type": "sensor", "multiInstance": False,
         "description": "Fixed Chinese agenda reminders as text for the existing TTS card.",
         "inputSchema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["start", "stop", "info"]}}, "required": ["action"]},
         "topic_out": [{"topic": TOPIC, "format": "data/json", "message_type": "std_msgs/msg/String"}]},
    ]


def dispatch_tool(service: MeetingService, name: str, arguments: dict) -> object:
    args = dict(arguments)
    action = args.get("action")
    if name == "meeting_audio":
        if action == "start":
            service.audio_started = True
            return {"state": "running", "topic_out": tools_list()[1]["topic_out"],
                    "audio_status": service.audio.error or service.last_audio_status}
        if action == "stop":
            service.audio_started = False
            return {"state": "idle"}
        if action == "info":
            return {"state": "running" if service.audio_started else "idle",
                    "topic_out": tools_list()[1]["topic_out"],
                    "audio_status": service.audio.error or service.last_audio_status}
    if name == "meeting_manager":
        if action in ("start", "stop", "info"):
            return {"state": "idle" if action == "stop" else "ready"}
        return service.action(args)
    raise ValueError(f"未知卡片：{name}")


def make_handler(service: MeetingService):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, payload: object, content_type: str = "application/json; charset=utf-8"):
            body = (json.dumps(payload, ensure_ascii=False).encode() if not isinstance(payload, bytes) else payload)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/meetings":
                return self._send(200, service.store.list_meetings())
            if path == "/api/tasks":
                return self._send(200, service.store.list_tasks())
            if path == "/api/status":
                return self._send(200, {"audio_status": service.audio.error or service.last_audio_status,
                                        "health_check_enabled": service.enable_health_check})
            if path.startswith("/api/meetings/"):
                try:
                    return self._send(200, service.action({"action": "get", "meeting_id": path.split("/")[-1]}))
                except ValueError as exc:
                    return self._send(404, {"error": str(exc)})
            return self._send(404, {"error": "此服务只提供会议 MCP 卡片；请使用 Agent Core 画布"})

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > 1_000_000:
                    raise ValueError("请求内容过大或为空")
                body = json.loads(self.rfile.read(size))
                if self.path == "/api/action":
                    return self._send(200, service.action(body))
                if self.path != "/mcp":
                    return self._send(404, {"error": "不存在"})
                rid, method, params = body.get("id"), body.get("method"), body.get("params") or {}
                if method == "initialize":
                    result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                              "serverInfo": {"name": "meeting-assistant", "version": "0.1.0"}}
                elif method == "tools/list":
                    result = {"tools": tools_list()}
                elif method == "tools/call":
                    value = dispatch_tool(service, params.get("name", ""), params.get("arguments") or {})
                    result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
                else:
                    raise ValueError(f"未知 MCP 方法：{method}")
                return self._send(200, {"jsonrpc": "2.0", "id": rid, "result": result})
            except (ValueError, TypeError, KeyError) as exc:
                if self.path == "/mcp":
                    return self._send(200, {"jsonrpc": "2.0", "id": locals().get("rid"),
                                            "error": {"code": -32602, "message": str(exc)}})
                return self._send(400, {"error": str(exc)})

    return Handler


def register_loop(port: int, stop: threading.Event):
    core = os.environ.get("AGENT_CORE_URL", "https://localhost:15678").rstrip("/")
    context = ssl._create_unverified_context() if core.startswith("https://localhost:") else None
    payload = json.dumps({"name": MCP_NAME, "url": f"http://localhost:{port}/mcp", "category": "driver"}).encode()
    while not stop.is_set():
        try:
            request = urllib.request.Request(f"{core}/api/mcp", payload,
                                             {"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=3, context=context):
                pass
            stop.wait(30)
        except Exception as exc:
            print(f"[register] {exc}", flush=True)
            stop.wait(5)


def main():
    port = int(os.environ.get("MEETING_PORT", "15740"))
    db_path = os.environ.get("MEETING_DB", "/opt/phanthy-motus/data/meeting-assistant/meetings.sqlite3")
    audio = AnnouncementPublisher(ROOT.parent / "assets", enabled=os.environ.get("MEETING_ROS", "1") == "1")
    service = MeetingService(db_path, audio=audio,
                             bumi_url=os.environ.get("BUMI_MCP_URL", "http://localhost:15704/mcp"),
                             enable_health_check=os.environ.get("MEETING_ENABLE_HEALTH_CHECK", "0") == "1")
    service.start_timer()
    if os.environ.get("REGISTER_AGENT_CORE", "1") == "1":
        threading.Thread(target=register_loop, args=(port, service._stop), daemon=True).start()
    http = ThreadingHTTPServer(("0.0.0.0", port), make_handler(service))
    print(f"[meeting] mcp=http://localhost:{port}/mcp", flush=True)
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        http.server_close()
        service.close()


if __name__ == "__main__":
    main()
