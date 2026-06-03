#!/usr/bin/env python3
"""将 hitl_sessions 中 status=pending 标为 expired（清理 E2E 测试遗留）。"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "lingji.db"


def main() -> int:
    if not DB.exists():
        print(f"未找到 {DB}")
        return 1
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT task_id, description FROM hitl_sessions WHERE status='pending'"
    ).fetchall()
    print(f"pending: {len(rows)}")
    for task_id, desc in rows:
        print(f"  {task_id[:28]}... {desc[:50]}")
    n = conn.execute(
        "UPDATE hitl_sessions SET status='expired', "
        "resolved_at=CURRENT_TIMESTAMP WHERE status='pending'"
    ).rowcount
    conn.commit()
    conn.close()
    print(f"expired: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
