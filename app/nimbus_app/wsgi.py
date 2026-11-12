"""gunicorn entry point: gunicorn nimbus_app.wsgi:app"""
from . import create_app

app = create_app()
