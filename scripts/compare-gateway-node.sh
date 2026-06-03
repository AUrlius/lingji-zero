#!/usr/bin/env bash
# Node Gateway Spike — 本地 health + 可选 prod-e2e 对比（8766，不碰生产 Go）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NODE_DIR="$ROOT/lingji-gateway-node"
PORT="${LINGJI_NODE_PORT:-8766}"
LOG="${LINGJI_NODE_LOG:-/tmp/lingji-gateway-node.log}"
TOKEN="${LINGJI_AUTH_TOKEN:-}"

if [[ -f "$ROOT/lingji-agent/config/default_config.yaml" ]]; then
  if [[ -z "$TOKEN" ]]; then
    TOKEN="$(grep -E '^\s*auth_token:' "$ROOT/lingji-agent/config/default_config.yaml" | head -1 | sed 's/.*: *//' | tr -d '"' | tr -d "'")"
  fi
fi

cd "$NODE_DIR"
if [[ ! -d node_modules ]]; then
  npm install
fi

echo "[compare] stop existing node gateway on :$PORT if any"
fuser -k "${PORT}/tcp" 2>/dev/null || true
sleep 1

echo "[compare] start node gateway → $LOG"
LINGJI_PORT="$PORT" LINGJI_AUTH_TOKEN="$TOKEN" nohup npm start >"$LOG" 2>&1 &
sleep 2

echo "[compare] health"
curl -sf "http://127.0.0.1:${PORT}/health"
echo

echo "[compare] node unit tests"
npm test

if [[ -n "$TOKEN" ]] && command -v python3 >/dev/null; then
  echo "[compare] prod-e2e g6_upload against localhost:$PORT (needs Agent on lingji-pc connected to same gateway)"
  echo "[compare] skip auto prod-e2e — run manually after pointing Agent to 127.0.0.1:$PORT:"
  echo "  cd $ROOT/lingji-agent && source .venv/bin/activate"
  echo "  LINGJI_GATEWAY_HOST=127.0.0.1 LINGJI_GATEWAY_PORT=$PORT python ../scripts/prod-e2e-smoke.py --section g6_upload --host 127.0.0.1 --port $PORT"
else
  echo "[compare] set LINGJI_AUTH_TOKEN or default_config.yaml for prod-e2e hint"
fi

echo "[compare] done — node gateway PID log: $LOG"
