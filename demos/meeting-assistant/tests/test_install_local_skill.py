import json
import shutil
import sqlite3
import subprocess
import sys
import unittest
import uuid
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_local_skill.py"


class InstallLocalSkillTests(unittest.TestCase):
    def test_creates_missing_skills_row(self):
        scratch = ROOT / ".tmp"
        scratch.mkdir(exist_ok=True)
        test_dir = scratch / f"install-skill-{uuid.uuid4().hex}"
        test_dir.mkdir()
        try:
            db = test_dir / "data.db"
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                conn.commit()
            subprocess.run(
                [sys.executable, str(SCRIPT), "--db", str(db),
                 "--skill", str(ROOT / "SKILL.md")],
                check=True, capture_output=True,
            )
            with closing(sqlite3.connect(db)) as conn:
                value = conn.execute(
                    "SELECT value FROM config WHERE key='skills'"
                ).fetchone()[0]
            self.assertEqual(
                json.loads(value)["installed"][0]["slug"], "meeting-full-cycle-assistant"
            )
        finally:
            shutil.rmtree(test_dir)

    def test_preserves_other_skills_and_updates_by_slug(self):
        scratch = ROOT / ".tmp"
        scratch.mkdir(exist_ok=True)
        test_dir = scratch / f"install-skill-{uuid.uuid4().hex}"
        test_dir.mkdir()
        try:
            db = test_dir / "data.db"
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                conn.execute(
                    "INSERT INTO config VALUES('skills', ?)",
                    (json.dumps({"installed": [
                        {"slug": "keep-me", "name": "其他技能"},
                        {"slug": "meeting-full-cycle-assistant", "version": "0.1.0",
                         "installedAt": "2026-09-24T12:00:00+08:00",
                         "instruction": "old meeting_manager instruction",
                         "requiredTools": ["meeting_manager", "meeting_audio"]}
                    ]}),),
                )
                conn.commit()
            command = [
                sys.executable, str(SCRIPT), "--db", str(db),
                "--skill", str(ROOT / "SKILL.md"),
            ]
            subprocess.run(command, check=True, capture_output=True)
            subprocess.run(command, check=True, capture_output=True)
            with closing(sqlite3.connect(db)) as conn:
                value = conn.execute(
                    "SELECT value FROM config WHERE key='skills'"
                ).fetchone()[0]
            skills = json.loads(value)["installed"]
            self.assertEqual([s["slug"] for s in skills], [
                "keep-me", "meeting-full-cycle-assistant",
            ])
            meeting = skills[1]
            self.assertTrue(meeting["active"])
            self.assertEqual(meeting["version"], "0.3.0")
            self.assertEqual(meeting["installedAt"], "2026-09-24T12:00:00+08:00")
            self.assertEqual(meeting["requiredTools"], ["mic", "asr", "tts", "speaker", "health_check"])
            self.assertNotIn("meeting_manager", meeting["instruction"])
            self.assertNotIn("meeting_audio", meeting["instruction"])
            self.assertIn("继续收听", meeting["instruction"])
            self.assertIn("严禁调用 TTS", meeting["instruction"])
            self.assertIn('action: "check"', meeting["instruction"])
            self.assertIn("temperature_unassessed", meeting["instruction"])
            self.assertNotIn("不要调用健康检查", meeting["instruction"])
            self.assertFalse(meeting["instruction"].startswith("---"))
            backups = list(test_dir.glob("skills-row-backup-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(
                json.loads(backups[0].read_text(encoding="utf-8"))["key"], "skills"
            )
            old = json.loads(json.loads(backups[0].read_text(encoding="utf-8"))["value"])
            self.assertEqual(old["installed"][1]["version"], "0.1.0")
            self.assertEqual(skills[0], {"slug": "keep-me", "name": "其他技能"})
        finally:
            shutil.rmtree(test_dir)


if __name__ == "__main__":
    unittest.main()
