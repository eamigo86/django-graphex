"""Number manipulation GraphQL directives."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from graphql import (
    GraphQLArgument,
    GraphQLError,
    GraphQLInt,
    GraphQLString,
    get_named_type,
)

from .base import BaseExtraGraphQLDirective

if TYPE_CHECKING:
    from graphql import GraphQLResolveInfo

__all__ = (
    "FloorGraphQLDirective",
    "CeilGraphQLDirective",
    "RoundGraphQLDirective",
    "AbsGraphQLDirective",
)


def _to_float(value: Any, directive_name: str) -> float:
    """Coerce *value* to float, raising GraphQLError on failure.

    Shared guard used by all numeric directives to convert implementation
    exceptions into GraphQL errors before they reach the client.

    Args:
        value: The field value to coerce.
        directive_name: The directive name shown in the error message (e.g. '@floor').

    Returns:
        The value coerced to float.

    Raises:
        GraphQLError: When the value cannot be interpreted as a number.
    """
    try:
        return float(value)
    except (ValueError, TypeError) as exc:
        raise GraphQLError(
            f"{directive_name} could not convert value {value!r} to a number."
        ) from exc


def _wants_string(info: GraphQLResolveInfo) -> bool:
    """Report whether the field's unwrapped return type is "String".

    Args:
        info: The GraphQL resolve info for the field.

    Returns:
        True when the unwrapped return type is the "String" type.
    """
    return get_named_type(info.return_type) is GraphQLString


def _coerce(number: Any, info: GraphQLResolveInfo) -> Any:
    """Coerce a number to a string when the field is a "String" field.

    Args:
        number: The numeric value to coerce.
        info: The GraphQL resolve info for the field.

    Returns:
        The number as a string when the field is a "String", else as-is.
    """
    return str(number) if _wants_string(info) else number


class FloorGraphQLDirective(BaseExtraGraphQLDirective):
    """Round a field value down to the nearest integer.

    Works on both "String" and "Float" fields; the result is coerced back to a
    string when the field's return type is "String". A None value passes through
    unchanged.
    """

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Resolve the floor directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.
            **kwargs: Additional resolver keyword arguments.

        Returns:
            The floored value, or None when the value is None.
        """
        if value is None:
            return None
        return _coerce(math.floor(_to_float(value, "@floor")), info)


class CeilGraphQLDirective(BaseExtraGraphQLDirective):
    """Round a field value up to the nearest integer.

    Works on both "String" and "Float" fields; the result is coerced back to a
    string when the field's return type is "String". A None value passes through
    unchanged.
    """

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Resolve the ceil directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.
            **kwargs: Additional resolver keyword arguments.

        Returns:
            The ceiled value, or None when the value is None.
        """
        if value is None:
            return None
        return _coerce(math.ceil(_to_float(value, "@ceil")), info)


class RoundGraphQLDirective(BaseExtraGraphQLDirective):
    """Round a number to a chosen number of decimal places.

    The "precision" argument selects the number of decimal places (default 0).
    A precision of 0 or below yields an integer. Works on both "String" and
    "Float" fields; the result is coerced back to a string when the field's
    return type is "String". A None value passes through unchanged.
    """

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Get arguments for the round directive.

        Returns:
            A mapping of argument names to their definitions.
        """
        return {
            "precision": GraphQLArgument(
                GraphQLInt, description="Number of decimal places (default: 0)"
            )
        }

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Resolve the round directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.
            **kwargs: Additional resolver keyword arguments.

        Returns:
            The rounded value, or None when the value is None.
        """
        if value is None:
            return None
        precision = args.get("precision") or 0
        rounded = round(_to_float(value, "@round"), int(precision))
        if precision <= 0:
            rounded = int(rounded)
        return _coerce(rounded, info)


class AbsGraphQLDirective(BaseExtraGraphQLDirective):
    """Take the absolute value of a field.

    Works on both "String" and "Float" fields; the result is coerced back to a
    string when the field's return type is "String". A None value passes through
    unchanged.
    """

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Resolve the abs directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.
            **kwargs: Additional resolver keyword arguments.

        Returns:
            The absolute value, or None when the value is None.
        """
        if value is None:
            return None
        return _coerce(abs(_to_float(value, "@abs")), info)
