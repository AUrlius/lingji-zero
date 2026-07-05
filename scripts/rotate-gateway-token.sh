#!/usr/bin/env bash
# 轮换生产 Gateway LINGJI_AUTH_TOKEN（一次性运维脚本，勿提交 token）
set -euo pipefail

HOST="${LINGJI_SSH_HOST:?set LINGJI_SSH_HOST}"
USER="${LINGJI_SSH_USER:-hermes}"
TOKEN="${1:-lingji-$(openssl rand -hex 8)}"
AGENT_CONFIG="${LINGJI_AGENT_CONFIG:-$(cd "$(dirname "$0")/../lingji-agent" && pwd)/config/default_config.yaml}"

echo "[rotate] new token: $TOKEN"
echo "[rotate] updating $USER@$HOST:/opt/lingji/env"
ssh -o StrictHostKeyChecking=accept-new "${USER}@${HOST}" \
  "echo LINGJI_AUTH_TOKEN=${TOKEN} | sudo tee /opt/lingji/env >/dev/null && sudo systemctl restart lingji-gateway && sleep 2 && curl -sf http://127.0.0.1:8765/health | grep -q ok"

if [[ -f "$AGENT_CONFIG" ]]; then
  python3 - "$AGENT_CONFIG" "$TOKEN" <<'PY'
import re, sys
path, token = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
if re.search(r'auth_token:\s*["\']', text):
    text = re.sub(r'(auth_token:\s*["\'])[^"\']*(["\'])', rf'\1{token}\2', text)
else:
    text = re.sub(r'(auth_token:\s*)\S+', rf'\1"{token}"', text)
open(path, "w", encoding="utf-8").write(text)
print(f"[rotate] updated {path}")
PY
fi

echo "[rotate] bookmark: https://lingji.mygoal.tech/?token=${TOKEN}"
echo "LINGJI_AUTH_TOKEN=${TOKEN}" > /tmp/lingji-new-token.env
echo "[rotate] saved /tmp/lingji-new-token.env (local only)"
