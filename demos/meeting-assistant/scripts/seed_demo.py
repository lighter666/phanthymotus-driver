"""Create one safe sample meeting with two unassigned draft actions."""

import os

from meeting_assistant.core import MeetingStore


path = os.environ.get("MEETING_DB", "demo.sqlite3")
store = MeetingStore(path)
try:
    existing = next((m for m in store.list_meetings() if m["title"] == "Bumi 项目周会（演示）"), None)
    if existing:
        print(f"示例会议已存在：{existing['id']}")
    else:
        meeting = store.create(
            "Bumi 项目周会（演示）", ["主持人", "开发同学", "测试同学"],
            [{"title": "上周进展", "minutes": 10},
             {"title": "风险与决策", "minutes": 15},
             {"title": "行动项确认", "minutes": 10}],
            ["投影", "网络"],
        )
        store.start(meeting["id"])
        store.add_note(meeting["id"], "decisions", "下一轮演示优先验证 Bumi 健康检查与会议提示音。")
        store.add_note(meeting["id"], "drafts", "完成健康检查三类状态的真机测试报告")
        store.add_note(meeting["id"], "drafts", "整理会议提示音播放与断连恢复记录")
        store.end(meeting["id"])
        print(f"示例会议已创建：{meeting['id']}；两个行动项仍为草稿，需主持人确认")
finally:
    store.close()
