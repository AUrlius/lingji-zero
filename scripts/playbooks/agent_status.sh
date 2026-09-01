#!/usr/bin/env bash
# playbook_id: agent.status
# cwd expected: /mnt/e/LingjiPlan/LingjiZero
# Does not execute arbitrary shell from arguments.
#
# Probe: Gateway /health, incoming dir writability, Agent process.
set -euo pipefail

PLAYBOOK_ID="agent.status"
EXPECTED_ROOT="/mnt/e/LingjiPlan/LingjiZero"
HEALTH_URL="${LINGJI_HEALTH_URL:-https://lingji.mygoal.tech/health}"
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
AGENT_DIR="${REPO_ROOT}/lingji-agent"

_timeout() {
  if command -v timeout >/dev/null 2>&1; then
    timeout 15 "$@"
  else
    "$@"
  fi
}
export -f _timeout

echo "=== ${PLAYBOOK_ID} ==="
echo "cwd=${REPO_ROOT}"

# --- Gateway health (skip with note if curl fails; not a hard fail) ---
health="skip"
if ! command -v curl >/dev/null 2>&1; then
  echo "health: SKIP (curl not found)"
else
  set +e
  health_body="$(_timeout curl -sf --max-time 5 "$HEALTH_URL" 2>/dev/null)"
  health_rc=$?
  set -e
  if [[ $health_rc -eq 0 ]]; then
    health="ok"
    echo "health: ok url=${HEALTH_URL} body=${health_body}"
  else
    echo "health: SKIP (curl failed or ${HEALTH_URL} unreachable)"
  fi
fi

# --- Incoming dir ---
incoming_default="${REPO_ROOT}/lingji-agent/data/incoming"
incoming_home="${HOME}/lingji-incoming"
if [[ -d "$incoming_default" ]]; then
  incoming="$incoming_default"
elif [[ -d "$incoming_home" ]]; then
  incoming="$incoming_home"
else
  incoming="$incoming_default"
fi
incoming_writable="false"
if [[ -d "$incoming" && -w "$incoming" ]]; then
  incoming_writable="true"
  echo "incoming: ${incoming} writable=true"
elif [[ -d "$incoming" ]]; then
  echo "incoming: ${incoming} writable=false"
else
  echo "incoming: ${incoming} missing (also checked ${incoming_home})"
fi

# --- Process: pgrep and/or python3 -m lingji_agent.main --status ---
agent="not_running"
echo "--- pgrep ---"
set +e
pgrep_out="$(pgrep -af '[l]ingji_agent' 2>/dev/null)"
pgrep_rc=$?
set -e
if [[ $pgrep_rc -eq 0 && -n "$pgrep_out" ]]; then
  echo "$pgrep_out"
  agent="running"
else
  echo "pgrep: no lingji_agent process"
fi

echo "--- python3 -m lingji_agent.main --status ---"
if [[ ! -d "$AGENT_DIR" ]]; then
  echo "NOTE: ${AGENT_DIR} missing; skip --status"
else
  set +e
  status_out="$(
    cd "$AGENT_DIR" || exit 1
    if [[ -f .venv/bin/activate ]]; then
      # shellcheck disable=SC1091
      source .venv/bin/activate
    fi
    _timeout python3 -m lingji_agent.main --status
  )"
  status_rc=$?
  set -e
  if [[ -n "$status_out" ]]; then
    echo "$status_out"
  fi
  if [[ $status_rc -eq 0 ]]; then
    agent="running"
  else
    echo "python --status: not running (exit ${status_rc})"
  fi
fi

echo "agent=${agent} health=${health} incoming_writable=${incoming_writable}"
EVIDENCE="{\"playbook_id\":\"${PLAYBOOK_ID}\",\"agent\":\"${agent}\",\"health\":\"${health}\",\"incoming\":\"${incoming}\",\"incoming_writable\":${incoming_writable}}"

if [[ "$agent" == "running" && "$incoming_writable" == "true" ]]; then
  STATUS=ok
else
  STATUS=fail
  exit 1
fi
