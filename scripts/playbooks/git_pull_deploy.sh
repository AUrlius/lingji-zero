#!/usr/bin/env bash
# playbook_id: git-pull-deploy
# cwd expected: /mnt/e/LingjiPlan/LingjiZero
# Does not execute arbitrary shell from arguments.
#
# git pull --ff-only only. Does NOT run deploy-gateway.sh (would SSH production).
set -euo pipefail

PLAYBOOK_ID="git-pull-deploy"
EXPECTED_ROOT="/mnt/e/LingjiPlan/LingjiZero"
STATUS=fail
EVIDENCE="{\"playbook_id\":\"${PLAYBOOK_ID}\"}"
trap 'echo "STATUS=${STATUS} ${EVIDENCE}"' EXIT

export GIT_TERMINAL_PROMPT=0
export GIT_PAGER=cat
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes -o ConnectTimeout=10}"

if [[ $# -gt 0 ]]; then
  echo "NOTE: ignoring extra args (playbooks do not take arbitrary shell)"
fi

cd "$EXPECTED_ROOT"

echo "=== ${PLAYBOOK_ID} ==="
echo "cwd=$(pwd)"

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "git: no origin remote"
  EVIDENCE="{\"playbook_id\":\"${PLAYBOOK_ID}\",\"git_pull\":\"failed\",\"deploy\":\"not_run\"}"
  STATUS=fail
  exit 1
fi

echo "git: origin=$(git remote get-url origin)"
echo "git: pull --ff-only"
if command -v timeout >/dev/null 2>&1; then
  timeout 90 git pull --ff-only
else
  git pull --ff-only
fi

echo "would-run: ./scripts/deploy-gateway.sh"
echo "NOTE: deploy NOT executed (would SSH production)"

EVIDENCE="{\"playbook_id\":\"${PLAYBOOK_ID}\",\"git_pull\":\"ok\",\"deploy\":\"not_run\"}"
STATUS=ok
