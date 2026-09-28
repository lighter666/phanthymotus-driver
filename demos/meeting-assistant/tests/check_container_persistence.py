"""Run on Bumi after deployment: verify the bind-mounted TXT survives container restart."""

import json
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:15742"
OUTPUT = Path("/home/noetix/meeting-minutes")


def request(method, params=None):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    req = urllib.request.Request(
        URL + "/mcp", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        value = json.load(response)
    if "error" in value:
        raise RuntimeError(value["error"])
    return value["result"]


def save(draft):
    result = request("tools/call", {"name": "meeting_minutes_export", "arguments": draft})
    return json.loads(result["content"][0]["text"])


def main():
    draft = {"action": "save", "title": f"容器持久化自动测试 {uuid.uuid4().hex}",
             "attendees": ["测试主持人"], "decisions": ["验证容器重启不丢失文件"],
             "tasks": [{"item": "核对持久化文件", "owner": "测试主持人"}]}
    first = save(draft)
    path = Path(first["path"])
    if path.parent != OUTPUT or first["status"] != "saved" or not path.is_file():
        raise RuntimeError(f"未在预定宿主机目录写入新文件：{first}")
    before = path.read_bytes()
    command = ["docker", "compose", "--env-file", ".env.minutes-export",
               "-f", "compose.minutes-export.yaml", "restart"]
    subprocess.run(command, cwd=ROOT, check=True)
    for _ in range(20):
        try:
            with urllib.request.urlopen(URL + "/healthz", timeout=2) as response:
                if json.load(response).get("status") == "ready":
                    break
        except Exception:
            time.sleep(0.5)
    else:
        raise RuntimeError("容器重启后服务未恢复；测试文件保留供排查")
    if not path.is_file() or path.read_bytes() != before:
        raise RuntimeError("容器重启后 TXT 丢失或内容变化；测试文件保留供排查")
    again = save(draft)
    if again["status"] != "existing" or again["path"] != str(path):
        raise RuntimeError(f"容器重启后重复调用未返回原文件：{again}")
    print(f"PASS: {path} survived restart, identical draft returned existing")
    path.unlink()


if __name__ == "__main__":
    main()
