"""Install or update the Bumi item handover Skill in a local Agent Core ConfigDB."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path


SLUG = "bumi-item-handover"
VERSION = "2.0.1"
DEFAULT_DB = Path("/opt/phanthy-motus/data/data.db")
DEFAULT_SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


def read_skill(path: Path) -> tuple[str, str]:
    content = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not content.startswith("---\n"):
        raise ValueError("SKILL.md 缺少开头的 YAML 元数据")
    end = content.find("\n---\n", 4)
    if end < 0:
        raise ValueError("SKILL.md 缺少结束的 YAML 分隔线")
    metadata = content[4:end]
    fields = dict(
        line.split(":", 1) for line in metadata.splitlines() if ":" in line
    )
    if fields.get("name", "").strip() != SLUG:
        raise ValueError(f"SKILL.md 的 name 必须是 {SLUG}")
    description = fields.get("description", "").strip()
    instruction = content[end + len("\n---\n"):].strip()
    if not description or not instruction:
        raise ValueError("SKILL.md 缺少 description 或指令正文")
    return description, instruction


def install(db_path: Path, skill_path: Path) -> tuple[str, Path | None]:
    if not db_path.is_file():
        raise FileNotFoundError(f"Agent Core 数据库不存在：{db_path}")
    description, instruction = read_skill(skill_path)
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    template = {
        "slug": SLUG,
        "name": "Bumi 办公物品借还自助核验",
        "description": description,
        "oneLiner": "自助核对人员、物品和配件，拍照记录差异",
        "instruction": instruction,
        "category": "robot",
        "version": VERSION,
        "author": "local",
        "installedAt": now,
        "active": True,
        "requiredTools": ["camera", "face_recognition", "ocr", "vop", "vision_capture"],
        "configSchema": {},
        "icon": "📷",
    }
    with closing(sqlite3.connect(db_path, timeout=15)) as conn:
        conn.execute("PRAGMA busy_timeout=15000")
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='config'"
        ).fetchone():
            raise ValueError("数据库没有 Agent Core 的 config 表")
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT value FROM config WHERE key='skills'").fetchone()
        old_value = row[0] if row else None
        settings = json.loads(old_value) if old_value else {"installed": []}
        if not isinstance(settings, dict) or not isinstance(settings.get("installed"), list):
            raise ValueError("skills 配置格式不正确，已停止写入")
        installed = settings["installed"]
        if any(not isinstance(item, dict) for item in installed):
            raise ValueError("installed 中存在无效 Skill，已停止写入")

        current = next((item for item in installed if item.get("slug") == SLUG), None)
        if current:
            template["installedAt"] = current.get("installedAt") or now
            template = {**current, **template}
        first_index = next(
            (index for index, item in enumerate(installed) if item.get("slug") == SLUG),
            len(installed),
        )
        updated = [item for item in installed if item.get("slug") != SLUG]
        updated.insert(first_index, template)
        if updated == installed:
            conn.rollback()
            return "unchanged", None

        settings["installed"] = updated
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = db_path.with_name(f"skills-row-backup-{SLUG}-{stamp}.json")
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump({"key": "skills", "value": old_value}, output, ensure_ascii=False)

        conn.execute(
            "INSERT INTO config(key, value) VALUES('skills', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(settings, ensure_ascii=False),),
        )
        saved = conn.execute("SELECT value FROM config WHERE key='skills'").fetchone()
        if not saved or json.loads(saved[0]) != settings:
            raise RuntimeError("skills 配置写入后核对失败，已回滚")
        conn.commit()

    with closing(sqlite3.connect(db_path)) as verify:
        actual = verify.execute("SELECT value FROM config WHERE key='skills'").fetchone()
        if not actual or json.loads(actual[0]) != settings:
            raise RuntimeError("提交后重新读取 skills 配置不一致，请使用备份排查")
    return ("updated" if current else "installed"), backup


def check_install(db_path: Path, skill_path: Path) -> None:
    """Read-only check that Agent Core stores this exact self-service Skill."""
    if not db_path.is_file():
        raise FileNotFoundError(f"Agent Core 数据库不存在：{db_path}")
    _, expected_instruction = read_skill(skill_path)
    with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as conn:
        row = conn.execute("SELECT value FROM config WHERE key='skills'").fetchone()
    settings = json.loads(row[0]) if row and row[0] else {"installed": []}
    if not isinstance(settings, dict) or not isinstance(settings.get("installed"), list):
        raise ValueError("skills 配置格式不正确")
    matches = [item for item in settings["installed"]
               if isinstance(item, dict) and item.get("slug") == SLUG]
    if len(matches) != 1:
        raise RuntimeError(f"数据库中应有 1 个 {SLUG}，实际找到 {len(matches)} 个")
    current = matches[0]
    instruction = current.get("instruction", "")
    same_instruction = instruction == expected_instruction
    old_prompt = any(phrase in instruction for phrase in (
        "请管理员", "由管理员确认", "管理员负责", "待管理员处理",
    ))
    print(f"数据库 Skill：{SLUG} 版本={current.get('version', '未知')} active={current.get('active')}")
    print(f"与本目录 SKILL.md 一致：{'是' if same_instruction else '否'}")
    print(f"包含旧版管理员提问：{'是' if old_prompt else '否'}")
    conflicting = [str(item.get("slug") or "无 slug") for item in settings["installed"]
                   if isinstance(item, dict) and item.get("slug") != SLUG
                   and item.get("active") is True
                   and "借还" in (str(item.get("name", "")) + str(item.get("description", "")))
                   and "请管理员" in str(item.get("instruction", ""))]
    print(f"其他激活的管理员版借还 Skill：{', '.join(conflicting) if conflicting else '无'}")
    if current.get("version") != VERSION or current.get("active") is not True \
            or not same_instruction or old_prompt or conflicting:
        raise RuntimeError("Bumi 数据库仍存在旧版借还指令；请更新当前 Skill，并停用冲突的旧借还 Skill")


def main() -> None:
    parser = argparse.ArgumentParser(description="本地安装 Bumi 办公物品借还 Skill")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--skill", type=Path, default=DEFAULT_SKILL)
    parser.add_argument("--check", action="store_true", help="只读核对数据库是否启用本目录的自助版 Skill")
    args = parser.parse_args()
    if args.check:
        check_install(args.db, args.skill)
        return
    status, backup = install(args.db, args.skill)
    print(f"{status}: {SLUG}")
    if backup:
        print(f"原 skills 配置备份：{backup}")
    print("已核对数据库写入；请刷新 Skill 列表并重新激活该 Skill 以加载新指令。")


if __name__ == "__main__":
    main()
