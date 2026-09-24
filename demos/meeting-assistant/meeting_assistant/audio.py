"""Publish fixed agenda reminders as text for the existing TTS card."""

from __future__ import annotations

import json
from pathlib import Path

TOPIC = "/meeting_assistant/announcements"
CUES = {
    "five_minutes": "本项议程还剩五分钟，请注意时间。",
    "time_up": "本项议程时间到，请主持人决定是否进入下一项。",
}


class AnnouncementPublisher:
    def __init__(self, assets: Path, enabled: bool = True):
        # Keep the old constructor shape so existing deployments can upgrade.
        self.error: str | None = None
        self._publisher = None
        self._node = None
        if not enabled:
            self.error = "ROS 提醒未启用"
            return
        try:
            import rclpy
            from std_msgs.msg import String

            if not rclpy.ok():
                rclpy.init()
            self._node = rclpy.create_node("meeting_announcement")
            self._publisher = self._node.create_publisher(String, TOPIC, 10)
            self._message_type = String
        except Exception as exc:
            self.error = f"ROS 提醒不可用：{exc}"

    @property
    def available(self) -> bool:
        return self._publisher is not None

    def announce(self, cue: str) -> bool:
        if not self.available:
            return False
        if cue not in CUES:
            self.error = f"未知提醒：{cue}"
            return False
        try:
            message = self._message_type()
            message.data = json.dumps({"text": CUES[cue]}, ensure_ascii=False)
            self._publisher.publish(message)
            self.error = None
            return True
        except Exception as exc:
            self.error = f"提醒发布失败：{exc}"
            return False

    def close(self):
        if self._node is not None:
            self._node.destroy_node()
