"""SQLite 验证——仿 AndroidWorld：adb shell sqlite3 直接在设备上查询。

userdebug 镜像自带 /system/bin/sqlite3 二进制，无需 pull DB 到本地。
比 adb pull + Python sqlite3 更简单，且自动处理 WAL 模式。

对应 AW 的 is_successful() 中 SQLite 部分：
  AW: env.controller.pull_file() → Python sqlite3 → query
  我们: adb shell sqlite3 <db> "<SQL>" → 解析输出

Usage:
    from fastaget.sqlite_verify import SQLiteVerifySpec, run_sqlite_verification
    spec = SQLiteVerifySpec(
        db_path="/data/data/com.arduia.expense/databases/accounting.db",
        sql="SELECT COUNT(*) FROM expense WHERE name LIKE '%Lunch%'",
        expect="1",
    )
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import ClassVar


# ── AndroidWorld 已知的 SQLite DB 路径 ──
KNOWN_DB_PATHS: ClassVar[dict[str, tuple[str, str, str]]] = {
    # (db_path, table_name, key_column) — AW 源码中定义
    "calendar": (
        "/data/data/com.simplemobiletools.calendar.pro/databases/events.db",
        "events",
        "title",
    ),
    "expense": (
        "/data/data/com.arduia.expense/databases/accounting.db",
        "expense",
        "name",
    ),
    "recipe": (
        "/data/data/com.flauschcode.broccoli/databases/broccoli",
        "recipes",
        "title",
    ),
    "retro_music": (
        "/data/data/code.name.monkey.retromusic/databases/playlist.db",
        "PlaylistEntity",
        "name",
    ),
    "vlc": (
        "/data/data/org.videolan.vlc/app_db/vlc_media.db",
        "Playlist",
        "name",
    ),
    "osmand": (
        "/data/data/net.osmand/databases/map_markers_db",
        "map_markers",
        "name",
    ),
    "tasks": (
        "/data/data/org.tasks/databases/tasks.db",
        "tasks",
        "title",
    ),
    "joplin": (
        "/data/data/net.cozic.joplin/databases/joplin.db",
        "notes",
        "title",
    ),
    "opentracks": (
        "/data/data/de.dennisguse.opentracks/databases/opentracks.db",
        "tracks",
        "name",
    ),
}


@dataclass
class SQLiteVerifySpec:
    """SQLite 数据库验证规则。

    直接拼 SQL 在设备端 sqlite3 执行，返回行数/值。
    """

    db_path: str = ""       # 设备上 DB 完整路径
    table: str = ""         # 表名
    where_col: str = ""     # 比对列
    expect_val: str = ""    # 期望值（LIKE 匹配）
    min_rows: int = 1       # 最少匹配行数
    not_empty: bool = False # 只要 COUNT(*) > 0 即可

    @classmethod
    def from_dict(cls, d: dict) -> "SQLiteVerifySpec":
        return cls(
            db_path=d.get("db_path", ""),
            table=d.get("table", ""),
            where_col=d.get("where_col", ""),
            expect_val=d.get("expect_val", ""),
            min_rows=d.get("min_rows", 1),
            not_empty=d.get("not_empty", False),
        )

    def to_sql(self) -> str:
        """生成 sqlite3 查询语句。"""
        if self.not_empty:
            return f"SELECT COUNT(*) FROM [{self.table}]"
        if self.where_col and self.expect_val:
            return (
                f"SELECT COUNT(*) FROM [{self.table}] "
                f"WHERE [{self.where_col}] LIKE '%{self.expect_val}%'"
            )
        if self.where_col:
            return f"SELECT COUNT(*) FROM [{self.table}] WHERE [{self.where_col}] IS NOT NULL"
        return f"SELECT COUNT(*) FROM [{self.table}]"


@dataclass
class SQLiteVerifyResult:
    passed: bool
    spec: SQLiteVerifySpec
    row_count: int = 0
    error: str = ""

    def reason(self) -> str:
        if self.error:
            return f"[sqlite:{self.spec.table}] {self.error}"
        return (
            f"[sqlite:{self.spec.table}] "
            f"COUNT={self.row_count} (需要 >={self.spec.min_rows})"
        )


def _adb_root(serial: str) -> bool:
    """确保 adb 以 root 运行（userdebug 镜像）。"""
    try:
        r = subprocess.run(
            ["adb", "-s", serial, "root"],
            capture_output=True, text=True, timeout=10,
        )
        return "restarting" in r.stdout or "already running as root" in r.stdout
    except Exception:
        return False


def _sqlite3_count(serial: str, db_path: str, sql: str) -> int | None:
    """在设备上执行 sqlite3 查询，返回 COUNT 结果。返回 None 表示失败。"""
    try:
        # 先强制 checkpoint WAL
        subprocess.run(
            ["adb", "-s", serial, "shell",
             f"sqlite3 {db_path} 'PRAGMA wal_checkpoint(TRUNCATE);'"],
            capture_output=True, text=True, timeout=10,
        )
        # 执行查询
        r = subprocess.run(
            ["adb", "-s", serial, "shell",
             f"sqlite3 {db_path} \"{sql}\""],
            capture_output=True, text=True, timeout=10,
        )
        output = r.stdout.strip()
        if output and output.isdigit():
            return int(output)
        return None
    except Exception:
        return None


def run_sqlite_verification(
    specs: list[SQLiteVerifySpec],
    serial: str,
) -> list[SQLiteVerifyResult]:
    """执行 SQLite 验证——adb shell sqlite3 直接在设备上查询。

    对应 AW 的 is_successful() 中 SQLite 部分。
    """
    _adb_root(serial)

    results: list[SQLiteVerifyResult] = []
    for spec in specs:
        try:
            sql = spec.to_sql()
            count = _sqlite3_count(serial, spec.db_path, sql)

            if count is None:
                results.append(SQLiteVerifyResult(
                    passed=False, spec=spec,
                    error=f"查询失败或 DB/表不存在: {spec.db_path}",
                ))
                continue

            passed = count >= spec.min_rows
            results.append(SQLiteVerifyResult(
                passed=passed, spec=spec, row_count=count,
            ))
        except Exception as e:
            results.append(SQLiteVerifyResult(
                passed=False, spec=spec, error=str(e)[:200],
            ))
    return results


def run_sqlite_verify_from_dicts(
    verify_dicts: list[dict],
    serial: str,
) -> list[SQLiteVerifyResult]:
    """从 YAML 字典列表创建 specs 并执行验证。"""
    specs = [SQLiteVerifySpec.from_dict(d) for d in verify_dicts]
    return run_sqlite_verification(specs, serial)


def run_text_answer_verification(
    agent_summary: str,
    expected: str,
) -> bool:
    """文本答案验证——fuzzy match agent 的 complete() 结果与预期答案。

    对应 AW 的 check_agent_answer()。
    """
    import re

    def _normalize(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    agent_norm = _normalize(agent_summary)
    expected_parts = [p.strip() for p in expected.split("|")]
    for part in expected_parts:
        part_norm = _normalize(part)
        if part_norm in agent_norm:
            return True
    return False
