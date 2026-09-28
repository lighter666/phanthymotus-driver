import json
import shutil
import sys
import threading
import unittest
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from minutes_export.service import MinutesStore
from minutes_export.server import dispatch_rpc, handler


class MinutesExportTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / ".tmp"
        scratch.mkdir(exist_ok=True)
        test_dir = scratch / f"minutes-{uuid.uuid4().hex}"
        test_dir.mkdir()
        self.addCleanup(lambda: shutil.rmtree(test_dir))
        self.output = test_dir / "minutes"
        self.store = MinutesStore(self.output)
        self.draft = {
            "action": "save",
            "title": "Bumi 产品演示准备",
            "attendees": ["张三", "李四"],
            "robot_status": "未检查",
            "decisions": ["完成演示检查"],
            "tasks": [
                {"item": "演示检查", "owner": "张三", "deadline": "2026-10-02 18:00 北京时间",
                 "deliverable": "演示检查清单", "reviewer": "李四",
                 "acceptance": "麦克风转写、任务字段和语音播报三项都有测试结果"},
                {"item": "准备演示视频", "deliverable": "演示视频"},
            ],
            "pending": ["投影和网络待确认"],
        }

    def test_utf8_content_includes_five_fields_and_missing_markers(self):
        result = self.store.save(self.draft)
        content = Path(result["path"]).read_text(encoding="utf-8")
        self.assertEqual(result["status"], "saved")
        self.assertIn("会议主题：Bumi 产品演示准备", content)
        self.assertIn("Bumi 健康检查：未检查", content)
        self.assertIn("关键决策：\n1. 完成演示检查", content)
        self.assertIn("负责人：张三", content)
        self.assertIn("截止时间：2026-10-02 18:00 北京时间", content)
        self.assertIn("交付物：演示检查清单", content)
        self.assertIn("验收人：李四", content)
        self.assertIn("验收标准：麦克风转写、任务字段和语音播报三项都有测试结果", content)
        self.assertIn("事项：准备演示视频\n   负责人：待确认\n   截止时间：待确认", content)
        self.assertIn("验收人：待确认\n   验收标准：待确认", content)
        self.assertIn("纪要状态：草稿", content)
        self.assertIn("投影和网络待确认", content)

    def test_same_draft_is_idempotent_after_restart_and_revision_is_new_file(self):
        first = self.store.save(self.draft)
        again = MinutesStore(self.output).save(self.draft)
        self.assertEqual(again["status"], "existing")
        self.assertEqual(first["path"], again["path"])
        revised = json.loads(json.dumps(self.draft, ensure_ascii=False))
        revised["tasks"][1]["owner"] = "李四"
        second = MinutesStore(self.output).save(revised)
        self.assertEqual(second["status"], "saved")
        self.assertNotEqual(first["path"], second["path"])
        self.assertEqual(len(list(self.output.glob("*.txt"))), 2)
        self.assertIn("负责人：待确认", Path(first["path"]).read_text(encoding="utf-8"))
        self.assertIn("负责人：李四", Path(second["path"]).read_text(encoding="utf-8"))

    def test_rejects_invalid_input_without_writing_or_accepting_path(self):
        bad = dict(self.draft, tasks="not a list")
        with self.assertRaises(ValueError):
            self.store.save(bad)
        with self.assertRaises(ValueError):
            self.store.save(dict(self.draft, save_path="/tmp/elsewhere"))
        with self.assertRaises(ValueError):
            self.store.save(dict(self.draft, title="\x00bad"))
        self.assertFalse(self.output.exists())

    def test_mcp_returns_path_only_after_success_and_rejects_unknown_tool(self):
        listed = dispatch_rpc(self.store, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        self.assertEqual(listed["result"]["tools"][0]["name"], "meeting_minutes_export")
        rejected = dispatch_rpc(self.store, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                             "params": {"name": "meeting_minutes_export", "arguments": {"action": "save", "tasks": 3}}})
        self.assertIn("error", rejected)
        self.assertNotIn("path", json.dumps(rejected))
        good = dispatch_rpc(self.store, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                         "params": {"name": "meeting_minutes_export", "arguments": self.draft}})
        value = json.loads(good["result"]["content"][0]["text"])
        self.assertTrue(Path(value["path"]).is_file())
        wrong = dispatch_rpc(self.store, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                          "params": {"name": "meeting_manager", "arguments": self.draft}})
        self.assertIn("error", wrong)

    def test_mcp_lifecycle_and_initialized_notification(self):
        self.assertIsNone(dispatch_rpc(self.store, {"jsonrpc": "2.0", "method": "notifications/initialized"}))
        stopped = dispatch_rpc(self.store, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                            "params": {"name": "meeting_minutes_export", "arguments": {"action": "stop"}}})
        self.assertEqual(json.loads(stopped["result"]["content"][0]["text"])["state"], "idle")
        refused = dispatch_rpc(self.store, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                            "params": {"name": "meeting_minutes_export", "arguments": self.draft}})
        self.assertIn("error", refused)
        started = dispatch_rpc(self.store, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                            "params": {"name": "meeting_minutes_export", "arguments": {"action": "start"}}})
        self.assertEqual(json.loads(started["result"]["content"][0]["text"])["state"], "ready")

    def test_http_mcp_writes_file_and_no_download_route(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.store))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), worker.join()))
        url = f"http://127.0.0.1:{server.server_port}"
        request = urllib.request.Request(url + "/mcp", method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                             "params": {"name": "meeting_minutes_export", "arguments": self.draft}},
                            ensure_ascii=False).encode("utf-8"))
        with urllib.request.urlopen(request) as response:
            value = json.loads(json.load(response)["result"]["content"][0]["text"])
        self.assertTrue(Path(value["path"]).exists())
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url + "/")
        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
