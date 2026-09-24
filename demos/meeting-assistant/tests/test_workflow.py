import json
import threading
import unittest
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from meeting_assistant.core import MeetingStore
from meeting_assistant.server import MeetingService, dispatch_tool, make_handler, tools_list


def future(hours=48):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).parent / f"test-{uuid.uuid4().hex}.sqlite3"
        self.store = MeetingStore(self.path)
        self.meeting = self.store.create("演示会议", ["张三", "李四"],
                                         [{"title": "讨论", "minutes": 10}, {"title": "总结", "minutes": 2}])
        self.mid = self.meeting["id"]

    def tearDown(self):
        self.store.close()
        for suffix in ("", "-wal", "-shm"):
            self.path.with_name(self.path.name + suffix).unlink(missing_ok=True)

    def test_preflight_requires_everyone_and_real_robot_report(self):
        self.assertFalse(self.meeting["preflight_ready"])
        for person in ("张三", "李四"):
            self.store.set_check(self.mid, "attendees", person, True)
        for item in ("投影", "网络"):
            self.store.set_check(self.mid, "equipment", item, True)
        with self.assertRaisesRegex(ValueError, "健康检查"):
            self.store.set_check(self.mid, "equipment", "Bumi", True)
        self.assertFalse(self.store.record_robot_health(self.mid, {"status": "数据不足"})["preflight_ready"])
        self.assertTrue(self.store.record_robot_health(self.mid, {"status": "正常"})["preflight_ready"])

    def test_agenda_cues_once_and_next_agenda_resets(self):
        at = datetime.now(timezone.utc).replace(microsecond=0)
        self.store.start(self.mid, at)
        self.assertEqual(self.store.tick(self.mid, at + timedelta(minutes=5))["announcements"], ["five_minutes"])
        self.assertEqual(self.store.tick(self.mid, at + timedelta(minutes=5))["announcements"], [])
        self.assertEqual(self.store.tick(self.mid, at + timedelta(minutes=10))["announcements"], ["time_up"])
        self.assertEqual(self.store.tick(self.mid, at + timedelta(minutes=11))["announcements"], [])
        self.store.next_agenda(self.mid, at + timedelta(minutes=11))
        self.assertEqual(self.store.tick(self.mid, at + timedelta(minutes=13))["announcements"], ["time_up"])

    def test_confirmation_submission_review_return_and_persistence(self):
        self.store.start(self.mid)
        draft = self.store.add_note(self.mid, "drafts", "完成电池测试")["drafts"][0]
        base = dict(owner="张三", deadline=future(), deliverable="测试报告",
                    reviewer="李四", acceptance="包含低电量和断流结果", confirmed=True)
        for key in ("owner", "deadline", "deliverable", "reviewer", "acceptance"):
            fields = dict(base)
            fields[key] = ""
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.store.confirm_task(self.mid, draft["id"], **fields)
        with self.assertRaisesRegex(ValueError, "明确确认"):
            self.store.confirm_task(self.mid, draft["id"], **{**base, "confirmed": False})
        task = self.store.confirm_task(self.mid, draft["id"], **base)
        with self.assertRaisesRegex(ValueError, "已生成"):
            self.store.confirm_task(self.mid, draft["id"], **base)
        with self.assertRaisesRegex(ValueError, "负责人"):
            self.store.submit_task(task["id"], "报告已完成", "李四")
        self.store.submit_task(task["id"], "报告链接", "张三")
        with self.assertRaisesRegex(ValueError, "验收人"):
            self.store.review_task(task["id"], True, "张三")
        returned = self.store.review_task(task["id"], False, "李四", "缺少断流结果")
        self.assertEqual(returned["status"], "returned")
        self.store.submit_task(task["id"], "补充断流结果的报告链接", "张三")
        self.assertEqual(self.store.review_task(task["id"], True, "李四")["status"], "accepted")
        self.store.close()
        self.store = MeetingStore(self.path)
        self.assertEqual(self.store.list_tasks(self.mid)[0]["status"], "accepted")
        self.assertEqual(self.store.get(self.mid)["drafts"][0]["task_id"], task["id"])

    def test_attention_states(self):
        self.store.start(self.mid)
        draft = self.store.add_note(self.mid, "drafts", "交付记录")["drafts"][0]
        task = self.store.confirm_task(self.mid, draft["id"], owner="张三", deadline=future(48),
                                       deliverable="记录", reviewer="李四", acceptance="可复核", confirmed=True)
        due = datetime.fromisoformat(task["deadline"])
        self.assertIsNone(self.store.list_tasks(self.mid, due-timedelta(hours=25))[0]["attention"])
        self.assertEqual(self.store.list_tasks(self.mid, due-timedelta(hours=23))[0]["attention"], "将到期")
        self.assertEqual(self.store.list_tasks(self.mid, due+timedelta(seconds=1))[0]["attention"], "逾期")
        self.store.submit_task(task["id"], "链接", "张三")
        self.assertEqual(self.store.list_tasks(self.mid, due+timedelta(seconds=1))[0]["attention"], "待验收")


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).parent / f"test-{uuid.uuid4().hex}.sqlite3"
        self.service = MeetingService(self.path)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.service))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.http.server_port}"

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.service.close()
        for suffix in ("", "-wal", "-shm"):
            self.path.with_name(self.path.name + suffix).unlink(missing_ok=True)

    def post(self, path, payload):
        request = urllib.request.Request(self.base+path, json.dumps(payload).encode(),
                                         {"Content-Type":"application/json"})
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    def test_http_and_mcp_expose_same_workflow(self):
        create = {"action":"create", "title":"测试会", "attendees":["甲", "乙"],
                  "agenda":[{"title":"议题", "minutes":1}]}
        meeting = self.post("/api/action", create)
        with urllib.request.urlopen(self.base+"/api/meetings") as response:
            self.assertEqual(json.load(response)[0]["id"], meeting["id"])
        rpc = self.post("/mcp", {"jsonrpc":"2.0", "id":2, "method":"tools/call",
                                 "params":{"name":"meeting_manager", "arguments":{"action":"get", "meeting_id":meeting["id"]}}})
        self.assertEqual(json.loads(rpc["result"]["content"][0]["text"])["meeting"]["id"], meeting["id"])
        names = [tool["name"] for tool in tools_list()]
        self.assertEqual(names, ["meeting_manager", "meeting_audio"])
        self.assertEqual(dispatch_tool(self.service, "meeting_audio", {"action":"info"})["topic_out"][0]["format"], "audio/pcm-16k")

    def test_robot_failure_is_data_insufficient(self):
        meeting = self.post("/api/action", {"action":"create", "title":"测试会", "attendees":["甲"],
                                             "agenda":[{"title":"议题", "minutes":1}]})
        with patch("meeting_assistant.server.call_mcp", side_effect=OSError("offline")):
            checked = self.post("/api/action", {"action":"check_robot", "meeting_id":meeting["id"]})
        robot = next(x for x in checked["equipment"] if x["name"] == "Bumi")
        self.assertEqual(robot["report"]["status"], "数据不足")
        self.assertFalse(robot["confirmed"])


if __name__ == "__main__":
    unittest.main()
