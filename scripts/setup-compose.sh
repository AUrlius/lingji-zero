#!/usr/bin/env bash
# 三期 3.3：一键检查环境并构建 compose 镜像
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "错误: 需要 Docker（含 docker compose）" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "已创建 .env（可选填 DEEPSEEK_API_KEY / LINGJI_AUTH_TOKEN）"
fi

echo "构建 Gateway 镜像..."
docker compose build gateway

echo ""
echo "下一步:"
echo "  docker compose up -d gateway"
echo "  ./scripts/compose-integration-smoke.sh"
