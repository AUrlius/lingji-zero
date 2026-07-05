#!/usr/bin/env python3
"""灵机计划 手机端 CLI 客户端

用法（Termux/终端）:
    python phone_client.py --device-id myphone

功能:
  - WebSocket 连接 Gateway
  - AUTH_REQ 握手 + HEARTBEAT 心跳
  - 交互式文本输入 → Agent
  - HITL 审批交互（approve/reject）
  - 断线自动重连
"""

import argparse
import asyncio
import json
import signal
import sys
import time
import uuid

import websockets

# ── 配置 ──────────────────────────────────────────────────

HEARTBEAT_INTERVAL = 15
RECONNECT_DELAY = 2
MAX_RECONNECT_DELAY = 30


# ── PhoneClient ───────────────────────────────────────────

class PhoneClient:
    def __init__(self, gateway_host: str, gateway_port: int, device_id: str):
        self.url = f"ws://{gateway_host}:{gateway_port}/ws"
        self.device_id = device_id
        self.ws = None
        self._running = False
        self._reconnect_delay = RECONNECT_DELAY
        self._input_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

    # ── 连接管理 ──────────────────────────────────────

    async def connect(self):
        """连接 Gateway，带指数退避重连"""
        while self._running:
            try:
                print(f"🔗 连接 {self.url} ...")
                self.ws = await websockets.connect(
                    self.url,
                    ping_interval=None,  # Gateway 自己管理 ping，避免冲突
                )
                self._reconnect_delay = RECONNECT_DELAY
                print(f"✅ 已连接 (设备: {self.device_id})")

                # AUTH 握手
                await self._send_auth()

                # 启动心跳 + 接收循环
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                await self._recv_loop()

            except (websockets.ConnectionClosed, OSError) as e:
                print(f"\n⚠️  连接断开: {e}")
            except Exception as e:
                print(f"\n⚠️  连接失败: {e}")

            if not self._running:
                break

            print(f"🔄 {self._reconnect_delay}s 后重连...")
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, MAX_RECONNECT_DELAY)

    async def _send_auth(self):
        msg = self._build_msg("AUTH_REQ", {"device_id": self.device_id})
        await self.ws.send(json.dumps(msg))

    async def _heartbeat_loop(self):
        while self._running and self.ws:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                msg = self._build_msg("HEARTBEAT", {})
                await self.ws.send(json.dumps(msg))
            except Exception:
                break

    # ── 消息收发 ──────────────────────────────────────

    async def _recv_loop(self):
        async for raw in self.ws:
            try:
                msg = json.loads(raw)
                await self._handle(msg)
            except json.JSONDecodeError:
                print(f"\n⚠️  无效消息: {raw[:100]}")

    async def _handle(self, msg: dict):
        msg_type = msg.get("msg_type", "?")
        payload = msg.get("payload", {})

        if msg_type == "AGENT_RES":
            text = payload.get("text", str(payload))
            status = payload.get("status", "")
            if status == "queued":
                print(f"\n📦 {text}")
            elif status == "connected":
                print(f"\n🔐 认证成功")
            else:
                print(f"\n🤖 {text}")

        elif msg_type == "HITL_REQ":
            await self._handle_hitl(payload)

        # 重新显示提示符
        print("> ", end="", flush=True)

    async def _handle_hitl(self, payload: dict):
        """处理 HITL 审批请求"""
        action = payload.get("action", "unknown")
        description = payload.get("description", str(payload))
        task_id = payload.get("task_id", str(uuid.uuid4()))

        print(f"\n{'='*50}")
        print(f"⚠️  危险操作需要确认")
        print(f"  操作: {description}")
        print(f"{'='*50}")

        while True:
            choice = input("  批准? (y/n): ").strip().lower()
            if choice in ("y", "yes"):
                decision = "approved"
                break
            elif choice in ("n", "no"):
                decision = "rejected"
                break

        reply = self._build_msg("HITL_RES", {
            "task_id": task_id,
            "decision": decision,
        })
        await self.ws.send(json.dumps(reply))
        print(f"  {'✅ 已批准' if decision == 'approved' else '❌ 已拒绝'}")

    async def send_text(self, text: str):
        msg = self._build_msg("CMD_TEXT", {"text": text})
        await self.ws.send(json.dumps(msg))

    def _build_msg(self, msg_type: str, payload: dict) -> dict:
        return {
            "msg_id": str(uuid.uuid4()),
            "msg_type": msg_type,
            "device_id": self.device_id,
            "timestamp": time.time(),
            "payload": payload,
        }

    # ── 交互循环 ──────────────────────────────────────

    async def input_loop(self):
        """用户输入循环（在单独的 task 中运行）"""
        print("\n⌨️  输入消息 (Ctrl+C 退出, /exit 退出):")
        while self._running:
            try:
                text = await asyncio.to_thread(input, "> ")
                text = text.strip()
                if not text:
                    continue
                if text == "/exit":
                    self._running = False
                    break
                await self.send_text(text)
            except (KeyboardInterrupt, EOFError):
                self._running = False
                break
            except Exception as e:
                print(f"\n⚠️  发送失败: {e}")

    # ── 生命周期 ──────────────────────────────────────

    async def run(self):
        self._running = True
        self._input_task = asyncio.create_task(self.input_loop())
        await self.connect()

    async def stop(self):
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._input_task:
            self._input_task.cancel()
        if self.ws:
            await self.ws.close()
        print("\n👋 已断开")


# ── 入口 ──────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="灵机计划 手机客户端")
    parser.add_argument("--host", default="lingji.mygoal.tech", help="Gateway 地址")
    parser.add_argument("--port", type=int, default=8765, help="Gateway 端口")
    parser.add_argument("--device-id", default="lingji-phone", help="设备标识")
    args = parser.parse_args()

    client = PhoneClient(args.host, args.port, args.device_id)

    # 优雅退出
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(client.stop()))

    try:
        await client.run()
    except Exception as e:
        print(f"❌ 致命错误: {e}")
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
