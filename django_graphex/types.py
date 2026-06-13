"""GraphQL type definitions for Django models."""

from __future__ import annotations

import warnings
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Manager, QuerySet
from django.utils.functional import SimpleLazyObject
from graphene import (
    ID,
    Argument,
    Boolean,
    Field,
    InputField,
    Int,
    Interface,
    List,
    ObjectType,
    Union,
)
from graphene.types.base import BaseOptions
from graphene.types.inputobjecttype import InputObjectType, InputObjectTypeContainer
from graphene.types.utils import yank_fields_from_attrs
from graphene.utils.deprecated import warn_deprecation
from graphene.utils.props import props
from graphql import GraphQLError

from .backends import resolve_backend
from .base_types import DjangoListObjectBase, factory_type
from .converter import construct_fields
from .errors import ErrorType
from .fields import DjangoListField, DjangoListObjectField, DjangoObjectField
from .native.validators import build_validator_model
from .nested import NestedFieldsMixin
from .paginations.pagination import BaseDjangoGraphqlPagination
from .registry import Registry, get_global_registry
from .settings import graphql_api_settings
from .utils import (
    _apply_optimizations,
    get_Object_or_None,
    is_valid_django_model,
    maybe_queryset,
    not_found_error,
    queryset_factory,
)

if TYPE_CHECKING:
    from django.db.models import Model
    from graphql import GraphQLResolveInfo as ResolveInfo

__all__ = (
    "DjangoObjectType",
    "DjangoInputObjectType",
    "DjangoListObjectType",
    "DjangoModelType",
    "DjangoUnionType",
    "DjangoInterfaceType",
)


class DjangoObjectOptions(BaseOptions):
    """Meta options container for Django object and list GraphQL types."""

    fields = None
    input_fields = None
    interfaces = ()
    model = None
    queryset = None
    registry = None
    connection = None
    create_container = None
    results_field_name = None
    filter_fields = ()
    input_for = None
    #: Max nested-object depth allowed below this type (None = no per-type limit).
    max_deep = None
    #: Cost weight of a field returning this type (None = default weight of 1).
    complexity = None
    #: GFK field name -> companion DjangoUnionType (Track 2). None when the type
    #: declares no GFK unions; the GFK converter falls back to
    #: GenericForeignKeyType in that case.
    gfk_unions = None


class DjangoModelTypeOptions(BaseOptions):
    """Meta options container for the Django model CRUD GraphQL type."""

    model = None
    queryset = None
    #: SerializerBackend handling validate/save/output (native Pydantic).
    backend = None

    arguments = None
    fields = None
    input_fields = None
    input_field_name = None

    mutation_output = None
    output_field_name = None
    output_type = None
    output_list_type = None
    nested_fields = None
    interfaces = ()

    # Subscription integration (optional; requires the [subscriptions] extra).
    stream = None
    serialize_data = None
    subscription_index_fields = ()
    #: Max nested-object depth allowed below this type (None = no per-type limit).
    max_deep = None
    #: Cost weight of a field returning this type (None = default weight of 1).
    complexity = None


class DjangoObjectType(ObjectType):
    """A Django model GraphQL type with enhanced features."""

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        model: type[Model] | None = None,
        registry: Registry | None = None,
        skip_registry: bool = False,
        only_fields: tuple[str, ...] = (),
        exclude_fields: tuple[str, ...] = (),
        include_fields: tuple[str, ...] = (),
        filter_fields: Any = None,
        interfaces: tuple[Any, ...] = (),
        max_deep: int | None = None,
        complexity: int | None = None,
        gfk_unions: dict | None = None,
        **options,
    ) -> None:
        """Initialize the subclass with meta options for a Django object type.

        Args:
            model: Django model this type represents.
            registry: Registry to register this type in; defaults to the
                global registry.
            skip_registry: When True, do not register this type.
            only_fields: Model field names to include exclusively.
            exclude_fields: Model field names to exclude.
            include_fields: Extra model field names to include.
            filter_fields: Field names usable for filtering.
            interfaces: GraphQL interfaces this type implements.
            max_deep: Max nested-object depth allowed below this type, enforced
                by "DepthLimitValidationRule"; "None" means no per-type limit.
            complexity: Cost weight of a field returning this type, used by
                "CostLimitValidationRule"; "None" means the default weight (1).
            gfk_unions: Optional mapping of GenericForeignKey field name to a
                companion "DjangoUnionType" (Track 2). When set, the GFK
                converter emits a typed Union field for that FK instead of the
                flat "GenericForeignKeyType".
            **options: Extra options forwarded to the parent implementation.
        """
        assert is_valid_django_model(model), (
            'You need to pass a valid Django Model in {}.Meta, received "{}".'
        ).format(cls.__name__, model)

        if not registry:
            registry = get_global_registry()

        assert isinstance(registry, Registry), (
            "The attribute registry in {} needs to be an instance of "
            'Registry, received "{}".'
        ).format(cls.__name__, registry)

        django_fields = yank_fields_from_attrs(
            construct_fields(
                model, registry, only_fields, include_fields, exclude_fields
            ),
            _as=Field,
        )

        _meta = DjangoObjectOptions(cls)
        _meta.model = model
        _meta.registry = registry
        _meta.filter_fields = filter_fields
        _meta.fields = django_fields
        _meta.max_deep = max_deep
        _meta.complexity = complexity
        _meta.gfk_unions = dict(gfk_unions) if gfk_unions else None

        super().__init_subclass_with_meta__(
            _meta=_meta, interfaces=interfaces, **options
        )

        if not skip_registry:
            registry.register(cls)

    def resolve_id(self, info: ResolveInfo) -> Any:
        """Resolve the "id" field for the object.

        Args:
            info: GraphQL resolve info for the current request.

        Returns:
            The primary key of the underlying model instance.
        """
        return self.pk

    @classmethod
    def is_type_of(cls, root: Any, info: ResolveInfo) -> bool:
        """Check whether the root object is an instance of this type.

        Args:
            root: Object being resolved.
            info: GraphQL resolve info for the current request.

        Returns:
            True if "root" is compatible with this type.

        Raises:
            Exception: If "root" is not a valid Django model instance.
        """
        if isinstance(root, SimpleLazyObject):
            root._setup()
            root = root._wrapped
        if isinstance(root, cls):
            return True
        if not is_valid_django_model(type(root)):
            raise TypeError(f'Received incompatible instance "{root}".')
        return isinstance(root, cls._meta.model)

    @classmethod
    def get_queryset(cls, queryset: QuerySet, info: ResolveInfo) -> QuerySet:
        """Return the queryset for this type.

        Args:
            queryset: Base queryset to scope.
            info: GraphQL resolve info for the current request.

        Returns:
            The queryset to use, unchanged by default.
        """
        return queryset

    @classmethod
    def get_node(cls, info: ResolveInfo, id: Any) -> Model | None:
        """Return a single node by its primary key.

        Args:
            info: GraphQL resolve info for the current request.
            id: Primary key of the object to fetch.

        Returns:
            The matching model instance, or None if it does not exist.
        """
        try:
            return cls._meta.model.objects.get(pk=id)
        except cls._meta.model.DoesNotExist:
            return None


