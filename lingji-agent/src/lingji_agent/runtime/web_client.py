"""Web client identity on an inbound gateway message."""

from __future__ import annotations

from lingji_agent.network.protocol import Message


def resolve_web_client(msg: Message) -> tuple[str, str]:
    """Return (connection_id, user_id). Sessions use user_id; WS route uses connection_id."""
    conn_id = msg.device_id
    raw = msg.payload.get("user_id")
    if isinstance(raw, str) and raw.strip():
        return conn_id, raw.strip()
    return conn_id, conn_id
