"""G6 Gateway /files 端到端（需可编译 lingji-gateway 或使用 LINGJI_GATEWAY_BIN）"""

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
import websockets

REPO_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_DIR = REPO_ROOT / "lingji-gateway"
PORT = int(os.environ.get("LINGJI_FILE_TEST_PORT", "28765"))
HOST = "127.0.0.1"
TOKEN = "g6-test-token"


def _build_gateway() -> Path:
    binary = GATEWAY_DIR / "lingji-gateway"
    result = subprocess.run(
        ["go", "build", "-o", "lingji-gateway", "."],
        cwd=str(GATEWAY_DIR),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.skip(f"go build failed: {result.stderr}")
    return binary


@pytest.fixture(scope="module")
def gateway_proc():
    binary = _build_gateway()
    env = os.environ.copy()
    env["LINGJI_PORT"] = str(PORT)
    env["LINGJI_AUTH_TOKEN"] = TOKEN
    proc = subprocess.Popen(
        [str(binary)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.5)
    if proc.poll() is not None:
        pytest.skip("gateway failed to start")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.asyncio
async def test_files_upload_download_roundtrip(gateway_proc, tmp_path):
    sample = tmp_path / "roundtrip.txt"
    sample.write_text("g6-roundtrip-content", encoding="utf-8")

    async with httpx.AsyncClient(base_url=f"http://{HOST}:{PORT}") as client:
        with sample.open("rb") as fh:
            up = await client.post(
                "/files",
                files={"file": (sample.name, fh, "text/plain")},
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
        assert up.status_code == 200, up.text
        data = up.json()
        assert data["file_id"]
        dl = await client.get(data["download_path"])
        assert dl.status_code == 200
        assert dl.text == "g6-roundtrip-content"


@pytest.mark.asyncio
async def test_agent_res_attachments_over_ws(gateway_proc, tmp_path):
    """Mock Agent 发送带 attachments 的 AGENT_RES，Phone 可收到。"""
    sample = tmp_path / "via-ws.txt"
    sample.write_text("ws-attachment", encoding="utf-8")

    async with httpx.AsyncClient(base_url=f"http://{HOST}:{PORT}") as client:
        with sample.open("rb") as fh:
            up = await client.post(
                "/files",
                files={"file": (sample.name, fh, "text/plain")},
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
        attachment = up.json()

    url = f"ws://{HOST}:{PORT}/ws?token={TOKEN}"
    phone_ws = await websockets.connect(url)
    agent_ws = await websockets.connect(url)

    await phone_ws.send(json.dumps({
        "msg_id": str(uuid.uuid4()),
        "msg_type": "AUTH_REQ",
        "device_id": "phone-g6",
        "timestamp": time.time(),
        "payload": {"device_id": "phone-g6"},
    }))
    await agent_ws.send(json.dumps({
        "msg_id": str(uuid.uuid4()),
        "msg_type": "AUTH_REQ",
        "device_id": "lingji-pc",
        "timestamp": time.time(),
        "payload": {"device_id": "lingji-pc"},
    }))
    await asyncio.sleep(0.2)

    await agent_ws.send(json.dumps({
        "msg_id": str(uuid.uuid4()),
        "msg_type": "AGENT_RES",
        "device_id": "lingji-pc",
        "timestamp": time.time(),
        "payload": {
            "text": "文件已准备好",
            "attachments": [{
                "file_id": attachment["file_id"],
                "name": attachment["name"],
                "size_bytes": attachment["size_bytes"],
                "mime": attachment["mime"],
                "download_path": attachment["download_path"],
            }],
        },
    }))

    deadline = time.time() + 5
    got = None
    while time.time() < deadline:
        raw = await asyncio.wait_for(phone_ws.recv(), timeout=2)
        msg = json.loads(raw)
        if msg.get("msg_type") == "AGENT_RES" and msg.get("payload", {}).get("attachments"):
            got = msg
            break

    await phone_ws.close()
    await agent_ws.close()

    assert got is not None
    att = got["payload"]["attachments"][0]
    async with httpx.AsyncClient(base_url=f"http://{HOST}:{PORT}") as client:
        dl = await client.get(att["download_path"])
    assert dl.status_code == 200
    assert dl.text == "ws-attachment"


@pytest.mark.asyncio
async def test_files_upload_unauthorized(gateway_proc):
    async with httpx.AsyncClient(base_url=f"http://{HOST}:{PORT}") as client:
        resp = await client.post("/files", files={"file": ("x.txt", b"x", "text/plain")})
    assert resp.status_code == 401
