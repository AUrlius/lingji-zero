#!/usr/bin/env bash
# 编码执行者包装：假定 cwd 为 {job_dir}/workspace（与 run_coding_cli 一致）。
# 优先读 JOB_DIR/executor_prompt.md，否则 brief.md；无头 Cursor 可 --force。
#
# 用法（由 coding.start_cmd 调用，勿手动 cd 到仓库根）:
#   coding.start_cmd: ["/mnt/e/LingjiPlan/LingjiZero/scripts/coding-run-cursor.sh"]
#
# 环境变量:
#   CURSOR_AGENT  无头 agent 可执行路径（缺省则 command -v agent）

set -euo pipefail

JOB_DIR="$(cd .. && pwd)"

if [[ -f "$JOB_DIR/executor_prompt.md" ]]; then
  PROMPT="$(cat "$JOB_DIR/executor_prompt.md")"
elif [[ -f "$JOB_DIR/brief.md" ]]; then
  PROMPT="$(cat "$JOB_DIR/brief.md")"
else
  echo "coding-run-cursor: missing executor_prompt.md and brief.md under $JOB_DIR" >&2
  exit 1
fi

if [[ -n "${CURSOR_AGENT:-}" ]]; then
  AGENT_BIN="$CURSOR_AGENT"
elif AGENT_BIN="$(command -v agent 2>/dev/null)"; then
  :
else
  echo "coding-run-cursor: agent not found (set CURSOR_AGENT or install agent on PATH)" >&2
  exit 1
fi

exec "$AGENT_BIN" -p --force --trust --sandbox disabled "$PROMPT"
