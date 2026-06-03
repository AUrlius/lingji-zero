"""HITL 与多会话切换交互"""

from lingji_agent.execution.hitl import find_pending_hitl_for_thread, thread_has_pending_hitl
from lingji_agent.foundation.db import init_db, save_checkpoint


class _FakePending:
    def __init__(self, thread_id: str, device_id: str = "phone-1"):
        self.thread_id = thread_id
        self.device_id = device_id
        self.user_text = "run rm"
        self.system_prompt = "sys"
        self.run_started_at = 0.0


def test_find_pending_hitl_from_memory_pending_runs():
    conn = init_db(":memory:")
    pending_runs = {"task-a": _FakePending("phone-1:thread-a")}
    conn.execute(
        """INSERT INTO hitl_sessions (id, checkpoint_id, task_id, description, risk_level, status)
           VALUES ('h1', 'cp1', 'task-a', '删除文件', 'critical', 'pending')"""
    )
    conn.execute(
        """INSERT INTO checkpoints (id, thread_id, agent_state_json, status)
           VALUES ('cp1', 'phone-1:thread-a', '{}', 'running')"""
    )
    conn.commit()

    hitl = find_pending_hitl_for_thread(conn, "phone-1:thread-a", pending_runs)
    assert hitl is not None
    assert hitl["task_id"] == "task-a"
    assert "删除" in hitl["description"]
    assert thread_has_pending_hitl(conn, "phone-1:thread-a", pending_runs)
    assert not thread_has_pending_hitl(conn, "phone-1:other", pending_runs)


def test_find_pending_hitl_from_db_only():
    conn = init_db(":memory:")
    state = {"messages": [{"role": "user", "content": "danger"}]}
    save_checkpoint(conn, "cp2", "phone-1:thread-b", state, status="running")
    conn.execute(
        """INSERT INTO hitl_sessions (id, checkpoint_id, task_id, description, risk_level, status)
           VALUES ('h2', 'cp2', 'task-b', '执行 shell', 'critical', 'pending')"""
    )
    conn.commit()

    hitl = find_pending_hitl_for_thread(conn, "phone-1:thread-b", {})
    assert hitl == {
        "task_id": "task-b",
        "description": "执行 shell",
        "risk_level": "critical",
    }
