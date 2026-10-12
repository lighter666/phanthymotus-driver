import csv
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import unittest
import uuid
from contextlib import closing, contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_local_skill.py"
SLUG = "bumi-item-handover"
FIELDS = (
    "asset_id", "asset_name", "category", "sn", "accessories", "status",
)
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


def write_assets(path: Path, rows=(), fields=FIELDS):
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def asset(asset_id="0001", name="投影仪A", category="投影仪", status="可用"):
    return {
        "asset_id": asset_id, "asset_name": name, "category": category,
        "sn": "SN-001", "accessories": "电源线1根", "status": status,
    }


def write_administrator(path: Path, name="", open_id=""):
    path.write_text(
        json.dumps({"name": name, "feishu_open_id": open_id}, ensure_ascii=False),
        encoding="utf-8",
    )


def read_settings(path: Path):
    with closing(sqlite3.connect(path)) as conn:
        row = conn.execute("SELECT value FROM config WHERE key='skills'").fetchone()
    return json.loads(row[0]) if row else None


def invoke(path: Path, assets: Path | None = None, *flags, administrator: Path | None = None):
    command = [sys.executable, "-X", "utf8", str(SCRIPT), "--db", str(path)]
    if assets:
        command.extend(["--assets", str(assets)])
    if administrator:
        command.extend(["--administrator", str(administrator)])
    command.extend(flags)
    return subprocess.run(
        command, text=True, encoding="utf-8", errors="replace", capture_output=True,
    )


def snapshot(instruction: str):
    tail = instruction.split("<!-- 资产目录数据开始", 1)[1]
    data, _ = json.JSONDecoder().raw_decode(tail[tail.index("{"):])
    return data


