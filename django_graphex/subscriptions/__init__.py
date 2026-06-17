"""Provide GraphQL subscriptions for django-graphex.

This subpackage backs the optional "subscriptions" extra. It is intentionally
not imported by the top-level "django_graphex" package: a base install
must never import "channels". Importing this package (or wiring the consumer)
is what pulls channels in, guarded below with a friendly message when the extra
is missing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    import channels  # noqa: F401
except ImportError as exc:  # pragma: no cover - exercised by the base-install CI job
    raise ImportError(
        "GraphQL subscriptions require the 'subscriptions' extra. Install with:\n"
        '    pip install "django-graphex[subscriptions]"'
    ) from exc

from .bindings import SubscriptionBinding
from .client import SubscriptionClientView
from .subscription import Subscription

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .subscription import (  # noqa: F401
        ActionSubscriptionEnum,
        SubscriptionField,
    )

__all__ = (
    "Subscription",
    "SubscriptionField",
    "SubscriptionClientView",
    "SubscriptionBinding",
    "ActionSubscriptionEnum",
)


def __getattr__(name: str) -> Any:
    """Lazily re-export the subscription class bases (PEP 562).

    S-sub-6 (graphene-removal): ``SubscriptionField`` is now a NATIVE marker class
    defined at module level in ``.subscription`` (graphene-free), and
    ``ActionSubscriptionEnum`` (a graphene ``Enum``) is built lazily there via the
    submodule's ``__getattr__`` ONLY for the graphene-backend-only test contract.
    Re-exporting ``ActionSubscriptionEnum`` EAGERLY here (``from .subscription
    import ActionSubscriptionEnum``) would fire that ``__getattr__`` — hence import
    graphene — at package import time, defeating the lazy seam. So the package
    re-export is deferred: ``subscriptions.ActionSubscriptionEnum`` /
    ``subscriptions.SubscriptionField`` resolve on first access, identity-stable
    with the ``.subscription`` definitions.
    """
    if name in ("ActionSubscriptionEnum", "SubscriptionField"):
        from . import subscription

        return getattr(subscription, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
