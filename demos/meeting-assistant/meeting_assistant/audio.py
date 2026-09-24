"""ROS2 PCM publisher for Bumi's existing speaker card."""

from __future__ import annotations

import threading
import time
import wave
from pathlib import Path

TOPIC = "/meeting_assistant/announcements"


class AnnouncementPublisher:
    def __init__(self, assets: Path, enabled: bool = True):
        self.assets = assets
        self.error: str | None = None
        self._publisher = None
        self._node = None
        self._lock = threading.Lock()
        if not enabled:
            self.error = "ROS 播报未启用"
            return
        try:
            import rclpy
            from audio_msgs.msg import AudioChunk

            if not rclpy.ok():
                rclpy.init()
            self._node = rclpy.create_node("meeting_announcement")
            self._publisher = self._node.create_publisher(AudioChunk, TOPIC, 10)
            self._chunk_type = AudioChunk
        except Exception as exc:
            self.error = f"ROS 播报不可用：{exc}"

    @property
    def available(self) -> bool:
        return self._publisher is not None

    def announce(self, cue: str) -> bool:
        if not self.available:
            return False
        path = self.assets / f"{cue}.wav"
        if not path.is_file():
            self.error = f"提示音文件缺失：{cue}"
            return False

        def worker():
            try:
                with self._lock, wave.open(str(path), "rb") as wav:
                    if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
                        raise ValueError("提示音须为 mono PCM16 16kHz WAV")
                    # Bumi SpeakerPlugin expects audio_msgs/AudioChunk with raw
                    # little-endian PCM bytes and this exact format string.
                    while True:
                        frames = wav.readframes(320)
                        if not frames:
                            break
                        msg = self._chunk_type()
                        msg.format = "pcm_16k_16bit_mono"
                        msg.data = frames
                        self._publisher.publish(msg)
                        time.sleep(0.02)
                self.error = None
            except Exception as exc:
                self.error = f"播报失败：{exc}"

        threading.Thread(target=worker, daemon=True, name=f"cue-{cue}").start()
        return True

    def close(self):
        if self._node is not None:
            self._node.destroy_node()
