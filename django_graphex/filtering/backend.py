"""The filter backend seam: model -> filter input type, value -> queryset.

Mirrors the ``SerializerBackend`` pattern (``backends.py``) so the filtering
layer is swappable and isolated. The package ships a single
:class:`NativeFilterBackend` built on Django's ORM lookups and ``Q`` objects;
:func:`resolve_filter_backend` is the factory seam.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .schema import build_filter_input_type
from .translate import to_q

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet

    from django_graphex.registry import Registry

__all__ = ("FilterBackend", "NativeFilterBackend", "resolve_filter_backend")


class FilterBackend:
    """Translate a model's filter declaration into schema + queryset effects."""

    def build_input_type(
        self,
        model: type[Model],
        filter_fields: Any,
        registry: Registry | None = None,
        custom_filters: list | None = None,
    ) -> Any:
        """Return the GraphQL input type for a model's filter declaration.

        Args:
            model: The Django model to build a filter input for.
            filter_fields: The ``Meta.filter_fields`` declaration.
            registry: The registry providing related types and choices enums.
            custom_filters: Optional list of ``(arg_name, method, metadata)``
                triples from ``@filter_field``-decorated methods.

        Returns:
            A graphene ``InputObjectType`` subclass, or ``None`` when no
            filterable fields are declared.
        """
        raise NotImplementedError

    def apply(self, queryset: QuerySet, value: Any) -> QuerySet:
        """Apply a filter input value to a queryset.

        Args:
            queryset: The base queryset to filter.
            value: The filter input value (an ``InputObjectTypeContainer``), or
                ``None`` / empty for a no-op.

        Returns:
            The filtered queryset.
        """
        raise NotImplementedError


class NativeFilterBackend(FilterBackend):
    """Native ``Q``-based filtering over Django's ORM lookups."""

    def build_input_type(
        self,
        model: type[Model],
        filter_fields: Any,
        registry: Registry | None = None,
        custom_filters: list | None = None,
    ) -> Any:
        """Build the recursive ``<Model>FilterInput`` type (memoized).

        Args:
            model: The Django model to build a filter input for.
            filter_fields: The ``Meta.filter_fields`` declaration.
            registry: The registry providing related types and choices enums.
            custom_filters: Optional list of ``(arg_name, method, metadata)``
                triples from ``@filter_field``-decorated methods.

        Returns:
            A graphene ``InputObjectType`` subclass, or ``None`` when no
            filterable fields are declared.
        """
        return build_filter_input_type(model, filter_fields, registry, custom_filters=custom_filters)

    def apply(self, queryset: QuerySet, value: Any) -> QuerySet:
        """Filter ``queryset`` with the ``Q`` translated from ``value``.

        Applies ``.distinct()`` when a to-many relation was traversed (to
        de-duplicate join fan-out). An empty/absent value is a no-op.

        Args:
            queryset: The base queryset to filter.
            value: The filter input value, or ``None`` / empty for a no-op.

        Returns:
            The filtered (and possibly de-duplicated) queryset.
        """
        if not value:
            return queryset
        q, touched_to_many = to_q(value, queryset.model)
        if not q:
            return queryset
        queryset = queryset.filter(q)
        if touched_to_many:
            queryset = queryset.distinct()
        return queryset


def resolve_filter_backend() -> FilterBackend:
    """Return the configured filter backend (the seam factory).

    Returns:
        A :class:`FilterBackend` instance (the native backend).
    """
    return NativeFilterBackend()
