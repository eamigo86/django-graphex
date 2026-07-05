"""Pagination classes for GraphQL queries.

This module provides various pagination implementations that can be used
with GraphQL fields to paginate query results.
"""

from __future__ import annotations

import base64
import binascii
import datetime
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from graphql import (
    GraphQLBoolean,
    GraphQLError,
    GraphQLField,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLString,
)

from django_graphex._strconv import to_snake_case
from django_graphex.base_types import DjangoListObjectBase
from django_graphex.core.bridge import GdxPayload
from django_graphex.core.ir import GdxMeta
from django_graphex.paginations.utils import (
    _get_count,
    _positive_int,
)
from django_graphex.settings import graphql_api_settings

#: Final fallback page size for cursor pagination when neither a default nor a
#: maximum is configured (the keyset always needs a concrete size).
DEFAULT_CURSOR_PAGE_SIZE = 20

# Separator used by Django ORM for relation traversal (e.g. "author__name").
_LOOKUP_SEP = "__"

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = (
    "LimitOffsetGraphqlPagination",
    "PageGraphqlPagination",
    "CursorGraphqlPagination",
    "NATIVE_CURSOR_PAGE_INFO",
)


# --------------------------------------------------------------------------- #
# Native pagination build path (S-del-backend-11 — graphene backend deleted)  #
# --------------------------------------------------------------------------- #
# S-page-7 migrated the pagination CONTAINER BUILD path off graphene entirely:
# ``to_graphql_fields`` is NATIVE-ONLY (always graphql-core ``GraphQLArgument``),
# the dead graphene branch in ``types.py`` is removed, and the native machinery
# (``NATIVE_CURSOR_PAGE_INFO``, ``get_native_page_info_field``,
# ``to_graphql_fields``) is graphql-core and is the ONLY pagination build path.
# S-del-backend-11 deleted the last DEAD-BUT-DEFINED graphene constructs (the
# graphene ``CursorPageInfo`` ``ObjectType`` + the graphene-bodied
# ``CursorGraphqlPagination.get_page_info_field``) and the lazy graphene accessor.

# ---------------------------------------------------------------------------
# Native CursorPageInfo
# ---------------------------------------------------------------------------
# Built eagerly at module import time. This singleton is used by the native
# compiler when assembling the CursorGraphqlPagination pageInfo field (WU6a).

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


def _sort_key(value: Any) -> tuple[bool, Any]:
    """Build a sort key tolerant of "None" values.

    Sorts "None" first and avoids "None < x" comparison errors.

    Args:
        value: The value to derive a sort key from.

    Returns:
        A tuple ordering "None" values before other values.
    """
    return (value is None, value if value is not None else 0)


def _coerce_like(raw: Any, sample: Any) -> Any:
    """Coerce a cursor-decoded string to the runtime type of *sample*.

    Cursor components are serialised as strings inside the opaque token, so the
    in-memory keyset comparison must convert them back to the row's own value
    type (int, date, etc.) before comparing — otherwise ``"10" < "2"`` (lexical)
    is wrong and ``int``/``date`` vs ``str`` raises ``TypeError``. This keeps the
    in-memory path in parity with the DB path, whose ``filter`` coerces the same
    string back to the field's runtime type. Unsupported samples and any failed
    coercion fall back to the raw string (lenient, matching the DB path).

    Args:
        raw: The decoded cursor component (typically a string).
        sample: A live value read from a row, used only for its type.

    Returns:
        *raw* coerced to ``type(sample)`` when possible, else *raw* unchanged.
    """
    if sample is None or not isinstance(raw, str):
        return raw
    if isinstance(sample, bool):
        return raw
    if isinstance(sample, int):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return raw
    # Temporal samples: str(value) is ISO 8601, so fromisoformat is the exact
    # inverse. Order matters — datetime is a subclass of date, so it is checked
    # first. A parse failure keeps the raw string (lenient fallback).
    if isinstance(sample, datetime.datetime):
        try:
            return datetime.datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            return raw
    if isinstance(sample, datetime.date):
        try:
            return datetime.date.fromisoformat(raw)
        except (TypeError, ValueError):
            return raw
    if isinstance(sample, datetime.time):
        try:
            return datetime.time.fromisoformat(raw)
        except (TypeError, ValueError):
            return raw
    return raw


def _normalize_ordering_term(term: str) -> str:
    """Normalize a single ordering term to snake_case, preserving direction.

    GraphQL exposes every field NAME in camelCase on the wire, so a client that
    reads ``createdAt`` in a type reasonably passes ``ordering: "createdAt"``.
    Django's ORM (and the model ``_meta.concrete_fields`` allowlist) speaks
    snake_case attnames, so the two spellings must converge to the SAME term.

    The leading ``-``/``+`` direction prefix is stripped, the bare term is run
    through :func:`~django_graphex._strconv.to_snake_case` (idempotent on
    snake_case input), and the prefix is re-attached. This is the ONE canonical
    conversion point every consumer routes through so the DB path, the in-memory
    path, and the window-prefetch pre-check never diverge.

    Args:
        term: A single ordering term, optionally prefixed with ``-`` or ``+``.

    Returns:
        The direction-preserving snake_case form of *term*. An empty/falsy term
        is returned unchanged.
    """
    if not term:
        return term
    if term[0] in "-+":
        return term[0] + to_snake_case(term[1:])
    return to_snake_case(term)


