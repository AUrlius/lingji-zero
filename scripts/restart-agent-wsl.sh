#!/usr/bin/env bash
# 从 LingjiZero 单一源码路径重启 WSL Agent（G6.2c 运维规范）
#
# 用法（WSL）:
#   cd /mnt/e/LingjiPlan/LingjiZero
#   ./scripts/restart-agent-wsl.sh
#
# 环境变量:
#   LINGJI_AGENT_LOG  日志路径（默认 /tmp/lingji-agent.log）

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_DIR="$REPO_ROOT/lingji-agent"
LOG_FILE="${LINGJI_AGENT_LOG:-/tmp/lingji-agent.log}"
WAIT_SEC="${LINGJI_AGENT_WAIT_SEC:-8}"

if [[ ! -d "$AGENT_DIR/.venv" ]]; then
  echo "缺少 $AGENT_DIR/.venv — 请先: cd $AGENT_DIR && python3 -m venv .venv && pip install -e ." >&2
  exit 1
fi

cd "$AGENT_DIR"
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[restart-agent] stop (LingjiZero path: $AGENT_DIR)"
python3 -m lingji_agent.main --stop || true

for _ in $(seq 1 15); do
  if ! python3 -m lingji_agent.main --status >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "[restart-agent] start → $LOG_FILE"
nohup python3 -m lingji_agent.main >"$LOG_FILE" 2>&1 &
sleep "$WAIT_SEC"

if python3 -m lingji_agent.main --status; then
  echo "[restart-agent] OK"
else
  echo "[restart-agent] FAIL: Agent 未在 ${WAIT_SEC}s 内就绪，见 $LOG_FILE" >&2
  tail -n 30 "$LOG_FILE" >&2 || true
  exit 1
fi

if grep -q incoming_dir "$LOG_FILE" 2>/dev/null; then
  grep incoming_dir "$LOG_FILE" | tail -1
else
  echo "[restart-agent] WARN: 日志中未见 incoming_dir 行，请检查 config.network.incoming_dir" >&2
fi
