"""WebSocket 客户端单元测试（Mock 模式）"""

import asyncio

import pytest

from lingji_agent.foundation.config import NetworkConfig
from lingji_agent.network.ws_client import GatewayClient
from lingji_agent.network.router import Router
from lingji_agent.network.protocol import Message, MsgType


class TestGatewayClient:
    def test_url_generation(self):
        cfg = NetworkConfig(gateway_host="10.0.0.1", gateway_port=1234)
        client = GatewayClient(cfg)
        assert client.url == "ws://10.0.0.1:1234/ws"

    def test_url_default(self):
        cfg = NetworkConfig()
        client = GatewayClient(cfg)
        assert client.url == "wss://lingji.mygoal.tech:443/ws"

    def test_reconnect_delay_default(self):
        cfg = NetworkConfig()
        client = GatewayClient(cfg)
        assert client._reconnect_delay == 1.0

    def test_custom_reconnect_delay(self):
        cfg = NetworkConfig(reconnect_delay=3.0, max_reconnect_delay=120.0)
        client = GatewayClient(cfg)
        assert client._reconnect_delay == 3.0

    def test_not_connected_initially(self):
        client = GatewayClient(NetworkConfig())
        assert not client.is_connected

    def test_router_integration(self):
        router = Router()
        client = GatewayClient(NetworkConfig(), router)
        assert client.router is router

    def test_default_router(self):
        client = GatewayClient(NetworkConfig())
        assert isinstance(client.router, Router)

    def test_on_connected_callback(self):
        client = GatewayClient(NetworkConfig())
        called = []

        client.on_connected(lambda: called.append(1))
        assert len(client._on_connected_callbacks) == 1

    def test_running_flag(self):
        client = GatewayClient(NetworkConfig())
        assert not client._running

    @pytest.mark.asyncio
    async def test_dispatch_one_swallows_handler_error(self):
        router = Router()

        async def boom(msg):
            raise RuntimeError("handler exploded")

        router.register(MsgType.CMD_TEXT, boom)
        client = GatewayClient(NetworkConfig(), router)
        msg = Message(msg_type=MsgType.CMD_TEXT, device_id="web-1", payload={})
        await client._dispatch_one(msg)

    @pytest.mark.asyncio
    async def test_listen_does_not_wait_for_slow_cmd_text(self):
        router = Router()
        order: list[str] = []
        released = asyncio.Event()

        async def slow_text(msg):
            order.append("text-start")
            await released.wait()
            order.append("text-end")

        async def list_sessions(msg):
            order.append("list")

        router.register(MsgType.CMD_TEXT, slow_text)
        router.register(MsgType.CMD_LIST_SESSIONS, list_sessions)
        client = GatewayClient(NetworkConfig(), router)
        queued = [
            Message(msg_type=MsgType.CMD_TEXT, device_id="w", payload={}).to_json(),
            Message(msg_type=MsgType.CMD_LIST_SESSIONS, device_id="w", payload={}).to_json(),
        ]

        class FakeWS:
            def __init__(self):
                self._i = 0
                self.closed = False

            async def recv(self):
                if self._i >= len(queued):
                    await asyncio.sleep(60)
                    raise asyncio.CancelledError()
                raw = queued[self._i]
                self._i += 1
                return raw

        client.ws = FakeWS()
        listen_task = asyncio.create_task(client._listen())
        try:
            for _ in range(80):
                if "list" in order:
                    break
                await asyncio.sleep(0.01)
            assert "list" in order
            assert "text-end" not in order
            released.set()
            for _ in range(40):
                if "text-end" in order:
                    break
                await asyncio.sleep(0.01)
            assert "text-end" in order
        finally:
            listen_task.cancel()
            try:
                await listen_task
            except asyncio.CancelledError:
                pass
