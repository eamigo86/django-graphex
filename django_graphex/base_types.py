"""Base types and utilities for django-graphex."""

from __future__ import annotations

import binascii
import datetime
from typing import TYPE_CHECKING, Any

import graphene
from graphene.types.datetime import Date, DateTime, Time
from graphene.utils.str_converters import to_camel_case
from graphql.language import ast

if TYPE_CHECKING:
    from graphql.language import ast as ast_types


def factory_type(operation: str, _type: Any, *args: Any, **kwargs: Any) -> Any:
    """Create a factory type based on the operation.

    Args:
        operation: one of "output", "input", or "list".
        _type: base GraphQL type the generated class derives from.
        *args: extra positional arguments (the input action for "input").
        **kwargs: type configuration such as "model", "name", and field lists.

    Returns:
        The generated GraphQL type class, or None for an unknown operation.
    """
    if operation == "output":

        class OutputMeta:
            model = kwargs.get("model")
            name = kwargs.get("name") or to_camel_case(
                f"{kwargs.get('model').__name__}_Generic_Type"
            )
            only_fields = kwargs.get("only_fields")
            exclude_fields = kwargs.get("exclude_fields")
            include_fields = kwargs.get("include_fields")
            filter_fields = kwargs.get("filter_fields")
            registry = kwargs.get("registry")
            skip_registry = kwargs.get("skip_registry")
            max_deep = kwargs.get("max_deep")
            complexity = kwargs.get("complexity")
            # fields = kwargs.get('fields')
            description = "Auto generated Type for {} model".format(
                kwargs.get("model").__name__
            )

        # Custom graphene fields declared on the owning DjangoModelType are
        # placed in the namespace *before* the type is created so graphene's
        # ObjectType base collects them and merges them with the model-derived
        # fields -- exactly as if written on a hand-rolled DjangoObjectType. Their
        # matching ``resolve_<field>`` methods ride along so a custom field is
        # resolved by its own resolver (not just ``source=``).
        namespace = {
            "Meta": OutputMeta,
            **(kwargs.get("extra_fields") or {}),
            **(kwargs.get("extra_resolvers") or {}),
        }
        return type("GenericType", (_type,), namespace)

    elif operation == "input":

        class GenericInputType(_type):
            class Meta:
                model = kwargs.get("model")
                name = kwargs.get("name") or to_camel_case(
                    f"{kwargs.get('model').__name__}_{args[0]}_Generic_Type"
                )
                only_fields = kwargs.get("only_fields")
                exclude_fields = kwargs.get("exclude_fields")
                nested_fields = kwargs.get("nested_fields")
                registry = kwargs.get("registry")
                skip_registry = kwargs.get("skip_registry")
                input_for = args[0]
                description = "Auto generated InputType for {} model".format(
                    kwargs.get("model").__name__
                )

        return GenericInputType

    elif operation == "list":

        class GenericListType(_type):
            class Meta:
                model = kwargs.get("model")
                name = kwargs.get("name") or to_camel_case(
                    f"{kwargs.get('model').__name__}_List_Type"
                )
                only_fields = kwargs.get("only_fields")
                exclude_fields = kwargs.get("exclude_fields")
                filter_fields = kwargs.get("filter_fields")
                results_field_name = kwargs.get("results_field_name")
                pagination = kwargs.get("pagination")
                queryset = kwargs.get("queryset")
                registry = kwargs.get("registry")
                max_deep = kwargs.get("max_deep")
                complexity = kwargs.get("complexity")
                description = "Auto generated list Type for {} model".format(
                    kwargs.get("model").__name__
                )

        return GenericListType

    return None


class DjangoListObjectBase:
    """Base class for Django list objects."""

    def __init__(
        self,
        results: Any,
        count: int,
        results_field_name: str = "results",
    ) -> None:
        """Initialize the Django list object.

        Args:
            results: the list of result objects.
            count: total number of results.
            results_field_name: name of the field holding the results.
        """
        self.results = results
        self.count = count
        self.results_field_name = results_field_name

    def to_dict(self) -> dict[str, Any]:
        """Convert the object to a dictionary.

        Returns:
            A dict with the results under "results_field_name" and the total
            under "count".
        """
        return {
            self.results_field_name: [e.to_dict() for e in self.results],
            "count": self.count,
        }


