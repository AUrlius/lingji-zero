"""WebSocket 混沌/韧性单测 — 四期 4.4"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from websockets.exceptions import ConnectionClosed

from lingji_agent.foundation.config import NetworkConfig
from lingji_agent.network.ws_client import GatewayClient


@pytest.mark.asyncio
async def test_reconnect_backoff_then_reset_on_success():
    cfg = NetworkConfig(
        gateway_host="127.0.0.1",
        gateway_port=18765,
        device_id="chaos-pc",
        reconnect_delay=1.0,
        max_reconnect_delay=60.0,
    )
    client = GatewayClient(cfg)
    client._running = True

    delays: list[float] = []
    attempts = 0
    mock_ws = AsyncMock()
    mock_ws.closed = False

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async def fake_connect(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("injected failure")
        return mock_ws

    listen_calls = 0

    async def fake_listen() -> None:
        nonlocal listen_calls
        listen_calls += 1
        if listen_calls == 1:
            raise ConnectionClosed(None, None)
        client._running = False

    with patch("lingji_agent.network.ws_client.websockets.connect", fake_connect):
        with patch("lingji_agent.network.ws_client.asyncio.sleep", fake_sleep):
            with patch.object(client, "_listen", fake_listen):
                with patch.object(client, "_send_auth", AsyncMock()):
                    with patch.object(client, "_heartbeat_loop", new=AsyncMock()):
                        await asyncio.wait_for(client.connect(), timeout=5)

    assert delays[:2] == [1.0, 2.0]
    assert client._reconnect_delay == 1.0


@pytest.mark.asyncio
async def test_reconnect_delay_caps_at_max():
    cfg = NetworkConfig(
        gateway_host="127.0.0.1",
        gateway_port=18765,
        reconnect_delay=4.0,
        max_reconnect_delay=10.0,
    )
    client = GatewayClient(cfg)
    client._running = True
    client._reconnect_delay = 8.0

    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        client._running = False

    with patch("lingji_agent.network.ws_client.websockets.connect", AsyncMock(side_effect=ConnectionError("fail"))):
        with patch("lingji_agent.network.ws_client.asyncio.sleep", fake_sleep):
            await client.connect()

    assert delays == [8.0]
    assert client._reconnect_delay == 10.0
