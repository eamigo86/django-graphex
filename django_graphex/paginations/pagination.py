"""Pagination classes for GraphQL queries.

This module provides various pagination implementations that can be used
with GraphQL fields to paginate query results.
"""

from __future__ import annotations

import base64
import binascii
import os
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from graphql import GraphQLError

from django_graphex.base_types import DjangoListObjectBase
from django_graphex.paginations.utils import (
    _get_count,
    _positive_int,
)
from django_graphex.settings import graphql_api_settings

#: True when GDX_BACKEND=native is set in the process environment.
#: Read once at import time (the flag is process-global and set before import).
_NATIVE_BACKEND: bool = os.environ.get("GDX_BACKEND", "graphene") == "native"

#: Final fallback page size for cursor pagination when neither a default nor a
#: maximum is configured (the keyset always needs a concrete size).
DEFAULT_CURSOR_PAGE_SIZE = 20

# Separator used by Django ORM for relation traversal (e.g. "author__name").
_LOOKUP_SEP = "__"

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from graphene import Field
    from graphql import GraphQLResolveInfo

    from django_graphex.paginations.utils import GenericPaginationField

__all__ = (
    "LimitOffsetGraphqlPagination",
    "PageGraphqlPagination",
    "CursorGraphqlPagination",
    "NATIVE_CURSOR_PAGE_INFO",
)


# --------------------------------------------------------------------------- #
# Lazy graphene accessor (S8f graphene-removal)                                #
# --------------------------------------------------------------------------- #
# ``pagination.py`` no longer imports graphene at the MODULE top level — that
# ``from graphene import Boolean, Field, Int, ObjectType, String`` blocked the
# graphene uninstall (S8i). The graphene constructs are STILL genuinely consumed
# by the native-default test contract:
#
# * the ``to_graphql_fields(native=False)`` else-branches build graphene
#   ``Int`` / ``String`` scalar args (forced graphene-shape by
#   ``_graphene_paginator_args`` for the graphene ``GenericPaginationField``);
# * ``CursorPageInfo`` is a graphene ``ObjectType`` (built lazily via module
#   ``__getattr__`` below) wrapped by ``get_page_info_field`` in a graphene
#   ``Field`` with ``Int`` / ``String`` args.
#
# These are exercised by tests/test_paginations.py, tests/test_pagination_edges.py
# and tests/test_pagination_internals.py on the native default. The constructs
# stay graphene and byte-identical; only the top-level import moves to a lazy,
# cached accessor. The NATIVE machinery (NATIVE_CURSOR_PAGE_INFO,
# get_native_page_info_field, to_graphql_fields(native=True)) is graphql-core and
# untouched.
_GRAPHENE: Any = None


def _g() -> Any:
    """Return the lazily imported, cached ``graphene`` module.

    The first call imports graphene (still installed until S8i) and caches it;
    subsequent calls reuse the cache. This keeps every graphene pagination
    construct byte-identical while removing the uninstall-blocking top-level
    ``from graphene import ...``.
    """
    global _GRAPHENE
    if _GRAPHENE is None:
        import graphene  # noqa: PLC0415

        _GRAPHENE = graphene
    return _GRAPHENE

# ---------------------------------------------------------------------------
# B7 — Native CursorPageInfo (GDX_BACKEND=native only)
# ---------------------------------------------------------------------------
# Built eagerly at module import time (only runs when GDX_BACKEND=native so the
# graphql-core types are always available). The graphene CursorPageInfo class
# below stays on the graphene path; this singleton is used by the native
# compiler when assembling the CursorGraphqlPagination pageInfo field (WU6a).

if _NATIVE_BACKEND:
    from graphql import (
        GraphQLBoolean,
        GraphQLField,
        GraphQLNonNull,
        GraphQLObjectType,
        GraphQLString,
    )

    from django_graphex.native.bridge import GdxPayload
    from django_graphex.native.ir import GdxMeta

    NATIVE_CURSOR_PAGE_INFO: Any = GraphQLObjectType(
        name="CursorPageInfo",
        fields=lambda: {
            "hasNextPage": GraphQLField(
                GraphQLNonNull(GraphQLBoolean),
                description=(
                    "True if at least one row exists after the last row of the page."
                ),
            ),
            "hasPreviousPage": GraphQLField(
                GraphQLNonNull(GraphQLBoolean),
                description=(
                    "True if at least one row exists before the first row of the page."
                ),
            ),
            "startCursor": GraphQLField(
                GraphQLString,
                description=(
                    "Cursor of the first row of the page (null if the page is empty)."
                ),
            ),
            "endCursor": GraphQLField(
                GraphQLString,
                description=(
                    "Cursor of the last row of the page (null if the page is empty)."
                ),
            ),
        },
        description="Forward keyset pagination metadata.",
        extensions={
            "gdx": GdxPayload(
                GdxMeta(
                    name="CursorPageInfo",
                )
            )
        },
    )
else:
    # Graphene path: NATIVE_CURSOR_PAGE_INFO is not used; set to None so import
    # sites that guard on _NATIVE_BACKEND don't need a separate check.
    NATIVE_CURSOR_PAGE_INFO = None


def _sort_key(value: Any) -> tuple[bool, Any]:
    """Build a sort key tolerant of "None" values.

    Sorts "None" first and avoids "None < x" comparison errors.

    Args:
        value: The value to derive a sort key from.

    Returns:
        A tuple ordering "None" values before other values.
    """
    return (value is None, value if value is not None else 0)