def resolver(attr_name: str, root: Any, instance: Any, info: Any) -> Any:
    """Resolve generic foreign key attributes.

    Args:
        attr_name: name of the attribute to resolve.
        root: the root value of the resolution.
        instance: the model instance to read from.
        info: the GraphQL resolve info.

    Returns:
        The resolved value for the requested attribute, or None when the name
        is unknown.
    """
    if attr_name == "app_label":
        return instance._meta.app_label
    elif attr_name == "id":
        return instance.id
    elif attr_name == "model_name":
        return instance._meta.model.__name__


class GenericForeignKeyType(graphene.ObjectType):
    """GraphQL type for Django GenericForeignKey fields."""

    app_label = graphene.String()
    id = graphene.ID()
    model_name = graphene.String()

    class Meta:
        """Meta configuration for GenericForeignKeyType."""

        description = " Auto generated Type for a model's GenericForeignKey field "
        default_resolver = resolver


class GenericForeignKeyInputType(graphene.InputObjectType):
    """GraphQL input type for Django GenericForeignKey fields."""

    app_label = graphene.Argument(graphene.String, required=True)
    id = graphene.Argument(graphene.ID, required=True)
    model_name = graphene.Argument(graphene.String, required=True)

    class Meta:
        """Meta configuration for GenericForeignKeyInputType."""

        description = " Auto generated InputType for a model's GenericForeignKey field "


# ************************************************ #
# ************** CUSTOM BASE TYPES *************** #
# ************************************************ #
class Binary(graphene.Scalar):
    """BinaryArray is used to convert a Django BinaryField to the string form."""

    @staticmethod
    def binary_to_string(value: bytes) -> str:
        """Convert binary data to string representation.

        Args:
            value: the binary data to convert.

        Returns:
            The hex-encoded string representation of the data.
        """
        return binascii.hexlify(value).decode("utf-8")

    serialize = binary_to_string
    parse_value = binary_to_string

    @classmethod
    def parse_literal(cls, node: ast_types.Node) -> str | None:
        """Parse a literal node from the GraphQL AST.

        Args:
            node: the AST node to parse.

        Returns:
            The decoded string for a string-value node, or None otherwise.
        """
        if isinstance(node, ast.StringValueNode):
            return cls.binary_to_string(node.value)
        return None


class CustomDateFormat:
    """Custom date format wrapper."""

    def __init__(self, date: str) -> None:
        """Initialize custom date format.

        Args:
            date: the pre-formatted date string to wrap.
        """
        self.date_str = date


class CustomTime(Time):
    """Custom time scalar type with support for custom date formats."""

    @staticmethod
    def serialize(time: Any) -> str:
        """Serialize a time value to a string.

        Args:
            time: a CustomDateFormat, datetime, or time value.

        Returns:
            The ISO-formatted time string, or the wrapped string for a
            CustomDateFormat.

        Raises:
            AssertionError: if "time" is not a compatible time value.
        """
        if isinstance(time, CustomDateFormat):
            return time.date_str

        if isinstance(time, datetime.datetime):
            time = time.time()

        assert isinstance(time, datetime.time), (
            f'Received not compatible time "{repr(time)}"'
        )
        return time.isoformat()


class CustomDate(Date):
    """Custom date scalar type with support for custom date formats."""

    @staticmethod
    def serialize(date: Any) -> str:
        """Serialize a date value to a string.

        Args:
            date: a CustomDateFormat, datetime, or date value.

        Returns:
            The ISO-formatted date string, or the wrapped string for a
            CustomDateFormat.

        Raises:
            AssertionError: if "date" is not a compatible date value.
        """
        if isinstance(date, CustomDateFormat):
            return date.date_str

        if isinstance(date, datetime.datetime):
            date = date.date()
        assert isinstance(date, datetime.date), (
            f'Received not compatible date "{repr(date)}"'
        )
        return date.isoformat()


class CustomDateTime(DateTime):
    """Custom datetime scalar type with support for custom date formats."""

    @staticmethod
    def serialize(dt: Any) -> str:
        """Serialize a datetime value to a string.

        Args:
            dt: a CustomDateFormat, datetime, or date value.

        Returns:
            The ISO-formatted datetime string, or the wrapped string for a
            CustomDateFormat.

        Raises:
            AssertionError: if "dt" is not a compatible datetime value.
        """
        if isinstance(dt, CustomDateFormat):
            return dt.date_str

        assert isinstance(dt, (datetime.datetime, datetime.date)), (
            f'Received not compatible datetime "{repr(dt)}"'
        )
        return dt.isoformat()
