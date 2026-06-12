"""String manipulation GraphQL directives."""

from __future__ import annotations

import base64
import re
from typing import TYPE_CHECKING, Any

from django.utils.text import slugify
from graphene.utils.str_converters import to_camel_case, to_snake_case
from graphql import (
    GraphQLArgument,
    GraphQLBoolean,
    GraphQLError,
    GraphQLInt,
    GraphQLNonNull,
    GraphQLString,
)

from ..utils import to_kebab_case
from .base import BaseExtraGraphQLDirective

if TYPE_CHECKING:
    from graphql import GraphQLResolveInfo

# Maximum allowed total width or precision in a @number format spec.
# This bounds the maximum output string length per field and prevents
# memory exhaustion from client-supplied specs like "1000000.5f".
_NUMBER_FORMAT_MAX_WIDTH = 100

# Regex to extract the numeric width and precision from a Python format spec.
# Matches optional fill/align, sign, grouping option, width, .precision.
_FORMAT_SPEC_NUMBERS_RE = re.compile(
    r"[^0-9]*(?P<width>[0-9]*)(?:\.(?P<precision>[0-9]+))?"
)

__all__ = (
    "DefaultGraphQLDirective",
    "Base64GraphQLDirective",
    "NumberGraphQLDirective",
    "CurrencyGraphQLDirective",
    "LowercaseGraphQLDirective",
    "UppercaseGraphQLDirective",
    "CapitalizeGraphQLDirective",
    "CamelCaseGraphQLDirective",
    "SnakeCaseGraphQLDirective",
    "KebabCaseGraphQLDirective",
    "SwapCaseGraphQLDirective",
    "StripGraphQLDirective",
    "TitleCaseGraphQLDirective",
    "CenterGraphQLDirective",
    "ReplaceGraphQLDirective",
    "TruncateGraphQLDirective",
    "SlugifyGraphQLDirective",
)


def _as_str(value: Any) -> str:
    """Coerce a value to a string, leaving real strings untouched.

    Args:
        value: The value to coerce.

    Returns:
        The value itself when it is already a string, otherwise its
        string representation.
    """
    return value if isinstance(value, str) else str(value)