def _resolve_polymorphic_type(cls: Any, instance: Any, info: ResolveInfo) -> Any:
    """Map a plain Django model instance to its registered DjangoObjectType.

    Shared by "DjangoUnionType" and "DjangoInterfaceType". Each prefetched /
    resolved row is a CONCRETE member model, so ``type(instance)`` yields the
    concrete class and the registry maps it to the right output type.

    Args:
        cls: the union or interface class whose registry is consulted.
        instance: the Django model instance being resolved.
        info: GraphQL resolve info for the current request (unused; kept for the
            graphene ``resolve_type`` signature).

    Returns:
        The registered "DjangoObjectType" subclass for ``type(instance)``.

    Raises:
        TypeError: if no "DjangoObjectType" is registered for the instance's
            model. This is intentional: a silent None would surface later as the
            opaque "Abstract type must resolve to an Object type" runtime error.
    """
    registry = getattr(cls, "_dgx_registry", None) or get_global_registry()
    object_type = registry.get_type_for_model(type(instance))
    if object_type is None:
        raise TypeError(
            "{cls}.resolve_type: no DjangoObjectType registered for "
            "{model!r}. Every member/implementor model must have a "
            "DjangoObjectType registered in the same registry.".format(
                cls=cls.__name__, model=type(instance).__name__
            )
        )
    return object_type


class DjangoUnionType(Union):
    """A GraphQL Union over explicitly enumerated DjangoObjectType members.

    Members are declared via ``Meta.gfk_types`` (a sequence of DjangoObjectType
    subclasses); they are NEVER discovered from the ContentType table.
    ``resolve_type`` maps a resolved Django row to its registered
    DjangoObjectType. ``Meta.possible_types`` is intentionally NOT set (it would
    collide with the DjangoObjectType ``is_type_of`` discrimination).
    """

    class Meta:
        """Meta configuration for DjangoUnionType."""

        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        gfk_types: tuple[Any, ...] = (),
        registry: Registry | None = None,
        _meta: Any = None,
        **options,
    ) -> None:
        """Initialize the union with its explicit member types.

        Args:
            gfk_types: the DjangoObjectType members of this union (>= 1).
            registry: registry to self-register in; defaults to the global one.
            _meta: optional pre-built meta options object.
            **options: extra options forwarded to ``graphene.Union``.
        """
        if not registry:
            registry = get_global_registry()

        member_types = tuple(gfk_types)
        assert member_types, (
            "{} must declare Meta.gfk_types with at least one "
            "DjangoObjectType member.".format(cls.__name__)
        )

        cls._dgx_member_models = tuple(t._meta.model for t in member_types)
        cls._dgx_registry = registry

        # graphene.Union requires a non-empty ``types``; feed the members in.
        super().__init_subclass_with_meta__(types=member_types, _meta=_meta, **options)

        # After super() so ``cls._meta.name`` is set.
        registry.register_polymorphic(cls)

    @classmethod
    def resolve_type(cls, instance: Any, info: ResolveInfo) -> Any:
        """Resolve a Django instance to its registered DjangoObjectType.

        Args:
            instance: the resolved Django model instance.
            info: GraphQL resolve info for the current request.

        Returns:
            The matching "DjangoObjectType" subclass.

        Raises:
            TypeError: if the instance's model has no registered type.
        """
        return _resolve_polymorphic_type(cls, instance, info)


class DjangoInterfaceType(Interface):
    """A GraphQL Interface enabling shared field declarations across types.

    Concrete "DjangoObjectType" subclasses declare membership via the existing
    ``Meta.interfaces`` kwarg. Field sharing is structural (schema-level) only;
    this MVP introduces no new queryset fetch path for interfaces.
    ``resolve_type`` follows the same model→registry→DjangoObjectType contract
    as "DjangoUnionType". ``Meta.possible_types`` is intentionally NOT set.
    """

    class Meta:
        """Meta configuration for DjangoInterfaceType."""

        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        registry: Registry | None = None,
        _meta: Any = None,
        **options,
    ) -> None:
        """Initialize the interface and self-register it.

        Args:
            registry: registry to self-register in; defaults to the global one.
            _meta: optional pre-built meta options object.
            **options: extra options forwarded to ``graphene.Interface``.
        """
        if not registry:
            registry = get_global_registry()

        cls._dgx_registry = registry

        super().__init_subclass_with_meta__(_meta=_meta, **options)

        # After super() so ``cls._meta.name`` is set.
        registry.register_polymorphic(cls)

    @classmethod
    def resolve_type(cls, instance: Any, info: ResolveInfo) -> Any:
        """Resolve a Django instance to its registered DjangoObjectType.

        Args:
            instance: the resolved Django model instance.
            info: GraphQL resolve info for the current request.

        Returns:
            The matching "DjangoObjectType" subclass.

        Raises:
            TypeError: if the instance's model has no registered type.
        """
        return _resolve_polymorphic_type(cls, instance, info)


