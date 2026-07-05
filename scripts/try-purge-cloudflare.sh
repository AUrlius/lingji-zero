#!/usr/bin/env bash
# Try Cloudflare purge from common credential locations.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURGE="$SCRIPT_DIR/purge-cloudflare-cache.sh"

try_purge() {
  if [[ -n "${CLOUDFLARE_API_TOKEN:-}" && -n "${CLOUDFLARE_ZONE_ID:-}" ]]; then
    bash "$PURGE"
    return 0
  fi
  return 1
}

# WSL / shell env
if try_purge; then exit 0; fi

# Optional local env file (gitignored)
for f in "$SCRIPT_DIR/../.cloudflare.env" "$HOME/.lingji-cloudflare.env"; do
  if [[ -f "$f" ]]; then
    # shellcheck disable=SC1090
    source "$f"
    if try_purge; then exit 0; fi
  fi
done

echo "[purge] 跳过: 未找到 CLOUDFLARE_API_TOKEN / CLOUDFLARE_ZONE_ID"
echo "[purge] 已部署 cache-bust (?v=0.1.2) + no-cache 头；用户加载首页即可绕过旧 JS 缓存"
echo "[purge] 手动 Purge: Cloudflare Dashboard → mygoal.tech → Caching → Purge Cache"
echo "[purge] 或: export CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ZONE_ID=... && $PURGE"
exit 0