class DefaultGraphQLDirective(BaseExtraGraphQLDirective):
    """Default to given value if None or empty string."""

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Get arguments for the default directive.

        Returns:
            A mapping of argument names to their definitions.
        """
        return {
            "to": GraphQLArgument(
                GraphQLNonNull(GraphQLString), description="Value to default to"
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
        """Resolve the default directive value.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The "to" argument when the value is empty, else the value.
        """
        if not value:
            return args.get("to")
        return value


class Base64GraphQLDirective(BaseExtraGraphQLDirective):
    """Base64 encode or decode string values."""

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Get arguments for the base64 directive.

        Returns:
            A mapping of argument names to their definitions.
        """
        return {
            "op": GraphQLArgument(
                GraphQLString, description='Action to perform: "encode" or "decode"'
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
    ) -> str | None:
        """Resolve the base64 directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The base64 encoded or decoded string, or None when empty.
        """
        if not value:
            return None

        op = args.get("op") or "encode"
        data = _as_str(value).encode("utf-8")
        if op == "decode":
            return base64.urlsafe_b64decode(data).decode("utf-8")
        return base64.urlsafe_b64encode(data).decode("ascii")


class NumberGraphQLDirective(BaseExtraGraphQLDirective):
    """String formatting like a specified Python number formatting."""

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Get arguments for the number directive.

        Returns:
            A mapping of argument names to their definitions.
        """
        return {
            "as": GraphQLArgument(
                GraphQLNonNull(GraphQLString),
                description="A Python format spec, e.g. '.2f'",
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
    ) -> str:
        """Resolve the number formatting directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The value formatted with the given Python format spec.

        Raises:
            GraphQLError: When the format spec's width or precision exceeds
                ``_NUMBER_FORMAT_MAX_WIDTH`` (prevents memory DoS via
                client-supplied specs like ``"1000000.5f"``).
        """
        spec = args.get("as") or ""
        m = _FORMAT_SPEC_NUMBERS_RE.match(spec)
        if m:
            raw_width = m.group("width")
            raw_precision = m.group("precision")
            width = int(raw_width) if raw_width else 0
            precision = int(raw_precision) if raw_precision else 0
            if width > _NUMBER_FORMAT_MAX_WIDTH or precision > _NUMBER_FORMAT_MAX_WIDTH:
                raise GraphQLError(
                    f"@number format spec width/precision must not exceed "
                    f"{_NUMBER_FORMAT_MAX_WIDTH}; got {spec!r}"
                )
        try:
            return format(float(value or 0), spec)
        except (ValueError, TypeError) as exc:
            raise GraphQLError(f"Invalid @number format spec {spec!r}: {exc}") from exc


class CurrencyGraphQLDirective(BaseExtraGraphQLDirective):
    """Format numeric values as currency."""

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Get arguments for the currency directive.

        Returns:
            A mapping of argument names to their definitions.
        """
        return {
            "symbol": GraphQLArgument(
                GraphQLString, description="Currency symbol (default: $)"
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
    ) -> str:
        """Resolve the currency formatting directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The value formatted as currency prefixed with the symbol.
        """
        symbol = args.get("symbol") or "$"
        return symbol + format(float(value or 0), ",.2f")


class LowercaseGraphQLDirective(BaseExtraGraphQLDirective):
    """Convert string to lowercase."""

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> str:
        """Resolve the lowercase directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The lowercased string.
        """
        return _as_str(value).lower()


class UppercaseGraphQLDirective(BaseExtraGraphQLDirective):
    """Convert string to uppercase."""

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> str:
        """Resolve the uppercase directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The uppercased string.
        """
        return _as_str(value).upper()


class CapitalizeGraphQLDirective(BaseExtraGraphQLDirective):
    """Capitalize the first character and lowercase the rest of the string."""

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> str:
        """Resolve the capitalize directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The capitalized string.
        """
        return _as_str(value).capitalize()


class CamelCaseGraphQLDirective(BaseExtraGraphQLDirective):
    """Convert string to camelCase."""

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> str:
        """Resolve the camelCase directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The camelCased string.
        """
        return to_camel_case(_as_str(value))


class SnakeCaseGraphQLDirective(BaseExtraGraphQLDirective):
    """Convert string to snake_case."""

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> str:
        """Resolve the snake_case directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The snake_cased string.
        """
        return to_snake_case(_as_str(value).title().replace(" ", ""))


class KebabCaseGraphQLDirective(BaseExtraGraphQLDirective):
    """Convert string to kebab-case."""

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> str:
        """Resolve the kebab-case directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The kebab-cased string.
        """
        return to_kebab_case(_as_str(value))


class SwapCaseGraphQLDirective(BaseExtraGraphQLDirective):
    """Swap the case of every character in the string.

    Uppercase characters are converted to lowercase and vice versa.
    """

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> str:
        """Resolve the swapcase directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The string with swapped character cases.
        """
        return _as_str(value).swapcase()


class StripGraphQLDirective(BaseExtraGraphQLDirective):
    """Remove the leading and trailing characters from the string.

    The "chars" argument is a string specifying the set of characters to be
    removed. If omitted, all leading/trailing whitespace is removed.
    """

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Get arguments for the strip directive.

        Returns:
            A mapping of argument names to their definitions.
        """
        return {
            "chars": GraphQLArgument(
                GraphQLString,
                description="Set of characters to remove (default: whitespace)",
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
    ) -> str:
        """Resolve the strip directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The string with the requested characters stripped.
        """
        # chars=None -> str.strip() removes all whitespace (spaces, tabs, ...).
        return _as_str(value).strip(args.get("chars"))


class TitleCaseGraphQLDirective(BaseExtraGraphQLDirective):
    """Titlecase the string so each word starts with an uppercase character.

    The remaining characters of every word are lowercased.
    """

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> str:
        """Resolve the title case directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The titlecased string.
        """
        return _as_str(value).title()


class CenterGraphQLDirective(BaseExtraGraphQLDirective):
    """Return centered in a string of length width.

    Padding is done using the specified fillchar.
    The original string is returned if width is less than or equal to len(s).
    """

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Get arguments for the center directive.

        Returns:
            A mapping of argument names to their definitions.
        """
        return {
            "width": GraphQLArgument(
                GraphQLNonNull(GraphQLInt), description="Total width of the result"
            ),
            "fillchar": GraphQLArgument(
                GraphQLString, description="Character used for padding (default: space)"
            ),
        }

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> str:
        """Resolve the center directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The centered string padded to the requested width.
        """
        value = _as_str(value)
        width = args.get("width")
        if width is None:
            width = len(value)
        return value.center(int(width), args.get("fillchar") or " ")


class ReplaceGraphQLDirective(BaseExtraGraphQLDirective):
    """Return a copy of the string with all occurrences of substring old replaced by new.

    If the optional argument count is given, only the first count occurrences are replaced.
    """

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Get arguments for the replace directive."""
        return {
            "old": GraphQLArgument(
                GraphQLNonNull(GraphQLString),
                description="Substring to replace",
            ),
            "new": GraphQLArgument(
                GraphQLNonNull(GraphQLString),
                description="Replacement substring",
            ),
            "count": GraphQLArgument(
                GraphQLInt, description="Maximum number of occurrences to replace"
            ),
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
        """Resolve the replace directive."""
        count = args.get("count")
        count = -1 if count is None else int(count)
        return _as_str(value).replace(args.get("old"), args.get("new"), count)


class TruncateGraphQLDirective(BaseExtraGraphQLDirective):
    """Shorten a string to "length" characters, appending "end" (default '…').

    Unless "killwords" is true, the string is cut on a word boundary.
    """

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Get arguments for the truncate directive."""
        return {
            "length": GraphQLArgument(
                GraphQLNonNull(GraphQLInt),
                description="Maximum number of characters to keep",
            ),
            "end": GraphQLArgument(
                GraphQLString,
                description="Suffix appended when truncated (default '…')",
            ),
            "killwords": GraphQLArgument(
                GraphQLBoolean,
                description="Cut in the middle of words instead of on a boundary",
            ),
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
        """Resolve the truncate directive."""
        text = _as_str(value)
        length = args.get("length")
        if length is None or len(text) <= length:
            return text

        end = args.get("end")
        if end is None:
            end = "…"
        if args.get("killwords"):
            return text[:length] + end
        truncated = text[:length].rsplit(" ", 1)[0]
        return truncated + end


class SlugifyGraphQLDirective(BaseExtraGraphQLDirective):
    """Convert a string into a URL-safe slug (Django "slugify")."""

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs,
    ) -> Any:
        """Resolve the slugify directive."""
        return slugify(_as_str(value))
