import json
import shutil
import sqlite3
import subprocess
import sys
import unittest
import uuid
from contextlib import contextmanager
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_local_skill.py"
SLUG = "bumi-item-handover"
SCRATCH = ROOT / ".tmp"
SCRATCH.mkdir(exist_ok=True)


@contextmanager
def trial_db():
    directory = SCRATCH / f"trial-{uuid.uuid4().hex}"
    directory.mkdir()
    try:
        yield directory / "data.db"
    finally:
        if directory.resolve().is_relative_to(SCRATCH.resolve()):
            shutil.rmtree(directory)


def create_db(path: Path, settings=None):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        if settings is not None:
            conn.execute(
                "INSERT INTO config(key, value) VALUES('skills', ?)",
                (json.dumps(settings, ensure_ascii=False),),
            )
        conn.commit()


def read_settings(path: Path):
    with closing(sqlite3.connect(path)) as conn:
        row = conn.execute("SELECT value FROM config WHERE key='skills'").fetchone()
    return json.loads(row[0]) if row else None


def run_install(path: Path):
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT), "--db", str(path)],
        text=True, encoding="utf-8", errors="replace", capture_output=True,
    )


class InstallLocalSkillTests(unittest.TestCase):
    def test_missing_row_is_created_with_backup(self):
        with trial_db() as db:
            create_db(db)
            result = run_install(db)
            self.assertEqual(result.returncode, 0, result.stderr)
            skill = read_settings(db)["installed"][0]
            self.assertEqual(skill["slug"], SLUG)
            self.assertEqual(skill["requiredTools"], ["camera", "face_recognition", "vision_capture"])
            self.assertIn("capture_photo", skill["instruction"])
            self.assertIn("recognize_by_stream", skill["instruction"])
            backups = list(db.parent.glob("skills-row-backup-bumi-item-handover-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertIsNone(json.loads(backups[0].read_text(encoding="utf-8"))["value"])

    def test_update_is_idempotent_and_preserves_other_skills(self):
        with trial_db() as db:
            other = {"slug": "keep-me", "name": "其他技能", "instruction": "keep"}
            old = {"slug": SLUG, "version": "0.1.0", "instruction": "old",
                   "installedAt": "2026-09-24T12:00:00+08:00", "custom": "retain"}
            original = {"installed": [other, old, {**old, "instruction": "duplicate"}],
                        "marketplace": {"enabled": False}}
            create_db(db, original)
            first = run_install(db)
            second = run_install(db)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("unchanged", second.stdout)
            settings = read_settings(db)
            self.assertEqual(settings["marketplace"], original["marketplace"])
            self.assertEqual([item["slug"] for item in settings["installed"]],
                             ["keep-me", SLUG])
            self.assertEqual(settings["installed"][0], other)
            skill = settings["installed"][1]
            self.assertEqual(skill["installedAt"], old["installedAt"])
            self.assertEqual(skill["custom"], "retain")
            self.assertEqual(skill["version"], "1.1.0")
            backups = list(db.parent.glob("skills-row-backup-bumi-item-handover-*.json"))
            self.assertEqual(len(backups), 1)
            backed_up = json.loads(backups[0].read_text(encoding="utf-8"))
            self.assertEqual(json.loads(backed_up["value"]), original)

    def test_bad_config_does_not_write_or_back_up(self):
        with trial_db() as db:
            original = {"installed": "wrong"}
            create_db(db, original)
            result = run_install(db)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(read_settings(db), original)
            self.assertEqual(list(db.parent.glob("skills-row-backup-*.json")), [])


if __name__ == "__main__":
    unittest.main()
