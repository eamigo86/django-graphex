"""Number manipulation GraphQL directives."""

from __future__ import annotations

import decimal
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


def _to_float(value: Any, directive_name: str) -> float | int | decimal.Decimal:
    """Coerce *value* to a number, raising GraphQLError on failure.

    Shared guard used by all numeric directives to convert implementation
    exceptions into GraphQL errors before they reach the client. Finite
    Decimal and plain int values are returned unchanged so Decimal and BigInt
    fields keep their exactness; everything else becomes a float.

    Args:
        value: The field value to coerce.
        directive_name: The directive name shown in the error message (e.g. '@floor').

    Returns:
        The exact Decimal or int, or the value coerced to float.

    Raises:
        GraphQLError: When the value cannot be interpreted as a number.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, decimal.Decimal) and value.is_finite():
        return value
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
    if not _wants_string(info):
        return number
    # Plain notation, as the Decimal scalar emits, rather than "1E+3".
    return format(number, "f") if isinstance(number, decimal.Decimal) else str(number)


def _round(
    number: float | int | decimal.Decimal, precision: int
) -> float | int | decimal.Decimal:
    """Round half-to-even to *precision* places, exactly for int and Decimal.

    Args:
        number: The value from _to_float.
        precision: Decimal places; zero or below rounds to a whole number.

    Returns:
        An int when precision is zero or below, otherwise a value of the input type.
    """
    if isinstance(number, decimal.Decimal):
        # Past the value's own magnitude the result is 0; past its scale, unchanged.
        precision = max(precision, -(number.adjusted() + 2))
        if precision >= -int(number.as_tuple().exponent):
            rounded = number
        else:
            with decimal.localcontext() as ctx:
                ctx.prec = len(number.as_tuple().digits) + 2
                rounded = number.quantize(decimal.Decimal(1).scaleb(-precision))
    else:
        rounded = round(number, precision)
    return int(rounded) if precision <= 0 else rounded


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

        Raises:
            GraphQLError: If the value is not numeric or is non-finite.
        """
        if value is None:
            return None
        number = _to_float(value, "@floor")
        if isinstance(number, float) and not math.isfinite(number):
            raise GraphQLError("@floor cannot operate on a non-finite value.")
        return _coerce(math.floor(number), info)


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
        precision = int(args.get("precision") or 0)
        return _coerce(_round(_to_float(value, "@round"), precision), info)


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
        number = _to_float(value, "@abs")
        # copy_abs: abs(Decimal) would round to the 28-digit context precision.
        if isinstance(number, decimal.Decimal):
            return _coerce(number.copy_abs(), info)
        return _coerce(abs(number), info)
