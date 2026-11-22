#!/bin/bash
# Serve the website and the app at their real names once DNS points at the server (dns.sh). Run in AWS CloudShell:
#   bash app_domain.sh
#
#   nimbusindex.com          the public website (the repo's site/ folder, copied to /srv/nimbus-site)
#   www.nimbusindex.com      -> redirects to nimbusindex.com
#   app.nimbusindex.com      the sign-in app
#   getnimbusindex.com, www  -> redirect to nimbusindex.com (that domain is for sending email; its mail records stay)
# The old sslip.io address keeps working for the app, so nothing breaks while DNS spreads. Caddy gets each name's
# HTTPS certificate on its own as soon as that name points here. Safe to run again.
set -euo pipefail
SITE=${SITE:-nimbusindex.com}
APP=${APP:-app.$SITE}
ALIAS=${ALIAS:-getnimbusindex.com}
for d in "$SITE" "$APP" "$ALIAS"; do [[ "$d" =~ ^[a-z0-9.-]+\.[a-z]{2,}$ ]] || { echo "Bad domain: $d"; exit 1; }; done
source <(curl -sL "${HELPER_URL:-https://raw.githubusercontent.com/ateeqkhan11/outage-telemetry/main/infra/aws/_ssm_run.sh}")
ssm_run "set -e
OLD=\$(grep -o '[0-9-]*\.sslip\.io' /etc/caddy/Caddyfile | head -1)
bash /opt/nimbus/src/infra/aws/publish_site.sh
cat > /etc/caddy/Caddyfile.new <<CADDY
(headers) {
	header {
		Strict-Transport-Security \"max-age=31536000\"
		X-Content-Type-Options nosniff
		Referrer-Policy strict-origin-when-cross-origin
		X-Frame-Options DENY
	}
}
$APP, \$OLD {
	import headers
	encode gzip
	reverse_proxy 127.0.0.1:8000
}
$SITE {
	import headers
	encode gzip
	root * /srv/nimbus-site
	file_server
}
www.$SITE, $ALIAS, www.$ALIAS {
	redir https://$SITE{uri} permanent
}
CADDY
sed -i 's#^NIMBUS_BASE_URL=.*#NIMBUS_BASE_URL=https://$APP#' /etc/nimbus/env
/usr/local/bin/caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile.new
chmod 755 /etc/caddy && chmod 644 /etc/caddy/Caddyfile.new && mv /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile
systemctl reset-failed caddy || true; systemctl restart caddy; systemctl restart nimbus-app
echo; cat /etc/caddy/Caddyfile"
echo
echo "Website: https://$SITE   App: https://$APP   (each works once its DNS points at this server)"
