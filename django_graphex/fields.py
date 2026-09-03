"""Custom GraphQL fields for Django models with filtering and pagination support."""

from __future__ import annotations

import operator
from functools import partial
from typing import TYPE_CHECKING, Any, Callable

from django.db.models import Count, F, JSONField, Prefetch
from django.db.models.constants import LOOKUP_SEP
from django.db.models.expressions import Window
from django.db.models.functions import RowNumber
from graphql import GraphQLID, GraphQLList, GraphQLNonNull

import django_graphex.settings as _settings_module
from django_graphex.filtering.backend import resolve_filter_backend
from django_graphex.settings import graphql_api_settings

from ._strconv import to_snake_case
from .base_types import DjangoListObjectBase
from .core.descriptors import (
    NativeList,
    NativeMountedField,
    NativeNonNull,
)
from .filtering.filter_field import apply_custom_filters
from .paginations.pagination import (
    BaseDjangoGraphqlPagination,
    _split_ordering,
    projected_ordering_attnames,
)
from .utils import (
    _apply_field_hook,
    _compute_child_only,
    _get_field_optimize_hook,
    apply_object_type_get_queryset,
    find_field,
    get_extra_filters,
    get_related_fields,
    is_valid_django_model,
    maybe_queryset,
    queryset_factory,
)

# ---------------------------------------------------------------------------
# G3 spike result: does .only() survive Window + filter(_gqx_rn) wrapping?
# Verified True on Django >= 4.2 / SQLite: the inner SELECT uses narrowed cols;
# the outer SELECT * selects from the already-narrowed subquery.
# If this is False, build_window_prefetch omits .only() (column over-fetch, but correct).
# ---------------------------------------------------------------------------
SELF_NARROW_VERIFIED: bool = True

# ---------------------------------------------------------------------------
# Prefix for the to_attr used by build_window_prefetch.  Results land in
# ``root._gqx_win_<accessor>`` (a plain list) instead of the normal
# ``_prefetched_objects_cache``.  list_resolver checks this attr first to
# distinguish a window-sliced empty result (offset-beyond-end) from a
# plain zero-child parent.
# ---------------------------------------------------------------------------
_GQX_WIN_ATTR_PREFIX: str = "_gqx_win_"
_GQX_ANN_ATTR_PREFIX: str = "_gqx_ann_"
# Prefix for the parent-annotation that carries the filtered child count.
# Applied by _apply_optimizations as a Subquery so list_resolver can read the
# count in memory instead of issuing a per-parent COUNT query for empty pages.
_GQX_CNT_ATTR_PREFIX: str = "_gqx_cnt_"

if TYPE_CHECKING:
    from django.db.models import Manager, Model
    from graphql import GraphQLResolveInfo as ResolveInfo


# All list/non-null wrapper currencies a field ``.type`` may carry during the
# native window: graphql-core ``GraphQLList`` / ``GraphQLNonNull`` (eager,
# compiled) AND the native lazy ``NativeList`` / ``NativeNonNull`` descriptors
# (S-ROOTS-c). Every one exposes ``.of_type``; ``_unwrap_type`` peels them to reach
# the inner node class that carries ``_meta`` (graphene ``Structure`` is gone —
# S8c).
_TYPE_WRAPPERS = (GraphQLNonNull, GraphQLList, NativeNonNull, NativeList)


def _unwrap_type(current_type: Any) -> Any:
    """Peel list / non-null wrappers to reach the inner node type.

    Mirrors the graphene Structure unwrap the field classes used before S8c,
    but over the native wrapper currency (graphql-core GraphQLList /
    GraphQLNonNull + lazy NativeList / NativeNonNull). Every wrapper
    exposes .of_type, so the loop is uniform.

    Args:
        current_type: A field .type (possibly wrapped).

    Returns:
        The innermost wrapped type (the node class carrying _meta).
    """
    while isinstance(current_type, _TYPE_WRAPPERS):
        current_type = current_type.of_type
    return current_type


def _id_argument() -> Any:
    """Return the id: ID! argument for DjangoObjectField (graphene-free).

    Replaces the graphene ID(required=True, description=...) extra-arg the
    field used to mount. The native compiler's
    to_graphql_argument accepts a graphql-core GraphQLArgument
    verbatim, so this is the byte-equivalent native currency.
    """
    from graphql import GraphQLArgument

    return GraphQLArgument(
        GraphQLNonNull(GraphQLID),
        description="Django object unique identification field",
    )


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
        """Test/no-postgres stand-in for ArrayField (backed by JSON)."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """Capture the base field positional argument, like ArrayField."""
            if args:
                self.base_field = args[0]
            super().__init__(**kwargs)


# *********************************************** #
# *********** FIELD FOR SINGLE OBJECT *********** #
# *********************************************** #
class DjangoObjectField(NativeMountedField):
    """GraphQL field for a single Django model object.

    Mounts an "id: ID!" argument and resolves the matching model instance by
    primary key, applying the output type's "get_queryset" hook and the
    selection-based query optimizer.
    """

    def __init__(self, _type: Any, *args: Any, **kwargs: Any) -> None:
        """Initialize the Django object field.

        Args:
            _type: the GraphQL object type for the resolved model.
            *args: extra positional arguments forwarded to the base field.
            **kwargs: extra keyword arguments forwarded to the base field.
        """
        kwargs["id"] = _id_argument()

        super().__init__(_type, *args, **kwargs)

    @property
    def model(self) -> type[Model]:
        """Return the Django model associated with this field.

        Returns:
            The Django model class backing the field's type.
        """
        return _unwrap_type(self.type)._meta.model

    @staticmethod
    def object_resolver(
        manager: Manager,
        output_type: Any,
        root: Any,
        info: ResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Resolve a single object by its ID, optimized for the selection.

        Args:
            manager: the model manager used to build the queryset.
            output_type: the "DjangoObjectType" subclass for this field,
                forwarded to "queryset_factory" so its "get_queryset" hook
                is applied before the optimizer runs.
            root: the root value of the resolution.
            info: the GraphQL resolve info.
            **kwargs: query arguments, including the object "id".

        Returns:
            The matching model instance, or None when it does not exist.
        """
        id = kwargs.pop("id", None)

        try:
            qs = queryset_factory(
                manager, root, info, output_type=output_type, **kwargs
            )
            return qs.get(pk=id)
        except manager.model.DoesNotExist:
            return None

    def wrap_resolve(self, parent_resolver: Callable) -> Callable:
        """Honor a custom "resolver" if given, else the built-in object resolver.

        When using the built-in "object_resolver", the resolver receives
        "(manager, output_type, root, info, **kwargs)" so the
        "DjangoObjectType.get_queryset" hook can be applied inside
        "queryset_factory".

        When a custom resolver is provided (e.g. "DjangoModelType.retrieve"),
        only the manager is bound -- the caller owns its own signature and
        already manages its own queryset scoping.

        Args:
            parent_resolver: the resolver supplied by the parent field.

        Returns:
            A partial that binds the manager (and output type for the built-in
            resolver) to the resolver.
        """
        if self.resolver:
            # Custom resolver: bind only the manager (preserve caller's sig).
            return partial(self.resolver, self.type._meta.model._default_manager)
        # Built-in resolver: bind manager + output_type so the hook fires.
        return partial(
            self.object_resolver,
            self.type._meta.model._default_manager,
            self.type,
        )


