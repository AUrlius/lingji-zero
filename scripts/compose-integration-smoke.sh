#!/usr/bin/env bash
# 三期 3.3：compose 起 Gateway + 跑三端集成脚本（6/6 计数）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/scripts/ci-integration.sh"
