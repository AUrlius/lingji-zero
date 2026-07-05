#!/usr/bin/env bash
set -euo pipefail

TOKEN="${LINGJI_AUTH_TOKEN:-lingji-5f652fd642911b68}"
HOST="${LINGJI_PUBLIC_HOST:-lingji.mygoal.tech}"

echo "[verify] JS with cache-bust query"
JS=$(curl -sf "https://${HOST}/js/lingji-api.js?v=0.1.2")
if echo "$JS" | grep -q 'lingji-b21aaff8'; then
  echo "FAIL: still contains old hardcoded token"
  exit 1
fi
if ! echo "$JS" | grep -q 'lingji_gateway_token'; then
  echo "FAIL: missing localStorage token logic"
  exit 1
fi
echo "OK: new JS (localStorage token, no lingji-b21aaff8)"

echo "[verify] index.html script tags"
IDX=$(curl -sf "https://${HOST}/")
echo "$IDX" | grep -q 'lingji-api.js?v=0.1.2' || { echo "FAIL: index missing v=0.1.2"; exit 1; }
echo "OK: index references versioned JS"

echo "[verify] health + agents"
curl -sf "https://${HOST}/health" | grep -q '"status":"ok"'
curl -sf "https://${HOST}/v1/agents?token=${TOKEN}" | grep -q lingji-pc
echo "OK: backend healthy"

echo "[verify] WebSocket auth"
python3 <<PY
import asyncio
import websockets

async def main():
    uri = "wss://${HOST}/ws?token=${TOKEN}"
    async with websockets.connect(uri) as ws:
        print("OK: WebSocket connected")

asyncio.run(main())
PY

echo "[verify] all checks passed"
