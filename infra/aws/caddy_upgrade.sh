#!/bin/bash
# On the app server: install or upgrade Caddy to the pinned version (checksum verified), then restart it.
# Called by app_update.sh on every deploy, so the server never stays on an old release. Safe to run again.
set -euo pipefail
V=${CADDY_VERSION:-2.11.9}
have=$(/usr/local/bin/caddy version 2>/dev/null | awk '{print $1}' | tr -d v || true)
if [ "$have" = "$V" ]; then echo "caddy $V already installed"; exit 0; fi
tmp=$(mktemp -d); cd "$tmp"
curl -fsSLO "https://github.com/caddyserver/caddy/releases/download/v$V/caddy_${V}_linux_arm64.tar.gz"
curl -fsSLO "https://github.com/caddyserver/caddy/releases/download/v$V/caddy_${V}_checksums.txt"
grep " caddy_${V}_linux_arm64.tar.gz\$" "caddy_${V}_checksums.txt" | sha512sum -c -
tar -xzf "caddy_${V}_linux_arm64.tar.gz" caddy
./caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile
install -m 755 caddy /usr/local/bin/caddy
cd /; rm -rf "$tmp"
systemctl restart caddy; sleep 2; systemctl is-active caddy
echo "caddy upgraded from ${have:-none} to $V"
