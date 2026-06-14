"""Utility functions and classes for pagination.

This module provides utility functions for pagination validation and
a generic pagination field class for reusable pagination logic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from dataclasses import field as _dc_field
from functools import partial
from typing import TYPE_CHECKING, Any

import graphene
from django.db import DatabaseError

from ..base_types import DjangoListObjectBase

if TYPE_CHECKING:
    from graphql import GraphQLResolveInfo

#: True when GDX_BACKEND=native is set in the process environment.
_NATIVE_BACKEND: bool = os.environ.get("GDX_BACKEND", "graphene") == "native"


def _graphene_paginator_args(paginator: Any) -> dict[str, Any]:
    """Return the paginator's args as GRAPHENE scalars regardless of backend.

    The graphene ``GenericPaginationField`` must always expose graphene-typed
    args (graphene ``to_arguments()`` sorts arg values and cannot order native
    ``GraphQLArgument`` instances). Forcing ``native=False`` keeps a single
    source of truth for arg names/descriptions while guaranteeing the graphene
    shape even when the process runs under ``GDX_BACKEND=native``.

    Args:
        paginator: The paginator instance.

    Returns:
        The paginator's GraphQL args as graphene scalar instances.
    """
    return paginator.to_graphql_fields(native=False)


def _paginate_list_base(
    paginator: Any,
    root: Any,
    **kwargs: Any,
) -> Any:
    """Slice a ``DjangoListObjectBase`` page, honoring ``already_paginated``.

    Backend-neutral pagination logic shared by the graphene
    ``GenericPaginationField`` and the native ``NativePaginationField``. When the
    root rows were already DB-sliced by the window-prefetch path
    (``already_paginated=True``) they are returned in order WITHOUT a second
    slice (the no-double-pagination coordination, design C3/D6). Otherwise the
    paginator slices ``root.results`` using the supplied pagination kwargs.

    Args:
        paginator: The paginator instance providing ``paginate_queryset``.
        root: The resolver root; pagination only applies to a
            ``DjangoListObjectBase``.
        **kwargs: The pagination arguments from the query (limit/offset/page/...).

    Returns:
        The sliced results, or ``None`` when ``root`` is not a list base.
    """
    if isinstance(root, DjangoListObjectBase):
        # When already_paginated is True the rows are already the DB-sliced page
        # — do NOT re-slice, just return them in order.
        if getattr(root, "already_paginated", False):
            return root.results
        return paginator.paginate_queryset(root.results, **kwargs)
    return None


@dataclass
class NativePaginationField:
    """Backend-neutral pagination field descriptor (B8 part 1).

    A plain dataclass carrying ``(type, paginator)`` with the
    ``list_resolver`` / ``wrap_resolve`` logic extracted from the graphene
    ``GenericPaginationField``. The native compiler (WU6a) consumes this to wire
    the paginator's args + slicing resolver directly onto the list container's
    results field. Has ZERO graphene imports in its own logic — the slicing is
    delegated to :func:`_paginate_list_base`.

    Attributes:
        type: The element (node) type the list paginates. Stored for callers
            that need the model/node back-reference; not used by the resolver.
        paginator: The paginator instance providing ``paginate_queryset``.
    """

    type: Any
    paginator: Any = None
    # Back-compat alias so callers that constructed the field with the legacy
    # ``paginator_instance`` keyword keep working.
    paginator_instance: Any = _dc_field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Reconcile the ``paginator`` / ``paginator_instance`` aliases."""
        if self.paginator is None and self.paginator_instance is not None:
            self.paginator = self.paginator_instance
        if self.paginator_instance is None:
            self.paginator_instance = self.paginator

    def list_resolver(
        self,
        manager: Any,
        root: Any,
        info: Any,
        **kwargs: Any,
    ) -> Any:
        """Resolve a paginated list page from a ``DjangoListObjectBase`` root.

        Args:
            manager: Accepted for signature parity with the graphene field's
                bound resolver; unused (the page rows come from ``root``).
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the current query.
            **kwargs: The pagination arguments from the query.

        Returns:
            The paginated results, or ``None`` when ``root`` is not a list base.
        """
        return _paginate_list_base(self.paginator, root, **kwargs)

    def wrap_resolve(self, parent_resolver: Any) -> Any:
        """Return a resolver ``(root, info, **kwargs) -> page`` for graphql-core.

        graphql-core calls a field resolver as ``resolve(root, info, **kwargs)``
        (no bound ``self``). The returned closure ignores the parent resolver
        (the page rows come from the ``DjangoListObjectBase`` root produced by
        the outer list field) and slices the page.

        Args:
            parent_resolver: The default field resolver (unused).

        Returns:
            A ``(root, info, **kwargs) -> page`` callable.
        """

        def _resolve(root: Any, info: Any, **kwargs: Any) -> Any:
            return _paginate_list_base(self.paginator, root, **kwargs)

        # Expose the paginator on the closure so the optimizer's
        # _resolve_results_paginator can recover it (parity with the graphene
        # field's partial(self.list_resolver, ...) whose __self__ is the field).
        _resolve.paginator_instance = self.paginator  # type: ignore[attr-defined]
        return _resolve