def _validate_ordering_terms(model: Any, ordering: str | list[str]) -> None:
    """Validate each ordering term against the model's concrete attnames.

    Rejects:
    - Terms whose root field (before '__') is not a concrete attname on the model.
      This covers invalid fields, relation-spanning lookups, and hidden/non-exposed
      columns (e.g. 'password', 'is_superuser').
    - Any term that contains '__' (relation traversal), regardless of root validity,
      to prevent arbitrary join-chain DoS.

    Only the concrete attnames from ``model._meta.concrete_fields`` are allowed,
    matching the pattern already used in ``django_graphex/fields.py:727``.

    Args:
        model: The Django model class whose ``_meta.concrete_fields`` defines the
            allowlist.
        ordering: A comma-separated ordering string or a list of ordering terms.
            Leading ``-``/``+`` direction prefixes are stripped before comparison.

    Raises:
        GraphQLError: When any term is invalid, contains a relation separator, or
            references a non-concrete/non-exposed column.
    """
    if not ordering:
        return

    concrete_attnames: set[str] = {
        f.attname
        for f in model._meta.concrete_fields  # type: ignore[union-attr]
    }

    if isinstance(ordering, str):
        terms = [t for t in ordering.replace(" ", "").split(",") if t]
    else:
        terms = [t for t in ordering if t]

    # Build the set of pk aliases: 'pk' plus the primary key's real attname and
    # field name (e.g. 'id' / 'id' for an auto pk, 'slug' / 'slug' for a custom
    # CharField pk).  These are fully supported by Django's ORM via order_by('pk')
    # and must not be rejected even though 'pk' itself is not in concrete_attnames.
    pk_aliases: set[str] = {"pk"}
    if model._meta.pk is not None:  # type: ignore[union-attr]
        pk_aliases.add(model._meta.pk.attname)  # type: ignore[union-attr]
        pk_aliases.add(model._meta.pk.name)  # type: ignore[union-attr]

    for term in terms:
        # Strip direction prefix
        bare = term.lstrip("-+")
        # Allow Django's native pk alias and the primary key's attname/name.
        # These resolve to the pk column via the ORM and are always valid.
        if bare in pk_aliases:
            continue
        # Reject any relation-spanning path (contains lookup separator)
        if _LOOKUP_SEP in bare:
            raise GraphQLError(
                f"Invalid ordering field: '{bare}'. "
                "Relation-spanning ordering is not permitted."
            )
        # Reject anything not in the concrete attname allowlist
        if bare not in concrete_attnames:
            raise GraphQLError(f"Invalid ordering field: '{bare}'.")


def _inmemory_order(items: Iterable[Any], ordering: Any) -> list[Any]:
    """Order an in-memory sequence of model instances by an ordering string.

    Used when a nested list resolves from the "prefetch_related" cache (a Python
    list) instead of a queryset. Supports a comma-separated list of direct fields
    with an optional leading "-" for descending; unknown or related lookups are
    ignored (treated as "None").

    Args:
        items: The model instances to order.
        ordering: A comma-separated ordering string or iterable of terms.

    Returns:
        A new list of the items ordered by the given ordering.
    """
    if not ordering:
        return list(items)
    if isinstance(ordering, str):
        terms = [t for t in ordering.replace(" ", "").split(",") if t]
    else:
        terms = [t for t in ordering if t]

    ordered = list(items)
    for term in reversed(terms):  # last key first -> stable multi-key sort
        reverse = term.startswith("-")
        field = term.lstrip("+-")
        ordered.sort(
            key=lambda obj, f=field: _sort_key(getattr(obj, f, None)),
            reverse=reverse,
        )
    return ordered


