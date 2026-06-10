"""Custom GraphQL fields for Django models with filtering and pagination support."""

from __future__ import annotations

import operator
from functools import partial
from typing import TYPE_CHECKING, Any, Callable

from django.db.models import JSONField, Prefetch
from graphene import ID, Argument, Field, List
from graphene.types.structures import NonNull, Structure

from django_graphex.filtering.backend import resolve_filter_backend
from django_graphex.settings import graphql_api_settings

from .base_types import DjangoListObjectBase
from .paginations.pagination import BaseDjangoGraphqlPagination
from .utils import (
    find_field,
    get_extra_filters,
    get_related_fields,
    is_valid_django_model,
    maybe_queryset,
    queryset_factory,
)

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
        manager: Manager, root: Any, info: ResolveInfo, **kwargs: Any
    ) -> Any:
        """Resolve a single object by its ID, optimized for the selection.

        Args:
            manager: the model manager used to build the queryset.
            root: the root value of the resolution.
            info: the GraphQL resolve info.
            **kwargs: query arguments, including the object "id".

        Returns:
            The matching model instance, or None when it does not exist.
        """
        id = kwargs.pop("id", None)

        try:
            qs = queryset_factory(manager, root, info, **kwargs)
            return qs.get(pk=id)
        except manager.model.DoesNotExist:
            return None

    def wrap_resolve(self, parent_resolver: Callable) -> Callable:
        """Honor a custom "resolver" if given, else the built-in object resolver.

        The resolver receives the model manager as its first positional argument:
        resolver(manager, root, info, **kwargs).

        Args:
            parent_resolver: the resolver supplied by the parent field.

        Returns:
            A partial that binds the model's default manager to the resolver.
        """
        resolver = self.resolver or self.object_resolver
        return partial(resolver, self.type._meta.model._default_manager)


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
        root: Any,
        info: ResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Resolve a filtered list of objects.

        Args:
            manager: the model manager used to build the base queryset.
            filter_backend: the native filter backend applied to the queryset.
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
            qs = queryset_factory(manager, root, info, **kwargs)
            qs = filter_backend.apply(qs, filter_value)

            if root and is_valid_django_model(root._meta.model):
                extra_filters = get_extra_filters(root, manager.model)
                qs = qs.filter(**extra_filters)

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
        """Return the base queryset for this field.

        Args:
            manager: the model manager used to build the queryset.
            root: the root value of the resolution.
            info: the GraphQL resolve info.
            **kwargs: query arguments.

        Returns:
            The base queryset built for the request.
        """
        return queryset_factory(manager, root, info, **kwargs)

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

        Args:
            parent_resolver: the resolver supplied by the parent field.

        Returns:
            A partial that binds the manager and filter backend.
        """
        resolver = self.resolver or self.list_resolver
        return partial(
            resolver,
            self.type._meta.model._default_manager,
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
        filter_value = kwargs.get("filter")

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