class DjangoInputObjectType(InputObjectType):
    """A Django model GraphQL input type."""

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        model: type[Model] | None = None,
        container: Any = None,
        registry: Registry | None = None,
        skip_registry: bool = False,
        connection: Any = None,
        use_connection: Any = None,
        only_fields: tuple[str, ...] = (),
        exclude_fields: tuple[str, ...] = (),
        filter_fields: Any = None,
        input_for: str = "create",
        nested_fields: Any = (),
        **options,
    ) -> None:
        """Initialize the subclass with meta options for a Django input type.

        Args:
            model: Django model this input type represents.
            container: Container class used to hold input values; one is
                generated when None.
            registry: Registry to register this type in; defaults to the
                global registry.
            skip_registry: When True, do not register this type.
            connection: Connection type associated with this input type.
            use_connection: Whether to use a connection for this input type.
            only_fields: Model field names to include exclusively.
            exclude_fields: Model field names to exclude.
            filter_fields: Field names usable for filtering.
            input_for: Operation the input is built for ("create", "update"
                or "delete").
            nested_fields: Nested fields to build into the input type.
            **options: Extra options forwarded to the parent implementation.
        """
        assert is_valid_django_model(model), (
            'You need to pass a valid Django Model in {}.Meta, received "{}".'
        ).format(cls.__name__, model)

        if not registry:
            registry = get_global_registry()

        assert isinstance(registry, Registry), (
            "The attribute registry in {} needs to be an instance of "
            'Registry, received "{}".'
        ).format(cls.__name__, registry)

        assert input_for.lower() in ("create", "delete", "update"), (
            'You need to pass a valid input_for value in {}.Meta, received "{}".'
        ).format(cls.__name__, input_for)

        input_for = input_for.lower()

        django_input_fields = yank_fields_from_attrs(
            construct_fields(
                model,
                registry,
                only_fields,
                None,
                exclude_fields,
                input_for,
                nested_fields,
            ),
            _as=InputField,
            sort=False,
        )

        for base in reversed(cls.__mro__):
            django_input_fields.update(
                yank_fields_from_attrs(base.__dict__, _as=InputField)
            )

        if container is None:
            container = type(cls.__name__, (InputObjectTypeContainer, cls), {})

        _meta = DjangoObjectOptions(cls)
        _meta.model = model
        _meta.registry = registry
        _meta.filter_fields = filter_fields
        _meta.fields = django_input_fields
        _meta.input_fields = django_input_fields
        _meta.connection = connection
        _meta.input_for = input_for
        _meta.container = container

        super(InputObjectType, cls).__init_subclass_with_meta__(
            _meta=_meta,
            **options,
        )

        if not skip_registry:
            registry.register(cls, for_input=input_for)

    @classmethod
    def get_type(cls) -> type[DjangoInputObjectType]:
        """Return the type when the unmounted type is mounted.

        This method is called when the unmounted type (an "InputObjectType"
        instance) is mounted as a "Field", "InputField" or "Argument".

        Returns:
            This input object type class.
        """
        return cls


class DjangoListObjectType(ObjectType):
    """A GraphQL type for paginated Django model lists."""

    class Meta:
        """Meta configuration for DjangoListObjectType."""

        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        model: type[Model] | None = None,
        registry: Registry | None = None,
        results_field_name: str | None = None,
        pagination: Any = None,
        only_fields: tuple[str, ...] = (),
        exclude_fields: tuple[str, ...] = (),
        filter_fields: Any = None,
        queryset: QuerySet | None = None,
        max_deep: int | None = None,
        complexity: int | None = None,
        **options,
    ) -> None:
        """Initialize the subclass with meta options for a Django list type.

        Args:
            model: Django model this list type represents.
            registry: Registry to register this type in; defaults to the
                global registry.
            results_field_name: Name of the field holding the result list;
                defaults to "results".
            pagination: Pagination instance to apply to the list.
            only_fields: Model field names to include exclusively.
            exclude_fields: Model field names to exclude.
            filter_fields: Field names usable for filtering.
            queryset: Base queryset used to build the list type.
            max_deep: Max nested-object depth allowed below this list type,
                enforced by "DepthLimitValidationRule"; "None" means no limit.
            complexity: Cost weight of a field returning this list type, used by
                "CostLimitValidationRule"; "None" means the default weight (1).
            **options: Extra options forwarded to the parent implementation.
        """
        assert is_valid_django_model(model), (
            'You need to pass a valid Django Model in {}.Meta, received "{}".'
        ).format(cls.__name__, model)

        if not registry:
            registry = get_global_registry()

        assert isinstance(queryset, QuerySet) or queryset is None, (
            "The attribute queryset in {} needs to be an instance of "
            'Django model queryset, received "{}".'
        ).format(cls.__name__, queryset)

        results_field_name = results_field_name or "results"

        baseType = registry.get_type_for_model(model)

        if not baseType:
            factory_kwargs = {
                "model": model,
                "only_fields": only_fields,
                "exclude_fields": exclude_fields,
                "filter_fields": filter_fields,
                "pagination": pagination,
                "queryset": queryset,
                "registry": registry,
                "skip_registry": False,
            }
            baseType = factory_type("output", DjangoObjectType, **factory_kwargs)

        filter_fields = filter_fields or baseType._meta.filter_fields

        paginator = None
        if pagination:
            paginator = pagination
            result_container = pagination.get_pagination_field(baseType)
        else:
            global_paginator = graphql_api_settings.DEFAULT_PAGINATION_CLASS
            if global_paginator:
                assert issubclass(global_paginator, BaseDjangoGraphqlPagination), (
                    'You need to pass a valid DjangoGraphqlPagination class in {}.Meta, received "{}".'
                ).format(cls.__name__, global_paginator)

                global_paginator = global_paginator()
                paginator = global_paginator
                result_container = global_paginator.get_pagination_field(baseType)
            else:
                result_container = DjangoListField(baseType)

        _meta = DjangoObjectOptions(cls)
        _meta.model = model
        _meta.registry = registry
        _meta.queryset = queryset
        _meta.baseType = baseType
        _meta.results_field_name = results_field_name
        _meta.filter_fields = filter_fields
        _meta.exclude_fields = exclude_fields
        _meta.only_fields = only_fields
        _meta.pagination = pagination
        _meta.max_deep = max_deep
        _meta.complexity = complexity
        _meta.fields = OrderedDict(
            [
                (results_field_name, result_container),
                (
                    "count",
                    Field(
                        Int,
                        name="totalCount",
                        description="Total count of matches elements",
                    ),
                ),
            ]
        )

        # Opt-in pagination metadata: paginators that support it (cursor) expose
        # a `pageInfo` field; others return None and add nothing.
        if paginator is not None:
            page_info_field = paginator.get_page_info_field(baseType)
            if page_info_field is not None:
                _meta.fields["page_info"] = page_info_field

        super().__init_subclass_with_meta__(_meta=_meta, **options)

        # Register as the model's canonical `list` type so nested relations can
        # reuse it (honoring this type's pagination/filter config). Last one wins.
        registry.register_list_type(model, cls)

    @classmethod
    def RetrieveField(cls, *args, **kwargs) -> DjangoObjectField:
        """Create a field for retrieving a single object.

        Args:
            *args: Positional arguments (currently unused).
            **kwargs: Keyword arguments forwarded to the field.

        Returns:
            A field that resolves a single object of the base type.
        """
        return DjangoObjectField(cls._meta.baseType, **kwargs)

    @classmethod
    def BaseType(cls) -> type[DjangoObjectType]:
        """Return the base GraphQL type for this list type.

        Returns:
            The base object type wrapped by this list type.
        """
        return cls._meta.baseType


