#!/usr/bin/env python3
"""灵机计划 三端集成测试

启动 Gateway → Agent(Mock LLM) → Phone Simulator → 验证消息闭环
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import websockets

REPO_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_DIR = REPO_ROOT / "lingji-gateway"

GATEWAY_PORT = int(os.environ.get("LINGJI_INTEGRATION_PORT", "18765"))
GATEWAY_HOST = os.environ.get("LINGJI_INTEGRATION_HOST", "127.0.0.1")
DEVICE_PC = "lingji-pc"
DEVICE_PHONE = "lingji-phone-test"

# ── Test Result ───────────────────────────────────────────

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def ok(self, name: str):
        self.passed += 1
        print(f"  ✅ {name}")

    def fail(self, name: str, detail: str = ""):
        self.failed += 1
        msg = f"  ❌ {name}"
        if detail:
            msg += f": {detail}"
        self.errors.append(msg)
        print(msg)

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*50}")
        print(f"结果: {self.passed}/{total} 通过, {self.failed} 失败")
        for e in self.errors:
            print(e)
        return self.failed == 0

# ── Gateway ───────────────────────────────────────────────

class GatewayProcess:
    def __init__(self, binary_path: str):
        self.binary = binary_path
        self.proc = None

    def start(self):
        env = os.environ.copy()
        env["LINGJI_PORT"] = str(GATEWAY_PORT)
        env["PATH"] = os.path.expanduser("~/.local/go/bin") + ":" + env.get("PATH", "")
        self.logfile = open("/tmp/gateway_test.log", "w")
        self.proc = subprocess.Popen(
            [self.binary], env=env, stdout=self.logfile, stderr=subprocess.STDOUT
        )
        time.sleep(1.5)
        return self.proc.poll() is None

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if hasattr(self, 'logfile'):
            self.logfile.close()

# ── Phone Simulator ───────────────────────────────────────

class PhoneSimulator:
    def __init__(self):
        self.ws = None
        self.received: list[dict] = []

    @property
    def url(self):
        return f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}/ws"

    async def connect(self):
        self.ws = await websockets.connect(self.url)
        await self.ws.send(json.dumps({
            "msg_id": str(uuid.uuid4()), "msg_type": "AUTH_REQ",
            "device_id": DEVICE_PHONE, "timestamp": time.time(),
            "payload": {"device_id": DEVICE_PHONE},
        }))

    async def send_text(self, text: str):
        await self.ws.send(json.dumps({
            "msg_id": str(uuid.uuid4()), "msg_type": "CMD_TEXT",
            "device_id": DEVICE_PHONE, "timestamp": time.time(),
            "payload": {"text": text},
        }))

    async def recv_until(self, msg_type: str, timeout: float = 10.0) -> dict | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=min(2, deadline - time.time()))
                msg = json.loads(raw)
                self.received.append(msg)
                if msg.get("msg_type") == msg_type:
                    return msg
            except asyncio.TimeoutError:
                pass
        return None

    async def close(self):
        if self.ws:
            await self.ws.close()

# ── Agent Simulator ───────────────────────────────────────

class MockAgent:
    def __init__(self):
        self.ws = None

    @property
    def url(self):
        return f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}/ws"

    async def connect(self):
        self.ws = await websockets.connect(self.url)
        await self.ws.send(json.dumps({
            "msg_id": str(uuid.uuid4()), "msg_type": "AUTH_REQ",
            "device_id": DEVICE_PC, "timestamp": time.time(),
            "payload": {"device_id": DEVICE_PC},
        }))

    async def serve(self):
        """接收 CMD_TEXT → 回复 AGENT_RES"""
        async for raw in self.ws:
            msg = json.loads(raw)
            print(f"  [debug] agent received: {msg.get('msg_type')} payload={str(msg.get('payload',''))[:80]}")
            if msg.get("msg_type") == "CMD_TEXT":
                user_text = msg.get("payload", {}).get("text", "")
                reply = {
                    "msg_id": str(uuid.uuid4()), "msg_type": "AGENT_RES",
                    "device_id": DEVICE_PC, "timestamp": time.time(),
                    "payload": {
                        "text": f"收到: {user_text}",
                        "status": "ok",
                        "target_device_id": msg.get("device_id"),
                    },
                }
                await self.ws.send(json.dumps(reply))

    async def close(self):
        if self.ws:
            await self.ws.close()

# ── Tests ─────────────────────────────────────────────────

async def test_gateway_health(r: TestResult):
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(GATEWAY_HOST, GATEWAY_PORT), timeout=5,
        )
        writer.write(b"GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=3)
        writer.close()
        if b"ok" in data:
            r.ok("Gateway /health 响应正常")
        else:
            r.fail("Gateway /health", f"响应异常: {data[:100]}")
    except Exception as e:
        r.fail("Gateway /health", str(e))

async def test_phone_connect_auth(r: TestResult):
    phone = PhoneSimulator()
    try:
        await phone.connect()
        msg = await phone.recv_until("AGENT_RES", timeout=5)
        if msg and msg.get("payload", {}).get("status") == "connected":
            r.ok("手机端认证成功")
        else:
            r.fail("手机端认证", f"非预期: {msg}")
    except Exception as e:
        r.fail("手机端连接", str(e))
    finally:
        await phone.close()

async def test_message_roundtrip(r: TestResult):
    """消息闭环: Phone → Gateway → Agent → Gateway → Phone"""
    try:
        url = f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}/ws"

        # Agent 先连接
        aws = await websockets.connect(url)
        await aws.send(json.dumps({"msg_id":"a1","msg_type":"AUTH_REQ","device_id":"lingji-pc","timestamp":time.time(),"payload":{"device_id":"lingji-pc"}}))
        auth_reply = json.loads(await asyncio.wait_for(aws.recv(), timeout=3))
        print(f"  [debug] agent auth: {auth_reply.get('payload',{}).get('status')}")

        # Phone 连接
        pws = await websockets.connect(url)
        await pws.send(json.dumps({"msg_id":"p1","msg_type":"AUTH_REQ","device_id":"phone-1","timestamp":time.time(),"payload":{"device_id":"phone-1"}}))
        phone_auth = json.loads(await asyncio.wait_for(pws.recv(), timeout=3))
        print(f"  [debug] phone auth: {phone_auth.get('payload',{}).get('status')}")

        await asyncio.sleep(0.3)

        # Phone 发消息
        await pws.send(json.dumps({"msg_id":"p2","msg_type":"CMD_TEXT","device_id":"phone-1","timestamp":time.time(),"payload":{"text":"hello"}}))
        print("  [debug] phone sent CMD_TEXT")

        # Agent 收消息
        agent_msg = json.loads(await asyncio.wait_for(aws.recv(), timeout=5))
        print(f"  [debug] agent got: {agent_msg.get('msg_type')} text={agent_msg.get('payload',{}).get('text','')}")

        # Agent 回复
        await aws.send(json.dumps({"msg_id":"a2","msg_type":"AGENT_RES","device_id":"lingji-pc","timestamp":time.time(),"payload":{"text":"reply ok","target_device_id":"phone-1"}}))
        print("  [debug] agent sent AGENT_RES")

        # Phone 收回复
        phone_reply = json.loads(await asyncio.wait_for(pws.recv(), timeout=5))
        reply_text = phone_reply.get("payload",{}).get("text","")
        print(f"  [debug] phone got: {reply_text}")

        if "reply" in reply_text:
            r.ok(f"消息闭环: 'hello' → '{reply_text}'")
        else:
            r.fail("消息闭环", f"回复不匹配: {reply_text}")

        await aws.close()
        await pws.close()
    except Exception as e:
        r.fail("消息闭环", str(e))

async def test_cross_device_isolation(r: TestResult):
    """双 Web 端：带 target_device_id 的回复只到发问端"""
    try:
        url = f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}/ws"
        pws_a = await websockets.connect(url)
        pws_b = await websockets.connect(url)
        aws = await websockets.connect(url)

        for ws, dev in [(pws_a, "phone-a"), (pws_b, "phone-b"), (aws, DEVICE_PC)]:
            await ws.send(json.dumps({
                "msg_id": str(uuid.uuid4()), "msg_type": "AUTH_REQ",
                "device_id": dev, "timestamp": time.time(),
                "payload": {"device_id": dev},
            }))
            await asyncio.wait_for(ws.recv(), timeout=3)

        await aws.send(json.dumps({
            "msg_id": "iso", "msg_type": "AGENT_RES", "device_id": DEVICE_PC,
            "timestamp": time.time(),
            "payload": {"text": "for a only", "target_device_id": "phone-a"},
        }))

        got_a = json.loads(await asyncio.wait_for(pws_a.recv(), timeout=3))
        if got_a.get("payload", {}).get("text") != "for a only":
            r.fail("双端隔离", f"phone-a 回复异常: {got_a}")
            return

        try:
            await asyncio.wait_for(pws_b.recv(), timeout=1)
            r.fail("双端隔离", "phone-b 不应收到定向回复")
        except asyncio.TimeoutError:
            r.ok("双端隔离: target_device_id 仅投递发问端")

        await pws_a.close()
        await pws_b.close()
        await aws.close()
    except Exception as e:
        r.fail("双端隔离", str(e))

async def test_multiple_messages(r: TestResult):
    phone = PhoneSimulator()
    agent = MockAgent()
    try:
        await phone.connect()
        await phone.recv_until("AGENT_RES", timeout=5)
        await agent.connect()
        serve_task = asyncio.create_task(agent.serve())
        await asyncio.sleep(0.5)

        for i, text in enumerate(["msg-1", "msg-2", "msg-3"]):
            await phone.send_text(text)
            reply = await phone.recv_until("AGENT_RES", timeout=5)
            if reply:
                r.ok(f"多轮消息 {i+1}/3")
            else:
                r.fail(f"多轮消息 {i+1}/3", "未收到回复")
                break
        serve_task.cancel()
    except Exception as e:
        r.fail("多轮对话", str(e))
    finally:
        await phone.close()
        await agent.close()

async def test_file_attachment_e2e(r: TestResult):
    """G6: 上传 /files → AGENT_RES attachments → Phone 下载内容一致"""
    try:
        tmp = Path("/tmp/lingji-g6-integration.txt")
        tmp.write_text("g6-integration-payload", encoding="utf-8")

        async with httpx.AsyncClient(base_url=f"http://{GATEWAY_HOST}:{GATEWAY_PORT}") as client:
            with tmp.open("rb") as fh:
                up = await client.post(
                    "/files",
                    files={"file": (tmp.name, fh, "text/plain")},
                )
            if up.status_code != 200:
                r.fail("G6 文件上传", up.text[:120])
                return
            att = up.json()

        url = f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}/ws"
        pws = await websockets.connect(url)
        aws = await websockets.connect(url)
        await pws.send(json.dumps({"msg_id":"p-auth","msg_type":"AUTH_REQ","device_id":"phone-g6","timestamp":time.time(),"payload":{"device_id":"phone-g6"}}))
        await aws.send(json.dumps({"msg_id":"a-auth","msg_type":"AUTH_REQ","device_id":"lingji-pc","timestamp":time.time(),"payload":{"device_id":"lingji-pc"}}))
        await asyncio.sleep(0.3)

        await aws.send(json.dumps({
            "msg_id": "a-file", "msg_type": "AGENT_RES", "device_id": "lingji-pc",
            "timestamp": time.time(),
            "payload": {
                "text": "请点击下载",
                "target_device_id": "phone-g6",
                "attachments": [{
                    "file_id": att["file_id"],
                    "name": att["name"],
                    "size_bytes": att["size_bytes"],
                    "mime": att["mime"],
                    "download_path": att["download_path"],
                }],
            },
        }))

        phone_msg = None
        deadline = time.time() + 5
        while time.time() < deadline:
            raw = await asyncio.wait_for(pws.recv(), timeout=2)
            msg = json.loads(raw)
            if msg.get("msg_type") == "AGENT_RES" and msg.get("payload", {}).get("attachments"):
                phone_msg = msg
                break

        if not phone_msg:
            r.fail("G6 attachments 转发", "Phone 未收到 attachments")
            await pws.close()
            await aws.close()
            return

        dl_path = phone_msg["payload"]["attachments"][0]["download_path"]
        async with httpx.AsyncClient(base_url=f"http://{GATEWAY_HOST}:{GATEWAY_PORT}") as client:
            dl = await client.get(dl_path)
        if dl.text == "g6-integration-payload":
            r.ok("G6 文件上传/下载闭环")
        else:
            r.fail("G6 下载内容", dl.text[:80])

        await pws.close()
        await aws.close()
    except Exception as e:
        r.fail("G6 文件闭环", str(e))

async def test_multi_agent_routing(r: TestResult):
    """多 PC：target_agent_id 路由到指定 Agent"""
    try:
        url = f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}/ws"
        pc_ws = await websockets.connect(url)
        laptop_ws = await websockets.connect(url)
        phone_ws = await websockets.connect(url)

        for ws, dev in [
            (pc_ws, "lingji-pc"),
            (laptop_ws, "lingji-laptop"),
            (phone_ws, "phone-multi"),
        ]:
            await ws.send(json.dumps({
                "msg_id": str(uuid.uuid4()), "msg_type": "AUTH_REQ",
                "device_id": dev, "timestamp": time.time(),
                "payload": {"device_id": dev},
            }))
            await asyncio.wait_for(ws.recv(), timeout=3)

        await asyncio.sleep(0.3)

        laptop_cmd = {
            "msg_id": "multi-laptop", "msg_type": "CMD_TEXT",
            "device_id": "phone-multi", "timestamp": time.time(),
            "payload": {"text": "to laptop", "target_agent_id": "lingji-laptop"},
        }
        await phone_ws.send(json.dumps(laptop_cmd))
        laptop_msg = json.loads(await asyncio.wait_for(laptop_ws.recv(), timeout=5))
        if laptop_msg.get("payload", {}).get("text") != "to laptop":
            r.fail("多 Agent 路由", f"笔记本未收到: {laptop_msg}")
            return

        try:
            await asyncio.wait_for(pc_ws.recv(), timeout=1)
            r.fail("多 Agent 路由", "lingji-pc 不应收到 laptop 定向消息")
            return
        except asyncio.TimeoutError:
            pass

        default_cmd = {
            "msg_id": "multi-default", "msg_type": "CMD_TEXT",
            "device_id": "phone-multi", "timestamp": time.time(),
            "payload": {"text": "to default pc"},
        }
        await phone_ws.send(json.dumps(default_cmd))
        pc_msg = json.loads(await asyncio.wait_for(pc_ws.recv(), timeout=5))
        if pc_msg.get("payload", {}).get("text") != "to default pc":
            r.fail("多 Agent 默认路由", f"lingji-pc 未收到: {pc_msg}")
            return

        r.ok("多 Agent 路由: target_agent_id + 默认 lingji-pc")

        await pc_ws.close()
        await laptop_ws.close()
        await phone_ws.close()
    except Exception as e:
        r.fail("多 Agent 路由", str(e))

async def test_agents_api(r: TestResult):
    try:
        url = f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}/ws"
        aws = await websockets.connect(url)
        await aws.send(json.dumps({
            "msg_id": str(uuid.uuid4()), "msg_type": "AUTH_REQ",
            "device_id": "lingji-pc", "timestamp": time.time(),
            "payload": {"device_id": "lingji-pc"},
        }))
        await asyncio.wait_for(aws.recv(), timeout=3)

        async with httpx.AsyncClient(base_url=f"http://{GATEWAY_HOST}:{GATEWAY_PORT}") as client:
            resp = await client.get("/v1/agents")
            if resp.status_code != 200:
                r.fail("/v1/agents", resp.text[:120])
                await aws.close()
                return
            data = resp.json()
            ids = {a["device_id"] for a in data.get("agents", [])}
            if "lingji-pc" not in ids:
                r.fail("/v1/agents", f"缺少 lingji-pc: {data}")
            elif data.get("default_agent_id") != "lingji-pc":
                r.fail("/v1/agents", f"default 异常: {data}")
            else:
                r.ok("/v1/agents 在线列表")

        await aws.close()
    except Exception as e:
        r.fail("/v1/agents", str(e))

# ── Main ──────────────────────────────────────────────────

async def run_tests(start_gateway: bool):
    results = TestResult()
    print("灵机计划 三端集成测试")
    print(f"Gateway: {GATEWAY_HOST}:{GATEWAY_PORT}\n")

    gateway = None
    if start_gateway:
        binary = os.environ.get(
            "LINGJI_GATEWAY_BIN",
            str(GATEWAY_DIR / "lingji-gateway"),
        )
        if not os.path.exists(binary):
            print(f"编译 Gateway ({GATEWAY_DIR})...")
            result = subprocess.run(
                ["go", "build", "-o", "lingji-gateway", "."],
                cwd=str(GATEWAY_DIR),
                env={
                    **os.environ,
                    "PATH": os.path.expanduser("~/.local/go/bin")
                    + ":"
                    + os.environ.get("PATH", ""),
                    "GOPROXY": os.environ.get(
                        "GOPROXY", "https://goproxy.cn,direct"
                    ),
                },
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                print(f"Gateway 编译失败:\n{result.stderr}")
                return False

        gateway = GatewayProcess(binary)
        print("启动 Gateway...")
        if not gateway.start():
            print("Gateway 启动失败!")
            return False
        print("Gateway 已启动\n")

    try:
        await test_gateway_health(results)
        print()
        await test_phone_connect_auth(results)
        print()
        await test_message_roundtrip(results)
        print()
        await test_cross_device_isolation(results)
        print()
        await test_multi_agent_routing(results)
        print()
        await test_agents_api(results)
        print()
        await test_multiple_messages(results)
        print()
        await test_file_attachment_e2e(results)
    finally:
        if gateway:
            gateway.stop()
            print("\nGateway 已停止")

    return results.summary()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-gateway", action="store_true")
    args = parser.parse_args()
    success = asyncio.run(run_tests(not args.no_gateway))
    sys.exit(0 if success else 1)
