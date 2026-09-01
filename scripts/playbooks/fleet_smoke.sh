#!/usr/bin/env bash
# playbook_id: fleet-smoke
# cwd expected: /mnt/e/LingjiPlan/LingjiZero
# Does not execute arbitrary shell from arguments.
#
# Local smoke only: write a tiny file under incoming and list it.
# Does not call fleet HTTP (no token).
set -euo pipefail

PLAYBOOK_ID="fleet-smoke"
EXPECTED_ROOT="/mnt/e/LingjiPlan/LingjiZero"
STATUS=fail
EVIDENCE="{\"playbook_id\":\"${PLAYBOOK_ID}\"}"
trap 'echo "STATUS=${STATUS} ${EVIDENCE}"' EXIT

if [[ $# -gt 0 ]]; then
  echo "NOTE: ignoring extra args (playbooks do not take arbitrary shell)"
fi

if [[ -d "$EXPECTED_ROOT" ]]; then
  cd "$EXPECTED_ROOT"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$SCRIPT_DIR/../.."
  echo "NOTE: expected cwd ${EXPECTED_ROOT} missing; using $(pwd)"
fi
REPO_ROOT="$(pwd)"

incoming_default="${REPO_ROOT}/lingji-agent/data/incoming"
incoming_home="${HOME}/lingji-incoming"
if [[ -d "$incoming_default" ]]; then
  incoming="$incoming_default"
elif [[ -d "$incoming_home" ]]; then
  incoming="$incoming_home"
else
  incoming="$incoming_default"
fi

echo "=== ${PLAYBOOK_ID} ==="
echo "cwd=${REPO_ROOT}"
echo "incoming=${incoming}"

mkdir -p "$incoming"
smoke_file="${incoming}/playbook-fleet-smoke-$(date +%Y%m%dT%H%M%S).txt"
printf 'fleet-smoke ok host=%s ts=%s\n' "$(hostname 2>/dev/null || echo unknown)" "$(date -Iseconds 2>/dev/null || date)" >"$smoke_file"

if [[ ! -f "$smoke_file" ]]; then
  echo "FAIL: file not created: ${smoke_file}"
  EVIDENCE="{\"playbook_id\":\"${PLAYBOOK_ID}\",\"file\":\"\"}"
  STATUS=fail
  exit 1
fi

echo "created: ${smoke_file}"
ls -l "$smoke_file"

EVIDENCE="{\"playbook_id\":\"${PLAYBOOK_ID}\",\"file\":\"${smoke_file}\"}"
STATUS=ok
