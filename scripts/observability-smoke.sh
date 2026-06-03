#!/usr/bin/env bash
# 四期 4.2 — observability 栈冒烟（Prometheus + Tempo + Grafana + OTel Collector）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Starting observability profile..."
docker compose --profile observability up -d

echo "==> Waiting for services..."
sleep 8

fail=0

check() {
  local name="$1"
  shift
  if "$@"; then
    echo "OK  $name"
  else
    echo "FAIL $name"
    fail=1
  fi
}

check "Grafana health" curl -sf "http://127.0.0.1:${LINGJI_GRAFANA_PORT:-3000}/api/health" >/dev/null
check "Prometheus ready" curl -sf "http://127.0.0.1:${LINGJI_PROMETHEUS_PORT:-9090}/-/ready" >/dev/null
check "Tempo ready" curl -sf "http://127.0.0.1:${LINGJI_TEMPO_PORT:-3200}/ready" >/dev/null

if curl -sf "http://127.0.0.1:9091/metrics" 2>/dev/null | grep -q lingji_cmd_total; then
  echo "OK  Agent metrics endpoint (9091)"
else
  echo "WARN Agent /metrics not reachable on :9091 (start WSL Agent separately)"
fi

if [ "$fail" -ne 0 ]; then
  echo "observability-smoke: FAILED"
  exit 1
fi

echo "observability-smoke: PASSED"
echo "Grafana: http://127.0.0.1:${LINGJI_GRAFANA_PORT:-3000} (admin / \${GRAFANA_ADMIN_PASSWORD:-admin})"