# *********************************************** #
# *************** FIELDS FOR LIST *************** #
# *********************************************** #
class DjangoListField(NativeMountedField):
    """GraphQL field for a list of Django model objects.

    A plain field wrapping "[Type!]". We deliberately do not extend
    graphene-django's "DjangoListField" (which asserts the inner type is its own
    "DjangoObjectType"); this library has its own "DjangoObjectType".
    """

    def __init__(self, _type: Any, *args: Any, **kwargs: Any) -> None:
        """Initialize the Django list field.

        Args:
            _type: the GraphQL object type for each list item.
            *args: extra positional arguments forwarded to the base field.
            **kwargs: extra keyword arguments forwarded to the base field.
        """
        # Unwrap an already-non-null inner type so we never double-wrap into
        # ``[Type!!]``. Covers the native wrappers (``NativeNonNull``), graphql-core
        # (``GraphQLNonNull``), AND a transitional graphene ``NonNull`` (the
        # converter still emits graphene types until S8e) — duck-typed by the
        # ``of_type`` + class-name shape so fields.py stays graphene-free.
        if isinstance(_type, (NativeNonNull, GraphQLNonNull)) or (
            hasattr(_type, "of_type") and type(_type).__name__ == "NonNull"
        ):
            _type = _type.of_type

        super().__init__(NativeList(NativeNonNull(_type)), *args, **kwargs)


def _resolve_custom_filters(_type: Any) -> list:
    """Resolve the @filter_field custom filters declared on a list type's node.

    The custom filters are declared on the node DjangoObjectType (stored as
    _dgx_custom_filters). A DjangoListObjectType wraps that node as its
    _meta.baseType and does NOT carry _dgx_custom_filters directly, so we
    fall back to the baseType lookup. This is the SINGLE source of truth for
    custom-filter propagation across EVERY list-field path (flat, list-object,
    AND nested) — keeping the native <Model>FilterInput shape identical on all
    paths so graphql-core never sees two same-named-but-different filter inputs
    (#1571).

    Args:
        _type: The GraphQL object/list type carrying the model + filter config.

    Returns:
        The list of (arg_name, method, metadata) triples, or [].
    """
    custom_filters = getattr(_type, "_dgx_custom_filters", None)
    if custom_filters is None:
        base_type = getattr(getattr(_type, "_meta", None), "baseType", None)
        custom_filters = getattr(base_type, "_dgx_custom_filters", None) or []
    return custom_filters


def _build_filter_arg(field: NativeMountedField, _type: Any, fields: Any) -> None:
    """Record the filter configuration (backend, fields, custom filters) on a field.

    Stores the resolved filter backend and the type's declared filter_fields
    on the field as backend-agnostic metadata. The native schema compiler
    (native.schema_compiler._filter_arg) reads field.fields /
    field.custom_filters / field.model and builds the native
    <Model>FilterInput (filtering.native_schema.build_filter_input_type)
    when it mounts the field, so no GraphQL input type is constructed here.

    Also picks up @filter_field-decorated methods from the type so the native
    compiler can inject them as scalar arguments in the filter input type.

    Args:
        field: The list field being configured.
        _type: The GraphQL object/list type carrying the model + filter config.
        fields: An explicit filter_fields override, or None to use the
            type's declaration.
    """
    field.filter_backend = resolve_filter_backend()
    field.filter_type = None

    declared_fields = fields if fields is not None else _type._meta.filter_fields
    field.fields = declared_fields

    # Pick up custom @filter_field methods registered on the type or its baseType
    # (DjangoListObjectType wraps a DjangoObjectType as its baseType).
    field.custom_filters = _resolve_custom_filters(_type)


