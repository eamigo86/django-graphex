"""Django model-based GraphQL mutations."""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured
from graphene import ID, Argument, Boolean, Field, List, ObjectType
from graphene.types.base import BaseOptions
from graphene.utils.deprecated import warn_deprecation
from graphene.utils.props import props

from ._compat import ErrorType
from .backends import resolve_backend
from .base_types import factory_type
from .native.validators import build_validator_model
from .nested import NestedFieldsMixin
from .registry import get_global_registry
from .types import DjangoInputObjectType, DjangoObjectType
from .utils import get_Object_or_None, not_found_error

if TYPE_CHECKING:
    from graphene import Field as GrapheneField
    from graphql import GraphQLResolveInfo


class SerializerMutationOptions(BaseOptions):
    """Options class for DjangoModelMutation configuration."""

    fields = None
    input_fields = None
    interfaces = ()
    backend = None
    action = None
    arguments = None
    output = None
    resolver = None
    nested_fields = None
    model_operations = ("create", "update", "delete")


class DjangoModelMutation(NestedFieldsMixin, ObjectType):
    """Django model mutation type definition."""

    ok = Boolean(description="Boolean field that return mutation result request.")
    errors = List(ErrorType, description="Errors list for the field")

    class Meta:
        """Meta configuration for DjangoModelMutation."""

        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        model: Any = None,
        pydantic_model: Any = None,
        only_fields: tuple[str, ...] = (),
        include_fields: tuple[str, ...] = (),
        exclude_fields: tuple[str, ...] = (),
        input_field_name: str | None = None,
        output_field_name: str | None = None,
        description: str = "",
        nested_fields: Any = (),
        model_operations: Any = ("create", "update", "delete"),
        **options: Any,
    ) -> None:
        """Initialize the subclass with its meta configuration.

        Args:
            only_fields: Field names to expose exclusively.
            include_fields: Field names to include.
            exclude_fields: Field names to exclude.
            input_field_name: Name of the input argument field.
            output_field_name: Name of the output field.
            description: Description for the generated mutation.
            nested_fields: Nested serializer fields configuration.
            model_operations: The mutation operations to generate; any subset of
                ``("create", "update", "delete")``. Operations left out are not
                built and their ``*Field()`` builders raise.
            **options: Additional options forwarded to the base class.

        Raises:
            ImproperlyConfigured: If no "Meta.model" is provided, or if
                "model_operations" contains an unknown operation.
        """
        pydantic_model = build_validator_model(cls, model, pydantic_model)
        backend = resolve_backend(model, pydantic_model=pydantic_model)
        model = backend.get_model()

        description = description or f"DjangoModelMutation for {model.__name__} model"

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

        factory_kwargs = {
            "model": model,
            "only_fields": only_fields,
            "include_fields": include_fields,
            "exclude_fields": exclude_fields,
            "nested_fields": nested_fields,
            "registry": registry,
            "skip_registry": False,
        }

        output_type = registry.get_type_for_model(model)

        if not output_type:
            output_type = factory_type("output", DjangoObjectType, **factory_kwargs)

        django_fields = OrderedDict({output_field_name: Field(output_type)})

        model_operations = tuple(op.lower() for op in model_operations)
        unknown = set(model_operations) - {"create", "update", "delete"}
        if unknown:
            raise ImproperlyConfigured(
                "Meta.model_operations of {} contains unknown operation(s) {}; "
                'only "create", "update" and "delete" are valid.'.format(
                    cls.__name__, sorted(unknown)
                )
            )

        global_arguments = {}
        for operation in ("create", "delete", "update"):
            if operation not in model_operations:
                continue
            global_arguments.update({operation: OrderedDict()})

            if operation != "delete":
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

        _meta = SerializerMutationOptions(cls)
        _meta.output = cls
        _meta.arguments = global_arguments
        _meta.model_operations = model_operations
        _meta.fields = django_fields
        _meta.output_type = output_type
        _meta.model = model
        _meta.backend = backend
        _meta.input_field_name = input_field_name
        _meta.output_field_name = output_field_name
        _meta.nested_fields = nested_fields

        super().__init_subclass_with_meta__(
            _meta=_meta, description=description, **options
        )

    @classmethod
    def get_errors(cls, errors: list[Any]) -> DjangoModelMutation:
        """Create an error response wrapping the provided errors.

        Args:
            errors: The list of error objects to report.

        Returns:
            A mutation instance carrying the errors and a falsy "ok".
        """
        errors_dict = {cls._meta.output_field_name: None, "ok": False, "errors": errors}

        return cls(**errors_dict)

    @classmethod
    def perform_mutate(cls, obj: Any, info: GraphQLResolveInfo) -> DjangoModelMutation:
        """Build a successful mutation response for the given object.

        Args:
            obj: The saved model instance to return.
            info: The GraphQL resolve info for the current field.

        Returns:
            A mutation instance carrying the object and a truthy "ok".
        """
        resp = {cls._meta.output_field_name: obj, "ok": True, "errors": None}

        return cls(**resp)

    @classmethod
    def create(
        cls, root: Any, info: GraphQLResolveInfo, **kwargs: Any
    ) -> DjangoModelMutation:
        """Create a new object using the provided data.

        Nested children declared in "Meta.nested_fields" are written atomically
        with the parent (see "NestedFieldsMixin.save_with_nested").

        Args:
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the current field.
            **kwargs: The mutation arguments, including the input data.

        Returns:
            A mutation response carrying the created object or errors.
        """
        data = kwargs.get(cls._meta.input_field_name)
        request_type = info.context.META.get("CONTENT_TYPE", "")
        if "multipart/form-data" in request_type:
            data.update({name: value for name, value in info.context.FILES.items()})

        ok, obj = cls.save_with_nested(
            root,
            info,
            data,
            instance=None,
        )
        if not ok:
            return cls.get_errors(obj)
        return cls.perform_mutate(obj, info)

    @classmethod
    def delete(
        cls, root: Any, info: GraphQLResolveInfo, **kwargs: Any
    ) -> DjangoModelMutation:
        """Delete an object identified by its ID.

        Args:
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the current field.
            **kwargs: The mutation arguments, including the object "id".

        Returns:
            A mutation response carrying the deleted object or errors.
        """
        pk = kwargs.get("id")

        old_obj = get_Object_or_None(cls._meta.model, pk=pk)
        if old_obj:
            old_obj.delete()
            old_obj.id = pk
            return cls.perform_mutate(old_obj, info)
        else:
            return cls.get_errors(not_found_error(cls._meta.model, pk))

    @classmethod
    def update(
        cls, root: Any, info: GraphQLResolveInfo, **kwargs: Any
    ) -> DjangoModelMutation:
        """Update an existing object with the provided data.

        Args:
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the current field.
            **kwargs: The mutation arguments, including the input data.

        Returns:
            A mutation response carrying the updated object or errors.
        """
        data = kwargs.get(cls._meta.input_field_name)
        request_type = info.context.META.get("CONTENT_TYPE", "")
        if "multipart/form-data" in request_type:
            data.update({name: value for name, value in info.context.FILES.items()})

        pk = data.pop("id")
        # Optional inputs the client omitted (relational fields especially)
        # arrive as an explicit ``null`` because the generated update input
        # gives them a ``None`` default. On a partial update treat ``null`` as
        # "not provided" so an untouched value isn't wrongly cleared -- a
        # required FK would otherwise fail validation with "This field may not
        # be null". Send an explicit value to change a field.
        data = {name: value for name, value in data.items() if value is not None}
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
    def CreateField(cls, *args: Any, **kwargs: Any) -> GrapheneField:
        """Build a GraphQL field for the create mutation.

        Args:
            *args: Positional arguments (unused).
            **kwargs: Extra keyword arguments forwarded to the field.

        Returns:
            The graphene field resolving to the create mutation.

        Raises:
            AttributeError: If "create" is not in Meta.model_operations.
        """
        cls._assert_operation("create")
        return Field(
            cls._meta.output,
            args=cls._meta.arguments["create"],
            resolver=cls.create,
            **kwargs,
        )

    @classmethod
    def DeleteField(cls, *args: Any, **kwargs: Any) -> GrapheneField:
        """Build a GraphQL field for the delete mutation.

        Args:
            *args: Positional arguments (unused).
            **kwargs: Extra keyword arguments forwarded to the field.

        Returns:
            The graphene field resolving to the delete mutation.

        Raises:
            AttributeError: If "delete" is not in Meta.model_operations.
        """
        cls._assert_operation("delete")
        return Field(
            cls._meta.output,
            args=cls._meta.arguments["delete"],
            resolver=cls.delete,
            **kwargs,
        )

    @classmethod
    def UpdateField(cls, *args: Any, **kwargs: Any) -> GrapheneField:
        """Build a GraphQL field for the update mutation.

        Args:
            *args: Positional arguments (unused).
            **kwargs: Extra keyword arguments forwarded to the field.

        Returns:
            The graphene field resolving to the update mutation.

        Raises:
            AttributeError: If "update" is not in Meta.model_operations.
        """
        cls._assert_operation("update")
        return Field(
            cls._meta.output,
            args=cls._meta.arguments["update"],
            resolver=cls.update,
            **kwargs,
        )

    @classmethod
    def _assert_operation(cls, operation: str) -> None:
        """Ensure "operation" is enabled in Meta.model_operations.

        Args:
            operation: The mutation operation being built.

        Raises:
            AttributeError: If the operation was excluded from model_operations.
        """
        if operation not in cls._meta.model_operations:
            raise AttributeError(
                '"{}" mutation is not enabled on {}; '
                "Meta.model_operations is {}.".format(
                    operation, cls.__name__, cls._meta.model_operations
                )
            )

    @classmethod
    def MutationFields(cls, *args: Any, **kwargs: Any) -> tuple[GrapheneField, ...]:
        """Build the mutation fields enabled by Meta.model_operations.

        Args:
            *args: Positional arguments forwarded to each field builder.
            **kwargs: Keyword arguments forwarded to each field builder.

        Returns:
            The create, delete and update graphene fields (in that order) for
            every operation enabled in ``Meta.model_operations``.
        """
        builders = (
            ("create", cls.CreateField),
            ("delete", cls.DeleteField),
            ("update", cls.UpdateField),
        )
        return tuple(
            build(*args, **kwargs)
            for operation, build in builders
            if operation in cls._meta.model_operations
        )
