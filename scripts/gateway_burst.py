#!/usr/bin/env python3
"""Gateway 突发负载抽检 — 四期 4.4

Mock Agent + 多 Phone 并发 CMD_TEXT，验证 Gateway 不崩溃且完成率达标。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path

import websockets

REPO = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO / "lingji-agent"

DEVICE_AGENT = "lingji-pc"
PHONE_PREFIX = "lingji-phone-burst"


async def check_health(host: str, port: int) -> bool:
    reader, writer = await asyncio.open_connection(host, port)
    writer.write(b"GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n")
    await writer.drain()
    data = await asyncio.wait_for(reader.read(512), timeout=3)
    writer.close()
    return b"ok" in data


class MockAgent:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.ws = None
        self.handled = 0

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}/ws"

    async def connect(self) -> None:
        self.ws = await websockets.connect(self.url)
        await self.ws.send(
            json.dumps(
                {
                    "msg_id": str(uuid.uuid4()),
                    "msg_type": "AUTH_REQ",
                    "device_id": DEVICE_AGENT,
                    "timestamp": time.time(),
                    "payload": {"device_id": DEVICE_AGENT},
                }
            )
        )
        await asyncio.wait_for(self.ws.recv(), timeout=5)

    async def serve(self) -> None:
        assert self.ws is not None
        async for raw in self.ws:
            msg = json.loads(raw)
            if msg.get("msg_type") == "CMD_TEXT":
                self.handled += 1
                await self.ws.send(
                    json.dumps(
                        {
                            "msg_id": str(uuid.uuid4()),
                            "msg_type": "AGENT_RES",
                            "device_id": DEVICE_AGENT,
                            "timestamp": time.time(),
                            "payload": {
                                "text": f"burst-ok-{self.handled}",
                                "status": "ok",
                            },
                        }
                    )
                )

    async def close(self) -> None:
        if self.ws:
            await self.ws.close()


async def phone_burst(
    host: str,
    port: int,
    phone_id: str,
    messages: int,
    rate: float,
) -> tuple[int, int, list[float]]:
    url = f"ws://{host}:{port}/ws"
    ok = 0
    errors = 0
    latencies: list[float] = []
    interval = 1.0 / rate if rate > 0 else 0

    ws = await websockets.connect(url)
    try:
        await ws.send(
            json.dumps(
                {
                    "msg_id": str(uuid.uuid4()),
                    "msg_type": "AUTH_REQ",
                    "device_id": phone_id,
                    "timestamp": time.time(),
                    "payload": {"device_id": phone_id},
                }
            )
        )
        await asyncio.wait_for(ws.recv(), timeout=5)

        for i in range(messages):
            if interval:
                await asyncio.sleep(interval)
            start = time.monotonic()
            await ws.send(
                json.dumps(
                    {
                        "msg_id": str(uuid.uuid4()),
                        "msg_type": "CMD_TEXT",
                        "device_id": phone_id,
                        "timestamp": time.time(),
                        "payload": {"text": f"burst-{phone_id}-{i}"},
                    }
                )
            )
            reply = None
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2)
                    msg = json.loads(raw)
                    if msg.get("msg_type") == "AGENT_RES":
                        reply = msg
                        break
                except asyncio.TimeoutError:
                    continue
            elapsed_ms = (time.monotonic() - start) * 1000
            if reply and "burst-ok" in reply.get("payload", {}).get("text", ""):
                ok += 1
                latencies.append(elapsed_ms)
            else:
                errors += 1
    except Exception:
        errors += messages - ok
    finally:
        await ws.close()

    return ok, errors, latencies


async def run_burst(
    host: str,
    port: int,
    phones: int,
    messages: int,
    rate: float,
    min_success_rate: float,
) -> dict:
    if not await check_health(host, port):
        print("Gateway /health 不可用", file=sys.stderr)
        return {"success": False, "error": "health_check_failed"}

    agent = MockAgent(host, port)
    await agent.connect()
    serve_task = asyncio.create_task(agent.serve())

    await asyncio.sleep(0.3)

    tasks = [
        phone_burst(host, port, f"{PHONE_PREFIX}-{i}", messages, rate)
        for i in range(phones)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    serve_task.cancel()
    try:
        await serve_task
    except asyncio.CancelledError:
        pass
    await agent.close()

    total_ok = 0
    total_errors = 0
    all_latencies: list[float] = []
    for item in results:
        if isinstance(item, Exception):
            total_errors += messages
            continue
        ok, err, lats = item
        total_ok += ok
        total_errors += err
        all_latencies.extend(lats)

    sent = phones * messages
    success_rate = total_ok / sent if sent else 0.0
    p99 = (
        statistics.quantiles(all_latencies, n=100)[98]
        if len(all_latencies) >= 2
        else (all_latencies[0] if all_latencies else 0.0)
    )

    summary = {
        "success": success_rate >= min_success_rate and await check_health(host, port),
        "sent": sent,
        "ok": total_ok,
        "errors": total_errors,
        "success_rate": round(success_rate, 4),
        "agent_handled": agent.handled,
        "p99_ms": round(p99, 2),
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway burst load spotcheck")
    parser.add_argument("--host", default=os.environ.get("LINGJI_INTEGRATION_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LINGJI_INTEGRATION_PORT", "18765")))
    parser.add_argument("--phones", type=int, default=5)
    parser.add_argument("--messages", type=int, default=20)
    parser.add_argument("--rate", type=float, default=10.0, help="messages per second per phone")
    parser.add_argument("--min-success-rate", type=float, default=0.95)
    parser.add_argument("--json", action="store_true", help="print JSON summary only")
    args = parser.parse_args()

    summary = asyncio.run(
        run_burst(
            args.host,
            args.port,
            args.phones,
            args.messages,
            args.rate,
            args.min_success_rate,
        )
    )

    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(f"burst summary: {summary}")

    return 0 if summary.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
