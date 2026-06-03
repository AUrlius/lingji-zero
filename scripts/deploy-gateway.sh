#!/usr/bin/env bash
# 四期 4.3：Gateway 发版 — scp + systemctl restart + health 验收
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GATEWAY_DIR="$ROOT/lingji-gateway"
BINARY=""
HOST="${LINGJI_SSH_HOST:-}"
USER="${LINGJI_SSH_USER:-hermes}"
REMOTE_PATH="${LINGJI_GATEWAY_PATH:-/opt/lingji/lingji-gateway}"
NO_BUILD=false
HEALTH_URL="${LINGJI_HEALTH_URL:-http://127.0.0.1:8765/health}"

usage() {
  cat <<EOF
用法: $0 [选项]

  --host HOST          SSH 目标（或 env LINGJI_SSH_HOST）
  --user USER          SSH 用户（默认 hermes）
  --binary PATH        本地二进制路径（默认先 GOOS=linux GOARCH=amd64 构建）
  --remote-path PATH   远端二进制路径（默认 /opt/lingji/lingji-gateway）
  --health-url URL     部署后健康检查 URL
  --no-build           不本地构建，须配合 --binary
  -h, --help           显示帮助

环境变量: LINGJI_SSH_HOST, LINGJI_SSH_USER, LINGJI_SSH_KEY（ssh 私钥路径）,
          LINGJI_GATEWAY_PATH, LINGJI_HEALTH_URL
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --user) USER="$2"; shift 2 ;;
    --binary) BINARY="$2"; shift 2 ;;
    --remote-path) REMOTE_PATH="$2"; shift 2 ;;
    --health-url) HEALTH_URL="$2"; shift 2 ;;
    --no-build) NO_BUILD=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$HOST" ]]; then
  echo "错误: 需要 --host 或 LINGJI_SSH_HOST" >&2
  exit 1
fi

SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
if [[ -n "${LINGJI_SSH_KEY:-}" ]]; then
  SSH_OPTS+=(-i "$LINGJI_SSH_KEY")
fi

if [[ -z "$BINARY" && "$NO_BUILD" == true ]]; then
  echo "错误: --no-build 需要 --binary" >&2
  exit 1
fi

if [[ -z "$BINARY" ]]; then
  echo "构建 linux/amd64 Gateway..."
  cd "$GATEWAY_DIR"
  GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -ldflags="-s -w" -o lingji-gateway .
  BINARY="$GATEWAY_DIR/lingji-gateway"
fi

if [[ ! -f "$BINARY" ]]; then
  echo "错误: 二进制不存在: $BINARY" >&2
  exit 1
fi

REMOTE_NEW="${REMOTE_PATH}.new"
REMOTE_BAK="${REMOTE_PATH}.bak"
REMOTE_STAGE="tmp/lingji-gateway.new"

echo "上传 $BINARY -> ${USER}@${HOST}:~/${REMOTE_STAGE}"
scp "${SSH_OPTS[@]}" "$BINARY" "${USER}@${HOST}:${REMOTE_STAGE}"

echo "原子替换并重启 lingji-gateway..."
ssh "${SSH_OPTS[@]}" "${USER}@${HOST}" bash -s <<EOF
set -euo pipefail
chmod +x "\${HOME}/${REMOTE_STAGE}"
if [[ -f "${REMOTE_PATH}" ]]; then
  sudo cp -a "${REMOTE_PATH}" "${REMOTE_BAK}"
fi
sudo install -m 755 "\${HOME}/${REMOTE_STAGE}" "${REMOTE_PATH}"
rm -f "\${HOME}/${REMOTE_STAGE}"
sudo systemctl restart lingji-gateway
sleep 2
curl -sf "http://127.0.0.1:8765/health" | grep -q ok
EOF

echo "远端 health OK，检查公网 URL: ${HEALTH_URL}"
if curl -sf "${HEALTH_URL}" | grep -q ok; then
  echo "部署成功: ${HEALTH_URL}"
else
  echo "警告: 公网 health 未通过，请检查 cloudflared / journalctl -u lingji-gateway" >&2
  exit 1
fi