class InstallLocalSkillTests(unittest.TestCase):
    def test_empty_catalog_never_creates_candidate(self):
        with trial_db() as db:
            create_db(db)
            result = invoke(db)
            self.assertEqual(result.returncode, 0, result.stderr)
            skill = read_settings(db)["installed"][0]
            self.assertEqual(skill["version"], "5.0.0")
            self.assertEqual(skill["requiredTools"], ["face_recognition", "tts", "channel_reply"])
            self.assertEqual(snapshot(skill["instruction"])["资产目录"], [])
            self.assertEqual(snapshot(skill["instruction"])["管理员配置"],
                             {"姓名": "未配置", "飞书ID": "未配置"})
            self.assertEqual(snapshot(skill["instruction"])["候选索引"],
                             {"按类别": {}, "按名称": {}})
            self.assertIn("待人工转发", skill["instruction"])
            backups = list(db.parent.glob("skills-row-backup-bumi-item-handover-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertIsNone(json.loads(backups[0].read_text(encoding="utf-8"))["value"])

    def test_catalog_selects_first_available_as_text_and_skips_borrowed(self):
        with trial_db() as db:
            create_db(db)
            catalog = db.parent / "assets.csv"
            write_assets(catalog, [
                asset("0009", "投影仪A"),
                asset("0000", "投影仪C", status="借出"),
                asset("0001", "投影仪B"),
                asset("L-01", "笔记本", category="笔记本", status="停用"),
            ])
            self.assertEqual(invoke(db, catalog, "--validate-assets").returncode, 0)
            result = invoke(db, catalog)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = snapshot(read_settings(db)["installed"][0]["instruction"])
            self.assertEqual([entry["资产编号"] for entry in data["资产目录"]],
                             ["0000", "0001", "0009", "L-01"])
            self.assertEqual(data["候选索引"]["按类别"], {"投影仪": "0001"})
            self.assertEqual(data["候选索引"]["按名称"],
                             {"投影仪B": "0001", "投影仪A": "0009"})
            self.assertEqual(data["资产目录"][1]["SN"], "SN-001")
            self.assertNotIn("管理员飞书ID", data["资产目录"][1])

    def test_no_available_asset_has_no_candidate(self):
        with trial_db() as db:
            create_db(db)
            catalog = db.parent / "assets.csv"
            write_assets(catalog, [asset(status="借出")])
            self.assertEqual(invoke(db, catalog).returncode, 0)
            self.assertEqual(snapshot(read_settings(db)["installed"][0]["instruction"])
                             ["候选索引"], {"按类别": {}, "按名称": {}})

    def test_bad_catalog_does_not_write_or_back_up(self):
        with trial_db() as db:
            create_db(db, {"installed": []})
            catalog = db.parent / "assets.csv"
            cases = [
                [asset(), asset()],
                [asset(status="未知")],
                [{**asset(), "asset_name": ""}],
            ]
            for rows in cases:
                with self.subTest(rows=rows):
                    write_assets(catalog, rows)
                    result = invoke(db, catalog)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(read_settings(db), {"installed": []})
                    self.assertEqual(list(db.parent.glob("skills-row-backup-*.json")), [])
            write_assets(catalog, [
                {key: asset()[key] for key in FIELDS[:-1]}
            ], fields=FIELDS[:-1])
            self.assertNotEqual(invoke(db, catalog).returncode, 0)

    def test_update_is_idempotent_preserves_other_skills_and_detects_csv_change(self):
        with trial_db() as db:
            other = {"slug": "keep-me", "name": "其他技能", "instruction": "keep"}
            old = {"slug": SLUG, "version": "0.1.0", "instruction": "old",
                   "installedAt": "2026-09-24T12:00:00+08:00", "custom": "retain"}
            original = {"installed": [other, old, {**old, "instruction": "duplicate"}],
                        "marketplace": {"enabled": False}}
            create_db(db, original)
            catalog = db.parent / "assets.csv"
            write_assets(catalog, [asset()])
            self.assertEqual(invoke(db, catalog).returncode, 0)
            unchanged = invoke(db, catalog)
            self.assertEqual(unchanged.returncode, 0, unchanged.stderr)
            self.assertIn("unchanged", unchanged.stdout)
            settings = read_settings(db)
            self.assertEqual(settings["marketplace"], original["marketplace"])
            self.assertEqual([item["slug"] for item in settings["installed"]],
                             ["keep-me", SLUG])
            self.assertEqual(settings["installed"][0], other)
            self.assertEqual(settings["installed"][1]["installedAt"], old["installedAt"])
            self.assertEqual(settings["installed"][1]["custom"], "retain")
            self.assertEqual(invoke(db, catalog, "--check").returncode, 0)
            write_assets(catalog, [asset(status="借出")])
            self.assertNotEqual(invoke(db, catalog, "--check").returncode, 0)
            self.assertEqual(invoke(db, catalog).returncode, 0)
            self.assertEqual(invoke(db, catalog, "--check").returncode, 0)
            self.assertEqual(len(list(db.parent.glob("skills-row-backup-*.json"))), 2)

    def test_bad_skills_config_does_not_write(self):
        with trial_db() as db:
            original = {"installed": "wrong"}
            create_db(db, original)
            self.assertNotEqual(invoke(db).returncode, 0)
            self.assertEqual(read_settings(db), original)
            self.assertEqual(list(db.parent.glob("skills-row-backup-*.json")), [])

    def test_single_administrator_config_and_change_detection(self):
        with trial_db() as db:
            create_db(db)
            catalog = db.parent / "assets.csv"
            admin = db.parent / "administrator.json"
            write_assets(catalog, [asset("0001"), asset("0002", "笔记本", "笔记本")])
            write_administrator(admin, "陈管理员", "ou_admin")
            self.assertEqual(invoke(db, catalog, administrator=admin).returncode, 0)
            data = snapshot(read_settings(db)["installed"][0]["instruction"])
            self.assertEqual(data["管理员配置"], {"姓名": "陈管理员", "飞书ID": "ou_admin"})
            self.assertTrue(all("管理员" not in row for row in data["资产目录"]))
            self.assertEqual(invoke(db, catalog, "--check", administrator=admin).returncode, 0)
            write_administrator(admin, "新管理员", "ou_new")
            self.assertNotEqual(invoke(db, catalog, "--check", administrator=admin).returncode, 0)
            self.assertEqual(invoke(db, catalog, administrator=admin).returncode, 0)
            self.assertEqual(invoke(db, catalog, "--check", administrator=admin).returncode, 0)

    def test_bad_administrator_config_does_not_write(self):
        with trial_db() as db:
            create_db(db, {"installed": []})
            admin = db.parent / "administrator.json"
            cases = [
                {"name": "", "feishu_open_id": "ou_admin"},
                {"name": "管理员"},
                {"name": "管理员", "feishu_open_id": 123},
            ]
            for bad in cases:
                with self.subTest(bad=bad):
                    admin.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
                    self.assertNotEqual(invoke(db, administrator=admin).returncode, 0)
                    self.assertEqual(read_settings(db), {"installed": []})
                    self.assertEqual(list(db.parent.glob("skills-row-backup-*.json")), [])

    def test_instruction_uses_only_supported_card_actions(self):
        instruction = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        calls = re.findall(
            r'\b(tts|face_recognition)\(action="([^"]+)"([^)]*)\)', instruction
        )
        self.assertTrue(calls)
        allowed = {"tts": {"speak"}, "face_recognition": {"start", "recognize_by_stream"}}
        for tool, action, arguments in calls:
            self.assertIn(action, allowed[tool])
            if action == "start":
                self.assertIn('input_topic="/remote_control/camera"', arguments)
        self.assertNotRegex(instruction, r'\bocr\(action=')
        self.assertIn("source_message_id", instruction)
        self.assertIn("管理员飞书确认", instruction)
        self.assertIn("归还请求｜待人工转发给资产管理员", instruction)
        self.assertIn("唯一资产管理员", instruction)
        self.assertIn("等候员工到场", instruction)

    def test_read_only_check_rejects_legacy_and_conflicting_skill(self):
        with trial_db() as db:
            old = {"slug": SLUG, "version": "1.2.0", "active": True,
                   "instruction": "请管理员确认物品"}
            conflicting = {"slug": "old-handover", "name": "旧借还流程",
                           "active": True, "instruction": "请管理员确认物品"}
            create_db(db, {"installed": [old, conflicting]})
            before = read_settings(db)
            stale = invoke(db, None, "--check")
            self.assertNotEqual(stale.returncode, 0)
            self.assertEqual(read_settings(db), before)
            self.assertEqual(invoke(db).returncode, 0)
            conflict = invoke(db, None, "--check")
            self.assertNotEqual(conflict.returncode, 0)
            self.assertIn("old-handover", conflict.stdout)
            settings = read_settings(db)
            settings["installed"][1]["active"] = False
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("UPDATE config SET value=? WHERE key='skills'",
                             (json.dumps(settings, ensure_ascii=False),))
                conn.commit()
            current = invoke(db, None, "--check")
            self.assertEqual(current.returncode, 0, current.stdout + current.stderr)
            self.assertIn("Skill、资产 CSV 及管理员配置一致：是", current.stdout)


if __name__ == "__main__":
    unittest.main()