class DjangoFilterListField(NativeMountedField):
    """GraphQL field for a filtered list of Django model objects.

    Mounts a "filter" argument built from the type's "filter_fields" and any
    "@filter_field" methods, then resolves the list by applying the filter
    backend and custom filters to the base queryset.
    """

    def __init__(
        self,
        _type: Any,
        fields: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Initialize the Django filter list field.

        Args:
            _type: the GraphQL object type for each list item.
            fields: filterable field configuration, or None to use the type's.
            *args: extra positional arguments forwarded to the base field.
            **kwargs: extra keyword arguments forwarded to the base field.
        """
        kwargs.setdefault("args", {})
        _build_filter_arg(self, _type, fields)

        if not kwargs.get("description", None):
            kwargs["description"] = f"{_type._meta.model.__name__} list"

        super().__init__(NativeList(_type), *args, **kwargs)

    @property
    def model(self) -> type[Model]:
        """Return the Django model associated with this field.

        Returns:
            The Django model class backing the field's type.
        """
        return _unwrap_type(self.type)._meta.model

    @staticmethod
    def list_resolver(
        manager: Manager,
        filter_backend: Any,
        custom_filters: list,
        output_type: Any,
        root: Any,
        info: ResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Resolve a filtered list of objects.

        Composition order: standard ORM lookups (via "filter_backend") then
        custom "@filter_field" methods ("custom_filters", in declaration
        order). The "get_queryset" hook fires before both filter stages on
        BOTH paths: inside "queryset_factory" for a fresh queryset, and
        explicitly on the related fast path that reads the rows straight off
        the parent's relation accessor.

        Args:
            manager: the model manager used to build the base queryset.
            filter_backend: the native filter backend applied to the queryset.
            custom_filters: list of "(arg_name, method, metadata)" triples
                from "@filter_field"-decorated methods on the output type.
            output_type: the "DjangoObjectType" subclass for this field,
                forwarded to "queryset_factory" so its "get_queryset" hook
                is applied before the optimizer runs.
            root: the root value of the resolution.
            info: the GraphQL resolve info.
            **kwargs: query arguments, including the "filter" value.

        Returns:
            The filtered queryset of model instances.
        """
        qs = None
        field = None
        filter_value = kwargs.get("filter")

        if root and is_valid_django_model(root._meta.model):
            available_related_fields = get_related_fields(root._meta.model)
            field = find_field(info.field_nodes[0], available_related_fields)

        if field is not None:
            try:
                qs = operator.attrgetter(
                    f"{getattr(field, 'related_name', None) or field.name}.all"
                )(root)()
                # The relation accessor bypasses queryset_factory, so the
                # row-level scope must be applied here too -- otherwise the
                # hook enforced at the top level leaks through the parent.
                qs = apply_object_type_get_queryset(qs, output_type, info)
                qs = filter_backend.apply(qs, filter_value)
                qs = apply_custom_filters(qs, custom_filters, info, filter_value)
            except AttributeError:
                qs = None

        if qs is None:
            qs = queryset_factory(
                manager, root, info, output_type=output_type, **kwargs
            )
            qs = filter_backend.apply(qs, filter_value)
            qs = apply_custom_filters(qs, custom_filters, info, filter_value)

            if root and is_valid_django_model(root._meta.model):
                extra_filters = get_extra_filters(root, manager.model)
                qs = qs.filter(**extra_filters)

        return maybe_queryset(qs)

    def wrap_resolve(self, parent_resolver: Callable) -> Callable:
        """Honor a custom "resolver" if given, else the built-in list resolver.

        When using the built-in "list_resolver", the resolver receives
        "(manager, filter_backend, custom_filters, output_type, root, info, **kwargs)"
        so the "DjangoObjectType.get_queryset" hook can be applied inside
        "queryset_factory" and "@filter_field" methods run after standard
        lookups.

        When a custom resolver is provided, only "(manager, filter_backend)"
        are bound -- the caller owns its own signature.

        Args:
            parent_resolver: the resolver supplied by the parent field.

        Returns:
            A partial that binds the leading positional arguments.
        """
        current_type = _unwrap_type(self.type)
        if self.resolver:
            # Custom resolver: bind only (manager, filter_backend).
            return partial(
                self.resolver,
                current_type._meta.model._default_manager,
                self.filter_backend,
            )
        custom_filters = getattr(self, "custom_filters", None) or []
        # Built-in resolver: bind (manager, filter_backend, custom_filters, output_type).
        return partial(
            self.list_resolver,
            current_type._meta.model._default_manager,
            self.filter_backend,
            custom_filters,
            current_type,
        )


class DjangoFilterPaginateListField(NativeMountedField):
    """GraphQL field for a filtered and paginated list of Django model objects.

    Extends the filtered-list behaviour with a pagination instance whose
    arguments the native compiler mounts; the resolver applies the filter
    backend, custom filters, and then paginates the resulting queryset.
    """

    def __init__(
        self,
        _type: Any,
        pagination: BaseDjangoGraphqlPagination | None = None,
        fields: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Initialize the Django filter paginate list field.

        Args:
            _type: the GraphQL object type for each list item.
            pagination: a pagination instance, or None to use the default.
            fields: filterable field configuration, or None to use the type's.
            *args: extra positional arguments forwarded to the base field.
            **kwargs: extra keyword arguments forwarded to the base field.
        """
        kwargs.setdefault("args", {})
        _build_filter_arg(self, _type, fields)

        if pagination is None:
            # Resolve the global default safely: DEFAULT_PAGINATION_CLASS may be
            # None, in which case the field simply has no pagination.
            default_paginator_class = graphql_api_settings.DEFAULT_PAGINATION_CLASS
            pagination = default_paginator_class() if default_paginator_class else None

        if pagination is not None:
            assert isinstance(pagination, BaseDjangoGraphqlPagination), (
                'You need to pass a valid DjangoGraphqlPagination in DjangoFilterPaginateListField, received "{}".'
            ).format(pagination)

            # The ordering allowlist is NOT stamped here. It is a per-SCHEMA
            # fact — which columns the node type publishes is decided by the
            # compiled type the schema being built holds, and this class body
            # can only name the class-def canonical instance, which is a
            # different object. ``schema_compiler._rescoped_paginate_field``
            # stamps a copy of this field and of this paginator against the
            # served node type instead, on every mount path (root fields and a
            # relation declared on a node type both route through
            # ``_build_filter_list_field``). Leaving the shared instance
            # untouched here is what lets one paginator back several fields in
            # several schemas without the last one built deciding for the rest.
            self.pagination = pagination

            # The native compiler (schema_compiler) wires pagination args
            # directly onto the list-container's ``results`` field, so the
            # pagination's graphene ``to_graphql_fields()`` are NOT mounted here.

        if not kwargs.get("description", None):
            kwargs["description"] = f"{_type._meta.model.__name__} list"

        super().__init__(NativeList(NativeNonNull(_type)), *args, **kwargs)

    @property
    def model(self) -> type[Model]:
        """Return the Django model associated with this field.

        Returns:
            The Django model class backing the field's type.
        """
        return _unwrap_type(self.type)._meta.model

    def get_queryset(
        self, manager: Manager, root: Any, info: ResolveInfo, **kwargs: Any
    ) -> Any:
        """Return the base queryset for this field, including the output type hook.

        Args:
            manager: the model manager used to build the queryset.
            root: the root value of the resolution.
            info: the GraphQL resolve info.
            **kwargs: query arguments.

        Returns:
            The base queryset built for the request (hook applied).
        """
        current_type = _unwrap_type(self.type)
        return queryset_factory(manager, root, info, output_type=current_type, **kwargs)

    def list_resolver(
        self,
        manager: Manager,
        filter_backend: Any,
        root: Any,
        info: ResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Resolve a filtered and paginated list of objects.

        Composition order: standard ORM lookups (via "filter_backend") then
        custom "@filter_field" methods (from "self.custom_filters").

        Args:
            manager: the model manager used to build the base queryset.
            filter_backend: the native filter backend applied to the queryset.
            root: the root value of the resolution.
            info: the GraphQL resolve info.
            **kwargs: query arguments, including filter and pagination values.

        Returns:
            The filtered and paginated queryset of model instances.
        """
        filter_value = kwargs.get("filter")
        qs = self.get_queryset(manager, root, info, **kwargs)
        qs = filter_backend.apply(qs, filter_value)

        # Apply custom @filter_field methods in declaration order.
        custom_filters = getattr(self, "custom_filters", None) or []
        qs = apply_custom_filters(qs, custom_filters, info, filter_value)

        if root and is_valid_django_model(root._meta.model):
            extra_filters = get_extra_filters(root, manager.model)
            qs = qs.filter(**extra_filters)

        if getattr(self, "pagination", None):
            qs = self.pagination.paginate_queryset(qs, **kwargs)

        return maybe_queryset(qs)

    def wrap_resolve(self, parent_resolver: Callable) -> Callable:
        """Honor a custom "resolver" if given, else the built-in list resolver.

        The resolver receives (manager, filter_backend) as its leading
        positional arguments, then root, info, **kwargs.

        Args:
            parent_resolver: the resolver supplied by the parent field.

        Returns:
            A partial that binds the manager and filter backend.
        """
        resolver = self.resolver or self.list_resolver
        current_type = _unwrap_type(self.type)
        return partial(
            resolver,
            current_type._meta.model._default_manager,
            self.filter_backend,
        )


class DjangoListObjectField(NativeMountedField):
    """GraphQL field for Django list objects with count and results.

    Resolves a "DjangoListObjectType" wrapper exposing both a "results" list
    and a lazily computed "totalCount", built from the filtered base queryset.
    """

    def __init__(
        self,
        _type: Any,
        fields: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Initialize the Django list object field.

        Args:
            _type: the GraphQL list object type to resolve.
            fields: filterable field configuration, or None to use the type's.
            *args: extra positional arguments forwarded to the base field.
            **kwargs: extra keyword arguments forwarded to the base field.
        """
        kwargs.setdefault("args", {})
        _build_filter_arg(self, _type, fields)

        if not kwargs.get("description", None):
            kwargs["description"] = f"{_type._meta.model.__name__} list"

        super().__init__(_type, *args, **kwargs)

    @property
    def model(self) -> type[Model]:
        """Return the Django model associated with this field.

        Returns:
            The Django model class backing the field's type.
        """
        return self.type._meta.model

    def list_resolver(
        self,
        manager: Manager,
        filter_backend: Any,
        output_type: Any,
        root: Any,
        info: ResolveInfo,
        **kwargs: Any,
    ) -> DjangoListObjectBase:
        """Resolve a list object with count and results.

        Args:
            manager: the model manager used to build the base queryset.
            filter_backend: the native filter backend applied to the queryset.
            output_type: the "DjangoObjectType" subclass for the list items,
                forwarded to "queryset_factory" so its "get_queryset" hook
                is applied before the optimizer runs. This is the item type
                ("DjangoListObjectType._meta.baseType"), not the wrapper type.
            root: the root value of the resolution.
            info: the GraphQL resolve info.
            **kwargs: query arguments, including the "filter" value.

        Returns:
            A list object holding the total count and result queryset.
        """
        filter_value = kwargs.get("filter")
        qs = queryset_factory(manager, root, info, output_type=output_type, **kwargs)
        qs = filter_backend.apply(qs, filter_value)

        # Apply custom @filter_field methods in declaration order.
        custom_filters = getattr(self, "custom_filters", None) or []
        qs = apply_custom_filters(qs, custom_filters, info, filter_value)

        # LAZY totalCount: pass a supplier instead of calling qs.count() here.
        # The COUNT query is deferred to first access of DjangoListObjectBase.count
        # (i.e. only when the client selects totalCount), saving ~1 SQL + ~1.4ms
        # per request otherwise. count() clones the queryset, so the deferred call
        # is correct even after the results were iterated.
        return DjangoListObjectBase(
            count=lambda qs=qs: qs.count(),
            results=maybe_queryset(qs),
            results_field_name=self.type._meta.results_field_name,
        )

    def wrap_resolve(self, parent_resolver: Callable) -> Callable:
        """Honor a custom "resolver" if given, else the built-in list resolver.

        The resolver receives (manager, filter_backend, output_type) as its
        leading positional arguments, then root, info, **kwargs.

        The "output_type" is the item type
        ("DjangoListObjectType._meta.baseType") so that
        "DjangoObjectType.get_queryset" is applied inside
        "queryset_factory" before the optimizer runs.

        When "Meta.queryset" is set on the list type, that queryset is used
        as the base (in place of "_default_manager") so user-supplied filters
        such as ".filter(is_active=True)" are applied on every request.

        Args:
            parent_resolver: the resolver supplied by the parent field.

        Returns:
            A partial that binds the queryset (or manager), filter backend,
            and item output type.
        """
        # Prefer Meta.queryset over _default_manager when the list type declared one.
        meta_queryset = getattr(self.type._meta, "queryset", None)
        base = (
            meta_queryset
            if meta_queryset is not None
            else self.type._meta.model._default_manager
        )
        if self.resolver:
            # Custom resolver (e.g. DjangoModelType.list): bind only
            # (manager, filter_backend) — the caller owns its own signature and
            # manages its own queryset scoping (no output_type threading).
            return partial(
                self.resolver,
                base,
                self.filter_backend,
            )
        # Built-in list_resolver: also bind the item output type so that
        # DjangoObjectType.get_queryset fires inside queryset_factory.
        # item_type is the DjangoObjectType backing the list
        # (DjangoListObjectType._meta.baseType).  DjangoModelType does NOT
        # carry _dgx_has_object_type_get_queryset so it is unaffected even if
        # the item_type lookup returns something unexpected.
        item_type = getattr(self.type._meta, "baseType", None)
        return partial(
            self.list_resolver,
            base,
            self.filter_backend,
            item_type,
        )


class DjangoNestedListObjectField(DjangoListObjectField):
    """Nested "results" plus "totalCount" list scoped to a parent's relation.

    Reuse the "DjangoListObjectField" shape, pagination, and ordering
    machinery; only the base queryset changes: it comes from the parent
    instance's relation accessor. When no filters are supplied it reads the
    relation through list(manager.all()) so the parent query's
    "prefetch_related" cache is used (no extra query, in-memory pagination on
    the "results" field). When filters are supplied it falls back to a
    per-parent DB query (the native backend needs a queryset).
    """

    def __init__(
        self,
        _type: Any,
        accessor: str | None = None,
        fields: Any = None,
        **kwargs: Any,
    ) -> None:
        """Store the "accessor" and build the field, filter only if declared.

        Unlike "DjangoListObjectField", a "filter" argument is built only when
        the list type declares filter config ("filter_fields"). Auto-generated
        nested list types without filters get no filter argument.

        Args:
            _type: the GraphQL list object type to resolve.
            accessor: the parent attribute name for the related set.
            fields: filterable field configuration, or None to use the type's.
            **kwargs: extra keyword arguments forwarded to the base field.
        """
        self.accessor = accessor
        self.filter_backend = resolve_filter_backend()
        self.filter_type = None

        declared_fields = fields if fields is not None else _type._meta.filter_fields
        self.fields = declared_fields
        # Propagate the node type's @filter_field custom filters EXACTLY like
        # DjangoListObjectField does (via _resolve_custom_filters). Without this the
        # nested filter input would drop them while the root/flat path keeps them,
        # producing two DIFFERENT-shaped GraphQLInputObjectType instances sharing
        # the name <Model>FilterInput -> graphql-core duplicate-name TypeError at
        # schema assembly (#1571). It also makes nested `results(filter:{search:…})`
        # consistent with the runtime list_resolver, which already reads
        # self.custom_filters via apply_custom_filters.
        self.custom_filters = _resolve_custom_filters(_type)
        # The native schema compiler builds the ``<Model>FilterInput`` and mounts
        # the ``filter`` arg from ``self.fields`` / ``self.filter_backend`` when it
        # compiles this field, so no GraphQL input type is constructed here.

        if not kwargs.get("description", None):
            kwargs["description"] = f"{_type._meta.model.__name__} list"

        # Skip DjangoListObjectField.__init__ (it would always build the arg).
        NativeMountedField.__init__(self, _type, **kwargs)

    def apply_filters(
        self,
        qs: Any,
        filter_backend: Any,
        filter_value: Any,
        info: Any,
    ) -> Any:
        """Apply the standard lookups AND the custom "@filter_field" methods.

        The single choke point for filtering on the nested path. The nested
        "<Model>FilterInput" is the SAME input type the top-level list mounts,
        so it advertises the node type's "@filter_field" arguments too; running
        only the backend lookups here made every one of those arguments a
        silent no-op on the nested path (wrong rows, and a hole when a custom
        filter is used for scoping). Composition order matches the top-level
        list resolvers: standard lookups first, custom methods after, in
        declaration order.

        Args:
            qs: The base queryset for the related set.
            filter_backend: The filter backend applied to the queryset.
            filter_value: The filter input value, or None.
            info: The GraphQL resolve info, forwarded to the custom methods.

        Returns:
            The queryset after both filter stages.
        """
        qs = filter_backend.apply(qs, filter_value)
        return apply_custom_filters(qs, self.custom_filters, info, filter_value)

    def build_prefetch(
        self, lookup: str, filter_value: Any, info: ResolveInfo
    ) -> Prefetch:
        """Build a "Prefetch" of the related set, filtered by "filter_value".

        Only the filter is applied here: ordering and pagination happen in memory
        downstream (on the "results" field), so the queryset is order-agnostic.
        Used by the optimizer to fetch a filtered nested list in one query for
        all parents (no per-parent N+1).

        Args:
            lookup: the relation lookup path to prefetch.
            filter_value: the filter input value applied to the related set.
            info: the GraphQL resolve info.

        Returns:
            A Prefetch object for the filtered related set.
        """
        model = self.type._meta.model
        qs = model._default_manager.all()
        qs = self.apply_filters(qs, self.filter_backend, filter_value, info)
        return Prefetch(lookup, queryset=qs)

    def build_window_prefetch(
        self,
        lookup: str,
        filter_value: Any,
        slice_tuple: tuple[int, int, list[str]] | None,
        related_field: Any,
        sub_selection: Any,
        fragments: dict[str, Any],
        child_gql_type: Any = None,
        child_graphene_type: Any = None,
        hook: Any = None,
        info: Any = None,
    ) -> Prefetch | None:
        """Build a window-function Prefetch that DB-side slices the nested list.

        Returns a "Prefetch" with a queryset annotated with "_gqx_rn"
        (ROW_NUMBER) and "_gqx_total" (COUNT(*)) window functions, filtered to
        the page window, so only the requested page rows are fetched per parent.

        Returns None when any applicability pre-check fails, signalling the
        caller to fall back to "build_prefetch".

        Wired into the live walker in C3. Results land in
        "root._gqx_win_<accessor>" via "to_attr" so "list_resolver" can
        distinguish an offset-beyond-end empty page from a genuine zero-child
        parent.

        Args:
            lookup: the ORM prefetch lookup path (e.g. "posts").
            filter_value: the user-supplied filter input, or None.
            slice_tuple: the "(offset, limit, ordering)" tuple from
                "paginator.prefetch_window_slice()", or None.
            related_field: the Django relation field for the reverse FK.
            sub_selection: the GraphQL "SelectionSetNode" for the child
                selection, or None (triggers full-load fallback).
            fragments: fragment definitions from the GraphQL resolve info.
            child_gql_type: the inner (row) "GraphQLObjectType" for the child
                selection -- NOT the "DjangoListObjectType" wrapper. Required
                for "AnnotatedField" self-collection (phase-d 7).
            child_graphene_type: the graphene type corresponding to
                "child_gql_type".
            hook: an optional "optimize_<field>" queryset hook applied to the
                filtered base queryset before the window expressions.
            info: the GraphQL resolve info, or None.

        Returns:
            A "Prefetch" with a window-annotated queryset, or None.
        """
        # --- Pre-check 1: OPTIMIZE_NESTED_PAGINATION setting --------------------
        # Access via module reference so override_settings reload is respected.
        if not _settings_module.graphql_api_settings.OPTIMIZE_NESTED_PAGINATION:
            return None

        # --- Pre-check 2: paginator declined (Cursor / unbounded / page<0) ------
        if slice_tuple is None:
            return None

        # --- Pre-check 3: M2M relation ------------------------------------------
        if getattr(related_field, "many_to_many", False):
            return None

        # --- Pre-check 4: must be one_to_many (reverse FK) with an FK field -----
        if not getattr(related_field, "one_to_many", False):
            return None
        fk_field = getattr(related_field, "field", None)
        if fk_field is None:
            return None
        fk_attname = fk_field.attname  # e.g. "author_id"

        offset, limit, order = slice_tuple

        # --- Pre-check 5: all ordering terms must be concrete attnames ----------
        child = self.type._meta.model
        concrete_attnames = {f.attname for f in child._meta.concrete_fields}
        # Narrow to what the child TYPE exposes. This path applies the ORDER BY
        # in SQL and hands back rows already sliced (``already_paginated``), so
        # ``paginate_queryset`` — and with it the ordering allowlist — never
        # runs: accepting a projected-away column here would sort by it and no
        # later guard would see the term. Declining instead routes the query to
        # the plain prefetch path, which rejects it with the same error the root
        # list gives.
        #
        # ``slice_tuple`` carries the resolved ordering but not its PROVENANCE,
        # so a paginator whose configured ``ordering=`` names a projected-away
        # column is declined here too. That costs the window optimization on
        # exactly that configuration; it never costs correctness, because the
        # plain prefetch path it falls back to applies the allowlist to the
        # client argument only and serves the operator's default unchanged.
        #
        # The allowlist is derived from ``child_gql_type`` — THIS schema's row
        # type, threaded in by the walker — rather than read off a paginator
        # instance the schemas share. A caller that passes no row type gets the
        # empty allowlist and the optimization simply declines, which is the
        # documented fallback above.
        concrete_attnames &= projected_ordering_attnames(child, child_gql_type)
        # order may be a comma-separated string ("id,-title") or an iterable of
        # strings. Normalize to a list of individual terms, converting any
        # camelCase spelling to its snake_case attname (``authorId`` ->
        # ``author_id``) via the SAME canonical helper the paginators use, so
        # the window optimization does NOT decline for a camelCase term and the
        # window ORDER BY built below emits real column expressions.
        if not order:
            order_terms: list[str] = [child._meta.pk.attname]
        else:
            order_terms = _split_ordering(order)
        for term in order_terms:
            col = term.lstrip("-+").split(LOOKUP_SEP)[0]
            if col not in concrete_attnames:
                return None

        # --- Pre-check 6: full-load detection ----------------------------------
        # When sub_selection is None we can't know which columns are needed,
        # but we also can't call _compute_child_only (requires a selection set).
        # Fall back to no-narrow (plan=None means skip .only()).
        plan = None
        if sub_selection is not None:
            plan = _compute_child_only(
                child,
                related_field,
                sub_selection,
                fragments,
                child_gql_type=child_gql_type,
                child_graphene_type=child_graphene_type,
            )
            if plan is None:
                # _collect_only_fields_is_full_load returned True → fall back
                return None

        # --- Pre-check 6b: aggregate-over-relation decline (phase-d §7 ADR-D4) --
        # A relation-traversing aggregate (e.g. Count("comments")) forces GROUP BY,
        # which does NOT compose with Window() in the same queryset.  Detect
        # structurally at build time via expr.contains_aggregate and return None
        # so the caller falls back to build_prefetch (plain prefetch path with the
        # annotation applied there via _narrow_plain_prefetch).
        if plan is not None and plan.child_annotations:
            for _ann_expr in plan.child_annotations.values():
                if getattr(_ann_expr, "contains_aggregate", False):
                    return None

        # --- Build the window queryset -----------------------------------------
        qs = child._default_manager.all()
        qs = self.apply_filters(qs, self.filter_backend, filter_value, info)

        # --- Phase E (AC1): apply optimize_<field> hook on filter-applied base qs
        # BEFORE pre-check 7 so a hook adding .distinct() triggers the clean
        # window opt-out (AC5). is_window=True because the final path is window.
        qs = _apply_field_hook(
            qs, hook, info, filter_value=filter_value, is_window=True
        )

        # --- Pre-check 7: G5 — filter forces .distinct() (to-many traversal) ---
        # Re-run on hook-modified qs (AC5): a hook adding .distinct() falls back.
        if getattr(getattr(qs, "query", None), "distinct", False):
            return None

        # Snapshot the queryset the window page is computed from, BEFORE the
        # window expressions: it is exactly the row set the empty-page count
        # must report.  Rebuilding it from the default manager (as this used to)
        # dropped both the custom filters and the optimize_<field> hook, so the
        # overshoot page reported a different — and unscoped — total.
        _cnt_base_qs = qs

        # Build order expressions for the window ORDER BY.
        order_exprs = [
            F(t.lstrip("-+")).desc() if t.startswith("-") else F(t.lstrip("-+")).asc()
            for t in order_terms
        ]

        # --- Phase-d §7: apply user concrete-column annotation BEFORE window exprs --
        # alias() first, then annotate() so that alias-backed expressions resolve.
        # Wrap in a targeted try/except: nested-Window or invalid expressions raise
        # FieldError at build time → return None to fall back to build_prefetch.
        if plan is not None and (plan.child_aliases or plan.child_annotations):
            try:
                if plan.child_aliases:
                    qs = qs.alias(**plan.child_aliases)
                if plan.child_annotations:
                    qs = qs.annotate(**plan.child_annotations)
            except Exception:  # noqa: BLE001 — includes FieldError, ValueError
                # Graceful fallback: return None so caller uses build_prefetch.
                return None

        qs = qs.annotate(
            _gqx_rn=Window(
                RowNumber(), partition_by=[F(fk_attname)], order_by=order_exprs
            ),
            _gqx_total=Window(Count("*"), partition_by=[F(fk_attname)]),
        )
        qs = qs.filter(_gqx_rn__gt=offset, _gqx_rn__lte=offset + limit)

        # Apply column narrowing only when the spike confirmed .only() survives.
        if SELF_NARROW_VERIFIED and plan is not None and plan.only_cols:
            if plan.child_select:
                qs = qs.select_related(*plan.child_select)
            qs = qs.only(*plan.only_cols)

        # Use to_attr so the resolver can distinguish a window-sliced empty result
        # (offset-beyond-end) from a plain zero-child empty prefetch cache.
        # to_attr stores results as a list on root._gqx_win_<accessor>, separate
        # from _prefetched_objects_cache.
        win_attr = _GQX_WIN_ATTR_PREFIX + self.accessor
        pf = Prefetch(lookup, queryset=qs, to_attr=win_attr)

        # --- #64: attach count-subquery metadata so _apply_optimizations can
        # annotate the parent queryset with a Subquery count.  This lets
        # list_resolver read the count in memory (zero extra queries) when the
        # window-sliced page is empty (offset-beyond-end or zero-child parent).
        #
        # We store a *factory* callable rather than a pre-built expression so
        # the Subquery is freshly constructed per request when needed.  The
        # factory captures the FK-attname and filter-applied queryset; the
        # caller (_apply_optimizations) supplies OuterRef('pk') at annotation time.
        # The base queryset snapshotted above (filters + hook applied, window
        # exprs not yet) is stored on the Prefetch so the annotation counts
        # EXACTLY the rows the window path pages over.
        pf._gqx_cnt_qs = _cnt_base_qs
        pf._gqx_cnt_fk_attname = fk_attname
        pf._gqx_cnt_attr = _GQX_CNT_ATTR_PREFIX + self.accessor

        return pf

    def list_resolver(
        self,
        manager: Manager,
        filter_backend: Any,
        output_type: Any,
        root: Any,
        info: ResolveInfo,
        **kwargs: Any,
    ) -> DjangoListObjectBase:
        """Resolve the nested list, preferring the parent's prefetch cache.

        "output_type" is accepted for signature compatibility with the parent
        class but is intentionally unused here: nested-relation fields resolve
        rows from the parent's prefetch cache or relation accessor, not from a
        fresh top-level queryset, so the item type's "get_queryset" hook is
        not applicable.

        Args:
            manager: the model manager used to build the base queryset.
            filter_backend: the native filter backend applied to the queryset.
            output_type: unused; present for signature compatibility with
                "DjangoListObjectField.list_resolver".
            root: the parent instance owning the related set.
            info: the GraphQL resolve info.
            **kwargs: query arguments, including the "filter" value.

        Returns:
            A list object holding the count and resolved results.
        """
        results_field_name = self.type._meta.results_field_name
        if root is None:
            return DjangoListObjectBase(
                count=0, results=[], results_field_name=results_field_name
            )

        # --- C3: check for window-sliced prefetch first -------------------------
        # build_window_prefetch stores results via to_attr="_gqx_win_<accessor>"
        # so we can distinguish an offset-beyond-end empty result (window active,
        # no rows in this page) from a zero-child parent (never had children).
        # Read filter_value early so the empty-cache branch can apply it.
        filter_value = kwargs.get("filter")

        win_attr = _GQX_WIN_ATTR_PREFIX + self.accessor
        win_results = getattr(root, win_attr, None)
        if win_results is not None:
            # Window-sliced path: rows may be empty (offset-beyond-end or zero-child).
            if win_results:
                # Non-empty page: partition count rides the first row.
                count = win_results[0]._gqx_total
            else:
                # Empty page: ambiguous (zero-child or offset-beyond-end).
                # --- #64 fix: prefer the pre-computed Subquery annotation ------
                # _apply_optimizations annotates the parent QS with a Subquery
                # count under `_gqx_cnt_<accessor>` so we read it in memory
                # instead of issuing a per-parent COUNT (N+1 elimination).
                cnt_attr = _GQX_CNT_ATTR_PREFIX + self.accessor
                _sentinel: Any = object()
                annotated_cnt = getattr(root, cnt_attr, _sentinel)
                if annotated_cnt is not _sentinel:
                    # Annotation is present: Subquery returns None when the parent
                    # has zero children → normalise to 0.
                    count = int(annotated_cnt) if annotated_cnt is not None else 0
                else:
                    # Fallback: issue a count() for backwards compatibility when
                    # the annotation is absent (e.g. a deeper nested list whose
                    # window Prefetch was re-rooted, OPTIMIZE_QUERYSET=False, a
                    # custom resolver that bypassed _apply_optimizations, or a
                    # degraded annotation).  MUST reproduce the row set
                    # build_window_prefetch paged over: the same user filter,
                    # the same custom @filter_field methods, AND the same
                    # optimize_<field> hook -- otherwise the overshoot page
                    # reports a different (and unscoped) total than page one.
                    manager_qs = getattr(root, self.accessor).all()
                    filtered_qs = self.apply_filters(
                        manager_qs, filter_backend, filter_value, info
                    )
                    # info is the resolve info of THIS field, so its parent type
                    # is the level-local owner of the optimize_<field> hook.
                    # Read defensively: direct list_resolver callers may pass a
                    # bare stub (or None) for info.
                    filtered_qs = _apply_field_hook(
                        filtered_qs,
                        _get_field_optimize_hook(
                            getattr(info, "parent_type", None),
                            getattr(info, "field_name", "") or "",
                        ),
                        info,
                        filter_value=filter_value,
                        is_window=True,
                    )
                    count = filtered_qs.count()
            return DjangoListObjectBase(
                count=count,
                results=win_results,
                results_field_name=results_field_name,
                already_paginated=True,
            )

        # If the optimizer prefetched this relation (filtered or full), use the
        # cache as-is and paginate/order it in memory -> no extra query.
        cache = getattr(root, "_prefetched_objects_cache", None) or {}
        if self.accessor in cache:
            results = list(cache[self.accessor])
            return DjangoListObjectBase(
                count=len(results),
                results=results,
                results_field_name=results_field_name,
            )

        related_manager = getattr(root, self.accessor)

        if filter_value:
            qs = self.apply_filters(
                related_manager.all(), filter_backend, filter_value, info
            )
            # LAZY totalCount: defer the COUNT to first .count access (only when
            # totalCount is selected). count() clones qs, safe post-iteration.
            return DjangoListObjectBase(
                count=lambda qs=qs: qs.count(),
                results=maybe_queryset(qs),
                results_field_name=results_field_name,
            )

        # Unfiltered and not prefetched: materialize the relation.
        results = list(related_manager.all())
        return DjangoListObjectBase(
            count=len(results),
            results=results,
            results_field_name=results_field_name,
        )

    def wrap_resolve(self, parent_resolver: Callable) -> Callable:
        """Bind (manager, filter_backend, output_type=None) to the nested resolver.

        Overrides the parent "DjangoListObjectField.wrap_resolve" because
        nested-relation fields obtain their rows from the parent's prefetch
        cache or relation accessor -- not from a fresh top-level queryset -- so
        the item type's "get_queryset" hook must NOT be applied here.
        "output_type" is bound as None; "list_resolver" accepts it for
        signature compatibility but ignores it.

        Wiring "get_queryset" on nested relations would require rebuilding
        the prefetch queryset inside the resolver, which conflicts with the
        window-pagination and prefetch optimizations. The documented hatch for
        per-relation row scoping is to DECLARE the relation on the parent type
        as a "DjangoFilterListField", which replaces this auto-expanded
        container and does apply the hook. A bare "resolve_<rel>" method is not
        the hatch: this method binds "self.resolver or self.list_resolver" and
        never consults the parent class.

        Args:
            parent_resolver: the resolver supplied by the parent field.

        Returns:
            A partial that binds the manager, filter backend, and a None
            output type placeholder.
        """
        resolver = self.resolver or self.list_resolver
        return partial(
            resolver,
            self.type._meta.model._default_manager,
            self.filter_backend,
            None,  # output_type: nested path does not apply get_queryset hook
        )


# ---------------------------------------------------------------------------
# AnnotatedField — declarative annotation-backed GraphQL field (phase-d)
# ---------------------------------------------------------------------------


class AnnotatedField(NativeMountedField):
    """A GraphQL field backed by a Django ORM annotation injected only when selected.

    The annotation is injected into the queryset as
    "qs.alias(**aliases).annotate(**{annotation_name: expression})" -- but ONLY
    when the field appears in the client's selection set. A default resolver reads
    "getattr(root, annotation_name, None)" so no explicit "resolve_<field>" is
    needed.
    """

    def __init__(
        self,
        type_: Any,
        expression: Any,
        aliases: dict | None = None,
        annotation_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the field with its Expression and optional aliases.

        Args:
            type_: the field output type (a graphql-core scalar, e.g.
                "graphql.GraphQLInt").
            expression: a Django "Expression" instance OR a zero-argument
                callable that returns one. Called lazily at injection time so
                the Expression is freshly constructed per request (no Django
                Expression reuse issues).
            aliases: an optional mapping applied via ".alias()" BEFORE
                ".annotate()". Useful when the main expression references an
                intermediate computed column.
            annotation_name: overrides the auto-derived "_gqx_ann_<field_name>"
                key. Use this when the default name would collide with a
                concrete model field attname.
            **kwargs: forwarded to the native field base ("NativeMountedField").
        """
        self.expression = expression
        self.aliases = aliases or {}
        self._explicit_annotation_name = annotation_name
        kwargs.setdefault("resolver", self._default_resolver)
        super().__init__(type_, **kwargs)

    def annotation_name(self, field_name: str) -> str:
        """Return the ORM annotation key for this field.

        Args:
            field_name: The GraphQL/Python field name (camelCase or snake_case).

        Returns:
            "self._explicit_annotation_name" when set, else
            "_gqx_ann_<snake_field_name>".
        """
        return self._explicit_annotation_name or (
            _GQX_ANN_ATTR_PREFIX + to_snake_case(field_name)
        )

    @staticmethod
    def resolve_expression(expr: Any) -> Any:
        """Resolve an expression or callable to a concrete Expression.

        Args:
            expr: A Django Expression instance or a zero-argument callable.

        Returns:
            The Expression instance (called if callable).
        """
        return expr() if callable(expr) else expr

    def _default_resolver(self, root: Any, info: Any, **kwargs: Any) -> Any:
        """Read the annotation value from "root".

        Derives the attribute name at resolve time from "info.field_name" so
        the same instance can be shared across types without a closure-binding
        bug.

        Args:
            root: the model instance returned by the queryset.
            info: the GraphQL resolve info.
            **kwargs: unused resolver arguments.

        Returns:
            The annotation value, or None when absent (field not selected /
            annotation not injected).
        """
        ann = self._explicit_annotation_name or (
            _GQX_ANN_ATTR_PREFIX + to_snake_case(info.field_name)
        )
        return getattr(root, ann, None)