def get_or_create_list_object_type(
    model: type[Model], registry: Registry | None = None
) -> type[DjangoListObjectType]:
    """Return the model's registered list type, creating one if needed.

    Reuses a user-defined or model list type (so its "pagination" and
    "filter_fields" are honored when the model appears nested under another
    model). Falls back to an auto-generated list type using the default
    paginator ("DEFAULT_PAGINATION_CLASS" or "LimitOffsetGraphqlPagination").

    Args:
        model: Django model whose list type is requested.
        registry: Registry to look up and register in; defaults to the global
            registry.

    Returns:
        The existing or newly created "DjangoListObjectType" subclass.
    """
    if registry is None:
        registry = get_global_registry()

    existing = registry.get_list_type_for_model(model)
    if existing is not None:
        return existing

    paginator_cls = graphql_api_settings.DEFAULT_PAGINATION_CLASS
    if paginator_cls is not None:
        pagination = paginator_cls()
    else:
        from .paginations.pagination import LimitOffsetGraphqlPagination

        pagination = LimitOffsetGraphqlPagination()

    # Inherit the node type's filter config so nested lists stay filterable.
    node = registry.get_type_for_model(model)
    filter_fields = getattr(node._meta, "filter_fields", None) if node else None

    # factory_type builds a DjangoListObjectType subclass which self-registers.
    return factory_type(
        "list",
        DjangoListObjectType,
        model=model,
        pagination=pagination,
        registry=registry,
        filter_fields=filter_fields,
    )


