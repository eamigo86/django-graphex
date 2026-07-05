"""String manipulation GraphQL directives."""

from __future__ import annotations

import base64
import re
from typing import TYPE_CHECKING, Any

from django.utils.text import slugify
from graphql import (
    GraphQLArgument,
    GraphQLBoolean,
    GraphQLError,
    GraphQLInt,
    GraphQLNonNull,
    GraphQLString,
)

from django_graphex._strconv import to_camel_case, to_snake_case

from ..utils import to_kebab_case
from .base import BaseExtraGraphQLDirective

if TYPE_CHECKING:
    from graphql import GraphQLResolveInfo

# Maximum allowed total width or precision in a @number format spec.
# This bounds the maximum output string length per field and prevents
# memory exhaustion from client-supplied specs like "1000000.5f".
_NUMBER_FORMAT_MAX_WIDTH = 100

# Maximum allowed width for the @center directive.
# str.center() accepts any non-negative int — including 2,147,483,647 (the
# maximum GraphQL Int), which would allocate a ~2 GB string from a single
# unauthenticated field.  We cap it at a generous but safe value.
_CENTER_MAX_WIDTH = 10_000

# Maximum digit-string length accepted by _extract_width_precision before
# calling int().  _NUMBER_FORMAT_MAX_WIDTH is 100 (at most 3 meaningful
# digits), so any digit run longer than this is unconditionally over the
# cap — no need to convert it.  We use 9 (one more than the max digit count
# for _NUMBER_FORMAT_MAX_WIDTH × 10) to give plenty of headroom while staying
# well clear of Python 3.11+'s 4300-digit int-string conversion limit.
_NUMBER_FORMAT_MAX_DIGIT_LEN = 9

# Regex matching the body of a Python format spec *after* the optional
# [[fill]align] prefix has been stripped.  Covers:
#   [sign][z][#][0][width][grouping_option][.precision][type]
# The leading [^0-9]* approach in the old regex failed when the fill char
# was a digit (e.g. "0<1000000f"): [^0-9]* stopped before the digit, then
# the width group captured only the fill digit (not the real width), so the
# DoS guard saw width=0 and let the huge spec through.
_FORMAT_SPEC_BODY_RE = re.compile(
    r"^[+\- ]?z?#?0?(?P<width>\d+)?[,_]?(?:\.(?P<precision>\d+))?[a-zA-Z%]?$"
)


