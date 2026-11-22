#!/bin/bash
# On the app server: copy the website (the repo's site/ folder) to /srv/nimbus-site, where Caddy serves it.
# Called by app_domain.sh and app_update.sh. Swaps the folder in one step so visitors never see half a site.
set -euo pipefail
REPO=/opt/nimbus/src
SRC=$REPO/site
[ -d "$SRC" ] || { echo "no site/ folder in the repo"; exit 0; }
# Refuse to publish a Methodology page that no longer matches the rules file, or any banned marketing phrase.
# Exit 1 from either script is a real finding; any other non-zero code means the check itself could not run.
gate() {  # gate <what failed on exit 1> <command...>
  local why=$1 rc=0; shift
  "$@" || rc=$?
  if [ "$rc" -eq 1 ]; then echo "NOT PUBLISHED: $why"; exit 1; fi
  if [ "$rc" -ne 0 ]; then echo "NOT PUBLISHED: the guard could not run (${2##*/} exited $rc)"; exit "$rc"; fi
}
gate "site/methodology is out of date with the rules" python3 "$REPO/scripts/build_methodology.py" --check
gate "the copy guard found banned phrases (see above)" python3 "$REPO/scripts/copy_guard.py" "$SRC"
rm -rf /srv/nimbus-site.new
cp -r "$SRC" /srv/nimbus-site.new
chown -R root:root /srv/nimbus-site.new && chmod -R a+rX,go-w /srv/nimbus-site.new
[ -d /srv/nimbus-site ] && mv /srv/nimbus-site /srv/nimbus-site.old
mv /srv/nimbus-site.new /srv/nimbus-site
rm -rf /srv/nimbus-site.old
echo "website published from $(runuser -u nimbus -- git -C /opt/nimbus/src log --oneline -1)"
