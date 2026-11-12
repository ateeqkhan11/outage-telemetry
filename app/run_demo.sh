#!/bin/sh
# Example-data copy of the app on http://localhost:8081 (six months of SIMULATED measurements; build it first with
#   PYTHONPATH=..:. ../.venv/bin/python -m nimbus_app.demo).  Every page shows an "Example data" banner.
cd "$(dirname "$0")"
D=instance/demo
export PYTHONPATH=.. NIMBUS_SECURE_COOKIES=0 NIMBUS_BASE_URL=http://localhost:8081 NIMBUS_DEMO=1 \
  NIMBUS_DB=$D/nimbus.db NIMBUS_DATA=$D/data NIMBUS_KEYS=$D/keys
exec ../.venv/bin/gunicorn --bind 127.0.0.1:8081 --workers 2 --access-logfile - nimbus_app.wsgi:app
