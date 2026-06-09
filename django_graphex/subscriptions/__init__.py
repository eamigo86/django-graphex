"""Provide GraphQL subscriptions for django-graphex.

This subpackage backs the optional "subscriptions" extra. It is intentionally
not imported by the top-level "django_graphex" package: a base install
must never import "channels". Importing this package (or wiring the consumer)
is what pulls channels in, guarded below with a friendly message when the extra
is missing.
"""

from __future__ import annotations

try:
    import channels  # noqa: F401
except ImportError as exc:  # pragma: no cover - exercised by the base-install CI job
    raise ImportError(
        "GraphQL subscriptions require the 'subscriptions' extra. Install with:\n"
        '    pip install "django-graphex[subscriptions]"'
    ) from exc

from .bindings import SubscriptionBinding
from .client import SubscriptionClientView
from .consumers import GraphqlAPIDemultiplexer
from .subscription import (
    ActionSubscriptionEnum,
    OperationSubscriptionEnum,
    Subscription,
    SubscriptionField,
)
from .views import SubscriptionGraphQLView

__all__ = (
    "Subscription",
    "SubscriptionField",
    "GraphqlAPIDemultiplexer",
    "SubscriptionGraphQLView",
    "SubscriptionClientView",
    "SubscriptionBinding",
    "ActionSubscriptionEnum",
    "OperationSubscriptionEnum",
)
