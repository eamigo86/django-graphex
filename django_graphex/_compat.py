"""Vendored helpers that used to come from ``graphene_django``.

``graphene-django`` is unmaintained; the package only ever used a handful of its
edge helpers (the rest of the integration -- type generation, the converter --
is ours). These small, self-contained reimplementations let us depend on
``graphene`` (core) directly and drop the ``graphene-django`` dependency without
any change to the public API.
"""

from __future__ import annotations

import inspect
import re
from typing import Any

import graphene
from django.db.models import JSONField, Manager, Model
from text_unidecode import unidecode

__all__ = (
    "ErrorType",
    "is_valid_django_model",
    "maybe_queryset",
    "to_const",
    "ArrayField",
    "HStoreField",
    "JSONField",
    "RangeField",
)


class ErrorType(graphene.ObjectType):
    """A field-scoped validation error: ``{field, messages}``.

    Mirrors ``graphene_django.types.ErrorType`` (the only part of it we use), so
    mutation error payloads are unchanged.
    """

    field = graphene.String(required=True)
    messages = graphene.List(graphene.NonNull(graphene.String), required=True)


def is_valid_django_model(model: Any) -> bool:
    """Return whether ``model`` is a Django model class.

    Args:
        model: The object to test.

    Returns:
        True if ``model`` is a subclass of ``django.db.models.Model``.
    """
    return inspect.isclass(model) and issubclass(model, Model)


def maybe_queryset(value: Any) -> Any:
    """Return a queryset for a manager, or the value unchanged.

    Args:
        value: A model manager or any other value.

    Returns:
        ``value.get_queryset()`` when ``value`` is a ``Manager``, else ``value``.
    """
    if isinstance(value, Manager):
        value = value.get_queryset()
    return value


def to_const(string: str) -> str:
    """Convert a label to an uppercase GraphQL enum constant name.

    Args:
        string: The human-readable label (e.g. a model choice display).

    Returns:
        An uppercase, underscore-separated constant safe for an enum name.
    """
    return re.sub(r"[\W|^]+", "_", unidecode(string)).upper()


class _MissingType:
    """Placeholder for a Postgres field type that is unavailable."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Accept and ignore any arguments."""


try:
    # Postgres-only fields; available when psycopg is installed.
    from django.contrib.postgres.fields import (  # type: ignore[assignment]
        ArrayField,
        HStoreField,
        RangeField,
    )
except ImportError:  # pragma: no cover
    HStoreField = RangeField = _MissingType  # type: ignore[misc,assignment]

    class ArrayField(JSONField):  # type: ignore[no-redef]
        """Test/no-postgres stand-in for ``ArrayField`` (backed by JSON)."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """Capture the base field positional argument, like ArrayField."""
            if args:
                self.base_field = args[0]
            super().__init__(**kwargs)