class GenericPaginationField(graphene.Field):
    """Generic pagination field with the logic needed to paginate a queryset."""

    def __init__(
        self, _type: Any, paginator_instance: Any, *args: Any, **kwargs: Any
    ) -> None:
        """Initialize the generic pagination field with a paginator instance.

        Args:
            _type: The GraphQL type to paginate.
            paginator_instance: The paginator providing the pagination logic.
            *args: Additional positional arguments for the base field.
            **kwargs: Additional keyword arguments for the base field.
        """
        kwargs.setdefault("args", {})

        self.paginator_instance = paginator_instance

        # The graphene field ALWAYS exposes graphene-typed pagination args, even
        # under GDX_BACKEND=native: graphene.Field.to_arguments() sorts arg
        # values and cannot order native GraphQLArgument instances, so a
        # graphene-built schema running in a native process still needs graphene
        # scalars here (the native compiler wires native args separately onto the
        # native container's results field). _graphene_paginator_args() forces
        # the graphene scalar shape regardless of the process backend flag.
        kwargs.update(_graphene_paginator_args(paginator_instance))
        kwargs.update(
            {
                "description": "{} list, paginated by {}".format(
                    _type._meta.model.__name__, paginator_instance.__name__
                )
            }
        )

        super().__init__(graphene.List(_type), *args, **kwargs)

    @property
    def model(self) -> Any:
        """Get the Django model associated with this pagination field.

        Returns:
            The Django model class backing this field.
        """
        return self.type.of_type._meta.node._meta.model

    def list_resolver(
        self,
        manager: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Resolve a paginated list using the configured paginator instance.

        Args:
            manager: The model manager providing the base queryset.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the current query.
            **kwargs: The pagination arguments from the query.

        Returns:
            The paginated results, or "None" when "root" is not a list base.
        """
        # Backend-neutral slicing (honors already_paginated, design C3/D6).
        return _paginate_list_base(self.paginator_instance, root, **kwargs)

    def wrap_resolve(self, parent_resolver: Any) -> Any:
        """Wrap the resolver with pagination logic.

        Args:
            parent_resolver: The resolver being wrapped.

        Returns:
            A partial that resolves the paginated list.
        """
        return partial(
            self.list_resolver, self.type.of_type._meta.model._default_manager
        )


def _positive_int(
    integer_string: Any, strict: bool = False, cutoff: int | None = None
) -> Any:
    """Cast a string to a strictly positive integer.

    Args:
        integer_string: The value to cast to an integer.
        strict: If "True", treat zero as invalid.
        cutoff: An optional maximum value to clamp the result to.

    Returns:
        The parsed integer, clamped to "cutoff" when provided.

    Raises:
        ValueError: If the value is negative or zero while strict.
    """
    if integer_string:
        ret = int(integer_string)
    else:
        return integer_string
    if ret < 0 or (ret == 0 and strict):
        raise ValueError()
    if cutoff:
        return min(ret, cutoff)
    return ret


def _nonzero_int(
    integer_string: Any, strict: bool = False, cutoff: int | None = None
) -> Any:
    """Cast a string to a strictly non-zero integer.

    Args:
        integer_string: The value to cast to an integer.
        strict: If "True", treat zero as invalid.
        cutoff: An optional maximum value to clamp the result to.

    Returns:
        The parsed integer, clamped to "cutoff" when provided.

    Raises:
        ValueError: If the value is zero while strict.
    """
    if integer_string:
        ret = int(integer_string)
    else:
        return integer_string
    if ret == 0 and strict:
        raise ValueError()
    if cutoff:
        return min(ret, cutoff)
    return ret


def _get_count(queryset: Any) -> int:
    """Determine an object count, supporting either querysets or regular lists.

    Args:
        queryset: A queryset or a regular list-like object to count.

    Returns:
        The number of objects in the given queryset or list.
    """
    try:
        return queryset.count()
    except (AttributeError, TypeError, DatabaseError):
        return len(queryset)