def _split_ordering(ordering: str | list[str]) -> list[str]:
    """Split an ordering value into normalized, non-empty snake_case terms.

    Accepts either a comma-separated string (``"createdAt,-authorId"``) or an
    iterable of terms and returns the list of individual terms, each normalized
    via :func:`_normalize_ordering_term`. Whitespace and empty entries are
    dropped, matching the historical parsing used across the paginators.

    Args:
        ordering: A comma-separated ordering string or an iterable of terms.

    Returns:
        The list of normalized, non-empty ordering terms.
    """
    if isinstance(ordering, str):
        raw = [t for t in ordering.replace(" ", "").split(",") if t]
    else:
        raw = [t for t in ordering if t]
    return [_normalize_ordering_term(t) for t in raw]


def _normalize_ordering(ordering: Any) -> Any:
    """Return *ordering* normalized to snake_case in the SAME shape it came in.

    A falsy value is returned unchanged. A single-term string stays a string; a
    multi-term (comma-containing) string stays a comma-joined string; a list
    stays a list. Keeping the shape lets each caller feed the result straight
    into its existing ``order_by`` branch (single term vs. splat) without
    behaviour changes beyond the snake_case conversion.

    Args:
        ordering: A comma-separated ordering string, a list of terms, or a
            falsy value.

    Returns:
        The normalized ordering in the same shape, or the original falsy value.
    """
    if not ordering:
        return ordering
    if isinstance(ordering, str):
        terms = _split_ordering(ordering)
        return ",".join(terms)
    return _split_ordering(ordering)


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

    # Normalize client-supplied camelCase spellings to snake_case attnames
    # BEFORE the allowlist check, so ``createdAt`` validates exactly like
    # ``created_at`` (and an invalid ``nonexistentField`` still fails).
    terms = _split_ordering(ordering)

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
    # Normalize camelCase terms to snake_case attnames so ``getattr`` reads the
    # real model attribute — otherwise a camelCase term silently degrades to a
    # None key (no-op sort). This keeps the in-memory path in parity with the DB
    # path for the same input.
    terms = _split_ordering(ordering)

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
    """Base class for all Django GraphQL pagination implementations.

    Concrete paginators subclass this to turn GraphQL field arguments into a
    sliced queryset (or in-memory list) page, and to expose their argument set
    and optional "pageInfo" field to the native schema compiler. The base
    defines the shared page-size resolution helper and NotImplementedError
    stubs the subclasses fill in.
    """

    __name__ = None

    def _resolve_page_size(
        self,
        requested: Any,
        default: int | None,
        maximum: int | None,
        param_label: str | None = None,
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
            param_label: When given (e.g. ``"limit"``/``"first"``/``"page size"``),
                a zero/negative page size is surfaced as a clean ``GraphQLError``
                naming that argument instead of a bare ``ValueError`` (which would
                escape the resolver as an HTTP 500). Mirrors the negative-offset
                guard's error convention.

        Returns:
            The effective, clamped page size, or ``None`` when unbounded.

        Raises:
            GraphQLError: If the resolved size is zero or negative and
                ``param_label`` is provided (bad client input).
            ValueError: If the resolved size is zero or negative and no
                ``param_label`` is provided (internal callers).
        """
        value = requested if requested is not None else default
        if value is None:
            value = maximum
        if value is None:
            return None
        try:
            value = _positive_int(value, strict=True)
        except ValueError as exc:
            if param_label is not None:
                label = param_label.capitalize()
                raise GraphQLError(
                    f"Invalid {param_label}: {value}. "
                    f"{label} must be a positive integer."
                ) from exc
            raise
        return min(value, maximum) if maximum is not None else value

    def get_page_info_field(self, type: Any) -> Any | None:
        """Return a "pageInfo" field for this paginator, or "None".

        Paginators that do not expose pagination metadata (limit/offset, page)
        return "None" so their list types gain no "pageInfo" field.

        S-del-backend-11: the native build path uses
        "get_native_page_info_field" (graphql-core); this base hook only ever
        returns None. The graphene-bodied "CursorGraphqlPagination" override was
        deleted with the graphene backend.

        Args:
            type: The GraphQL list type the field belongs to.

        Returns:
            None (no pagination metadata at the base level).
        """
        return None

    def to_graphql_fields(self, *, native: bool = True) -> dict[str, Any]:
        """Convert pagination parameters to graphql-core field arguments.

        S-page-7 (graphene-removal): the build path is NATIVE-ONLY — this always
        returns graphql-core "GraphQLArgument" instances. The "native" keyword is
        retained for signature/back-compat stability (callers that still pass
        "native=..." keep working) but is ignored; there is no graphene branch.

        Args:
            native: Accepted for back-compat; ignored (always native).

        Returns:
            A mapping of argument names to "GraphQLArgument" definitions.

        Raises:
            NotImplementedError: Always, since child classes must implement it.
        """
        raise NotImplementedError(
            "to_graphql_field() function must be implemented into child classes."
        )

    def get_native_page_info_field(self, node_type: Any) -> Any:
        """Return a native (graphql-core) "pageInfo" field, or None.

        The base implementation returns None (no pagination metadata),
        mirroring "get_page_info_field". Cursor pagination overrides this to
        expose a native "CursorPageInfo" field.

        Args:
            node_type: The compiled element (node) "GraphQLObjectType" the list
                paginates.

        Returns:
            A "graphql.GraphQLField", or None when no metadata is exposed.
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

        The base implementation always returns None, signalling that this
        paginator does not support DB-side window slicing and the caller should
        fall back to the standard in-memory path.

        Subclasses that can derive (offset, limit, ordering) from "**kwargs"
        without needing the total row count at build time SHOULD override this
        method and return the resolved triple. They MUST return None whenever
        the slice cannot be determined without a count (e.g. negative page
        number) or the paginator is unbounded.

        Args:
            **kwargs: The pagination arguments as extracted from the GraphQL
                query (same names the paginator uses in "paginate_queryset").

        Returns:
            A (offset, limit, ordering) tuple, or None to fall back to the
            in-memory path.
        """
        return None

    def prefetch_window_slice_ordering_check(
        self, model: Any, ordering: str | list[str]
    ) -> None:
        """Validate ordering terms for a given model before DB-side window slicing.

        Delegates to "_validate_ordering_terms". Exposed as a method so tests
        and callers can exercise the guard without constructing a queryset.

        Args:
            model: The Django model class to validate against.
            ordering: A comma-separated ordering string or a list of ordering
                terms.

        Raises:
            GraphQLError: When any term is invalid or relation-spanning.
        """
        _validate_ordering_terms(model, ordering)


class LimitOffsetGraphqlPagination(BaseDjangoGraphqlPagination):
    """Pagination implementation using limit and offset parameters.

    The client controls the page with a "limit" (page size, clamped at
    "max_limit") and an "offset" (starting index), plus an optional "ordering"
    term. This is the simplest paginator and the only one that supports DB-side
    window slicing (via "prefetch_window_slice") because its offset/limit are
    derivable without a total row count.
    """

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

    def to_graphql_fields(self, *, native: bool = True) -> dict[str, Any]:
        """Convert limit/offset parameters to graphql-core field arguments.

        S-page-7: NATIVE-ONLY — always returns "{name: GraphQLArgument}"
        instances so the native compiler can embed them directly as field args.
        The "native" keyword is accepted for back-compat and ignored.

        Args:
            native: Accepted for back-compat; ignored (always native).

        Returns:
            A mapping of argument names to "GraphQLArgument" definitions.
        """
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

    def paginate_queryset(self, qs: Any, **kwargs: Any) -> Any:
        """Paginate a queryset or an in-memory list using limit and offset.

        Args:
            qs: The queryset or list to paginate.
            **kwargs: The pagination arguments from the query.

        Returns:
            The paginated slice of results.

        Raises:
            GraphQLError: On a zero/negative limit, a negative offset, or an
                invalid/relation-spanning ordering term (bad client input).
        """
        limit = self._resolve_page_size(
            kwargs.get(self.limit_query_param, None),
            self.default_limit,
            self.max_limit,
            param_label="limit",
        )

        # Unbounded only when neither a default nor a max is configured.
        if limit is None:
            return qs

        # Normalize camelCase ordering to snake_case attnames at the single
        # canonical entry point, so the DB path, the in-memory path, and the
        # validation allowlist all see the same terms.
        order = _normalize_ordering(
            kwargs.pop(self.ordering_param, None) or self.ordering
        )
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

        Mirrors the resolution logic of "paginate_queryset" exactly so that the
        window-slice math is byte-for-byte identical to the in-memory path:

        - "limit" is resolved via "_resolve_page_size" (default + clamping).
        - When resolved "limit" is None (unbounded), returns None so the caller
          falls back to the in-memory path.
        - "offset" defaults to 0.
        - "ordering" falls back to "self.ordering" when not supplied.

        Args:
            **kwargs: Pagination arguments extracted from the GraphQL query
                (same names as used by "paginate_queryset").

        Returns:
            A (offset, limit, ordering) tuple, or None when unbounded.

        Raises:
            GraphQLError: On a zero/negative limit or a negative offset (bad
                client input), matching "paginate_queryset".
        """
        limit = self._resolve_page_size(
            kwargs.get(self.limit_query_param, None),
            self.default_limit,
            self.max_limit,
            param_label="limit",
        )
        if limit is None:
            return None
        offset = kwargs.get(self.offset_query_param, 0) or 0
        if offset < 0:
            raise GraphQLError(
                f"Invalid offset: {offset}. Offset must be a non-negative integer."
            )
        # Normalize camelCase ordering so the window pre-check (which matches
        # terms against concrete snake_case attnames) does not decline the
        # optimization for a camelCase spelling.
        order = _normalize_ordering(
            kwargs.pop(self.ordering_param, None) or self.ordering
        )
        return (offset, abs(limit), order)


class PageGraphqlPagination(BaseDjangoGraphqlPagination):
    """Pagination implementation using page number and page size parameters.

    The client controls the page with a 1-based "page" number and an optional
    per-page size (when "page_size_query_param" is configured), plus an optional
    "ordering" term. A negative page counts back from the last page, which needs
    the total row count and therefore disables DB-side window slicing for that
    case.
    """

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

    def to_graphql_fields(self, *, native: bool = True) -> dict[str, Any]:
        """Convert page pagination parameters to graphql-core field arguments.

        S-page-7: NATIVE-ONLY — always returns "{name: GraphQLArgument}"
        instances. The "native" keyword is accepted for back-compat and
        ignored.

        Args:
            native: Accepted for back-compat; ignored (always native).

        Returns:
            A mapping of argument names to "GraphQLArgument" definitions.
        """
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

    def paginate_queryset(self, qs: Any, **kwargs: Any) -> Any:
        """Paginate a queryset using page number and page size parameters.

        Args:
            qs: The queryset or list to paginate.
            **kwargs: The pagination arguments from the query.

        Returns:
            The paginated slice of results, or "None" when no page size is set.

        Raises:
            GraphQLError: On a zero page number, a zero/negative page size, or
                an invalid/relation-spanning ordering term (bad client input).
        """
        page = kwargs.pop(self.page_query_param, 1)
        requested = (
            kwargs.get(self.page_size_query_param)
            if self.page_size_query_param
            else None
        )
        page_size = self._resolve_page_size(
            requested, self.page_size, self.max_page_size, param_label="page size"
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

        # Normalize camelCase ordering to snake_case attnames (see LimitOffset).
        order = _normalize_ordering(
            kwargs.pop(self.ordering_param, None) or self.ordering
        )

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

        Mirrors the resolution logic of "paginate_queryset":

        - When "page_size" resolves to None (unbounded), returns None.
        - When "page < 0" (count-relative offset), returns None because the
          offset cannot be computed without the total row count at build time.
        - For "page >= 0", "offset = page_size * (page - 1)".

        Args:
            **kwargs: Pagination arguments extracted from the GraphQL query
                (same names as used by "paginate_queryset").

        Returns:
            A (offset, page_size, ordering) tuple, or None to fall back.
        """
        page = kwargs.pop(self.page_query_param, 1)
        requested = (
            kwargs.get(self.page_size_query_param)
            if self.page_size_query_param
            else None
        )
        page_size = self._resolve_page_size(
            requested, self.page_size, self.max_page_size, param_label="page size"
        )
        if page_size is None:
            return None
        if page <= 0:
            # page < 0: count-relative offset requires total count at build time.
            # page == 0: offset = page_size*(0-1) = negative — invalid.
            # Both cases fall back to the in-memory path.
            return None
        offset = page_size * (page - 1)
        # Normalize camelCase ordering (see LimitOffset.prefetch_window_slice).
        order = _normalize_ordering(
            kwargs.pop(self.ordering_param, None) or self.ordering
        )
        return (offset, page_size, order)


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
        translatable to a row offset without a full table scan. This is out of
        scope for v1 window optimisation.

        Args:
            **kwargs: The pagination arguments from the query (unused — this
                paginator never supports DB-side window slicing).

        Returns:
            Always None, so the caller falls back to the in-memory path.
        """
        # Opaque keyset; DB-side window slice is out of scope for v1.
        return None

    # -- cursor helpers -----------------------------------------------------
    #: Unit-separator byte that partitions the ordering value from the pk inside
    #: a composite keyset cursor. It is a control character, so it never collides
    #: with a real string ordering value (e.g. a name containing ``:``).
    _CURSOR_PK_SEP = "\x1f"

    #: Null-value marker byte for the value component of a composite cursor. A
    #: real ordering value serialises via ``str(value)``, so a bare NUL byte can
    #: never be produced by a genuine value — it unambiguously encodes a NULL
    #: ordering value (distinct from the literal string ``"None"``). This lets a
    #: NULL boundary round-trip back to a real ``None`` for the isnull-aware
    #: keyset predicate instead of degrading to a broken ``"None"`` string.
    _CURSOR_NULL = "\x00"

    @staticmethod
    def encode_cursor(value: Any, pk: Any = None) -> str:
        """Encode an ordering-field value (and optional pk) into a cursor.

        The keyset cursor is a composite of the boundary row's ordering value
        AND its primary key. The pk is the deterministic tiebreak that keeps rows
        sharing the same ordering value from being skipped between pages: without
        it, "value > boundary" silently drops every other tied row.

        When "pk" is None a legacy value-only cursor is produced (the pk
        component is simply absent); this keeps the encoding backward-compatible
        for callers that only have the ordering value and lets "decode_cursor"
        still recover that value.

        Args:
            value: The ordering-field value of the boundary row.
            pk: The primary key of the boundary row, or None for a value-only
                cursor.

        Returns:
            The opaque cursor string for the given (value, pk) pair.
        """
        # A NULL ordering value is serialised as the dedicated NUL marker so it
        # round-trips back to a real ``None`` (not the string "None"); the
        # isnull-aware keyset predicate needs the true NULL to place the row.
        value_part = (
            CursorGraphqlPagination._CURSOR_NULL if value is None else f"{value}"
        )
        payload = f"cursor:{value_part}"
        if pk is not None:
            payload = f"{payload}{CursorGraphqlPagination._CURSOR_PK_SEP}{pk}"
        return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")

    @staticmethod
    def _encode_row_cursor(row: Any, field_name: str) -> str:
        """Encode a boundary *row* into a composite ``(value, pk)`` cursor.

        Args:
            row: The boundary model instance.
            field_name: The bare ordering-field name to read from *row*.

        Returns:
            The opaque composite cursor for the row.
        """
        return CursorGraphqlPagination.encode_cursor(
            getattr(row, field_name), getattr(row, "pk", None)
        )

    @staticmethod
    def decode_cursor(cursor: str) -> str | None:
        """Decode an opaque cursor back into its ordering-field value.

        The pk component (present in composite keyset cursors) is stripped; only
        the ordering value is returned. Use "decode_cursor_parts" when both the
        value and the pk are needed for the keyset predicate.

        Args:
            cursor: The opaque cursor string to decode.

        Returns:
            The decoded ordering-field value, or "None" when the boundary row's
            ordering value was NULL.

        Raises:
            ValueError: If the cursor is malformed or not a valid cursor.
        """
        value, _pk = CursorGraphqlPagination.decode_cursor_parts(cursor)
        return value

    @staticmethod
    def decode_cursor_parts(cursor: str) -> tuple[str | None, str | None]:
        """Decode a cursor into its (ordering value, pk) components.

        Args:
            cursor: The opaque cursor string to decode.

        Returns:
            A (value, pk) tuple. "value" is "None" when the boundary row's
            ordering value was NULL (encoded via the NUL marker). "pk" is "None"
            for a legacy value-only cursor that carries no pk component.

        Raises:
            ValueError: If the cursor is malformed or not a valid cursor.
        """
        try:
            raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            raise ValueError(f"Invalid pagination cursor: {cursor!r}")
        prefix, sep, rest = raw.partition(":")
        if prefix != "cursor" or not sep:
            raise ValueError(f"Invalid pagination cursor: {cursor!r}")
        # Split on the LAST separator: the pk is always the trailing component
        # and pks never contain the unit separator, so an ordering VALUE that
        # itself carries one or more "\x1f" bytes still round-trips losslessly
        # (a first-separator "partition" would spill the value tail into the pk).
        value, pk_sep, pk = rest.rpartition(CursorGraphqlPagination._CURSOR_PK_SEP)
        # rpartition puts everything in the tail when no separator exists; for a
        # legacy value-only cursor (no pk component) the whole "rest" is the
        # value, so recover it from "pk" and report a None pk.
        if not pk_sep:
            value, pk = pk, None
        # A lone NUL marker decodes back to a real NULL ordering value.
        decoded_value = None if value == CursorGraphqlPagination._CURSOR_NULL else value
        return decoded_value, pk

    def _ordering_field(self) -> tuple[str, str, bool]:
        """Return the ordering term, field name and direction for the ordering.

        Returns:
            A tuple of the order-by term, the bare field name and whether the
            ordering is descending.
        """
        field = self.ordering.split(",")[0].strip()
        descending = field.startswith("-")
        return field, field.lstrip("+-"), descending

    def _order_terms(self, order_term: str, descending: bool) -> tuple[Any, str]:
        """Return the ``order_by`` terms with deterministic NULL placement + pk.

        The pk is always appended so rows sharing the same ordering value have a
        stable, repeatable order — the precondition for a tie-safe keyset cursor.
        The pk direction mirrors the ordering direction (``-pk`` when descending)
        so the composite ``(value, pk)`` boundary advances monotonically.

        NULL placement is pinned to match the in-memory path's ``_sort_key``
        (which sorts NULLs LAST ascending, FIRST descending): the primary term is
        expressed as ``F(field).asc(nulls_last=True)`` /
        ``F(field).desc(nulls_first=True)`` so the DB and in-memory sequences over
        NULL-bearing data are identical. Without an explicit clause the backends
        disagree (SQLite/SQLite nulls-first vs. PostgreSQL nulls-last ascending),
        which would silently break DB/in-memory parity and cursor determinism.

        Args:
            order_term: The primary ordering term (may carry a ``-``/``+`` prefix).
            descending: Whether the primary ordering is descending.

        Returns:
            A ``(order_by_expr, pk_term)`` pair for ``qs.order_by(*terms)``.
        """
        from django.db.models import F

        bare = order_term.lstrip("+-")
        primary = (
            F(bare).desc(nulls_first=True)
            if descending
            else F(bare).asc(nulls_last=True)
        )
        return primary, ("-pk" if descending else "pk")

    @staticmethod
    def _keyset_predicate(
        field_name: str, descending: bool, value: Any, pk: Any
    ) -> Any:
        """Build the compound keyset ``Q`` predicate for "rows after the cursor".

        Ascending order advances when ``field > value`` OR (``field == value`` AND
        ``pk > pk``); descending mirrors this with ``lt``. This compound boundary
        is what makes tied ordering values safe: the pk tiebreak resumes exactly
        after the boundary row instead of skipping every other tied row.

        NULL boundaries are handled explicitly so the predicate stays consistent
        with the deterministic NULL placement of :meth:`_order_terms` (ascending
        -> NULLs last, descending -> NULLs first) — SQL ``field > NULL`` is never
        true, so a plain comparison would drop every page after a NULL boundary.
        The isnull-aware branches are:

        - Ascending, boundary NOT NULL: everything greater, the pk-tied tail of
          the same value, AND the whole trailing NULL group.
        - Ascending, boundary NULL: only the NULL group advanced by pk (nothing
          non-NULL sorts after a NULL when NULLs are last).
        - Descending, boundary NULL: the NULL group advanced by pk (descending)
          plus the entire non-NULL body (NULLs are first).
        - Descending, boundary NOT NULL: everything smaller and the pk-tied tail
          (no NULL row sorts after a non-NULL when NULLs are first).

        Args:
            field_name: The bare ordering-field name.
            descending: Whether the ordering is descending.
            value: The boundary row's ordering value ("None" for a NULL boundary).
            pk: The boundary row's primary key.

        Returns:
            A Django ``Q`` object selecting the rows strictly after the boundary.
        """
        from django.db.models import Q

        cmp = "lt" if descending else "gt"
        isnull = f"{field_name}__isnull"

        if value is None:
            # Boundary row's ordering value is NULL.
            within_null_group = Q(**{isnull: True, f"pk__{cmp}": pk})
            if descending:
                # NULLs first: the rest of the NULL group (by pk) plus every
                # non-NULL row (which all sort after the leading NULL group).
                return within_null_group | Q(**{isnull: False})
            # Ascending, NULLs last: nothing non-NULL follows a NULL boundary;
            # only advance within the trailing NULL group by pk.
            return within_null_group

        # Boundary row's ordering value is NOT NULL.
        strictly_beyond = Q(**{f"{field_name}__{cmp}": value})
        pk_tied = Q(**{field_name: value, f"pk__{cmp}": pk})
        if descending:
            # NULLs first: no NULL row sorts after a non-NULL boundary.
            return strictly_beyond | pk_tied
        # Ascending, NULLs last: the trailing NULL group all sorts after any
        # non-NULL boundary, so include it explicitly.
        return strictly_beyond | pk_tied | Q(**{isnull: True})

    @staticmethod
    def _inmemory_after_cursor(
        obj: Any,
        field_name: str,
        descending: bool,
        value: Any,
        pk: Any,
    ) -> bool:
        """Return whether *obj* sorts strictly after the composite cursor boundary.

        Mirrors :meth:`_keyset_predicate` for the in-memory (prefetch-cache) path
        so both paths agree on which rows follow a tied boundary.

        Args:
            obj: The candidate model instance.
            field_name: The bare ordering-field name.
            descending: Whether the ordering is descending.
            value: The boundary row's ordering value (as decoded from the cursor).
            pk: The boundary row's primary key (as decoded from the cursor).

        Returns:
            ``True`` when *obj* comes after the boundary in the ordered sequence.
        """
        obj_value = getattr(obj, field_name, None)
        obj_pk = getattr(obj, "pk", None)
        # The cursor components arrive as strings (they were serialised into the
        # opaque token). Coerce them to the runtime type of the row's own value/pk
        # so the comparison is numeric/date-aware instead of a broken lexical
        # "10" < "2", and so int-vs-str never raises a TypeError.
        boundary_value = _coerce_like(value, obj_value)
        boundary_pk = _coerce_like(pk, obj_pk) if pk is not None else None
        obj_key = _sort_key(obj_value)
        boundary_key = _sort_key(boundary_value)
        if obj_key != boundary_key:
            return obj_key < boundary_key if descending else obj_key > boundary_key
        # Same ordering value: fall back to the pk tiebreak. A missing boundary pk
        # (legacy value-only cursor) has no tiebreak, so it mirrors the DB legacy
        # ``field__gt``/``field__lt`` branch — a row with the equal value is NOT
        # "after" the boundary (strict value comparison).
        if boundary_pk is None:
            return False
        obj_pk_key = _sort_key(obj_pk)
        boundary_pk_key = _sort_key(boundary_pk)
        return (
            obj_pk_key < boundary_pk_key if descending else obj_pk_key > boundary_pk_key
        )

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
            param_label="first",
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

    def to_graphql_fields(self, *, native: bool = True) -> dict[str, Any]:
        """Convert cursor pagination parameters to graphql-core field arguments.

        S-page-7: NATIVE-ONLY — always returns "{name: GraphQLArgument}"
        instances. The "native" keyword is accepted for back-compat and
        ignored.

        Args:
            native: Accepted for back-compat; ignored (always native).

        Returns:
            A mapping of argument names to "GraphQLArgument" definitions.
        """
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

    def _inmemory_cursor_start(
        self,
        items: Sequence[Any],
        field_name: str,
        descending: bool,
        cursor: str | None,
    ) -> int:
        """Find the index of the first row after the composite cursor boundary.

        The match compares each row against the decoded ``(value, pk)`` boundary
        using the same keyset logic as the DB path, so tied ordering values
        resume at the correct pk instead of being skipped. Because it scans by
        boundary comparison (not exact equality), a boundary row that is no
        longer in the list still yields the correct resume index.

        Args:
            items: The ordered in-memory items to scan.
            field_name: The ordering field name to read from each item.
            descending: Whether the ordering is descending.
            cursor: The cursor whose following row index is sought.

        Returns:
            The index of the first row after the cursor, or 0 when not found.

        Raises:
            GraphQLError: If the cursor is malformed (mirrors the DB path).
        """
        if not cursor:
            return 0
        try:
            value, pk = self.decode_cursor_parts(cursor)
        except ValueError as exc:
            raise GraphQLError("Invalid cursor") from exc
        for index, obj in enumerate(items):
            if self._inmemory_after_cursor(obj, field_name, descending, value, pk):
                return index
        return len(items)

    def paginate_queryset(self, qs: Any, **kwargs: Any) -> Any:
        """Paginate a queryset or in-memory list by forward keyset cursor.

        Args:
            qs: The queryset or list to paginate.
            **kwargs: The pagination arguments from the query.

        Returns:
            The paginated slice of results.

        Raises:
            GraphQLError: On a malformed/tampered cursor or a zero/negative
                "first" page size (bad client input).
        """
        order_term, field_name, descending = self._ordering_field()
        page_size = self._page_size(**kwargs)
        cursor = kwargs.get(self.cursor_query_param, None)

        if not isinstance(qs, QuerySet):
            items = self._inmemory_keyset_order(qs, field_name, descending)
            start = self._inmemory_cursor_start(items, field_name, descending, cursor)
            return items[start : start + page_size]

        qs = qs.order_by(*self._order_terms(order_term, descending))
        if cursor:
            # Wrap both decode_cursor_parts and the subsequent qs.filter() because a
            # tampered cursor can fail at two points:
            #   1. decode_cursor_parts raises ValueError for malformed base64 or
            #      bad prefix.
            #   2. qs.filter(...) raises Django ValidationError when the decoded
            #      value/pk cannot be coerced to the field's type (e.g. a string
            #      passed to an IntegerField or DateTimeField). Either should
            #      produce a clean GraphQLError, not an unhandled HTTP 500.
            try:
                value, pk = self.decode_cursor_parts(cursor)
                if pk is None:
                    # Legacy value-only cursor: fall back to the plain value
                    # boundary (no pk tiebreak available). A NULL boundary value
                    # cannot use a "field > NULL" comparison (never true), so
                    # route it through the isnull-aware group filter instead.
                    qs = qs.filter(
                        self._legacy_value_predicate(field_name, descending, value)
                    )
                else:
                    qs = qs.filter(
                        self._keyset_predicate(field_name, descending, value, pk)
                    )
            except (ValueError, ValidationError) as exc:
                raise GraphQLError("Invalid cursor") from exc

        return qs[:page_size]

    @staticmethod
    def _legacy_value_predicate(field_name: str, descending: bool, value: Any) -> Any:
        """Build the pk-less (legacy) "rows after the cursor" predicate.

        The composite keyset predicate needs a pk tiebreak; a legacy value-only
        cursor has none, so this reproduces the historical plain-value boundary
        (``field > value`` ascending, ``field < value`` descending). A NULL
        boundary value can never satisfy a ``> / <`` comparison, so it selects the
        appropriate NULL-relative group instead (the trailing NULL group when
        ascending with NULLs last; the whole non-NULL body when descending with
        NULLs first) — deterministic placement without a tiebreak.

        Args:
            field_name: The bare ordering-field name.
            descending: Whether the ordering is descending.
            value: The boundary ordering value ("None" for a NULL boundary).

        Returns:
            A Django ``Q`` object selecting the rows after the value boundary.
        """
        from django.db.models import Q

        if value is None:
            # Ascending NULLs last: nothing follows a NULL boundary without a
            # pk tiebreak. Descending NULLs first: the entire non-NULL body does.
            return Q(**{f"{field_name}__isnull": False}) if descending else Q(pk__in=[])
        lookup = f"{field_name}__{'lt' if descending else 'gt'}"
        return Q(**{lookup: value})

    @staticmethod
    def _inmemory_keyset_order(
        items: Iterable[Any], field_name: str, descending: bool
    ) -> list[Any]:
        """Order in-memory rows by ``(ordering value, pk)`` with a stable tiebreak.

        Produces the same sequence the DB path gets from ``order_by(field, "pk")``:
        the primary ordering value, then the pk as the deterministic tie-breaker
        (both flipped when descending). Applying the least-significant key (pk)
        first and the primary key last leans on Python's stable sort to build the
        composite order in two passes.

        Args:
            items: The rows to order.
            field_name: The bare ordering-field name to read from each row.
            descending: Whether the ordering is descending.

        Returns:
            A new list ordered by the composite keyset.
        """
        ordered = list(items)
        # Least-significant key first: pk tiebreak.
        ordered.sort(
            key=lambda obj: _sort_key(getattr(obj, "pk", None)),
            reverse=descending,
        )
        # Most-significant key last: the primary ordering value (stable sort keeps
        # the pk order within tied values).
        ordered.sort(
            key=lambda obj: _sort_key(getattr(obj, field_name, None)),
            reverse=descending,
        )
        return ordered

    # -- pageInfo -----------------------------------------------------------
    def get_native_page_info_field(self, node_type: Any) -> Any:
        """Return a native "CursorPageInfo" field with first/cursor args.

        Mirrors "get_page_info_field" for the native compiler: the field's type
        is the shared "NATIVE_CURSOR_PAGE_INFO" "GraphQLObjectType" and the
        resolver computes the page info from the "DjangoListObjectBase" root
        (same logic as the graphene resolver).

        Args:
            node_type: The compiled element (node) "GraphQLObjectType" (unused;
                accepted for signature parity with the base method).

        Returns:
            A "graphql.GraphQLField" for the cursor "pageInfo".
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

        Raises:
            GraphQLError: On a malformed/tampered cursor or a zero/negative
                "first" page size (bad client input).
        """
        order_term, field_name, descending = self._ordering_field()
        page_size = self._page_size(**kwargs)
        cursor = kwargs.get(self.cursor_query_param, None)

        if not isinstance(qs, QuerySet):
            items = self._inmemory_keyset_order(qs, field_name, descending)
            start = self._inmemory_cursor_start(items, field_name, descending, cursor)
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
                "start_cursor": self._encode_row_cursor(window[0], field_name),
                "end_cursor": self._encode_row_cursor(window[-1], field_name),
            }

        ordered = qs.order_by(*self._order_terms(order_term, descending))
        page_qs = ordered
        if cursor:
            # Same guard as in paginate_queryset: a tampered cursor can fail at
            # decode_cursor_parts (malformed base64) or at filter() (type coercion).
            try:
                value, pk = self.decode_cursor_parts(cursor)
                if pk is None:
                    page_qs = page_qs.filter(
                        self._legacy_value_predicate(field_name, descending, value)
                    )
                else:
                    page_qs = page_qs.filter(
                        self._keyset_predicate(field_name, descending, value, pk)
                    )
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

        first_row = rows[0]
        start_value = getattr(first_row, field_name)
        start_pk = first_row.pk

        # Exact hasPreviousPage: is there a row strictly before the first one?
        # The "before" predicate is the mirror of the keyset predicate (the
        # opposite comparison direction), including the pk tiebreak so a tied
        # boundary is judged correctly instead of by value alone.
        has_previous_page = ordered.filter(
            self._keyset_predicate(field_name, not descending, start_value, start_pk)
        ).exists()

        return {
            "has_next_page": has_next_page,
            "has_previous_page": has_previous_page,
            "start_cursor": self._encode_row_cursor(first_row, field_name),
            "end_cursor": self._encode_row_cursor(rows[-1], field_name),
        }