def _extract_width_precision(spec: str) -> tuple[int, int]:
    """Extract the numeric width and precision from a Python format mini-language spec.

    Handles the optional ``[[fill]align]`` prefix correctly so that a digit
    fill character (e.g. ``0<1000000f``) does not bypass the width check.

    Args:
        spec: A Python format spec string as supplied to the ``@number`` directive.

    Returns:
        A ``(width, precision)`` tuple of integers (0 when absent).
    """
    body = spec
    # Strip optional [[fill]align]: if the second character is an align char
    # the first character is the fill (may be a digit or any other char).
    if len(body) >= 2 and body[1] in "<>=^":
        body = body[2:]
    elif body and body[0] in "<>=^":
        body = body[1:]

    m = _FORMAT_SPEC_BODY_RE.match(body)
    if not m:
        return 0, 0
    raw_width = m.group("width")
    raw_precision = m.group("precision")
    # Guard against Python 3.11+ int-string conversion limit (4300 digits).
    # Any digit run longer than _NUMBER_FORMAT_MAX_DIGIT_LEN is unconditionally
    # over _NUMBER_FORMAT_MAX_WIDTH, so return a sentinel that guarantees the
    # width/precision guard in resolve() fires its clean GraphQLError path —
    # never let int() touch a giant string.
    if raw_width and len(raw_width) > _NUMBER_FORMAT_MAX_DIGIT_LEN:
        return _NUMBER_FORMAT_MAX_WIDTH + 1, 0
    if raw_precision and len(raw_precision) > _NUMBER_FORMAT_MAX_DIGIT_LEN:
        return 0, _NUMBER_FORMAT_MAX_WIDTH + 1
    return (int(raw_width) if raw_width else 0), (
        int(raw_precision) if raw_precision else 0
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
    """Substitute a fallback value when the field is None or empty.

    The required "to" argument supplies the replacement, returned whenever the
    field value is falsy (None or an empty string); otherwise the original value
    is passed through.
    """

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
        **kwargs: Any,
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
    """Base64-encode or decode a string field value.

    The optional "op" argument selects "encode" (default) or "decode"; both use
    the URL-safe alphabet. An empty field value yields None.
    """

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
        **kwargs: Any,
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

        Raises:
            GraphQLError: When "op" is "decode" and the value is not valid
                base64 or does not decode to a UTF-8 string.
        """
        if not value:
            return None

        op = args.get("op") or "encode"
        data = _as_str(value).encode("utf-8")
        if op == "decode":
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8")
            except (Exception,) as exc:
                raise GraphQLError(
                    "@base64 could not decode value: input is not valid base64 or "
                    "does not decode to a UTF-8 string."
                ) from exc
        return base64.urlsafe_b64encode(data).decode("ascii")


class NumberGraphQLDirective(BaseExtraGraphQLDirective):
    """Format a numeric field value with a Python format spec.

    The required "as" argument is a Python format-mini-language spec (for example
    ".2f"). The value is coerced to float first, then formatted. The spec's
    width and precision are bounded to guard against memory exhaustion from
    hostile client-supplied specs.
    """

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
        **kwargs: Any,
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
                "_NUMBER_FORMAT_MAX_WIDTH" (this bounds output length and
                prevents memory exhaustion from client-supplied specs like
                "1000000.5f"), when the value cannot be coerced to a number, or
                when the format spec itself is invalid.
        """
        spec = args.get("as") or ""
        width, precision = _extract_width_precision(spec)
        if width > _NUMBER_FORMAT_MAX_WIDTH or precision > _NUMBER_FORMAT_MAX_WIDTH:
            raise GraphQLError(
                f"@number format spec width/precision must not exceed "
                f"{_NUMBER_FORMAT_MAX_WIDTH}; got {spec!r}"
            )
        # Coerce the value to float first; blame the VALUE on failure.
        try:
            float_value = float(value or 0)
        except (ValueError, TypeError) as exc:
            raise GraphQLError(
                f"@number could not coerce value {value!r} to a number: {exc}"
            ) from exc
        # Apply the format spec; blame the SPEC on failure.
        try:
            return format(float_value, spec)
        except (ValueError, TypeError) as exc:
            raise GraphQLError(f"Invalid @number format spec {spec!r}: {exc}") from exc


class CurrencyGraphQLDirective(BaseExtraGraphQLDirective):
    """Format a numeric field value as a currency string.

    The value is rendered with thousands separators and two decimal places,
    prefixed by the optional "symbol" argument (defaulting to "$").
    """

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
        **kwargs: Any,
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

        Raises:
            GraphQLError: When the value cannot be interpreted as a number.
        """
        symbol = args.get("symbol") or "$"
        try:
            return symbol + format(float(value or 0), ",.2f")
        except (ValueError, TypeError) as exc:
            raise GraphQLError(
                f"@currency could not format value {value!r}: expected a numeric value."
            ) from exc


class LowercaseGraphQLDirective(BaseExtraGraphQLDirective):
    """Lowercase every character of the field value.

    Non-string values are stringified before conversion.
    """

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
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
    """Uppercase every character of the field value.

    Non-string values are stringified before conversion.
    """

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
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
    """Capitalize the field value.

    The first character is uppercased and the rest are lowercased. Non-string
    values are stringified before conversion.
    """

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
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
    """Convert the field value to camelCase.

    Non-string values are stringified before conversion.
    """

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
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
    """Convert the field value to snake_case.

    Non-string values are stringified before conversion.
    """

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
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
    """Convert the field value to kebab-case.

    Non-string values are stringified before conversion.
    """

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
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
        **kwargs: Any,
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
        **kwargs: Any,
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
        **kwargs: Any,
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
        **kwargs: Any,
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

        Raises:
            GraphQLError: When the requested width exceeds "_CENTER_MAX_WIDTH"
                (this cap prevents a single field from allocating a huge string),
                or when "fillchar" is not exactly one character.
        """
        value = _as_str(value)
        width = args.get("width")
        if width is None:
            width = len(value)
        int_width = int(width)
        if int_width > _CENTER_MAX_WIDTH:
            raise GraphQLError(
                f"@center width must not exceed {_CENTER_MAX_WIDTH}; got {int_width}"
            )
        # Use None-check (not truthiness) so an explicit empty-string fillchar
        # is caught by the length guard below instead of silently defaulting
        # to a space.
        raw_fillchar = args.get("fillchar")
        fillchar = raw_fillchar if raw_fillchar is not None else " "
        if len(fillchar) != 1:
            raise GraphQLError(
                f"@center fillchar must be exactly one character; got {fillchar!r} "
                f"(length {len(fillchar)})."
            )
        return value.center(int_width, fillchar)


class ReplaceGraphQLDirective(BaseExtraGraphQLDirective):
    """Return a copy of the string with all occurrences of substring old replaced by new.

    If the optional argument count is given, only the first count occurrences are replaced.
    """

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Get arguments for the replace directive.

        Returns:
            A mapping of argument names to their definitions.
        """
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
        **kwargs: Any,
    ) -> Any:
        """Resolve the replace directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The string with occurrences of "old" replaced by "new". When
            "count" is given only the first "count" occurrences are replaced.
        """
        count = args.get("count")
        count = -1 if count is None else int(count)
        return _as_str(value).replace(args.get("old"), args.get("new"), count)


class TruncateGraphQLDirective(BaseExtraGraphQLDirective):
    """Shorten a string to "length" characters, appending "end" (default '…').

    Unless "killwords" is true, the string is cut on a word boundary.
    """

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Get arguments for the truncate directive.

        Returns:
            A mapping of argument names to their definitions.
        """
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
        **kwargs: Any,
    ) -> Any:
        """Resolve the truncate directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The string shortened to "length" characters with "end" appended, or
            the original text when it already fits. Unless "killwords" is true,
            the cut falls on a word boundary.
        """
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
    """Convert the field value into a URL-safe slug.

    Delegates to Django's "slugify"; non-string values are stringified first.
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
        """Resolve the slugify directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The URL-safe slug produced by Django's "slugify".
        """
        return slugify(_as_str(value))
