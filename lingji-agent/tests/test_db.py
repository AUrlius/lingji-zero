"""数据库模块单元测试"""

import json
import os
import tempfile
import uuid

import pytest

from lingji_agent.foundation.db import (
    init_db,
    save_checkpoint,
    load_checkpoint,
    get_pending_hitl_sessions,
    update_hitl_session,
)


class TestDB:
    @pytest.fixture
    def db_path(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        yield path
        os.unlink(path)

    def test_init_creates_tables(self, db_path):
        conn = init_db(db_path)
        try:
            # 验证三张表存在
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] for row in cursor.fetchall()]
            assert "messages" in tables
            assert "tasks" in tables
            assert "audit_log" in tables
        finally:
            conn.close()

    def test_init_idempotent(self, db_path):
        """多次 init_db 不报错"""
        conn1 = init_db(db_path)
        conn1.close()
        conn2 = init_db(db_path)
        conn2.close()

    def test_insert_message(self, db_path):
        conn = init_db(db_path)
        try:
            conn.execute(
                "INSERT INTO messages (direction, msg_type, payload) VALUES (?, ?, ?)",
                ("incoming", "CMD_TEXT", '{"text":"hello"}'),
            )
            conn.commit()
            row = conn.execute("SELECT direction, msg_type FROM messages").fetchone()
            assert row[0] == "incoming"
            assert row[1] == "CMD_TEXT"
        finally:
            conn.close()

    def test_insert_task(self, db_path):
        conn = init_db(db_path)
        try:
            conn.execute(
                "INSERT INTO tasks (description) VALUES (?)",
                ("test task",),
            )
            conn.commit()
            row = conn.execute("SELECT status FROM tasks").fetchone()
            assert row[0] == "pending"  # 默认值
        finally:
            conn.close()


def test_checkpoint_schema_exists():
    conn = init_db(":memory:")
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = [t[0] for t in tables]
    assert "checkpoints" in table_names
    assert "hitl_sessions" in table_names


def test_save_and_load_checkpoint():
    conn = init_db(":memory:")
    state = {"messages": [{"role": "user", "content": "hello"}], "tool_round": 2}
    save_checkpoint(conn, "ck-001", "thread-1", state, status="waiting_hitl")
    loaded = load_checkpoint(conn, "thread-1")
    assert loaded is not None
    assert loaded["status"] == "waiting_hitl"
    assert loaded["state"]["tool_round"] == 2


def test_hitl_session_lifecycle():
    conn = init_db(":memory:")
    sid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO hitl_sessions (id, checkpoint_id, task_id, description, risk_level) VALUES (?, ?, ?, ?, ?)",
        (sid, "ck-001", "task-1", "delete file", "critical"),
    )
    conn.commit()

    pending = get_pending_hitl_sessions(conn)
    assert len(pending) == 1
    assert pending[0]["description"] == "delete file"

    update_hitl_session(conn, sid, "approved")
    pending_after = get_pending_hitl_sessions(conn)
    assert len(pending_after) == 0