# *********************************************** #
# ************ PAGINATION ClASSES *************** #
# *********************************************** #
class BaseDjangoGraphqlPagination:
    """Base class for all Django GraphQL pagination implementations."""

    __name__ = None

    def _resolve_page_size(
        self,
        requested: Any,
        default: int | None,
        maximum: int | None,
    ) -> int | None:
        """Return the effective page size, with ``maximum`` as a hard ceiling.

        Resolution order is ``requested`` -> ``default`` -> ``maximum``; the
        result is always clamped at ``maximum`` when one is set. This makes a
        configured maximum a real ceiling even when the client omits the
        page-size argument (it falls back to the maximum instead of returning an
        unbounded queryset). ``None`` is returned only when ``requested``,
        ``default`` and ``maximum`` are all unset -- i.e. no pagination is
        configured, preserving the historical "return everything" behavior.

        Args:
            requested: The page size the client asked for (may be ``None``).
            default: The configured default page size (may be ``None``).
            maximum: The configured maximum page size (may be ``None``).

        Returns:
            The effective, clamped page size, or ``None`` when unbounded.

        Raises:
            ValueError: If the resolved size is zero or negative.
        """
        value = requested if requested is not None else default
        if value is None:
            value = maximum
        if value is None:
            return None
        value = _positive_int(value, strict=True)
        return min(value, maximum) if maximum is not None else value

    def get_pagination_field(self, type: Any) -> GenericPaginationField:
        """Get a pagination field for the given GraphQL type.

        Args:
            type: The GraphQL type to paginate.

        Returns:
            A pagination field bound to this paginator instance.
        """
        # Lazy import: GenericPaginationField is a graphene Field subclass built
        # on first access (S8f), so importing it here keeps the module top level
        # graphene-free.
        from django_graphex.paginations.utils import (  # noqa: PLC0415
            GenericPaginationField,
        )

        return GenericPaginationField(type, paginator_instance=self)

    def get_page_info_field(self, type: Any) -> Field | None:
        """Return a "pageInfo" field for this paginator, or "None".

        Paginators that do not expose pagination metadata (limit/offset, page)
        return "None" so their list types gain no "pageInfo" field.

        Args:
            type: The GraphQL list type the field belongs to.

        Returns:
            The "pageInfo" field, or "None" when no metadata is exposed.
        """
        return None

    def to_graphql_fields(self, *, native: bool | None = None) -> dict[str, Any]:
        """Convert pagination parameters to GraphQL field arguments.

        Args:
            native: When ``True`` return graphql-core ``GraphQLArgument``
                instances; when ``False`` return graphene scalar instances.
                Defaults to the process backend flag (``_NATIVE_BACKEND``) so
                existing callers keep their behavior. The graphene
                ``GenericPaginationField`` passes ``native=False`` so a
                graphene-built schema running in a native process still gets
                sortable graphene args.

        Returns:
            A mapping of argument names to GraphQL field definitions.

        Raises:
            NotImplementedError: Always, since child classes must implement it.
        """
        raise NotImplementedError(
            "to_graphql_field() function must be implemented into child classes."
        )

    def get_native_page_info_field(self, node_type: Any) -> Any:
        """Return a native (graphql-core) ``pageInfo`` field, or ``None``.

        The base implementation returns ``None`` (no pagination metadata),
        mirroring :meth:`get_page_info_field`. Cursor pagination overrides this
        to expose a native ``CursorPageInfo`` field under ``GDX_BACKEND=native``.

        Args:
            node_type: The compiled element (node) ``GraphQLObjectType`` the
                list paginates.

        Returns:
            A ``graphql.GraphQLField``, or ``None`` when no metadata is exposed.
        """
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert pagination configuration to a dictionary.

        Returns:
            A mapping describing the pagination configuration.

        Raises:
            NotImplementedError: Always, since child classes must implement it.
        """
        raise NotImplementedError(
            "to_dict() function must be implemented into child classes."
        )

    def paginate_queryset(self, qs: Any, **kwargs: Any) -> Any:
        """Paginate the given queryset with the provided parameters.

        Args:
            qs: The queryset or list to paginate.
            **kwargs: The pagination arguments from the query.

        Returns:
            The paginated results.

        Raises:
            NotImplementedError: Always, since child classes must implement it.
        """
        raise NotImplementedError(
            "paginate_queryset() function must be implemented into child classes."
        )

    def prefetch_window_slice(self, **kwargs: Any) -> tuple[int, int, Any] | None:
        """Return the (offset, limit, ordering) tuple for DB-side window slicing.

        The base implementation always returns ``None``, signalling that this
        paginator does not support DB-side window slicing and the caller should
        fall back to the standard in-memory path.

        Subclasses that can derive (offset, limit, ordering) from ``**kwargs``
        without needing the total row count at build time SHOULD override this
        method and return the resolved triple. They MUST return ``None``
        whenever the slice cannot be determined without a count (e.g. negative
        page number) or the paginator is unbounded.

        Args:
            **kwargs: The pagination arguments as extracted from the GraphQL
                query (same names the paginator uses in ``paginate_queryset``).

        Returns:
            A ``(offset, limit, ordering)`` tuple, or ``None`` to fall back to
            the in-memory path.
        """
        return None

    def prefetch_window_slice_ordering_check(
        self, model: Any, ordering: str | list[str]
    ) -> None:
        """Validate ordering terms for a given model before DB-side window slicing.

        Delegates to :func:`_validate_ordering_terms`.  Exposed as a method so
        tests and callers can exercise the guard without constructing a queryset.

        Args:
            model: The Django model class to validate against.
            ordering: A comma-separated ordering string or a list of ordering terms.

        Raises:
            GraphQLError: When any term is invalid or relation-spanning.
        """
        _validate_ordering_terms(model, ordering)


class LimitOffsetGraphqlPagination(BaseDjangoGraphqlPagination):
    """Pagination implementation using limit and offset parameters."""

    __name__ = "LimitOffsetPaginator"

    def __init__(
        self,
        default_limit: int = graphql_api_settings.DEFAULT_PAGE_SIZE,
        max_limit: int = graphql_api_settings.MAX_PAGE_SIZE,
        ordering: str = "",
        limit_query_param: str = "limit",
        offset_query_param: str = "offset",
        ordering_param: str = "ordering",
    ) -> None:
        """Initialize limit/offset pagination with configuration parameters.

        Args:
            default_limit: The limit to use when the client provides none.
            max_limit: The maximum allowable limit the client may request.
            ordering: The default ordering applied to lists of objects.
            limit_query_param: The name of the "limit" query parameter.
            offset_query_param: The name of the "offset" query parameter.
            ordering_param: The name of the "ordering" query parameter.
        """
        # A numeric value indicating the limit to use if one is not provided by the client in a query parameter.
        self.default_limit = default_limit

        # If set this is a numeric value indicating the maximum allowable limit that may be requested by the client.
        self.max_limit = max_limit

        # Default ordering value: ""
        self.ordering = ordering

        # A string value indicating the name of the "limit" query parameter.
        self.limit_query_param = limit_query_param

        # A string value indicating the name of the "offset" query parameter.
        self.offset_query_param = offset_query_param

        # A string or tuple/list of strings that indicates the default ordering when obtaining lists of objects.
        # Uses Django order_by syntax
        self.ordering_param = ordering_param

    def to_dict(self) -> dict[str, Any]:
        """Convert limit/offset pagination configuration to a dictionary.

        Returns:
            A mapping describing the limit/offset pagination configuration.
        """
        return {
            "limit_query_param": self.limit_query_param,
            "default_limit": self.default_limit,
            "max_limit": self.max_limit,
            "offset_query_param": self.offset_query_param,
            "ordering_param": self.ordering_param,
            "ordering": self.ordering,
        }

    def to_graphql_fields(self, *, native: bool | None = None) -> dict[str, Any]:
        """Convert limit/offset parameters to GraphQL field arguments.

        Under the native path returns ``{name: GraphQLArgument}`` instances
        so the native compiler can embed them directly as field args.
        Under the graphene path returns graphene scalar instances (unchanged).

        Args:
            native: Force the arg flavour (native graphql-core vs graphene
                scalars). Defaults to the process backend flag.

        Returns:
            A mapping of argument names to GraphQL field definitions.
        """
        if native is None:
            native = _NATIVE_BACKEND
        if native:
            from graphql import GraphQLArgument, GraphQLInt, GraphQLString

            return {
                self.limit_query_param: GraphQLArgument(
                    GraphQLInt,
                    default_value=self.default_limit,
                    description=(
                        "Number of results to return per page. Default "
                        "'default_limit': {}, and 'max_limit': {}".format(
                            self.default_limit, self.max_limit
                        )
                    ),
                ),
                self.offset_query_param: GraphQLArgument(
                    GraphQLInt,
                    description=(
                        "The initial index from which to return the results. Default: 0"
                    ),
                ),
                self.ordering_param: GraphQLArgument(
                    GraphQLString,
                    description=(
                        "A string or comma delimited string value that indicates the "
                        "default ordering when obtaining lists of objects."
                    ),
                ),
            }
        graphene = _g()
        return {
            self.limit_query_param: graphene.Int(
                default_value=self.default_limit,
                description="Number of results to return per page. Default "
                "'default_limit': {}, and 'max_limit': {}".format(
                    self.default_limit, self.max_limit
                ),
            ),
            self.offset_query_param: graphene.Int(
                description="The initial index from which to return the results. Default: 0"
            ),
            self.ordering_param: graphene.String(
                description="A string or comma delimited string value that indicates the "
                "default ordering when obtaining lists of objects."
            ),
        }

    def paginate_queryset(self, qs: Any, **kwargs: Any) -> Any:
        """Paginate a queryset or an in-memory list using limit and offset.

        Args:
            qs: The queryset or list to paginate.
            **kwargs: The pagination arguments from the query.

        Returns:
            The paginated slice of results.
        """
        limit = self._resolve_page_size(
            kwargs.get(self.limit_query_param, None),
            self.default_limit,
            self.max_limit,
        )

        # Unbounded only when neither a default nor a max is configured.
        if limit is None:
            return qs

        order = kwargs.pop(self.ordering_param, None) or self.ordering
        offset = kwargs.get(self.offset_query_param, 0) or 0

        # Reject negative offsets before any DB or in-memory slice attempt.
        # A negative offset causes Django's QuerySet.__getitem__ to raise a
        # raw ValueError("Negative indexing is not supported") which escapes
        # the resolver as an unhandled 500. Clean GraphQLError is the project
        # standard for bad client input (see test_pagination_hardening.py).
        if offset < 0:
            raise GraphQLError(
                f"Invalid offset: {offset}. Offset must be a non-negative integer."
            )

        if not isinstance(qs, QuerySet):
            # Nested list resolved from the prefetch cache: order/slice in memory.
            # G4 ordering parity: when no explicit ordering is given and the items
            # are Django model instances, fall back to pk-ascending order so the
            # in-memory path agrees with the window path (which always emits
            # ORDER BY pk as a deterministic tiebreak).
            if not order and qs:
                meta = getattr(getattr(qs[0].__class__, "_meta", None), "pk", None)
                if meta is not None:
                    order = meta.attname
            items = _inmemory_order(qs, order) if order else list(qs)
            return items[offset : offset + abs(limit)]

        # Validate ordering terms against the queryset model's concrete attnames
        # before calling qs.order_by().  An invalid term would otherwise cause
        # Django to raise FieldError, leaking the full model field list (CWE-209).
        if order:
            _validate_ordering_terms(qs.model, order)
            if "," in order:
                order = order.strip(",").replace(" ", "").split(",")
                if len(order) > 0:
                    qs = qs.order_by(*order)
            else:
                qs = qs.order_by(order)

        return qs[offset : offset + abs(limit)]

    def prefetch_window_slice(self, **kwargs: Any) -> tuple[int, int, Any] | None:
        """Return (offset, limit, ordering) for DB-side window slicing.

        Mirrors the resolution logic of ``paginate_queryset`` exactly so that
        the window-slice math is byte-for-byte identical to the in-memory path:
        - ``limit`` is resolved via ``_resolve_page_size`` (default + clamping).
        - When resolved ``limit`` is ``None`` (unbounded), returns ``None`` so
          the caller falls back to the in-memory path.
        - ``offset`` defaults to 0.
        - ``ordering`` falls back to ``self.ordering`` when not supplied.

        Args:
            **kwargs: Pagination arguments extracted from the GraphQL query
                (same names as used by ``paginate_queryset``).

        Returns:
            ``(offset, limit, ordering)`` tuple, or ``None`` when unbounded.
        """
        limit = self._resolve_page_size(
            kwargs.get(self.limit_query_param, None),
            self.default_limit,
            self.max_limit,
        )
        if limit is None:
            return None
        offset = kwargs.get(self.offset_query_param, 0) or 0
        if offset < 0:
            raise GraphQLError(
                f"Invalid offset: {offset}. Offset must be a non-negative integer."
            )
        order = kwargs.pop(self.ordering_param, None) or self.ordering
        return (offset, abs(limit), order)


class PageGraphqlPagination(BaseDjangoGraphqlPagination):
    """Pagination implementation using page number and page size parameters."""

    __name__ = "PagePaginator"

    def __init__(
        self,
        page_size: int = graphql_api_settings.DEFAULT_PAGE_SIZE,
        page_size_query_param: str | None = None,
        max_page_size: int = graphql_api_settings.MAX_PAGE_SIZE,
        ordering: str = "",
        ordering_param: str = "ordering",
    ) -> None:
        """Initialize page-based pagination with configuration parameters.

        Args:
            page_size: The default number of results per page.
            page_size_query_param: The name of the page size query parameter,
                or "None" to disable client control of the page size.
            max_page_size: The maximum page size the client may request.
            ordering: The default ordering applied to lists of objects.
            ordering_param: The name of the "ordering" query parameter.
        """
        # Client can control the page using this query parameter.
        self.page_query_param = "page"

        # The default page size. Defaults to `None`.
        self.page_size = page_size

        # Client can control the page size using this query parameter.
        # Default is 'None'. Set to eg 'page_size' to enable usage.
        self.page_size_query_param = page_size_query_param

        # Set to an integer to limit the maximum page size the client may request.
        # Only relevant if 'page_size_query_param' has also been set.
        self.max_page_size = max_page_size

        # Default ordering value: ""
        self.ordering = ordering

        # A string or comma delimited string value that indicates the default ordering when obtaining lists of objects.
        # Uses Django order_by syntax
        self.ordering_param = ordering_param

        self.page_size_query_description = (
            "Number of results to return per page. Default 'page_size': {}".format(
                self.page_size
            )
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert page pagination configuration to a dictionary.

        Returns:
            A mapping describing the page pagination configuration.
        """
        return {
            "page_size_query_param": self.page_size_query_param,
            "page_size": self.page_size,
            "page_query_param": self.page_query_param,
            "max_page_size": self.max_page_size,
            "ordering_param": self.ordering_param,
            "ordering": self.ordering,
        }

    def to_graphql_fields(self, *, native: bool | None = None) -> dict[str, Any]:
        """Convert page pagination parameters to GraphQL field arguments.

        Under the native path returns ``{name: GraphQLArgument}`` instances.
        Under the graphene path returns graphene scalar instances (unchanged).

        Args:
            native: Force the arg flavour (native graphql-core vs graphene
                scalars). Defaults to the process backend flag.

        Returns:
            A mapping of argument names to GraphQL field definitions.
        """
        if native is None:
            native = _NATIVE_BACKEND
        if native:
            from graphql import GraphQLArgument, GraphQLInt, GraphQLString

            paginator_dict: dict[str, Any] = {
                self.page_query_param: GraphQLArgument(
                    GraphQLInt,
                    default_value=1,
                    description=(
                        "A page number within the result paginated set. Default: 1"
                    ),
                ),
                self.ordering_param: GraphQLArgument(
                    GraphQLString,
                    description=(
                        "A string or comma delimited string value that indicates the "
                        "default ordering when obtaining lists of objects."
                    ),
                ),
            }
            if self.page_size_query_param:
                paginator_dict[self.page_size_query_param] = GraphQLArgument(
                    GraphQLInt,
                    description=self.page_size_query_description,
                )
            return paginator_dict

        graphene = _g()
        paginator_dict = {
            self.page_query_param: graphene.Int(
                default_value=1,
                description="A page number within the result paginated set. Default: 1",
            ),
            self.ordering_param: graphene.String(
                description="A string or comma delimited string value that indicates the "
                "default ordering when obtaining lists of objects."
            ),
        }

        if self.page_size_query_param:
            paginator_dict.update(
                {
                    self.page_size_query_param: graphene.Int(
                        description=self.page_size_query_description
                    )
                }
            )

        return paginator_dict

    def paginate_queryset(self, qs: Any, **kwargs: Any) -> Any:
        """Paginate a queryset using page number and page size parameters.

        Args:
            qs: The queryset or list to paginate.
            **kwargs: The pagination arguments from the query.

        Returns:
            The paginated slice of results, or "None" when no page size is set.
        """
        page = kwargs.pop(self.page_query_param, 1)
        requested = (
            kwargs.get(self.page_size_query_param)
            if self.page_size_query_param
            else None
        )
        page_size = self._resolve_page_size(
            requested, self.page_size, self.max_page_size
        )

        # Use an explicit raise (not assert) so the validation survives python -O.
        # assert statements are compiled out under python -O / PYTHONOPTIMIZE=1,
        # which would silently accept page=0 and compute a negative offset slice.
        if page == 0:
            raise GraphQLError(
                "Page value for PageGraphqlPagination must be a non-zero value"
            )
        if page_size is None:
            """
            raise ValueError('Page_size value for PageGraphqlPagination must be a non-null value, you must set global'
                             ' DEFAULT_PAGE_SIZE on DJANGO_GRAPHEX dict on your settings.py or specify a '
                             'page_size_query_param value on paginations declaration to specify a custom page size '
                             'value through a query parameters')
            """
            return None

        # COUNT is only needed for negative-page (last-page) navigation.
        # For positive pages the offset is computed from page_size alone, so
        # issuing an unconditional COUNT on every request is unnecessary and
        # expensive on large tables.
        if page < 0:
            count = _get_count(qs)
            offset = max(0, int(count + page_size * page))
        else:
            offset = page_size * (page - 1)

        order = kwargs.pop(self.ordering_param, None) or self.ordering

        if not isinstance(qs, QuerySet):
            # Nested list resolved from the prefetch cache: order/slice in memory.
            # G4 ordering parity: when no explicit ordering is given and items are
            # Django model instances, fall back to pk-ascending order so the
            # in-memory path agrees with the window path.
            if not order and qs:
                meta = getattr(getattr(qs[0].__class__, "_meta", None), "pk", None)
                if meta is not None:
                    order = meta.attname
            items = _inmemory_order(qs, order) if order else list(qs)
            return items[offset : offset + page_size]

        # Validate ordering terms against the queryset model's concrete attnames
        # before calling qs.order_by() — same security guard as LimitOffset.
        if order:
            _validate_ordering_terms(qs.model, order)
            if "," in order:
                order = order.strip(",").replace(" ", "").split(",")
                if len(order) > 0:
                    qs = qs.order_by(*order)
            else:
                qs = qs.order_by(order)

        return qs[offset : offset + page_size]

    def prefetch_window_slice(self, **kwargs: Any) -> tuple[int, int, Any] | None:
        """Return (offset, page_size, ordering) for DB-side window slicing.

        Mirrors the resolution logic of ``paginate_queryset``:
        - When ``page_size`` resolves to ``None`` (unbounded), returns ``None``.
        - When ``page < 0`` (count-relative offset), returns ``None`` because
          the offset cannot be computed without the total row count at build time.
        - For ``page >= 0``, ``offset = page_size * (page - 1)``.

        Args:
            **kwargs: Pagination arguments extracted from the GraphQL query
                (same names as used by ``paginate_queryset``).

        Returns:
            ``(offset, page_size, ordering)`` tuple, or ``None`` to fall back.
        """
        page = kwargs.pop(self.page_query_param, 1)
        requested = (
            kwargs.get(self.page_size_query_param)
            if self.page_size_query_param
            else None
        )
        page_size = self._resolve_page_size(
            requested, self.page_size, self.max_page_size
        )
        if page_size is None:
            return None
        if page <= 0:
            # page < 0: count-relative offset requires total count at build time.
            # page == 0: offset = page_size*(0-1) = negative — invalid.
            # Both cases fall back to the in-memory path.
            return None
        offset = page_size * (page - 1)
        order = kwargs.pop(self.ordering_param, None) or self.ordering
        return (offset, page_size, order)


