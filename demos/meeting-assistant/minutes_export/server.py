"""Loopback-only MCP endpoint for the meeting minutes export card."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .service import MinutesStore


TOOL = {
    "name": "meeting_minutes_export", "type": "actuator", "multiInstance": False,
    "description": "把会议纪要草稿保存到 Bumi 本地 TXT；缺失的任务字段标为待确认，不派单。",
    "inputSchema": {
        "type": "object", "additionalProperties": False, "required": ["action"],
        "properties": {
            "action": {"type": "string", "enum": ["save"]},
            "title": {"type": "string"}, "attendees": {"type": "array", "items": {"type": "string"}},
            "robot_status": {"type": "string"},
            "decisions": {"type": "array", "items": {"type": "string"}},
            "pending": {"type": "array", "items": {"type": "string"}},
            "tasks": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                "properties": {key: {"type": "string"} for key in
                               ("item", "owner", "deadline", "deliverable", "reviewer", "acceptance")}}},
        },
    },
}


def dispatch_rpc(store, body):
    request_id = body.get("id") if isinstance(body, dict) else None
    try:
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
            raise ValueError("invalid JSON-RPC request")
        if "id" not in body:
            return None
        params = body.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        method = body.get("method")
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "bumi-meeting-minutes-export", "version": "1.0.0"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [TOOL]}
        elif method == "tools/call":
            if params.get("name") != TOOL["name"] or not isinstance(params.get("arguments"), dict):
                raise ValueError("unknown tool or invalid arguments")
            value = store.dispatch(params["arguments"])
            result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
        else:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32601, "message": "Method not found"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except (ValueError, TypeError, RuntimeError, OSError) as exc:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32602, "message": str(exc)}}


def handler(store):
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status, value):
            raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/healthz":
                return self.send_json(200, {"status": "ready"})
            return self.send_json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/mcp":
                return self.send_json(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 262144:
                    return self.send_json(413, {"error": "invalid body size"})
                body = json.loads(self.rfile.read(length))
            except (ValueError, TypeError):
                return self.send_json(400, {"error": "invalid JSON"})
            response = dispatch_rpc(store, body)
            if response is None:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return self.send_json(200, response)
    return Handler


def main():
    directory = Path(os.environ.get("MEETING_EXPORT_DIR", "/data"))
    public_directory = Path(os.environ.get("MEETING_PUBLIC_DIR", "/home/noetix/meeting-minutes"))
    store = MinutesStore(directory, public_directory)
    server = ThreadingHTTPServer(("127.0.0.1", 15742), handler(store))
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
