"""ASGI entrypoint: HTTP via Django, WebSocket via the native subscription consumer."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402

# Wrap the HTTP app so static files (admin CSS, /static/...) are served while
# DEBUG is True -- daphne does not serve them on its own like `runserver` does.
django_asgi_app = ASGIStaticFilesHandler(get_asgi_application())

from blog.consumers import AppWSConsumer  # noqa: E402
from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.sessions import SessionMiddlewareStack  # noqa: E402
from django.urls import path  # noqa: E402

# SessionMiddlewareStack populates scope["session"] and AuthMiddlewareStack
# populates scope["user"] from the session. v2.0 authenticates at the WebSocket
# connection scope (connection_init is the auth boundary), so the subscription's
# authorize/scope hooks can read scope["user"] -- this is the standard Channels
# pattern and is what the private noteSubscription flow relies on.
_ws_app = SessionMiddlewareStack(
    AuthMiddlewareStack(URLRouter([path("ws/graphql/", AppWSConsumer.as_asgi())]))
)

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": _ws_app,
    }
)