#: Process-wide cache for the lazily built graphene ``CursorPageInfo`` class.
_CURSOR_PAGE_INFO: Any = None


def _build_cursor_page_info() -> type:
    """Build (and cache) the graphene ``CursorPageInfo`` ``ObjectType``.

    S8f (graphene-removal): ``CursorPageInfo`` subclasses graphene
    ``ObjectType``, which the ``class`` statement would evaluate at MODULE import
    time (re-introducing the uninstall-blocking top-level graphene import). The
    class is therefore built lazily here against the graphene module resolved by
    :func:`_g`, and cached so its identity is stable. The resulting graphene type
    is byte-identical to the eager definition; only the import timing moved. This
    is the GRAPHENE-path page-info type; the native compiler uses the separate
    graphql-core :data:`NATIVE_CURSOR_PAGE_INFO` singleton.
    """
    graphene = _g()

    class CursorPageInfo(graphene.ObjectType):
        """Forward keyset pagination metadata for "CursorGraphqlPagination"."""

        class Meta:
            """Meta configuration for CursorPageInfo."""

            description = "Forward keyset pagination metadata."

        has_next_page = graphene.Boolean(
            required=True,
            description=(
                "True if at least one row exists after the last row of the page."
            ),
        )
        has_previous_page = graphene.Boolean(
            required=True,
            description=(
                "True if at least one row exists before the first row of the page."
            ),
        )
        start_cursor = graphene.String(
            description=(
                "Cursor of the first row of the page (null if the page is empty)."
            )
        )
        end_cursor = graphene.String(
            description=(
                "Cursor of the last row of the page (null if the page is empty)."
            )
        )

    return CursorPageInfo


