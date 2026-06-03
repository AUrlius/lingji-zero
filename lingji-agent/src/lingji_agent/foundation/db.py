"""SQLite 持久化 — 表 DDL（LLDD）"""

import json
import sqlite3


def init_db(path: str = "lingji.db"):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT NOT NULL,
            msg_type TEXT NOT NULL,
            payload TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL DEFAULT 'pending',
            description TEXT,
            result TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS checkpoints (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            agent_state_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS hitl_sessions (
            id TEXT PRIMARY KEY,
            checkpoint_id TEXT NOT NULL REFERENCES checkpoints(id),
            task_id TEXT NOT NULL,
            description TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            resolved_at DATETIME
        );

        CREATE INDEX IF NOT EXISTS idx_checkpoints_thread ON checkpoints(thread_id);
        CREATE INDEX IF NOT EXISTS idx_checkpoints_status ON checkpoints(status);
        CREATE INDEX IF NOT EXISTS idx_hitl_sessions_checkpoint ON hitl_sessions(checkpoint_id);
        CREATE INDEX IF NOT EXISTS idx_hitl_sessions_pending ON hitl_sessions(status) WHERE status = 'pending';

        CREATE TABLE IF NOT EXISTS chat_sessions (
            thread_id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_device ON chat_sessions(device_id, updated_at DESC);
    """)
    conn.commit()
    return conn


def save_checkpoint(conn, checkpoint_id: str, thread_id: str, agent_state: dict, status: str = "running"):
    conn.execute(
        """INSERT OR REPLACE INTO checkpoints (id, thread_id, agent_state_json, status, updated_at)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (checkpoint_id, thread_id, json.dumps(agent_state), status),
    )
    conn.commit()


def load_checkpoint(conn, thread_id: str) -> dict | None:
    row = conn.execute(
        "SELECT agent_state_json, status FROM checkpoints WHERE thread_id = ? ORDER BY updated_at DESC LIMIT 1",
        (thread_id,),
    ).fetchone()
    if row:
        return {"state": json.loads(row[0]), "status": row[1]}
    return None


def get_pending_hitl_sessions(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, checkpoint_id, task_id, description, risk_level FROM hitl_sessions WHERE status = 'pending'"
    ).fetchall()
    return [
        {"id": r[0], "checkpoint_id": r[1], "task_id": r[2], "description": r[3], "risk_level": r[4]}
        for r in rows
    ]


def get_pending_hitl_sessions_with_checkpoints(conn) -> list[dict]:
    """未决 HITL + 关联 checkpoint（含 thread_id 与 agent_state）。"""
    rows = conn.execute(
        """
        SELECT h.id, h.checkpoint_id, h.task_id, h.description, h.risk_level,
               c.thread_id, c.agent_state_json, c.status, h.created_at
        FROM hitl_sessions h
        JOIN checkpoints c ON c.id = h.checkpoint_id
        WHERE h.status = 'pending'
        ORDER BY h.created_at ASC
        """
    ).fetchall()
    return [
        {
            "id": r[0],
            "checkpoint_id": r[1],
            "task_id": r[2],
            "description": r[3],
            "risk_level": r[4],
            "thread_id": r[5],
            "agent_state_json": r[6],
            "checkpoint_status": r[7],
            "created_at": r[8],
        }
        for r in rows
    ]


def get_pending_hitl_session_by_task_id(conn, task_id: str) -> dict | None:
    rows = get_pending_hitl_sessions_with_checkpoints(conn)
    for row in rows:
        if row["task_id"] == task_id:
            return row
    return None


def get_checkpoint_by_id(conn, checkpoint_id: str) -> dict | None:
    row = conn.execute(
        "SELECT id, thread_id, agent_state_json, status FROM checkpoints WHERE id = ?",
        (checkpoint_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "thread_id": row[1],
        "agent_state_json": row[2],
        "status": row[3],
    }


def update_hitl_session(conn, session_id: str, status: str):
    conn.execute(
        "UPDATE hitl_sessions SET status = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, session_id),
    )
    conn.commit()


def _session_title(text: str, max_len: int = 40) -> str:
    one_line = " ".join(text.strip().split())
    if len(one_line) <= max_len:
        return one_line or "新对话"
    return one_line[: max_len - 1] + "…"


def upsert_chat_session(
    conn,
    device_id: str,
    thread_id: str,
    title: str,
    *,
    set_active: bool = True,
) -> None:
    if set_active:
        conn.execute(
            "UPDATE chat_sessions SET is_active = 0 WHERE device_id = ?",
            (device_id,),
        )
    conn.execute(
        """
        INSERT INTO chat_sessions (thread_id, device_id, title, updated_at, is_active)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(thread_id) DO UPDATE SET
            title = CASE WHEN excluded.title != '' THEN excluded.title ELSE chat_sessions.title END,
            updated_at = CURRENT_TIMESTAMP,
            is_active = excluded.is_active
        """,
        (thread_id, device_id, title, 1 if set_active else 0),
    )
    conn.commit()


def list_chat_sessions(conn, device_id: str, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """
        SELECT thread_id, title, updated_at, is_active
        FROM chat_sessions
        WHERE device_id = ?
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (device_id, limit),
    ).fetchall()
    return [
        {
            "thread_id": r[0],
            "title": r[1],
            "updated_at": r[2],
            "active": bool(r[3]),
        }
        for r in rows
    ]


def get_active_chat_thread(conn, device_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT thread_id FROM chat_sessions
        WHERE device_id = ? AND is_active = 1
        ORDER BY updated_at DESC LIMIT 1
        """,
        (device_id,),
    ).fetchone()
    return row[0] if row else None


def set_active_chat_session(conn, device_id: str, thread_id: str) -> None:
    conn.execute(
        "UPDATE chat_sessions SET is_active = 0 WHERE device_id = ?",
        (device_id,),
    )
    conn.execute(
        """
        UPDATE chat_sessions SET is_active = 1, updated_at = CURRENT_TIMESTAMP
        WHERE thread_id = ? AND device_id = ?
        """,
        (thread_id, device_id),
    )
    conn.commit()
