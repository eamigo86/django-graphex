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

from ..core.scalars import _DECIMAL_MAX_PLAIN_PADDING, _plain_decimal
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
    # Plain notation, as the Decimal scalar emits (scientific form past its
    # padding bound), rather than "1E+3".
    return (
        _plain_decimal(number) if isinstance(number, decimal.Decimal) else str(number)
    )


def _integral(number: decimal.Decimal) -> int | decimal.Decimal:
    """Turn an integral Decimal into an int unless that expansion is unbounded.

    A Decimal such as 1E+100000 is already integral; expanding it to an int is
    quadratic and the text of an int over 4300 digits is refused. Past the
    plain-notation padding bound of the Decimal scalar the Decimal itself is
    returned so the serializer keeps the scientific form in constant time.

    Args:
        number: A Decimal with no fractional part.

    Returns:
        An int, or the unchanged Decimal when its magnitude is beyond the bound.
    """
    if number.is_zero():
        return 0
    if number.adjusted() >= _DECIMAL_MAX_PLAIN_PADDING:
        return number
    return int(number)


def _to_integral(number: Any, rounding: str) -> Any:
    """Round to a whole number in the given mode, exactly for Decimal.

    Args:
        number: The value from _to_float.
        rounding: A decimal rounding mode, applied to Decimal values only.

    Returns:
        A whole number: an int, or a Decimal past the plain-notation bound.
    """
    if isinstance(number, decimal.Decimal):
        if number.as_tuple().exponent >= 0:  # type: ignore[operator]
            return _integral(number)
        return _integral(number.to_integral_value(rounding=rounding))
    return math.floor(number) if rounding == decimal.ROUND_FLOOR else math.ceil(number)


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
        target = -precision
        rounded = number
        # A value already at or coarser than the target scale is unchanged.
        if number.as_tuple().exponent < target:  # type: ignore[operator]
            # Size the context to the result (plus one digit for a carry) so the
            # quantize can neither overflow its precision nor round twice.
            ctx = decimal.Context(
                prec=max(number.adjusted() - target + 2, 1),
                rounding=decimal.ROUND_HALF_EVEN,
                Emax=decimal.MAX_EMAX,
                Emin=decimal.MIN_EMIN,
            )
            rounded = number.quantize(decimal.Decimal((0, (1,), target)), context=ctx)
        return _integral(rounded) if precision <= 0 else rounded
    # A whole number far below half of 10 ** -precision rounds to 0; skip building
    # that power. 10 ** k > 2 ** (3 * k) >= 2 ** (bit_length + 1) > 2 * |n|.
    if isinstance(number, int) and -3 * precision > number.bit_length():
        return 0
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
        return _coerce(_to_integral(number, decimal.ROUND_FLOOR), info)


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
        number = _to_float(value, "@ceil")
        return _coerce(_to_integral(number, decimal.ROUND_CEILING), info)


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
