#!/usr/bin/env bash
# 四期 4.3：compose Gateway + 三端集成脚本（6/6），供 CI 与本地冒烟复用
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HOST_PORT="${LINGJI_HOST_PORT:-18765}"
AGENT_DIR="$ROOT/lingji-agent"
PYTHON="${PYTHON:-python3}"

if ! command -v docker >/dev/null 2>&1; then
  echo "错误: 需要 Docker（含 docker compose）" >&2
  exit 1
fi

cleanup() {
  docker compose stop gateway >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "构建 Gateway 镜像..."
docker compose build gateway

echo "启动 Gateway (compose)..."
docker compose up -d gateway

echo "等待 /health ..."
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${HOST_PORT}/health" >/dev/null; then
    break
  fi
  if [[ "$i" -eq 30 ]]; then
    echo "Gateway health 超时" >&2
    docker compose logs gateway >&2 || true
    exit 1
  fi
  sleep 1
done

if [[ -d "$AGENT_DIR/.venv" ]]; then
  # shellcheck disable=SC1091
  source "$AGENT_DIR/.venv/bin/activate"
  PYTHON="${PYTHON:-python}"
fi

echo "安装 Agent 依赖..."
cd "$AGENT_DIR"
"$PYTHON" -m pip install -e . -q

export LINGJI_INTEGRATION_HOST=127.0.0.1
export LINGJI_INTEGRATION_PORT="$HOST_PORT"

echo "运行 integration_test.py (--no-gateway)..."
"$PYTHON" tests/integration_test.py --no-gateway
