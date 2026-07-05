#!/usr/bin/env bash
# Purge Cloudflare cache for lingji.mygoal.tech (requires API token).
#
# Usage:
#   export CLOUDFLARE_API_TOKEN=...
#   export CLOUDFLARE_ZONE_ID=...   # mygoal.tech zone
#   ./scripts/purge-cloudflare-cache.sh
#
# Or purge everything:
#   PURGE_EVERYTHING=1 ./scripts/purge-cloudflare-cache.sh

set -euo pipefail

ZONE_ID="${CLOUDFLARE_ZONE_ID:-}"
TOKEN="${CLOUDFLARE_API_TOKEN:-}"
HOST="${LINGJI_PUBLIC_HOST:-lingji.mygoal.tech}"

if [[ -z "$TOKEN" || -z "$ZONE_ID" ]]; then
  echo "错误: 需要 CLOUDFLARE_API_TOKEN 与 CLOUDFLARE_ZONE_ID" >&2
  echo "在 Cloudflare Dashboard → mygoal.tech → Overview 右侧可复制 Zone ID" >&2
  exit 1
fi

if [[ "${PURGE_EVERYTHING:-}" == "1" ]]; then
  BODY='{"purge_everything":true}'
  echo "[purge] Purge Everything for zone $ZONE_ID"
else
  URLS=$(cat <<EOF
{"files":[
  "https://${HOST}/",
  "https://${HOST}/index.html",
  "https://${HOST}/js/lingji-api.js",
  "https://${HOST}/js/ui.js",
  "https://${HOST}/css/app.css"
]}
EOF
)
  BODY="$URLS"
  echo "[purge] Custom purge for https://${HOST}/..."
fi

curl -sf -X POST "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/purge_cache" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  --data "$BODY" | grep -q '"success":true'

echo "[purge] OK"
