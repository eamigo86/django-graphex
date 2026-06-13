"""ASGI entrypoint: HTTP via Django, WebSocket via the subscription consumer."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402

# Wrap the HTTP app so static files (admin CSS, /static/...) are served while
# DEBUG is True -- daphne does not serve them on its own like `runserver` does.
django_asgi_app = ASGIStaticFilesHandler(get_asgi_application())

from blog.consumers import AppDemultiplexer  # noqa: E402
from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.sessions import SessionMiddlewareStack  # noqa: E402
from django.urls import path  # noqa: E402

# SessionMiddlewareStack populates scope["session"] so the channel ownership
# guard can compare the WebSocket session key against the HTTP session key.
# Without it scope["session"] is None, the registry stores owner="" for every
# connection, and the private noteSubscription flow (which has a real session
# key on the HTTP side) is always rejected.
#
# AuthMiddlewareStack additionally populates scope["user"] from the session,
# which allows any consumer code that checks request.user to work correctly
# (not strictly required by the current playground, but is the standard
# Channels pattern and costs nothing extra when sessions are already enabled).
_ws_app = SessionMiddlewareStack(
    AuthMiddlewareStack(URLRouter([path("ws/graphql/", AppDemultiplexer.as_asgi())]))
)

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": _ws_app,
    }
)
