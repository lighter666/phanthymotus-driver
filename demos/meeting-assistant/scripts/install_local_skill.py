"""Install the meeting Skill into Agent Core's local ConfigDB.

This is for offline demos where Resource Center is unavailable. It updates
only the `skills` row and keeps a private copy of the previous row.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

SLUG = "meeting-full-cycle-assistant"
DEFAULT_DB = Path("/opt/phanthy-motus/data/data.db")
DEFAULT_SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


def read_skill(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md 缺少开头的 YAML 元数据")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise ValueError("SKILL.md 缺少结束的 YAML 分隔线")
    metadata = text[4:marker]
    description = next(
        (line.split(":", 1)[1].strip() for line in metadata.splitlines()
         if line.startswith("description:")), ""
    )
    instruction = text[marker + len("\n---\n"):].strip()
    if not instruction or not description:
        raise ValueError("SKILL.md 缺少说明或指令正文")
    return description, instruction


def install(db_path: Path, skill_path: Path) -> tuple[str, Path | None]:
    if not db_path.is_file():
        raise FileNotFoundError(f"Agent Core 数据库不存在：{db_path}")
    description, instruction = read_skill(skill_path)
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    template = {
        "slug": SLUG,
        "name": "会议全流程助手",
        "description": description,
        "oneLiner": "听取汇报，口头总结负责人、期限、交付物和验收标准",
        "instruction": instruction,
        "category": "robot",
        "version": "0.1.0",
        "author": "local",
        "installedAt": now,
        "active": True,
        "requiredTools": ["meeting_manager", "meeting_audio", "mic", "asr", "tts", "speaker"],
        "configSchema": {},
        "icon": "📋",
    }
    with closing(sqlite3.connect(db_path, timeout=15)) as conn:
        conn.execute("PRAGMA busy_timeout=15000")
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='config'"
        ).fetchone():
            raise ValueError("数据库没有 Agent Core 的 config 表")
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT value FROM config WHERE key='skills'"
        ).fetchone()
        old_value = row[0] if row else None
        settings = json.loads(old_value) if old_value else {"installed": []}
        if not isinstance(settings, dict) or not isinstance(settings.get("installed"), list):
            raise ValueError("skills 配置格式不正确，已停止写入")
        installed = settings["installed"]
        existing = next((s for s in installed if s.get("slug") == SLUG), None)
        if existing:
            template["installedAt"] = existing.get("installedAt") or now
            template = {**existing, **template}
        updated = [s for s in installed if s.get("slug") != SLUG]
        updated.insert(
            next((i for i, s in enumerate(installed) if s.get("slug") == SLUG), len(installed)),
            template,
        )
        if updated == installed:
            conn.rollback()
            return "unchanged", None
        settings["installed"] = updated

        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = db_path.with_name(f"skills-row-backup-{stamp}.json")
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump({"key": "skills", "value": old_value}, file, ensure_ascii=False)
        conn.execute(
            "INSERT INTO config(key, value) VALUES('skills', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(settings, ensure_ascii=False),),
        )
        conn.commit()
        return ("updated" if existing else "installed"), backup


def main() -> None:
    parser = argparse.ArgumentParser(description="本地安装 Bumi 会议 Skill")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--skill", type=Path, default=DEFAULT_SKILL)
    args = parser.parse_args()
    status, backup = install(args.db, args.skill)
    print(f"{status}: {SLUG}")
    if backup:
        print(f"原 skills 配置备份：{backup}")
    print("active=true 表示已在 Skill 列表启用；完整指令在 Agent 调用 activate_skill 后加载。")


if __name__ == "__main__":
    main()
