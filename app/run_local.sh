#!/bin/sh
# Local development server on http://localhost:8080 (plain HTTP, so secure cookies are off).
cd "$(dirname "$0")"
export PYTHONPATH=.. NIMBUS_SECURE_COOKIES=0 NIMBUS_BASE_URL=http://localhost:8080
exec ../.venv/bin/gunicorn --bind 127.0.0.1:8080 --workers 2 --access-logfile - nimbus_app.wsgi:app
