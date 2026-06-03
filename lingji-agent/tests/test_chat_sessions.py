"""G6.3 — chat_sessions SQLite"""

from lingji_agent.foundation.db import (
    init_db,
    list_chat_sessions,
    upsert_chat_session,
    get_active_chat_thread,
)


def test_chat_sessions_crud(tmp_path):
    db_path = tmp_path / "test.db"
    conn = init_db(str(db_path))

    upsert_chat_session(conn, "phone-1", "phone-1:aaa", "第一条", set_active=True)
    upsert_chat_session(conn, "phone-1", "phone-1:bbb", "第二条", set_active=True)

    active = get_active_chat_thread(conn, "phone-1")
    assert active == "phone-1:bbb"

    sessions = list_chat_sessions(conn, "phone-1")
    assert len(sessions) == 2
    assert {s["thread_id"] for s in sessions} == {"phone-1:aaa", "phone-1:bbb"}
    active_rows = [s for s in sessions if s["active"]]
    assert len(active_rows) == 1
    assert active_rows[0]["thread_id"] == "phone-1:bbb"

    conn.close()
