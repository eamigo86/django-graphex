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
    """Lazily re-export the graphene-backed subscription class bases (PEP 562).

    S8g (graphene-removal): ``ActionSubscriptionEnum`` (graphene ``Enum``) and
    ``SubscriptionField`` (graphene ``Field``) are built lazily in
    ``.subscription`` via a module-level ``__getattr__`` so a bare ``import``
    never pulls graphene. Re-exporting them EAGERLY here (``from .subscription
    import ActionSubscriptionEnum, SubscriptionField``) would fire that
    ``__getattr__`` at package import time, defeating the lazy seam. So the
    package re-export is also deferred: ``subscriptions.ActionSubscriptionEnum``
    / ``subscriptions.SubscriptionField`` resolve to the lazily built class on
    first access, identity-stable with the ``.subscription`` cache.
    """
    if name in ("ActionSubscriptionEnum", "SubscriptionField"):
        from . import subscription

        return getattr(subscription, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
