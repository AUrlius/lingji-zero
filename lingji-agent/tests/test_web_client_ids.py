"""Fleet phase 1.5 — Web connection_id vs user_id."""

from lingji_agent.main import _resolve_web_client
from lingji_agent.network.protocol import Message, MsgType


def test_resolve_web_client_with_user_id():
    msg = Message(
        msg_type=MsgType.CMD_TEXT,
        device_id="conn-abc",
        payload={"user_id": "user-xyz", "text": "hi"},
    )
    conn, user = _resolve_web_client(msg)
    assert conn == "conn-abc"
    assert user == "user-xyz"


def test_resolve_web_client_legacy():
    msg = Message(
        msg_type=MsgType.CMD_TEXT,
        device_id="phone-1",
        payload={"text": "hi"},
    )
    conn, user = _resolve_web_client(msg)
    assert conn == "phone-1"
    assert user == "phone-1"
