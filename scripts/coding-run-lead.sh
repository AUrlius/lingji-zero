#!/usr/bin/env bash
# 编码领队包装：假定 cwd 为 {job_dir}/lead（与 CursorPlanLeadRuntime 一致）。
# 优先读 JOB_DIR/brief.md，否则 cwd/brief_in.md；若有 questions_in.md 则追加。
# 只读 Cursor：agent -p --trust（禁止 force / yolo 标志）。
#
# 用法（由 coding.lead_cmd 调用，勿手动 cd 到仓库根）:
#   coding.lead_cmd: ["/mnt/e/LingjiPlan/LingjiZero/scripts/coding-run-lead.sh"]
#
# 环境变量:
#   CURSOR_AGENT  无头 agent 可执行路径（缺省则 command -v agent）

set -euo pipefail

JOB_DIR="$(cd .. && pwd)"

if [[ -f "$JOB_DIR/brief.md" ]]; then
  PROMPT="$(cat "$JOB_DIR/brief.md")"
elif [[ -f brief_in.md ]]; then
  PROMPT="$(cat brief_in.md)"
else
  echo "coding-run-lead: missing brief.md under $JOB_DIR and brief_in.md in cwd" >&2
  exit 1
fi

if [[ -f questions_in.md ]]; then
  PROMPT="${PROMPT}"$'\n\n'"$(cat questions_in.md)"
fi

if [[ -n "${CURSOR_AGENT:-}" ]]; then
  AGENT_BIN="$CURSOR_AGENT"
elif AGENT_BIN="$(command -v agent 2>/dev/null)"; then
  :
else
  echo "coding-run-lead: agent not found (set CURSOR_AGENT or install agent on PATH)" >&2
  exit 1
fi

exec "$AGENT_BIN" -p --trust "$PROMPT"
