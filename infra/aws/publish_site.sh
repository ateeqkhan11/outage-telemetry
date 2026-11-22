#!/bin/bash
# On the app server: copy the website (the repo's site/ folder) to /srv/nimbus-site, where Caddy serves it.
# Called by app_domain.sh and app_update.sh. Swaps the folder in one step so visitors never see half a site.
set -euo pipefail
SRC=/opt/nimbus/src/site
[ -d "$SRC" ] || { echo "no site/ folder in the repo"; exit 0; }
rm -rf /srv/nimbus-site.new
cp -r "$SRC" /srv/nimbus-site.new
chown -R root:root /srv/nimbus-site.new && chmod -R a+rX,go-w /srv/nimbus-site.new
[ -d /srv/nimbus-site ] && mv /srv/nimbus-site /srv/nimbus-site.old
mv /srv/nimbus-site.new /srv/nimbus-site
rm -rf /srv/nimbus-site.old
echo "website published from $(runuser -u nimbus -- git -C /opt/nimbus/src log --oneline -1)"
