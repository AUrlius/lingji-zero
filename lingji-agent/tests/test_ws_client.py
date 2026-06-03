"""WebSocket 客户端单元测试（Mock 模式）"""

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