class DjangoModelType(NestedFieldsMixin, ObjectType):
    """DjangoModelType definition."""

    ok = Boolean(description="Boolean field that return mutation result request.")
    errors = List(ErrorType, description="Errors list for the field")

    #: Permission classes checked per action before each CRUD operation. Empty
    #: (the default) means no checks. See "django_graphex.permissions".
    permission_classes = ()

    class Meta:
        """Meta configuration for DjangoModelType."""

        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        model: Any = None,
        pydantic_model: Any = None,
        queryset: QuerySet | None = None,
        only_fields: tuple[str, ...] = (),
        include_fields: tuple[str, ...] = (),
        exclude_fields: tuple[str, ...] = (),
        pagination: Any = None,
        input_field_name: str | None = None,
        output_field_name: str | None = None,
        results_field_name: str | None = None,
        nested_fields: Any = (),
        filter_fields: Any = None,
        description: str = "",
        stream: str | None = None,
        serialize_data: bool | None = None,
        subscription_index_fields: tuple[str, ...] | list[str] | None = None,
        max_deep: int | None = None,
        complexity: int | None = None,
        **options,
    ) -> None:
        """Initialize the subclass with meta options for a model type.

        Args:
            queryset: Base queryset used for retrieve and list operations.
            only_fields: Model field names to include exclusively.
            include_fields: Extra model field names to include.
            exclude_fields: Model field names to exclude.
            pagination: Pagination instance to apply to list results.
            input_field_name: Name of the mutation input argument.
            output_field_name: Name of the field holding the mutation output.
            results_field_name: Name of the field holding list results.
            nested_fields: Nested fields to build into the input types.
            filter_fields: Field names usable for filtering.
            description: GraphQL description for this type.
            stream: Subscription stream name; required to expose a subscription.
            serialize_data: Force full or id-only subscription payloads, or
                "None" to inherit the global setting.
            subscription_index_fields: Optional model field names routing
                notifications to value-scoped groups (only matching subscribers
                are woken). Must be a subset of what "subscription_scope" returns.
            max_deep: Max nested-object depth allowed below this type's output
                type, enforced by "DepthLimitValidationRule"; "None" = no limit.
            complexity: Cost weight of a field returning this type's output type,
                used by "CostLimitValidationRule"; "None" = default weight (1).
            **options: Extra options forwarded to the parent implementation.

        Raises:
            ImproperlyConfigured: If "Meta.model" is not provided.
        """
        pydantic_model = build_validator_model(cls, model, pydantic_model)
        backend = resolve_backend(model, pydantic_model=pydantic_model)
        model = backend.get_model()

        description = description or f"DjangoModelType for {model.__name__} model"

        input_field_name = input_field_name or f"new_{model._meta.model_name}"
        output_field_name = output_field_name or model._meta.model_name

        input_class = getattr(cls, "Arguments", None)
        if not input_class:
            input_class = getattr(cls, "Input", None)
            if input_class:
                warn_deprecation(
                    (
                        "Please use {name}.Arguments instead of {name}.Input."
                        "Input is now only used in ClientMutationID.\nRead more: "
                        "https://github.com/graphql-python/graphene/blob/2.0/UPGRADE-v2.0.md#mutation-input"
                    ).format(name=cls.__name__)
                )
        if input_class:
            arguments = props(input_class)
        else:
            arguments = {}

        registry = get_global_registry()

        # Custom graphene fields declared on this DjangoModelType -- or on
        # any of its bases up to (but excluding) DjangoModelType, e.g. an
        # abstract mixin -- are collected and added to the generated output type,
        # so a separate DjangoObjectType is not required just to expose extra
        # fields. Bases are walked first so a subclass can override an inherited
        # field; the base DjangoModelType is skipped because its `ok` /
        # `errors` are wrapper fields, not output fields. The collected fields are
        # later kept off the wrapper type itself (see below).
        extra_fields: dict = {}
        for klass in reversed(cls.__mro__):
            if issubclass(klass, DjangoModelType) and klass is not DjangoModelType:
                extra_fields.update(
                    yank_fields_from_attrs(dict(vars(klass)), _as=Field)
                )

        # Forward each custom field's `resolve_<name>` method (most-derived wins)
        # onto the generated output type so the field resolves through it.
        extra_resolvers: dict = {}
        for klass in reversed(cls.__mro__):
            if issubclass(klass, DjangoModelType) and klass is not DjangoModelType:
                for attr_name, attr in vars(klass).items():
                    if (
                        attr_name.startswith("resolve_")
                        and attr_name[len("resolve_") :] in extra_fields
                        and callable(attr)
                    ):
                        extra_resolvers[attr_name] = attr

        factory_kwargs = {
            "model": model,
            "only_fields": only_fields,
            "include_fields": include_fields,
            "exclude_fields": exclude_fields,
            "filter_fields": filter_fields,
            "pagination": pagination,
            "queryset": queryset,
            "nested_fields": nested_fields,
            "registry": registry,
            "skip_registry": False,
            "results_field_name": results_field_name,
            "extra_fields": extra_fields,
            "extra_resolvers": extra_resolvers,
            "max_deep": max_deep,
            "complexity": complexity,
        }

        output_type = registry.get_type_for_model(model)

        if not output_type:
            output_type = factory_type("output", DjangoObjectType, **factory_kwargs)
        elif extra_fields:
            warnings.warn(
                "{name}: custom fields declared on the type are ignored because a "
                "DjangoObjectType is already registered for {model}; declare them on "
                "that DjangoObjectType instead.".format(
                    name=cls.__name__, model=model.__name__
                ),
                stacklevel=2,
            )

        output_list_type = factory_type("list", DjangoListObjectType, **factory_kwargs)

        django_fields = OrderedDict({output_field_name: Field(output_type)})

        global_arguments = {}
        for operation in ("create", "delete", "update"):
            global_arguments.update({operation: OrderedDict()})

            if operation != "delete":
                nested_map = nested_fields if isinstance(nested_fields, dict) else {}
                if nested_map:
                    # Mirror of the DjangoModelMutation gate (see mutation.py):
                    # a nested ``DjangoModelType`` builds a DISTINCT input with
                    # ``skip_registry=True`` so the generic ``(model, operation)``
                    # slot stays pristine for plain hosts and the converter's
                    # child lookups. The helpers live in mutation.py; importing
                    # them lazily here avoids the module-load circular import
                    # (mutation.py imports this module).
                    from .mutation import (
                        _ensure_child_generic_input,
                        _nested_input_name,
                    )

                    for child_model in nested_map.values():
                        _ensure_child_generic_input(child_model, operation, registry)
                    input_type = factory_type(
                        "input",
                        DjangoInputObjectType,
                        operation,
                        **{
                            **factory_kwargs,
                            "name": _nested_input_name(
                                model,
                                operation,
                                nested_map,
                                only_fields,
                                exclude_fields,
                                include_fields,
                            ),
                            "skip_registry": True,
                        },
                    )
                else:
                    input_type = registry.get_type_for_model(model, for_input=operation)

                    if not input_type:
                        input_type = factory_type(
                            "input", DjangoInputObjectType, operation, **factory_kwargs
                        )

                global_arguments[operation].update(
                    {input_field_name: Argument(input_type, required=True)}
                )
            else:
                global_arguments[operation].update(
                    {
                        "id": Argument(
                            ID,
                            required=True,
                            description="Django object unique identification field",
                        )
                    }
                )
            global_arguments[operation].update(arguments)

        _meta = DjangoModelTypeOptions(cls)
        _meta.mutation_output = cls
        _meta.arguments = global_arguments
        _meta.fields = django_fields
        _meta.output_type = output_type
        _meta.output_list_type = output_list_type
        _meta.model = model
        _meta.registry = registry
        # `is not None` (not `or`): a QuerySet's truthiness would execute it here.
        _meta.queryset = queryset if queryset is not None else model._default_manager
        _meta.backend = backend
        _meta.input_field_name = input_field_name
        _meta.output_field_name = output_field_name
        _meta.nested_fields = nested_fields
        _meta.stream = stream
        _meta.serialize_data = serialize_data
        _meta.subscription_index_fields = tuple(subscription_index_fields or ())
        _meta.max_deep = max_deep
        _meta.complexity = complexity

        super().__init_subclass_with_meta__(
            _meta=_meta, description=description, **options
        )

        # The custom fields belong on the generated output type, not on this
        # wrapper. graphene's ObjectType base re-collects them from the class
        # body (and bases) into `_meta.fields`, so drop them here.
        for field_name in extra_fields:
            cls._meta.fields.pop(field_name, None)

    @classmethod
    def list_object_type(cls) -> type[DjangoListObjectType]:
        """Return the list object type for this model type.

        Returns:
            The configured list object type.
        """
        return cls._meta.output_list_type

    @classmethod
    def object_type(cls) -> type[DjangoObjectType]:
        """Return the output object type for this model type.

        Returns:
            The configured output object type.
        """
        return cls._meta.output_type

    @classmethod
    def get_errors(cls, errors: list) -> DjangoModelType:
        """Create an error response object from validation errors.

        Args:
            errors: List of error entries describing the failure.

        Returns:
            An instance of this type flagged as not "ok" carrying the errors.
        """
        errors_dict = {cls._meta.output_field_name: None, "ok": False, "errors": errors}

        return cls(**errors_dict)

    @classmethod
    def perform_mutate(cls, obj: Model, info: ResolveInfo) -> DjangoModelType:
        """Create a successful mutation response with the given object.

        The object is re-read through "get_queryset" so annotated and related
        fields resolve in the response; it falls back to "obj" when the re-read
        yields nothing (e.g. "filter_queryset" excludes it), so a mutation
        never returns null for an object it just wrote.

        When the mutation selection set contains a sub-field for the output
        object (named by "Meta.output_field_name"), the re-read queryset is
        passed through the query optimizer using that sub-selection.  This
        eliminates N+1 queries for to-one relations (e.g. ForeignKey,
        OneToOneField) that are selected in the mutation response.

        Args:
            obj: Model instance produced by the mutation.
            info: GraphQL resolve info for the current request.

        Returns:
            An instance of this type flagged as "ok" carrying the object.
        """
        base_qs = cls.get_queryset(
            cls._meta.model._default_manager, info, obj=obj
        ).filter(pk=obj.pk)

        # Locate the sub-field node for the output object within the mutation
        # selection set (e.g. "post" inside "{ ok post { title author { name } } }").
        # If found, optimise the re-read queryset using that sub-selection so
        # to-one relations are joined via select_related instead of lazy-loading.
        output_field_name = cls._meta.output_field_name
        sub_field_node = None
        try:
            root_node = info.field_nodes[0] if info.field_nodes else None
            if root_node is not None and getattr(root_node, "selection_set", None):
                for sel in root_node.selection_set.selections:
                    sel_name = getattr(getattr(sel, "name", None), "value", None)
                    if sel_name == output_field_name:
                        sub_field_node = sel
                        break
        except Exception:  # pragma: no cover — defensive; never raise on best-effort
            sub_field_node = None

        if sub_field_node is not None and getattr(
            sub_field_node, "selection_set", None
        ):
            from types import SimpleNamespace

            sub_info = SimpleNamespace(
                field_nodes=[sub_field_node],
                fragments=getattr(info, "fragments", {}),
                variable_values=getattr(info, "variable_values", {}) or {},
                return_type=None,
                schema=getattr(info, "schema", None),
                context=getattr(info, "context", None),
            )
            try:
                base_qs = _apply_optimizations(
                    base_qs,
                    cls._meta.model,
                    sub_info,  # type: ignore[arg-type]
                    {},
                    False,
                )
            except Exception:  # pragma: no cover — degrade gracefully  # nosec B110
                # Best-effort optimization: an optimizer failure must never
                # break the mutation; the unoptimized re-read is still correct.
                pass

        refreshed = base_qs.first()
        resp = {
            output_field_name: refreshed or obj,
            "ok": True,
            "errors": None,
        }

        return cls(**resp)

    @classmethod
    def get_queryset(
        cls, manager: Manager | QuerySet, info: ResolveInfo, **kwargs
    ) -> QuerySet:
        """Return the base queryset for retrieve, list and mutation responses.

        Override to customize the base queryset (e.g. "select_related" or
        "annotate"). "info.context" is the request. The default uses
        "Meta.queryset" (else the field's manager) and applies
        "filter_queryset".

        Args:
            manager: Default manager or queryset to fall back to.
            info: GraphQL resolve info for the current request.
            **kwargs: Extra arguments forwarded to "filter_queryset".

        Returns:
            The scoped queryset to use.
        """
        qs = cls._meta.queryset if cls._meta.queryset is not None else manager
        if isinstance(qs, Manager):
            qs = qs.all()
        return cls.filter_queryset(qs, info, **kwargs)

    @classmethod
    def filter_queryset(cls, qs: QuerySet, info: ResolveInfo, **kwargs) -> QuerySet:
        """Scope the queryset per request.

        This is a hook meant to be overridden. The default returns "qs"
        unchanged.

        Args:
            qs: Queryset to scope.
            info: GraphQL resolve info for the current request.
            **kwargs: Extra arguments available for scoping.

        Returns:
            The (optionally) scoped queryset.
        """
        return qs

    @classmethod
    def subscription_scope(cls, info: ResolveInfo, **kwargs) -> dict | None:
        """Return server-forced notification filters for a subscriber.

        Hook meant to be overridden when the subscription must be row-scoped
        (e.g. ``{"owner": info.context.user.pk}``). It is evaluated at subscribe
        time (the user is available) and enforced per event at delivery, in
        memory when possible, so the client can neither widen nor drop it.

        Unlike ``filter_queryset`` (an opaque queryset transform used by the
        query/list resolvers), this returns a plain filter mapping so it can be
        applied to a single changed instance without a per-event query. The
        default returns ``None`` (no scoping).

        Args:
            info: GraphQL resolve info for the subscribe request.
            **kwargs: The subscription arguments.

        Returns:
            The forced filter mapping, or ``None``.
        """
        return None

    # -- permissions -------------------------------------------------------- #
    @classmethod
    def get_permissions(cls) -> list[Any]:
        """Instantiate the configured "permission_classes".

        Returns:
            A list of permission instances.
        """
        return [permission() for permission in cls.permission_classes]

    @classmethod
    def check_permissions(cls, info: ResolveInfo, action: str, **kwargs) -> None:
        """Raise "GraphQLError" if any permission denies the action.

        Args:
            info: GraphQL resolve info for the current request.
            action: Action name being checked (e.g. "create", "list").
            **kwargs: Extra arguments passed to each permission check.

        Raises:
            GraphQLError: If any permission denies the action.
        """
        method_name = f"has_{action}_permission"
        for permission in cls.get_permissions():
            if getattr(permission, method_name)(info, cls._meta.model, **kwargs) is (
                False
            ):
                raise GraphQLError(
                    "You do not have permission to perform this action.",
                    extensions={"code": "PERMISSION_DENIED", "status_code": 403},
                )

    @classmethod
    def authorize(cls, info: ResolveInfo, action: str, **kwargs) -> None:
        """Authorize an action before it runs via permission checks.

        Called by every CRUD method; override to customize (e.g. skip checks
        in local development). Raises "GraphQLError" when denied.

        Args:
            info: GraphQL resolve info for the current request.
            action: Action name being authorized (e.g. "create", "list").
            **kwargs: Extra arguments passed to the permission checks.

        Raises:
            GraphQLError: If the action is not allowed.
        """
        cls.check_permissions(info, action, **kwargs)

    @classmethod
    def create(cls, root: Any, info: ResolveInfo, **kwargs) -> DjangoModelType:
        """Create a new object using the serializer.

        Nested children declared in "Meta.nested_fields" are written atomically
        with the parent (see "NestedFieldsMixin.save_with_nested").

        Args:
            root: Root value passed to the resolver.
            info: GraphQL resolve info for the current request.
            **kwargs: Resolver arguments including the input data.

        Returns:
            A success response with the created object, or an error response.
        """
        data = kwargs.get(cls._meta.input_field_name)
        cls.authorize(info, "create", data=data)
        request_type = info.context.META.get("CONTENT_TYPE", "")
        if "multipart/form-data" in request_type:
            data.update({name: value for name, value in info.context.FILES.items()})

        ok, obj = cls.save_with_nested(root, info, data, instance=None)
        if not ok:
            return cls.get_errors(obj)
        return cls.perform_mutate(obj, info)

    @classmethod
    def delete(cls, root: Any, info: ResolveInfo, **kwargs) -> DjangoModelType:
        """Delete an object by its primary key.

        Args:
            root: Root value passed to the resolver.
            info: GraphQL resolve info for the current request.
            **kwargs: Resolver arguments including the object "id".

        Returns:
            A success response with the deleted object, or an error response
            when no matching object exists.
        """
        cls.authorize(info, "delete", data=kwargs)
        pk = kwargs.get("id")

        old_obj = get_Object_or_None(cls._meta.model, pk=pk)
        if old_obj:
            old_obj.delete()
            setattr(old_obj, old_obj._meta.pk.attname, pk)
            return cls.perform_mutate(old_obj, info)
        else:
            return cls.get_errors(not_found_error(cls._meta.model, pk))

    @classmethod
    def update(cls, root: Any, info: ResolveInfo, **kwargs) -> DjangoModelType:
        """Update an existing object using the serializer.

        Args:
            root: Root value passed to the resolver.
            info: GraphQL resolve info for the current request.
            **kwargs: Resolver arguments including the input data.

        Returns:
            A success response with the updated object, or an error response
            when no matching object exists.
        """
        data = kwargs.get(cls._meta.input_field_name)
        cls.authorize(info, "update", data=data)
        request_type = info.context.META.get("CONTENT_TYPE", "")
        if "multipart/form-data" in request_type:
            data.update({name: value for name, value in info.context.FILES.items()})

        pk = data.pop("id")
        old_obj = get_Object_or_None(cls._meta.model, pk=pk)
        if old_obj:
            ok, obj = cls.save_with_nested(
                root,
                info,
                data,
                instance=old_obj,
            )
            if not ok:
                return cls.get_errors(obj)
            return cls.perform_mutate(obj, info)
        else:
            return cls.get_errors(not_found_error(cls._meta.model, pk))

    @classmethod
    def retrieve(
        cls, manager: Manager | QuerySet, root: Any, info: ResolveInfo, **kwargs
    ) -> Model | None:
        """Retrieve a single object by primary key, optimized for selection.

        Args:
            manager: Default manager or queryset to retrieve from.
            root: Root value passed to the resolver.
            info: GraphQL resolve info for the current request.
            **kwargs: Resolver arguments including the object "id".

        Returns:
            The matching model instance, or None if it does not exist.
        """
        cls.authorize(info, "retrieve")
        pk = kwargs.pop("id", None)

        base = cls.get_queryset(manager, info, **kwargs)
        try:
            qs = queryset_factory(base, root, info, **kwargs)
            return qs.get(pk=pk)
        except manager.model.DoesNotExist:
            return None

    @classmethod
    def list(
        cls,
        manager: Manager | QuerySet,
        filter_backend: Any,
        root: Any,
        info: ResolveInfo,
        **kwargs,
    ) -> DjangoListObjectBase:
        """List objects with filtering and pagination support.

        Args:
            manager: Default manager or queryset to list from.
            filter_backend: The native filter backend applied to the queryset.
            root: Root value passed to the resolver.
            info: GraphQL resolve info for the current request.
            **kwargs: Resolver arguments including the ``filter`` value.

        Returns:
            A list result container with the count and matching objects.
        """
        cls.authorize(info, "list")
        base = cls.get_queryset(manager, info, **kwargs)
        qs = queryset_factory(base, root, info, **kwargs)

        qs = filter_backend.apply(qs, kwargs.get("filter"))
        count = qs.count()

        return DjangoListObjectBase(
            count=count,
            results=maybe_queryset(qs),
            results_field_name=cls.list_object_type()._meta.results_field_name,
        )

    @classmethod
    def RetrieveField(cls, *args, **kwargs) -> DjangoObjectField:
        """Create a field for retrieving a single object.

        Args:
            *args: Positional arguments (currently unused).
            **kwargs: Keyword arguments forwarded to the field.

        Returns:
            A field that resolves a single object via "retrieve".
        """
        return DjangoObjectField(cls._meta.output_type, resolver=cls.retrieve, **kwargs)

    @classmethod
    def ListField(cls, *args, **kwargs) -> DjangoListObjectField:
        """Create a field for listing objects.

        Args:
            *args: Positional arguments (currently unused).
            **kwargs: Keyword arguments forwarded to the field.

        Returns:
            A field that resolves a list of objects via "list".
        """
        return DjangoListObjectField(
            cls._meta.output_list_type, resolver=cls.list, **kwargs
        )

    @classmethod
    def CreateField(cls, *args, **kwargs) -> Field:
        """Create a field for creating objects.

        Args:
            *args: Positional arguments (currently unused).
            **kwargs: Keyword arguments forwarded to the field.

        Returns:
            A mutation field wired to the "create" resolver.
        """
        return Field(
            cls._meta.mutation_output,
            args=cls._meta.arguments["create"],
            resolver=cls.create,
            **kwargs,
        )

    @classmethod
    def DeleteField(cls, *args, **kwargs) -> Field:
        """Create a field for deleting objects.

        Args:
            *args: Positional arguments (currently unused).
            **kwargs: Keyword arguments forwarded to the field.

        Returns:
            A mutation field wired to the "delete" resolver.
        """
        return Field(
            cls._meta.mutation_output,
            args=cls._meta.arguments["delete"],
            resolver=cls.delete,
            **kwargs,
        )

    @classmethod
    def UpdateField(cls, *args, **kwargs) -> Field:
        """Create a field for updating objects.

        Args:
            *args: Positional arguments (currently unused).
            **kwargs: Keyword arguments forwarded to the field.

        Returns:
            A mutation field wired to the "update" resolver.
        """
        return Field(
            cls._meta.mutation_output,
            args=cls._meta.arguments["update"],
            resolver=cls.update,
            **kwargs,
        )

    @classmethod
    def QueryFields(cls, *args, **kwargs) -> tuple[Any, Any]:
        """Return retrieve and list fields for GraphQL queries.

        Args:
            *args: Positional arguments forwarded to the field builders.
            **kwargs: Keyword arguments forwarded to the field builders.

        Returns:
            A tuple of the retrieve field and the list field.
        """
        retrieve_field = cls.RetrieveField(*args, **kwargs)
        list_field = cls.ListField(*args, **kwargs)

        return retrieve_field, list_field

    @classmethod
    def MutationFields(cls, *args, **kwargs) -> tuple[Any, Any, Any]:
        """Return create, delete and update fields for GraphQL mutations.

        Args:
            *args: Positional arguments forwarded to the field builders.
            **kwargs: Keyword arguments forwarded to the field builders.

        Returns:
            A tuple of the create, delete and update fields.
        """
        create_field = cls.CreateField(*args, **kwargs)
        delete_field = cls.DeleteField(*args, **kwargs)
        update_field = cls.UpdateField(*args, **kwargs)

        return create_field, delete_field, update_field

    @classmethod
    def subscription_type(cls) -> Any:
        """Return the cached "Subscription" subclass for this model type.

        Built lazily from "Meta.model" / "Meta.stream" /
        "Meta.serialize_data" so that the base install never imports the
        optional "[subscriptions]" extra (Channels) until subscriptions are
        actually used. Pass it to a "GraphqlAPIDemultiplexer".

        Returns:
            The generated "Subscription" subclass.

        Raises:
            ImproperlyConfigured: If "Meta.stream" was not set.
        """
        sub = cls.__dict__.get("_subscription_cls")
        if sub is None:
            if not cls._meta.stream:
                raise ImproperlyConfigured(
                    "{}.Meta.stream must be set to expose a subscription.".format(
                        cls.__name__
                    )
                )
            # Lazy import keeps the base install free of Channels.
            from django_graphex.subscriptions import Subscription

            parent = cls

            def _authorize_subscription(_sub_cls, info, **kwargs):
                # Honor the type's permission_classes / authorize at subscribe.
                # (No kwargs forwarded: the subscription's own ``action`` arg
                # would collide with ``authorize(info, action, ...)``.)
                return parent.authorize(info, "subscribe")

            def _subscription_scope(_sub_cls, info, **kwargs):
                # Honor the type's row-scoping as server-forced notify filters.
                return parent.subscription_scope(info, **kwargs)

            meta_attrs = {
                "model": cls._meta.model,
                "pydantic_model": getattr(cls._meta.backend, "pydantic_model", None),
                "stream": cls._meta.stream,
                "serialize_data": cls._meta.serialize_data,
                "subscription_index_fields": cls._meta.subscription_index_fields,
            }

            sub = type(
                f"{cls.__name__}Subscription",
                (Subscription,),
                {
                    "Meta": type("Meta", (), meta_attrs),
                    "authorize_subscription": classmethod(_authorize_subscription),
                    "subscription_scope": classmethod(_subscription_scope),
                },
            )
            cls._subscription_cls = sub
        return sub

    @classmethod
    def SubscriptionField(cls, *args, **kwargs) -> Any:
        """Mount this type's subscription on a root subscription "ObjectType".

        Args:
            *args: Positional arguments forwarded to the field builder.
            **kwargs: Keyword arguments forwarded to the field builder.

        Returns:
            The "SubscriptionField" carrying the generated subscription's
            resolver.
        """
        return cls.subscription_type().Field(*args, **kwargs)
