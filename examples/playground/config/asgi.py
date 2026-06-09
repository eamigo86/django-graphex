"""ASGI entrypoint: HTTP via Django, WebSocket via the subscription consumer."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402

# Wrap the HTTP app so static files (admin CSS, /static/...) are served while
# DEBUG is True -- daphne does not serve them on its own like `runserver` does.
django_asgi_app = ASGIStaticFilesHandler(get_asgi_application())

from blog.consumers import AppDemultiplexer  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from django.urls import path  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": URLRouter([path("ws/graphql/", AppDemultiplexer.as_asgi())]),
    }
)
