"""HITL recovery expiry — sticky pending cleanup."""

from datetime import datetime, timedelta, timezone

from lingji_agent.execution.hitl import find_pending_hitl_for_thread, hitl_remaining_seconds
from lingji_agent.foundation.db import init_db, save_checkpoint, update_hitl_session


def test_hitl_remaining_seconds_full_when_no_created_at():
    assert hitl_remaining_seconds(None, 300) == 300.0


def test_hitl_remaining_seconds_decreases_with_age():
    old = (datetime.now(timezone.utc) - timedelta(seconds=100)).strftime("%Y-%m-%d %H:%M:%S")
    remaining = hitl_remaining_seconds(old, 300)
    assert 190 <= remaining <= 210


def test_hitl_remaining_seconds_zero_when_past_timeout():
    old = (datetime.now(timezone.utc) - timedelta(seconds=400)).strftime("%Y-%m-%d %H:%M:%S")
    assert hitl_remaining_seconds(old, 300) <= 0


def test_find_pending_hitl_ignores_expired_session():
    conn = init_db(":memory:")
    save_checkpoint(conn, "cp-exp", "phone-1:thread-x", {"messages": []}, status="running")
    conn.execute(
        """INSERT INTO hitl_sessions (id, checkpoint_id, task_id, description, risk_level, status)
           VALUES ('h-exp', 'cp-exp', 'task-exp', 'delete', 'critical', 'pending')"""
    )
    conn.commit()
    assert find_pending_hitl_for_thread(conn, "phone-1:thread-x", {}) is not None

    update_hitl_session(conn, "h-exp", "expired")
    assert find_pending_hitl_for_thread(conn, "phone-1:thread-x", {}) is None


def test_find_pending_hitl_ignores_timeout_session():
    conn = init_db(":memory:")
    save_checkpoint(conn, "cp-to", "phone-1:thread-y", {"messages": []}, status="running")
    conn.execute(
        """INSERT INTO hitl_sessions (id, checkpoint_id, task_id, description, risk_level, status)
           VALUES ('h-to', 'cp-to', 'task-to', 'shell', 'critical', 'pending')"""
    )
    conn.commit()
    update_hitl_session(conn, "h-to", "timeout")
    assert find_pending_hitl_for_thread(conn, "phone-1:thread-y", {}) is None
