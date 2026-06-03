#!/usr/bin/env python3
"""灵机计划 端到端验证 v2 — 文件信号版本"""

import asyncio
import json
import os
import subprocess
import sys
import time
import websockets

GATEWAY_PORT = 19771
GATEWAY_HOST = "127.0.0.1"
SIGNAL_FILE = "/tmp/lingji_e2e_signal.txt"
LOG_FILE = "/tmp/lingji_agent_e2e.log"


async def test_e2e():
    print("=" * 60)
    print("灵机计划 端到端验证")
    print("=" * 60)

    # Clean signal file
    if os.path.exists(SIGNAL_FILE):
        os.unlink(SIGNAL_FILE)

    # 1. Start Gateway
    print("\n[1/4] 启动 Gateway...")
    gw_env = os.environ.copy()
    gw_env["LINGJI_PORT"] = str(GATEWAY_PORT)
    gw_env["PATH"] = os.path.expanduser("~/.local/go/bin") + ":" + gw_env.get("PATH", "")
    gw_proc = subprocess.Popen(
        [os.path.expanduser("~/lingji-gateway/lingji-gateway")],
        env=gw_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1.5)
    print(f"   PID: {gw_proc.pid}")

    # Health check
    try:
        r, w = await asyncio.wait_for(
            asyncio.open_connection(GATEWAY_HOST, GATEWAY_PORT), timeout=5,
        )
        w.write(b"GET /health HTTP/1.0\r\nHost: l\r\n\r\n")
        await w.drain()
        data = await asyncio.wait_for(r.read(512), timeout=3)
        w.close()
        print(f"   Health: {data.decode().split(chr(13)+chr(10))[-1]}")
    except Exception as e:
        print(f"   Health FAILED: {e}")
        gw_proc.terminate()
        return

    # 2. Write Agent script to file (avoids subprocess quoting issues)
    agent_py = f"""import asyncio, json, time, os
from lingji_agent.foundation.config import load_config
from lingji_agent.cognitive.llm_provider import create_connector
from lingji_agent.cognitive.orchestrator import build_graph, run_agent
from lingji_agent.cognitive.prompt_manager import PromptManager
from lingji_agent.execution.registry import registry
from lingji_agent.execution.tools import fs_tools, sys_tools
from lingji_agent.network.ws_client import GatewayClient
from lingji_agent.network.router import Router
from lingji_agent.network.protocol import Message, MsgType

SIGNAL = "{SIGNAL_FILE}"
LOG = "{LOG_FILE}"

def signal(msg):
    with open(SIGNAL, 'w') as f: f.write(msg)

def log(msg):
    with open(LOG, 'a') as f: f.write(msg + '\\n')

async def main():
    cfg = load_config()
    cfg.network.gateway_host = '{GATEWAY_HOST}'
    cfg.network.gateway_port = {GATEWAY_PORT}
    conn = create_connector(cfg)
    pm = PromptManager(device_id=cfg.network.device_id, registry=registry)
    graph = build_graph(connector=conn, registry=registry)
    log(f'Model: {{conn.model_name}}, tools: {{len(registry.list_all())}}')
    
    router = Router()
    async def on_cmd(msg):
        text = msg.payload.get('text', '')
        log(f'Received: {{text}}')
        prompt = pm.build_system_prompt()
        result = await run_agent(graph=graph, user_message=text, system_prompt=prompt, connector=conn, registry=registry)
        reply = result.get('final_response', '')
        log(f'Reply: {{reply[:200]}}')
        signal('REPLY:' + reply)
    
    router.register(MsgType.CMD_TEXT, on_cmd)
    client = GatewayClient(cfg.network, router)
    
    def on_connected():
        signal('READY')
        log('Connected to gateway')
    
    client.on_connected(on_connected)
    log('Starting client...')
    await client.start()

asyncio.run(main())
"""
    agent_script = os.path.expanduser("~/lingji-agent/tests/_e2e_agent.py")
    with open(agent_script, "w") as f:
        f.write(agent_py)

    # 3. Start Agent
    print("\n[2/4] 启动 Agent...")
    agent_proc = subprocess.Popen(
        [os.path.expanduser("~/lingji-agent/.venv/bin/python"), "-u", agent_script],
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    print(f"   PID: {agent_proc.pid}")

    # Wait for READY signal
    print("   等待连接...")
    deadline = time.time() + 15
    ready = False
    while time.time() < deadline:
        await asyncio.sleep(0.3)
        if agent_proc.poll() is not None:
            print("   Agent 异常退出!")
            if os.path.exists(LOG_FILE):
                print("   Log:", open(LOG_FILE).read()[-500:])
            gw_proc.terminate()
            return
        if os.path.exists(SIGNAL_FILE):
            sig = open(SIGNAL_FILE).read().strip()
            if sig == "READY":
                ready = True
                os.unlink(SIGNAL_FILE)
                break

    if not ready:
        print("   Agent 超时!")
        gw_proc.terminate()
        agent_proc.terminate()
        return

    print("   Agent 已连接!")

    # 4. Phone test
    print("\n[3/4] 模拟手机发消息...")
    ws = await websockets.connect(f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}/ws")
    await ws.send(json.dumps({
        "msg_id": "p1", "msg_type": "AUTH_REQ",
        "device_id": "phone", "timestamp": time.time(),
        "payload": {"device_id": "phone"},
    }))
    auth = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
    print(f"   Auth: {auth.get('payload', {}).get('status', '?')}")

    await asyncio.sleep(0.3)
    test_msg = "用一句话介绍你自己，用中文"
    await ws.send(json.dumps({
        "msg_id": "p2", "msg_type": "CMD_TEXT",
        "device_id": "phone", "timestamp": time.time(),
        "payload": {"text": test_msg},
    }))
    print(f"   Sent: {test_msg}")
    print("   等待 LLM 响应...")

    # Wait for reply via Gateway or signal file
    got_reply = False
    deadline = time.time() + 60
    while time.time() < deadline:
        # Check Gateway WS
        try:
            reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            text = reply.get("payload", {}).get("text", "")
            if text and "queued" not in text and "不在线" not in text:
                print(f"\n{'='*60}")
                print(f"🤖 Agent 回复:")
                print(f"   {text}")
                print(f"{'='*60}")
                got_reply = True
                break
        except asyncio.TimeoutError:
            pass

        # Check signal file
        if os.path.exists(SIGNAL_FILE):
            sig = open(SIGNAL_FILE).read().strip()
            if sig.startswith("REPLY:"):
                text = sig[6:]
                print(f"\n🤖 Agent 回复:")
                print(f"   {text}")
                os.unlink(SIGNAL_FILE)
                got_reply = True
                break

        if agent_proc.poll() is not None:
            print("   Agent 已退出!")
            break

    if not got_reply:
        print("   超时!")
        if os.path.exists(LOG_FILE):
            print("   Agent log:", open(LOG_FILE).read()[-500:])

    await ws.close()

    # 5. Cleanup
    print("\n[4/4] 清理...")
    agent_proc.terminate()
    gw_proc.terminate()
    try: agent_proc.wait(timeout=3)
    except: pass
    try: gw_proc.wait(timeout=3)
    except: pass
    os.unlink(agent_script)
    if os.path.exists(SIGNAL_FILE): os.unlink(SIGNAL_FILE)
    print("完成!")


if __name__ == "__main__":
    asyncio.run(test_e2e())
