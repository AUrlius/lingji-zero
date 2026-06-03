"""消息路由分发（Sprint 1 T-1.4）"""

from lingji_agent.network.protocol import Message, MsgType


class Router:
    def __init__(self):
        self._handlers: dict[MsgType, list] = {}

    def register(self, msg_type: MsgType, handler):
        self._handlers.setdefault(msg_type, []).append(handler)

    async def dispatch(self, msg: Message):
        for handler in self._handlers.get(msg.msg_type, []):
            await handler(msg)
