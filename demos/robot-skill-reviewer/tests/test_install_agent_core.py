"""Checks for the offline Agent Core Skill installer."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "install_agent_core.py"
SPEC = importlib.util.spec_from_file_location("install_agent_core", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        fd, name = tempfile.mkstemp(suffix=".db", dir=Path(__file__).resolve().parent)
        os.close(fd)
        self.db = Path(name)
        self.addCleanup(self.db.unlink, missing_ok=True)
        self.initial = {"installed": [{"slug": "meeting-full-cycle-assistant", "active": True}]}
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute(
                "INSERT INTO config(key, value) VALUES(?, ?)",
                ("skills", json.dumps(self.initial)),
            )
            conn.commit()

    def read_settings(self) -> dict:
        with closing(sqlite3.connect(self.db)) as conn:
            value = conn.execute(
                "SELECT value FROM config WHERE key='skills'"
            ).fetchone()[0]
        return json.loads(value)

    def test_preserves_existing_skill_and_embeds_rubric(self) -> None:
        status, backup = MODULE.install(self.db, ROOT)
        self.assertEqual(status, "installed")
        self.assertIsNotNone(backup)
        self.addCleanup(backup.unlink, missing_ok=True)
        self.assertEqual(json.loads(backup.read_text(encoding="utf-8"))["value"],
                         json.dumps(self.initial))
        settings = self.read_settings()
        self.assertEqual(len(settings["installed"]), 2)
        reviewer = settings["installed"][1]
        self.assertEqual(reviewer["slug"], "robot-skill-reviewer")
        self.assertTrue(reviewer["active"])
        self.assertIn("一票否决项", reviewer["instruction"])
        self.assertIn("评分表", reviewer["instruction"])

    def test_repeat_is_idempotent(self) -> None:
        _, created_backup = MODULE.install(self.db, ROOT)
        self.addCleanup(created_backup.unlink, missing_ok=True)
        before = self.read_settings()
        status, backup = MODULE.install(self.db, ROOT)
        self.assertEqual((status, backup), ("unchanged", None))
        self.assertEqual(before, self.read_settings())

    def test_missing_rubric_does_not_change_database(self) -> None:
        with patch.object(MODULE, "build_skill", side_effect=FileNotFoundError("rubric missing")):
            with self.assertRaises(FileNotFoundError):
                MODULE.install(self.db, ROOT)
        self.assertEqual(self.read_settings(), self.initial)


if __name__ == "__main__":
    unittest.main()
