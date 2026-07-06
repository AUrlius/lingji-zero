"""异步 WebSocket 客户端 — 连接 Gateway + AUTH 握手 + 心跳 + 指数退避重连（Sprint 1 T-1.4）"""

import asyncio
import logging

import websockets

from lingji_agent.foundation.config import NetworkConfig
from lingji_agent.network.protocol import Message, MsgType
from lingji_agent.network.router import Router

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 15  # 秒


class GatewayClient:
    def __init__(self, config: NetworkConfig, router: Router | None = None):
        self.config = config
        self.router = router or Router()
        self.ws = None
        self._running = False
        self._reconnect_delay = config.reconnect_delay
        self._heartbeat_task: asyncio.Task | None = None
        self._on_connected_callbacks: list = []

    @property
    def url(self) -> str:
        scheme = "wss" if self.config.gateway_port == 443 else "ws"
        base = f"{scheme}://{self.config.gateway_host}:{self.config.gateway_port}/ws"
        if self.config.auth_token:
            from urllib.parse import urlencode
            base += f"?token={self.config.auth_token}"
        return base

    @property
    def is_connected(self) -> bool:
        return self.ws is not None and not self.ws.closed if hasattr(self.ws, 'closed') else False

    def on_connected(self, callback):
        """注册连接成功回调"""
        self._on_connected_callbacks.append(callback)

    async def connect(self):
        """连接 Gateway，带指数退避重连"""
        while self._running:
            try:
                extra_headers = {}
                if self.config.auth_token:
                    extra_headers["Authorization"] = f"Bearer {self.config.auth_token}"

                self.ws = await websockets.connect(
                    self.url,
                    additional_headers=extra_headers if extra_headers else None,
                    ping_interval=20,   # 主动发 ping 保持连接
                    ping_timeout=30,    # 等 pong 的超时
                )
                logger.info("已连接 Gateway: %s", self.url)
                self._reconnect_delay = self.config.reconnect_delay

                # AUTH_REQ 握手
                await self._send_auth()

                # 启动心跳
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                # 通知回调
                for cb in self._on_connected_callbacks:
                    try:
                        cb()
                    except Exception:
                        pass

                # 消息接收循环
                await self._listen()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("连接失败 (%s)，%ss 后重连", e, self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, self.config.max_reconnect_delay
                )

    async def _send_auth(self):
        """发送 AUTH_REQ 握手消息（含认证 token）"""
        payload = {"device_id": self.config.device_id}
        if self.config.display_name:
            payload["display_name"] = self.config.display_name
        if self.config.auth_token:
            payload["token"] = self.config.auth_token
        msg = Message(
            msg_type=MsgType.AUTH_REQ,
            device_id=self.config.device_id,
            payload=payload,
        )
        await self.send(msg)
        logger.debug("已发送 AUTH_REQ: %s", self.config.device_id)

    async def _heartbeat_loop(self):
        """定时发送心跳"""
        try:
            while self._running and self.ws and not getattr(self.ws, 'closed', False):
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                try:
                    msg = Message(
                        msg_type=MsgType.HEARTBEAT,
                        device_id=self.config.device_id,
                    )
                    await self.send(msg)
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    async def _listen(self):
        """消息接收循环"""
        from websockets.exceptions import ConnectionClosed
        while True:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=30)
                msg = Message.from_json(raw)
                await self.router.dispatch(msg)
            except asyncio.TimeoutError:
                continue
            except ConnectionClosed:
                raise
            except Exception as e:
                logger.warning("消息处理失败: %s", e)

    async def send(self, msg: Message):
        """发送消息"""
        if self.ws and not getattr(self.ws, 'closed', False):
            await self.ws.send(msg.to_json())

    async def start(self):
        """启动客户端"""
        self._running = True
        await self.connect()

    async def stop(self):
        """停止客户端"""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self.ws:
            await self.ws.close()
            self.ws = None
