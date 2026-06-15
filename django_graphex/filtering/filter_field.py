"""``@filter_field`` decorator for per-field custom GraphQL filter args.

Provides the public ``filter_field`` decorator that allows a ``DjangoObjectType``
(or ``DjangoModelType``) subclass to declare custom filter arguments directly
on the type class, next to the logic that implements them.

Usage::

    from django_graphex import filter_field

    class PostType(DjangoObjectType):
        class Meta:
            model = Post
            filter_fields = {"title": ("exact", "icontains")}

        @filter_field(description="Full-text search")  # defaults to String
        def search(cls, queryset, info, value):
            return queryset.filter(
                Q(title__icontains=value) | Q(body__icontains=value)
            )

Contract:
- ``graphene_type``: the scalar/type for the argument (default: the native
  graphql-core ``String`` scalar). The parameter NAME is kept for backward
  compatibility with 1.x — it accepts EITHER a native graphql-core type
  (``graphql.GraphQLInt`` etc.) OR a legacy graphene scalar/type
  (``graphene.Int`` etc.); the native filter builder normalizes both. See
  UPGRADE-2.0 for the deprecation-rename note.
- ``description``: optional GraphQL description string.
- The decorated method receives ``(cls, queryset, info, value) -> QuerySet``.
  The decorator handles classmethod semantics — do NOT stack ``@classmethod``.
- The GraphQL argument name equals the method name.
- Composition order at query time: standard lookups → custom ``@filter_field``
  methods in declaration order → ``filter_queryset`` (last).
"""

from __future__ import annotations

from typing import Any, Callable

from graphql import GraphQLString

__all__ = ("filter_field", "apply_custom_filters")

#: Reserved pagination / ordering / built-in argument names that ``@filter_field``
#: method names must not collide with. These come from the three built-in
#: paginators (LimitOffset, Page, Cursor) plus the standard list-field args.
RESERVED_FILTER_ARGS: frozenset[str] = frozenset(
    {
        # LimitOffsetGraphqlPagination
        "limit",
        "offset",
        "ordering",
        # PageGraphqlPagination
        "page",
        "page_size",
        # CursorGraphqlPagination
        "first",
        "cursor",
        # Built-in list field args
        "filter",
        "id",
    }
)


def filter_field(
    graphene_type: Any = GraphQLString,
    *,
    description: str | None = None,
) -> Callable:
    """Decorator that marks a method as a custom GraphQL filter argument.

    Args:
        graphene_type: The scalar or type for the argument. Defaults to the
            native graphql-core ``String`` scalar (``graphql.GraphQLString``).
            The parameter name is kept for backward compatibility — it accepts
            EITHER a native graphql-core type OR a legacy graphene scalar/type;
            the native filter builder normalizes both (see UPGRADE-2.0 for the
            deprecation-rename note).
        description: Optional description string for the GraphQL argument.

    Returns:
        A decorator that attaches ``_dgx_filter_field`` metadata to the method.
    """

    def decorator(fn: Callable) -> Callable:
        fn._dgx_filter_field = {
            "graphene_type": graphene_type,
            "description": description,
        }
        return fn

    return decorator


def apply_custom_filters(
    queryset: Any,
    custom_filters: list[tuple[str, Callable, Any]],
    info: Any,
    filter_value: Any,
) -> Any:
    """Apply custom ``@filter_field`` methods to a queryset in declaration order.

    Args:
        queryset: The base queryset to filter.
        custom_filters: List of ``(arg_name, method, metadata)`` triples collected
            by the metaclass from the type class.
        info: The GraphQL resolve info.
        filter_value: The filter input value (an ``InputObjectTypeContainer``),
            or ``None`` / empty for a no-op.

    Returns:
        The queryset after all applicable custom filters are applied.
    """
    if not filter_value or not custom_filters:
        return queryset

    for arg_name, method, _meta in custom_filters:
        # Native (GDX_BACKEND=native) delivers the filter input as a plain DICT
        # with snake out_name keys (graphql-core does not rehydrate an object);
        # graphene delivers an ``InputObjectTypeContainer`` accessed by attribute.
        # Read both shapes so custom @filter_field args fire under either backend.
        if isinstance(filter_value, dict):
            value = filter_value.get(arg_name, None)
        else:
            value = getattr(filter_value, arg_name, None)
        if value is None:
            continue
        queryset = method(queryset, info, value)

    return queryset


def collect_custom_filters(
    cls: type,
) -> list[tuple[str, Callable, dict[str, Any]]]:
    """Collect ``@filter_field``-decorated methods from a class in MRO order.

    Walks the MRO in reverse so that the most-derived class overrides bases.
    Declaration order within a class is preserved (Python 3.7+ dict ordering).

    The stored callable is **bound to ``cls``**: calling it as
    ``bound_fn(queryset, info, value)`` is equivalent to
    ``fn(cls, queryset, info, value)``.  This implements the decorator's
    "classmethod semantics internally" contract.

    Args:
        cls: The ``DjangoObjectType`` subclass being constructed.

    Returns:
        Ordered list of ``(arg_name, bound_classmethod_callable, metadata)``
        triples, one per ``@filter_field``-decorated method found.
    """
    import functools

    seen: dict[str, tuple[str, Callable, dict[str, Any]]] = {}
    for klass in reversed(cls.__mro__):
        for attr_name, attr in vars(klass).items():
            if callable(attr) and hasattr(attr, "_dgx_filter_field"):
                meta = attr._dgx_filter_field
                # Bind cls so the caller uses (queryset, info, value).
                bound = functools.partial(attr, cls)
                bound._dgx_filter_field = meta  # type: ignore[attr-defined]
                seen[attr_name] = (attr_name, bound, meta)

    return list(seen.values())
