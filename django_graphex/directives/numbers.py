"""Number manipulation GraphQL directives."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from graphql import GraphQLArgument, GraphQLInt, GraphQLString, get_named_type

from .base import BaseExtraGraphQLDirective

if TYPE_CHECKING:
    from graphql import GraphQLResolveInfo

__all__ = (
    "FloorGraphQLDirective",
    "CeilGraphQLDirective",
    "RoundGraphQLDirective",
    "AbsGraphQLDirective",
)


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
    """Floor value for both String and Float fields."""

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> Any:
        """Resolve the floor directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The floored value, or None when the value is None.
        """
        if value is None:
            return None
        return _coerce(math.floor(float(value)), info)


class CeilGraphQLDirective(BaseExtraGraphQLDirective):
    """Ceil value for both String and Float fields."""

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> Any:
        """Resolve the ceil directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The ceiled value, or None when the value is None.
        """
        if value is None:
            return None
        return _coerce(math.ceil(float(value)), info)


class RoundGraphQLDirective(BaseExtraGraphQLDirective):
    """Round a number to "precision" decimal places (default 0)."""

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
        **kwargs,
    ) -> Any:
        """Resolve the round directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The rounded value, or None when the value is None.
        """
        if value is None:
            return None
        precision = args.get("precision") or 0
        rounded = round(float(value), int(precision))
        if precision <= 0:
            rounded = int(rounded)
        return _coerce(rounded, info)


class AbsGraphQLDirective(BaseExtraGraphQLDirective):
    """Absolute value for both String and Float fields."""

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> Any:
        """Resolve the abs directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The absolute value, or None when the value is None.
        """
        if value is None:
            return None
        return _coerce(abs(float(value)), info)
