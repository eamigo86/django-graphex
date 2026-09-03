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
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402
from channels.sessions import SessionMiddlewareStack  # noqa: E402
from django.urls import path  # noqa: E402


def build_websocket_application() -> AllowedHostsOriginValidator:
    """Build the routed WebSocket app, Origin-validated and session-authenticated.

    Built by a function so tests and deployments can construct the stack after
    Django loads their explicit ALLOWED_HOSTS values. The playground deliberately
    ships no wildcard: otherwise the outer validator would accept every Origin.

    Layers, outermost first:

    - "AllowedHostsOriginValidator" checks the handshake's Origin against
      ALLOWED_HOSTS. This is NOT optional on a session-authenticated socket: a
      WebSocket handshake is an ordinary HTTP request that carries cookies and
      is not subject to CORS, so without it any other site can open a socket as
      your logged-in visitor and read every subscription they are entitled to.
      It is the WebSocket counterpart of REQUIRE_CSRF_HEADER, which guards the
      HTTP side but never sees this endpoint.
    - "SessionMiddlewareStack" populates scope["session"], and
      "AuthMiddlewareStack" populates scope["user"] from it. The subscription
      authenticates at the connection scope (connection_init is the auth
      boundary), so the authorize/scope hooks read scope["user"] -- the
      standard Channels pattern, and what the private noteSubscription flow
      relies on.

    Returns:
        app: The Origin-validated, session-authenticated WebSocket application.
    """
    return AllowedHostsOriginValidator(
        SessionMiddlewareStack(
            AuthMiddlewareStack(
                URLRouter([path("ws/graphql/", AppWSConsumer.as_asgi())])
            )
        )
    )


application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": build_websocket_application(),
    }
)
