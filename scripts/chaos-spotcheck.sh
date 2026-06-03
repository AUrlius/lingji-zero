#!/usr/bin/env bash
# 四期 4.4：压力 + 混沌抽检（compose Gateway）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HOST_PORT="${LINGJI_HOST_PORT:-18765}"
AGENT_DIR="$ROOT/lingji-agent"
PYTHON="${PYTHON:-python3}"
SKIP_BURST=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-burst) SKIP_BURST=true; shift ;;
    -h|--help)
      echo "用法: $0 [--skip-burst]"
      exit 0
      ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "错误: 需要 Docker（含 docker compose）" >&2
  exit 1
fi

cleanup() {
  docker compose stop gateway >/dev/null 2>&1 || true
}
trap cleanup EXIT

wait_health() {
  echo "等待 /health ..."
  for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:${HOST_PORT}/health" >/dev/null; then
      return 0
    fi
    if [[ "$i" -eq 30 ]]; then
      echo "Gateway health 超时" >&2
      docker compose logs gateway >&2 || true
      return 1
    fi
    sleep 1
  done
}

setup_agent_env() {
  if [[ -d "$AGENT_DIR/.venv" ]]; then
    # shellcheck disable=SC1091
    source "$AGENT_DIR/.venv/bin/activate"
    PYTHON="${PYTHON:-python}"
  fi
  cd "$AGENT_DIR"
  "$PYTHON" -m pip install -e . -q
  export LINGJI_INTEGRATION_HOST=127.0.0.1
  export LINGJI_INTEGRATION_PORT="$HOST_PORT"
}

echo "=== 4.4 混沌抽检：构建并启动 Gateway ==="
docker compose build gateway
docker compose up -d gateway
wait_health

setup_agent_env

echo "=== 基线集成 6/6 ==="
"$PYTHON" tests/integration_test.py --no-gateway

if [[ "$SKIP_BURST" != true ]]; then
  echo "=== 压力抽检 gateway_burst ==="
  "$PYTHON" "$ROOT/scripts/gateway_burst.py" \
    --host 127.0.0.1 \
    --port "$HOST_PORT" \
    --phones 5 \
    --messages 20

  echo "=== 混沌：重启 Gateway ==="
  docker compose restart gateway
  wait_health
  sleep 2

  echo "=== 恢复后压力抽检 ==="
  "$PYTHON" "$ROOT/scripts/gateway_burst.py" \
    --host 127.0.0.1 \
    --port "$HOST_PORT" \
    --phones 3 \
    --messages 10
fi

echo "=== 4.4 chaos-spotcheck 通过 ==="
