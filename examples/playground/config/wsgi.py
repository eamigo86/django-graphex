"""WSGI entrypoint (HTTP only; subscriptions need ASGI - see asgi.py)."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
