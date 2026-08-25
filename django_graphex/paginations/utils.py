"""Utility functions and classes for pagination.

This module provides utility functions for pagination validation and
a generic pagination field class for reusable pagination logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _dc_field
from typing import Any

from django.db import DatabaseError

from ..base_types import DjangoListObjectBase

# --------------------------------------------------------------------------- #
# Native pagination machinery (S-del-backend-11 — graphene backend deleted)   #
# --------------------------------------------------------------------------- #
# S-page-7 migrated the pagination CONTAINER BUILD path off graphene entirely.
# The native container is assembled by ``types._make_list_fields_thunk_for`` from
# ``to_graphql_fields(native=True)`` + ``NativePaginationField`` +
# ``get_native_page_info_field``. S-del-backend-11 deleted the last DEAD-BUT-
# DEFINED graphene construct (the graphene ``GenericPaginationField`` ``Field``
# subclass) and the lazy graphene accessor.


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

    A plain dataclass carrying "(type, paginator)" with the "list_resolver" /
    "wrap_resolve" logic extracted from the graphene "GenericPaginationField".
    The native compiler (WU6a) consumes this to wire the paginator's args +
    slicing resolver directly onto the list container's results field. Has ZERO
    graphene imports in its own logic — the slicing is delegated to
    "_paginate_list_base".

    Attributes:
        type: The element (node) type the list paginates. Stored for callers
            that need the model/node back-reference; not used by the resolver.
        paginator: The paginator instance providing "paginate_queryset".
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
        """Resolve a paginated list page from a "DjangoListObjectBase" root.

        Args:
            manager: Accepted for signature parity with the graphene field's
                bound resolver; unused (the page rows come from "root").
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the current query.
            **kwargs: The pagination arguments from the query.

        Returns:
            The paginated results, or None when "root" is not a list base.
        """
        return _paginate_list_base(self.paginator, root, **kwargs)

    def wrap_resolve(self, parent_resolver: Any) -> Any:
        """Return a resolver "(root, info, **kwargs) -> page" for graphql-core.

        graphql-core calls a field resolver as "resolve(root, info, **kwargs)"
        (no bound "self"). The returned closure ignores the parent resolver (the
        page rows come from the "DjangoListObjectBase" root produced by the
        outer list field) and slices the page.

        Args:
            parent_resolver: The default field resolver (unused).

        Returns:
            A "(root, info, **kwargs) -> page" callable.
        """

        def _resolve(root: Any, info: Any, **kwargs: Any) -> Any:
            return _paginate_list_base(self.paginator, root, **kwargs)

        # Expose the paginator on the closure so the optimizer's
        # _resolve_results_paginator can recover it (parity with the graphene
        # field's partial(self.list_resolver, ...) whose __self__ is the field).
        _resolve.paginator_instance = self.paginator  # type: ignore[attr-defined]
        return _resolve


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
    # Only ``None`` / empty-string are true passthroughs. The int ``0`` MUST fall
    # through to the strict/negative check below — the old ``if integer_string:``
    # guard treated ``0`` as falsy and early-returned it, so ``strict=True`` never
    # rejected a zero page size (silent empty page / silent default fallback).
    if integer_string is None or integer_string == "":
        return integer_string
    ret = int(integer_string)
    if ret < 0 or (ret == 0 and strict):
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