def __getattr__(name: str) -> Any:
    """Lazily resolve module-level ``CursorPageInfo`` (PEP 562).

    Accessing ``pagination.CursorPageInfo`` (import or attribute) builds the
    graphene ``ObjectType`` on first use and caches it, so a bare ``import`` of
    this module never triggers the graphene import. Any other attribute name
    raises ``AttributeError`` as usual.
    """
    if name == "CursorPageInfo":
        global _CURSOR_PAGE_INFO
        if _CURSOR_PAGE_INFO is None:
            _CURSOR_PAGE_INFO = _build_cursor_page_info()
        return _CURSOR_PAGE_INFO
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class CursorGraphqlPagination(BaseDjangoGraphqlPagination):
    """Forward keyset (cursor) pagination over a single ordering field.

    An opaque "cursor" encodes the ordering-field value of a boundary row and
    "first" controls the page size. The list type also gains a "pageInfo"
    field ("CursorPageInfo") carrying the same arguments, so clients read
    "endCursor" from the response and pass it back as the next "cursor"
    instead of building it by hand.

    The "ordering" must reference a single field (an optional leading "-"
    selects descending order); a comma-separated value uses its first field.
    """

    __name__ = "CursorPaginator"
    cursor_query_description = (
        "Opaque cursor; returns the results that come after it in the ordering."
    )
    first_query_description = "Number of results to return per page."

    def __init__(
        self,
        ordering: str = "-created",
        cursor_query_param: str = "cursor",
        first_query_param: str = "first",
        page_size: int = graphql_api_settings.DEFAULT_PAGE_SIZE,
        max_page_size: int = graphql_api_settings.MAX_PAGE_SIZE,
    ) -> None:
        """Initialize cursor-based pagination with configuration parameters.

        Args:
            ordering: The single-field ordering used for keyset pagination.
            cursor_query_param: The name of the "cursor" query parameter.
            first_query_param: The name of the "first" query parameter.
            page_size: The default number of results per page.
            max_page_size: The maximum "first" the client may request; defaults
                to the global "MAX_PAGE_SIZE".
        """
        self.ordering = ordering or "id"
        self.cursor_query_param = cursor_query_param
        self.first_query_param = first_query_param
        self.page_size = page_size
        self.max_page_size = max_page_size

    def prefetch_window_slice(self, **kwargs: Any) -> tuple[int, int, Any] | None:
        """Return None — opaque keyset cursors cannot be expressed as a window offset.

        DB-side ROW_NUMBER slicing requires a concrete (offset, limit) pair;
        cursor-based pagination uses an opaque keyset boundary which is not
        translatable to a row offset without a full table scan.  This is out of
        scope for v1 window optimisation.
        """
        # Opaque keyset; DB-side window slice is out of scope for v1.
        return None

    # -- cursor helpers -----------------------------------------------------
    @staticmethod
    def encode_cursor(value: Any) -> str:
        """Encode an ordering-field value into an opaque cursor string.

        Args:
            value: The ordering-field value to encode.

        Returns:
            The opaque cursor string for the given value.
        """
        return base64.urlsafe_b64encode(f"cursor:{value}".encode("utf-8")).decode(
            "ascii"
        )

    @staticmethod
    def decode_cursor(cursor: str) -> str:
        """Decode an opaque cursor back into its ordering-field value.

        Args:
            cursor: The opaque cursor string to decode.

        Returns:
            The decoded ordering-field value.

        Raises:
            ValueError: If the cursor is malformed or not a valid cursor.
        """
        try:
            raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            raise ValueError(f"Invalid pagination cursor: {cursor!r}")
        prefix, sep, value = raw.partition(":")
        if prefix != "cursor" or not sep:
            raise ValueError(f"Invalid pagination cursor: {cursor!r}")
        return value

    def _ordering_field(self) -> tuple[str, str, bool]:
        """Return the ordering term, field name and direction for the ordering.

        Returns:
            A tuple of the order-by term, the bare field name and whether the
            ordering is descending.
        """
        field = self.ordering.split(",")[0].strip()
        descending = field.startswith("-")
        return field, field.lstrip("+-"), descending

    def _page_size(self, **kwargs: Any) -> int:
        """Resolve the effective page size from "first" or defaults.

        Args:
            **kwargs: The pagination arguments from the query.

        Returns:
            The effective page size to apply.
        """
        page_size = self._resolve_page_size(
            kwargs.get(self.first_query_param, None),
            self.page_size,
            self.max_page_size,
        )
        return page_size or DEFAULT_CURSOR_PAGE_SIZE

    def to_dict(self) -> dict[str, Any]:
        """Convert cursor pagination configuration to a dictionary.

        Returns:
            A mapping describing the cursor pagination configuration.
        """
        return {
            "ordering": self.ordering,
            "cursor_query_param": self.cursor_query_param,
            "first_query_param": self.first_query_param,
            "page_size": self.page_size,
            "max_page_size": self.max_page_size,
        }

    def to_graphql_fields(self, *, native: bool | None = None) -> dict[str, Any]:
        """Convert cursor pagination parameters to GraphQL field arguments.

        Under the native path returns ``{name: GraphQLArgument}`` instances.
        Under the graphene path returns graphene scalar instances (unchanged).

        Args:
            native: Force the arg flavour (native graphql-core vs graphene
                scalars). Defaults to the process backend flag.

        Returns:
            A mapping of argument names to GraphQL field definitions.
        """
        if native is None:
            native = _NATIVE_BACKEND
        if native:
            from graphql import GraphQLArgument, GraphQLInt, GraphQLString

            return {
                self.first_query_param: GraphQLArgument(
                    GraphQLInt,
                    description=self.first_query_description,
                ),
                self.cursor_query_param: GraphQLArgument(
                    GraphQLString,
                    description=self.cursor_query_description,
                ),
            }
        graphene = _g()
        return {
            self.first_query_param: graphene.Int(
                description=self.first_query_description
            ),
            self.cursor_query_param: graphene.String(
                description=self.cursor_query_description
            ),
        }

    def _inmemory_cursor_start(
        self, items: Sequence[Any], field_name: str, cursor: str | None
    ) -> int:
        """Find the index of the first row after the given cursor.

        The match is performed by comparing the encoded ordering-field value.

        Args:
            items: The ordered in-memory items to scan.
            field_name: The ordering field name to read from each item.
            cursor: The cursor whose following row index is sought.

        Returns:
            The index of the first row after the cursor, or 0 when not found.
        """
        if not cursor:
            return 0
        for index, obj in enumerate(items):
            if self.encode_cursor(getattr(obj, field_name, None)) == cursor:
                return index + 1
        return 0

    def paginate_queryset(self, qs: Any, **kwargs: Any) -> Any:
        """Paginate a queryset or in-memory list by forward keyset cursor.

        Args:
            qs: The queryset or list to paginate.
            **kwargs: The pagination arguments from the query.

        Returns:
            The paginated slice of results.
        """
        order_term, field_name, descending = self._ordering_field()
        page_size = self._page_size(**kwargs)
        cursor = kwargs.get(self.cursor_query_param, None)

        if not isinstance(qs, QuerySet):
            items = _inmemory_order(qs, order_term)
            start = self._inmemory_cursor_start(items, field_name, cursor)
            return items[start : start + page_size]

        qs = qs.order_by(order_term)
        if cursor:
            # Wrap both decode_cursor and the subsequent qs.filter() because a
            # tampered cursor can fail at two points:
            #   1. decode_cursor raises ValueError for malformed base64 or bad prefix.
            #   2. qs.filter(**{field__gt: value}) raises Django ValidationError when
            #      the decoded string cannot be coerced to the field's type (e.g. a
            #      string passed to an IntegerField or DateTimeField). Either should
            #      produce a clean GraphQLError, not an unhandled HTTP 500.
            try:
                value = self.decode_cursor(cursor)
                lookup = f"{field_name}__{'lt' if descending else 'gt'}"
                qs = qs.filter(**{lookup: value})
            except (ValueError, ValidationError) as exc:
                raise GraphQLError("Invalid cursor") from exc

        return qs[:page_size]

    # -- pageInfo -----------------------------------------------------------
    def get_page_info_field(self, type: Any) -> Field:
        """Return the "pageInfo" field for a cursor-paginated list type.

        Args:
            type: The GraphQL list type the field belongs to.

        Returns:
            The "pageInfo" field exposing the cursor pagination metadata.
        """

        def resolver(
            root: Any, info: GraphQLResolveInfo, **kwargs: Any
        ) -> dict[str, Any] | None:
            """Resolve the cursor pagination metadata for the list root.

            Args:
                root: The root value passed to the resolver.
                info: The GraphQL resolve info for the current query.
                **kwargs: The pagination arguments from the query.

            Returns:
                The page info mapping, or "None" when "root" is not a list base.
            """
            if isinstance(root, DjangoListObjectBase):
                return self.get_page_info(root.results, **kwargs)
            return None

        graphene = _g()
        # Resolve the lazily built graphene CursorPageInfo via the module's
        # PEP 562 __getattr__ (bare-name lookup would NameError here since the
        # class is no longer a module-level binding).
        cursor_page_info = __getattr__("CursorPageInfo")
        return graphene.Field(
            cursor_page_info,
            args={
                self.first_query_param: graphene.Int(
                    description=self.first_query_description
                ),
                self.cursor_query_param: graphene.String(
                    description=self.cursor_query_description
                ),
            },
            resolver=resolver,
            description="Forward keyset pagination metadata.",
        )

    def get_native_page_info_field(self, node_type: Any) -> Any:
        """Return a native ``CursorPageInfo`` field with first/cursor args.

        Mirrors :meth:`get_page_info_field` for the native compiler: the field's
        type is the shared ``NATIVE_CURSOR_PAGE_INFO`` ``GraphQLObjectType`` and
        the resolver computes the page info from the ``DjangoListObjectBase``
        root (same logic as the graphene resolver).

        Args:
            node_type: The compiled element (node) ``GraphQLObjectType`` (unused;
                accepted for signature parity with the base method).

        Returns:
            A ``graphql.GraphQLField`` for the cursor ``pageInfo``.
        """
        from graphql import GraphQLArgument, GraphQLField, GraphQLInt, GraphQLString

        def _native_resolver(root: Any, info: Any, **kwargs: Any) -> Any:
            if not isinstance(root, DjangoListObjectBase):
                return None
            info_dict = self.get_page_info(root.results, **kwargs)
            # get_page_info returns snake_case keys; the native CursorPageInfo
            # fields are camelCase, so remap to the wire keys the default
            # field resolver reads (no per-field resolver on the page-info type).
            return {
                "hasNextPage": info_dict["has_next_page"],
                "hasPreviousPage": info_dict["has_previous_page"],
                "startCursor": info_dict["start_cursor"],
                "endCursor": info_dict["end_cursor"],
            }

        return GraphQLField(
            NATIVE_CURSOR_PAGE_INFO,
            args={
                self.first_query_param: GraphQLArgument(
                    GraphQLInt, description=self.first_query_description
                ),
                self.cursor_query_param: GraphQLArgument(
                    GraphQLString, description=self.cursor_query_description
                ),
            },
            resolve=_native_resolver,
            description="Forward keyset pagination metadata.",
        )

    def get_page_info(self, qs: Any, **kwargs: Any) -> dict[str, Any]:
        """Compute the "CursorPageInfo" for the page described by the arguments.

        Mirrors "paginate_queryset": orders by "ordering", applies the incoming
        cursor and limits to "first" rows, then derives the boundary cursors and
        the "hasNextPage" and "hasPreviousPage" flags.

        Args:
            qs: The queryset or list to inspect.
            **kwargs: The pagination arguments from the query.

        Returns:
            A mapping of the page info fields for the described page.
        """
        order_term, field_name, descending = self._ordering_field()
        page_size = self._page_size(**kwargs)
        cursor = kwargs.get(self.cursor_query_param, None)

        if not isinstance(qs, QuerySet):
            items = _inmemory_order(qs, order_term)
            start = self._inmemory_cursor_start(items, field_name, cursor)
            window = items[start : start + page_size]
            if not window:
                return {
                    "has_next_page": False,
                    "has_previous_page": False,
                    "start_cursor": None,
                    "end_cursor": None,
                }
            return {
                "has_next_page": (start + page_size) < len(items),
                "has_previous_page": start > 0,
                "start_cursor": self.encode_cursor(getattr(window[0], field_name)),
                "end_cursor": self.encode_cursor(getattr(window[-1], field_name)),
            }

        ordered = qs.order_by(order_term)
        page_qs = ordered
        if cursor:
            # Same guard as in paginate_queryset: a tampered cursor can fail at
            # decode_cursor (malformed base64) or at filter() (type coercion).
            try:
                value = self.decode_cursor(cursor)
                lookup = f"{field_name}__{'lt' if descending else 'gt'}"
                page_qs = page_qs.filter(**{lookup: value})
            except (ValueError, ValidationError) as exc:
                raise GraphQLError("Invalid cursor") from exc

        # Fetch one extra row to detect a following page without a COUNT.
        rows = list(page_qs[: page_size + 1])
        has_next_page = len(rows) > page_size
        rows = rows[:page_size]

        if not rows:
            return {
                "has_next_page": False,
                "has_previous_page": False,
                "start_cursor": None,
                "end_cursor": None,
            }

        start_value = getattr(rows[0], field_name)
        end_value = getattr(rows[-1], field_name)

        # Exact hasPreviousPage: is there a row strictly before the first one?
        before_lookup = f"{field_name}__{'gt' if descending else 'lt'}"
        has_previous_page = ordered.filter(**{before_lookup: start_value}).exists()

        return {
            "has_next_page": has_next_page,
            "has_previous_page": has_previous_page,
            "start_cursor": self.encode_cursor(start_value),
            "end_cursor": self.encode_cursor(end_value),
        }
