#!/usr/bin/env bash
# playbook_id: agent.restart
# cwd expected: /mnt/e/LingjiPlan/LingjiZero
# Does not execute arbitrary shell from arguments.
#
# Conservative: git pull --ff-only (pull failure is not a hard fail);
# then run scripts/restart-agent-wsl.sh. Missing restart script → STATUS=fail.
set -euo pipefail

PLAYBOOK_ID="agent.restart"
EXPECTED_ROOT="/mnt/e/LingjiPlan/LingjiZero"
STATUS=fail
git_pull="skipped"
restart="skip"
EVIDENCE="{\"playbook_id\":\"${PLAYBOOK_ID}\"}"
trap 'echo "STATUS=${STATUS} ${EVIDENCE}"' EXIT

export GIT_TERMINAL_PROMPT=0
export GIT_PAGER=cat
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes -o ConnectTimeout=10}"

if [[ $# -gt 0 ]]; then
  echo "NOTE: ignoring extra args (playbooks do not take arbitrary shell)"
fi

cd "$EXPECTED_ROOT"

_git_pull() {
  if command -v timeout >/dev/null 2>&1; then
    timeout 90 git pull --ff-only origin main
  else
    git pull --ff-only origin main
  fi
}

echo "=== ${PLAYBOOK_ID} ==="
echo "cwd=$(pwd)"

# Pull: allow fail (no remote / not ff / network). Do not abort the playbook.
if git remote get-url origin >/dev/null 2>&1; then
  echo "git: origin=$(git remote get-url origin)"
  set +e
  _git_pull
  pull_rc=$?
  set -e
  if [[ $pull_rc -eq 0 ]]; then
    git_pull="ok"
    echo "git: pull --ff-only origin main ok"
  else
    git_pull="failed"
    echo "git: pull failed (rc=${pull_rc}); continuing to restart"
  fi
else
  git_pull="skipped"
  echo "git: no origin remote; skip pull (not a hard fail)"
fi

RESTART="./scripts/restart-agent-wsl.sh"
if [[ ! -f "$RESTART" ]]; then
  restart="skip"
  echo "SKIP: ${RESTART} missing"
  EVIDENCE="{\"playbook_id\":\"${PLAYBOOK_ID}\",\"git_pull\":\"${git_pull}\",\"restart\":\"${restart}\"}"
  STATUS=fail
  exit 1
fi

echo "restart: running ${RESTART}"
if [[ -x "$RESTART" ]]; then
  "$RESTART"
else
  echo "NOTE: ${RESTART} not marked executable (drvfs); running via bash"
  bash "$RESTART"
fi
restart="ok"

EVIDENCE="{\"playbook_id\":\"${PLAYBOOK_ID}\",\"git_pull\":\"${git_pull}\",\"restart\":\"${restart}\"}"
STATUS=ok
