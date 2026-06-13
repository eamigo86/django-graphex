"""Custom GraphQL fields for Django models with filtering and pagination support."""

from __future__ import annotations

import operator
from functools import partial
from typing import TYPE_CHECKING, Any, Callable

from django.db.models import Count, F, JSONField, Prefetch
from django.db.models.constants import LOOKUP_SEP
from django.db.models.expressions import Window
from django.db.models.functions import RowNumber
from graphene import ID, Argument, Field, List
from graphene.types.structures import NonNull, Structure
from graphene.utils.str_converters import to_snake_case

import django_graphex.settings as _settings_module
from django_graphex.filtering.backend import resolve_filter_backend
from django_graphex.settings import graphql_api_settings

from .base_types import DjangoListObjectBase
from .paginations.pagination import BaseDjangoGraphqlPagination
from .utils import (
    _apply_field_hook,
    _compute_child_only,
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

if TYPE_CHECKING:
    from django.db.models import Manager, Model
    from graphql import GraphQLResolveInfo as ResolveInfo


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


# *********************************************** #
# *********** FIELD FOR SINGLE OBJECT *********** #
# *********************************************** #
class DjangoObjectField(Field):
    """GraphQL field for a single Django model object."""

    def __init__(self, _type: Any, *args: Any, **kwargs: Any) -> None:
        """Initialize the Django object field.

        Args:
            _type: the GraphQL object type for the resolved model.
            *args: extra positional arguments forwarded to the base field.
            **kwargs: extra keyword arguments forwarded to the base field.
        """
        kwargs["id"] = ID(
            required=True, description="Django object unique identification field"
        )

        super().__init__(_type, *args, **kwargs)

    @property
    def model(self) -> type[Model]:
        """Return the Django model associated with this field.

        Returns:
            The Django model class backing the field's type.
        """
        current_type = self.type
        while isinstance(current_type, Structure):
            current_type = current_type.of_type
        return current_type._meta.model

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
            output_type: the ``DjangoObjectType`` subclass for this field,
                forwarded to ``queryset_factory`` so its ``get_queryset`` hook
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

        When using the built-in ``object_resolver``, the resolver receives
        ``(manager, output_type, root, info, **kwargs)`` so the
        ``DjangoObjectType.get_queryset`` hook can be applied inside
        ``queryset_factory``.

        When a custom resolver is provided (e.g. ``DjangoModelType.retrieve``),
        only the manager is bound — the caller owns its own signature and
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
class DjangoListField(Field):
    """GraphQL field for a list of Django model objects.

    A plain ``graphene.Field`` wrapping ``[Type!]``. We deliberately do *not*
    extend graphene-django's ``DjangoListField`` (which asserts the inner type is
    its own ``DjangoObjectType``); this library has its own ``DjangoObjectType``.
    """

    def __init__(self, _type: Any, *args: Any, **kwargs: Any) -> None:
        """Initialize the Django list field.

        Args:
            _type: the GraphQL object type for each list item.
            *args: extra positional arguments forwarded to the base field.
            **kwargs: extra keyword arguments forwarded to the base field.
        """
        if isinstance(_type, NonNull):
            _type = _type.of_type

        super().__init__(List(NonNull(_type)), *args, **kwargs)


def _build_filter_arg(field: Field, _type: Any, fields: Any) -> None:
    """Attach a single ``filter`` argument (the native input type) to a field.

    Builds the recursive ``<Model>FilterInput`` from the type's declared
    ``filter_fields`` via the native filter backend and stores both the backend
    and the input type on the field for the resolver to use.

    Args:
        field: The list field being configured.
        _type: The GraphQL object/list type carrying the model + filter config.
        fields: An explicit ``filter_fields`` override, or None to use the
            type's declaration.
    """
    field.filter_backend = resolve_filter_backend()
    field.filter_type = None

    declared_fields = fields if fields is not None else _type._meta.filter_fields
    field.fields = declared_fields
    if declared_fields:
        field.filter_type = field.filter_backend.build_input_type(
            _type._meta.model, declared_fields, _type._meta.registry
        )


class DjangoFilterListField(Field):
    """GraphQL field for a filtered list of Django model objects."""

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
        if self.filter_type is not None:
            kwargs["args"]["filter"] = Argument(
                self.filter_type, description="Filtering options for the list"
            )

        if not kwargs.get("description", None):
            kwargs["description"] = f"{_type._meta.model.__name__} list"

        super().__init__(List(_type), *args, **kwargs)

    @property
    def model(self) -> type[Model]:
        """Return the Django model associated with this field.

        Returns:
            The Django model class backing the field's type.
        """
        current_type = self.type
        while isinstance(current_type, Structure):
            current_type = current_type.of_type
        return current_type._meta.model

    @staticmethod
    def list_resolver(
        manager: Manager,
        filter_backend: Any,
        output_type: Any,
        root: Any,
        info: ResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Resolve a filtered list of objects.

        Args:
            manager: the model manager used to build the base queryset.
            filter_backend: the native filter backend applied to the queryset.
            output_type: the ``DjangoObjectType`` subclass for this field,
                forwarded to ``queryset_factory`` so its ``get_queryset`` hook
                is applied before the optimizer runs.
            root: the root value of the resolution.
            info: the GraphQL resolve info.
            **kwargs: query arguments, including the ``filter`` value.

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
                qs = filter_backend.apply(qs, filter_value)
            except AttributeError:
                qs = None

        if qs is None:
            qs = queryset_factory(
                manager, root, info, output_type=output_type, **kwargs
            )
            qs = filter_backend.apply(qs, filter_value)

            if root and is_valid_django_model(root._meta.model):
                extra_filters = get_extra_filters(root, manager.model)
                qs = qs.filter(**extra_filters)

        return maybe_queryset(qs)

    def wrap_resolve(self, parent_resolver: Callable) -> Callable:
        """Honor a custom "resolver" if given, else the built-in list resolver.

        When using the built-in ``list_resolver``, the resolver receives
        ``(manager, filter_backend, output_type, root, info, **kwargs)`` so
        the ``DjangoObjectType.get_queryset`` hook can be applied inside
        ``queryset_factory``.

        When a custom resolver is provided, only ``(manager, filter_backend)``
        are bound — the caller owns its own signature.

        Args:
            parent_resolver: the resolver supplied by the parent field.

        Returns:
            A partial that binds the leading positional arguments.
        """
        current_type = self.type
        while isinstance(current_type, Structure):
            current_type = current_type.of_type
        if self.resolver:
            # Custom resolver: bind only (manager, filter_backend).
            return partial(
                self.resolver,
                current_type._meta.model._default_manager,
                self.filter_backend,
            )
        # Built-in resolver: bind (manager, filter_backend, output_type).
        return partial(
            self.list_resolver,
            current_type._meta.model._default_manager,
            self.filter_backend,
            current_type,
        )


class DjangoFilterPaginateListField(Field):
    """GraphQL field for a filtered and paginated list of Django model objects."""

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
        if self.filter_type is not None:
            kwargs["args"]["filter"] = Argument(
                self.filter_type, description="Filtering options for the list"
            )

        if pagination is None:
            # Resolve the global default safely: DEFAULT_PAGINATION_CLASS may be
            # None, in which case the field simply has no pagination.
            default_paginator_class = graphql_api_settings.DEFAULT_PAGINATION_CLASS
            pagination = default_paginator_class() if default_paginator_class else None

        if pagination is not None:
            assert isinstance(pagination, BaseDjangoGraphqlPagination), (
                'You need to pass a valid DjangoGraphqlPagination in DjangoFilterPaginateListField, received "{}".'
            ).format(pagination)

            pagination_kwargs = pagination.to_graphql_fields()

            self.pagination = pagination
            kwargs.update(**pagination_kwargs)

        if not kwargs.get("description", None):
            kwargs["description"] = f"{_type._meta.model.__name__} list"

        super().__init__(List(NonNull(_type)), *args, **kwargs)

    @property
    def model(self) -> type[Model]:
        """Return the Django model associated with this field.

        Returns:
            The Django model class backing the field's type.
        """
        current_type = self.type
        while isinstance(current_type, Structure):
            current_type = current_type.of_type
        return current_type._meta.model

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
        current_type = self.type
        while isinstance(current_type, Structure):
            current_type = current_type.of_type
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

        Args:
            manager: the model manager used to build the base queryset.
            filter_backend: the native filter backend applied to the queryset.
            root: the root value of the resolution.
            info: the GraphQL resolve info.
            **kwargs: query arguments, including filter and pagination values.

        Returns:
            The filtered and paginated queryset of model instances.
        """
        qs = self.get_queryset(manager, root, info, **kwargs)
        qs = filter_backend.apply(qs, kwargs.get("filter"))

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
        current_type = self.type
        while isinstance(current_type, Structure):
            current_type = current_type.of_type
        return partial(
            resolver,
            current_type._meta.model._default_manager,
            self.filter_backend,
        )


class DjangoListObjectField(Field):
    """GraphQL field for Django list objects with count and results."""

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
        if self.filter_type is not None:
            kwargs["args"]["filter"] = Argument(
                self.filter_type, description="Filtering options for the list"
            )

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
        root: Any,
        info: ResolveInfo,
        **kwargs: Any,
    ) -> DjangoListObjectBase:
        """Resolve a list object with count and results.

        Args:
            manager: the model manager used to build the base queryset.
            filter_backend: the native filter backend applied to the queryset.
            root: the root value of the resolution.
            info: the GraphQL resolve info.
            **kwargs: query arguments, including the ``filter`` value.

        Returns:
            A list object holding the total count and result queryset.
        """
        qs = queryset_factory(manager, root, info, **kwargs)
        qs = filter_backend.apply(qs, kwargs.get("filter"))
        count = qs.count()

        return DjangoListObjectBase(
            count=count,
            results=maybe_queryset(qs),
            results_field_name=self.type._meta.results_field_name,
        )

    def wrap_resolve(self, parent_resolver: Callable) -> Callable:
        """Honor a custom "resolver" if given, else the built-in list resolver.

        The resolver receives (manager, filter_backend) as its leading
        positional arguments, then root, info, **kwargs.

        When ``Meta.queryset`` is set on the list type, that queryset is used
        as the base (in place of ``_default_manager``) so user-supplied filters
        such as ``.filter(is_active=True)`` are applied on every request.

        Args:
            parent_resolver: the resolver supplied by the parent field.

        Returns:
            A partial that binds the queryset (or manager) and filter backend.
        """
        resolver = self.resolver or self.list_resolver
        # Prefer Meta.queryset over _default_manager when the list type declared one.
        meta_queryset = getattr(self.type._meta, "queryset", None)
        base = (
            meta_queryset
            if meta_queryset is not None
            else self.type._meta.model._default_manager
        )
        return partial(
            resolver,
            base,
            self.filter_backend,
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

        Unlike "DjangoListObjectField", a ``filter`` argument is built only when
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
        if declared_fields:
            self.filter_type = self.filter_backend.build_input_type(
                _type._meta.model, declared_fields, _type._meta.registry
            )
            if self.filter_type is not None:
                kwargs.setdefault("args", {})
                kwargs["args"]["filter"] = Argument(
                    self.filter_type, description="Filtering options for the list"
                )

        if not kwargs.get("description", None):
            kwargs["description"] = f"{_type._meta.model.__name__} list"

        # Skip DjangoListObjectField.__init__ (it would always build the arg).
        Field.__init__(self, _type, **kwargs)

    def build_prefetch(
        self, lookup: str, filter_value: Any, info: ResolveInfo
    ) -> Prefetch:
        """Build a "Prefetch" of the related set, filtered by ``filter_value``.

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
        qs = self.filter_backend.apply(qs, filter_value)
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

        Returns a ``Prefetch`` with a queryset annotated with ``_gqx_rn``
        (ROW_NUMBER) and ``_gqx_total`` (COUNT(*)) window functions, filtered to
        the page window, so only the requested page rows are fetched per parent.

        Returns ``None`` when any applicability pre-check fails, signalling the
        caller to fall back to ``build_prefetch``.

        Wired into the live walker in C3.  Results land in
        ``root._gqx_win_<accessor>`` via ``to_attr`` so ``list_resolver`` can
        distinguish an offset-beyond-end empty page from a genuine zero-child
        parent.

        Args:
            lookup: the ORM prefetch lookup path (e.g. ``"posts"``).
            filter_value: the user-supplied filter input, or ``None``.
            slice_tuple: ``(offset, limit, ordering)`` from
                ``paginator.prefetch_window_slice()``, or ``None``.
            related_field: the Django relation field for the reverse FK.
            sub_selection: the GraphQL ``SelectionSetNode`` for the child
                selection, or ``None`` (triggers full-load fallback).
            fragments: fragment definitions from the GraphQL resolve info.
            child_gql_type: The inner (row) ``GraphQLObjectType`` for the child
                selection — NOT the ``DjangoListObjectType`` wrapper.  Required
                for ``AnnotatedField`` self-collection (phase-d §7).
            child_graphene_type: The graphene type corresponding to
                ``child_gql_type``.

        Returns:
            A ``Prefetch`` with a window-annotated queryset, or ``None``.
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
        # order may be a comma-separated string ("id,-title") or an iterable of strings.
        # Normalize to a list of individual terms.
        if not order:
            order_terms: list[str] = [child._meta.pk.attname]
        elif isinstance(order, str):
            order_terms = [t for t in order.replace(" ", "").split(",") if t]
        else:
            order_terms = [t for t in order if t]
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
        qs = self.filter_backend.apply(qs, filter_value)

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
        return Prefetch(lookup, queryset=qs, to_attr=win_attr)

    def list_resolver(
        self,
        manager: Manager,
        filter_backend: Any,
        root: Any,
        info: ResolveInfo,
        **kwargs: Any,
    ) -> DjangoListObjectBase:
        """Resolve the nested list, preferring the parent's prefetch cache.

        Args:
            manager: the model manager used to build the base queryset.
            filter_backend: the native filter backend applied to the queryset.
            root: the parent instance owning the related set.
            info: the GraphQL resolve info.
            **kwargs: query arguments, including the ``filter`` value.

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
                # Use a slice-independent count that ignores the page window but
                # MUST apply the same user filter that build_window_prefetch used.
                # Without the filter, the count would reflect the unfiltered partition
                # size (all children) rather than the filtered K that the user
                # requested — a correctness regression for filtered nested lists.
                manager_qs = getattr(root, self.accessor).all()
                filtered_qs = filter_backend.apply(manager_qs, filter_value)
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
            qs = filter_backend.apply(related_manager.all(), filter_value)
            return DjangoListObjectBase(
                count=qs.count(),
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


# ---------------------------------------------------------------------------
# AnnotatedField — declarative annotation-backed GraphQL field (phase-d)
# ---------------------------------------------------------------------------


class AnnotatedField(Field):
    """A GraphQL field backed by a Django ORM annotation injected only when selected.

    The annotation is injected into the queryset as
    ``qs.alias(**aliases).annotate(**{annotation_name: expression})`` — but ONLY
    when the field appears in the client's selection set.  A default resolver reads
    ``getattr(root, annotation_name, None)`` so no explicit ``resolve_<field>`` is
    needed.

    Args:
        type_: The graphene output type (e.g. ``graphene.Int``).
        expression: A Django ``Expression`` instance OR a zero-argument callable
            that returns one.  Called lazily at injection time so the Expression
            is freshly constructed per request (no Django Expression reuse issues).
        aliases: Optional ``dict[str, Expression|callable]`` applied via
            ``.alias()`` BEFORE ``.annotate()``.  Useful when the main expression
            references an intermediate computed column.
        annotation_name: Override the auto-derived ``_gqx_ann_<field_name>`` key.
            Use this when the default name would collide with a concrete model
            field attname.
        **kwargs: Forwarded to ``graphene.Field``.
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

        See the class docstring for the full parameter reference.
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
            ``self._explicit_annotation_name`` when set, else
            ``_gqx_ann_<snake_field_name>``.
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
        """Read the annotation value from ``root``.

        Derives the attribute name at resolve time from ``info.field_name`` so
        the same instance can be shared across types without a closure-binding
        bug.

        Args:
            root: The model instance returned by the queryset.
            info: The GraphQL resolve info.
            **kwargs: Unused resolver arguments.

        Returns:
            The annotation value, or ``None`` when absent (field not selected /
            annotation not injected).
        """
        ann = self._explicit_annotation_name or (
            _GQX_ANN_ATTR_PREFIX + to_snake_case(info.field_name)
        )
        return getattr(root, ann, None)
