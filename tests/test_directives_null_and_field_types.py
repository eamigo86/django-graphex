# -*- coding: utf-8 -*-
"""Null handling and field-type awareness for the string-family directives.

Three defects, all in "directives/string.py":

(a) every string directive stringified a NULL field value through "_as_str",
    so a null column surfaced as the literal text "None" ("@uppercase" ->
    "NONE", "@slugify" -> "none"). The numeric family already returns None for
    a None value, so the two families disagreed;
(b) "@default" substituted its fallback for ANY falsy value, so a legitimate
    "0", "False" or "[]" was replaced by the fallback string and then failed
    serialization;
(c) "@number" / "@currency" always returned a formatted STRING, so on the
    "Int" / "Float" fields they are documented for the field nulled with an
    opaque "Int cannot represent non-integer value" coercion error.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from graphql import GraphQLFloat, GraphQLInt, GraphQLString

from django_graphex.directives.string import (
    CapitalizeGraphQLDirective,
    CenterGraphQLDirective,
    CurrencyGraphQLDirective,
    DefaultGraphQLDirective,
    KebabCaseGraphQLDirective,
    LowercaseGraphQLDirective,
    NumberGraphQLDirective,
    ReplaceGraphQLDirective,
    SlugifyGraphQLDirective,
    SnakeCaseGraphQLDirective,
    StripGraphQLDirective,
    SwapCaseGraphQLDirective,
    TitleCaseGraphQLDirective,
    TruncateGraphQLDirective,
    UppercaseGraphQLDirective,
)


def _info(return_type: Any = GraphQLString) -> SimpleNamespace:
    """Build a minimal stand-in for GraphQLResolveInfo carrying "return_type".

    Args:
        return_type: The field return type the directive's resolve should see.

    Returns:
        A namespace exposing "return_type", enough for the directive resolvers
        under test.
    """
    return SimpleNamespace(return_type=return_type)


#: "(directive, args)" pairs for every string directive that must pass a NULL
#: field value straight through instead of rendering the text "None".
_NULL_CASES: tuple[tuple[Any, dict[str, Any]], ...] = (
    (UppercaseGraphQLDirective, {}),
    (LowercaseGraphQLDirective, {}),
    (CapitalizeGraphQLDirective, {}),
    (SlugifyGraphQLDirective, {}),
    (SnakeCaseGraphQLDirective, {}),
    (KebabCaseGraphQLDirective, {}),
    (SwapCaseGraphQLDirective, {}),
    (TitleCaseGraphQLDirective, {}),
    (StripGraphQLDirective, {"chars": None}),
    (CenterGraphQLDirective, {"width": 10, "fillchar": "-"}),
    (ReplaceGraphQLDirective, {"old": "a", "new": "b", "count": None}),
    (TruncateGraphQLDirective, {"length": 3, "end": None, "killwords": None}),
)


class TestStringDirectivesPassNullThrough:
    """A NULL field value must stay NULL through every string directive.

    Guards defect (a): "_as_str" called "str(None)", so the API answered with
    the literal text "None" for a null column.
    """

    @pytest.mark.parametrize(("directive", "args"), _NULL_CASES)
    def test_none_value_returns_none(
        self, directive: Any, args: dict[str, Any]
    ) -> None:
        """Resolving a None value must return None, not a stringified "None".

        If this breaks, a null column renders as the text "None" (or "NONE",
        or the slug "none") — data corruption from the client's point of view.

        Args:
            directive: The directive class under test.
            args: The coerced directive arguments to pass to "resolve".
        """
        assert directive.resolve(None, args, None, None, _info()) is None

    def test_non_null_value_still_transformed(self) -> None:
        """A real string value must still be transformed as before.

        If this breaks, the null guard would swallow ordinary values too.
        """
        assert UppercaseGraphQLDirective.resolve("ab", {}, None, None, _info()) == "AB"
        assert SlugifyGraphQLDirective.resolve("A B", {}, None, None, _info()) == "a-b"

    def test_non_string_value_still_stringified(self) -> None:
        """A non-string, non-null value must still be stringified.

        If this breaks, "@uppercase" on an Int field stops working entirely
        instead of only skipping nulls.
        """
        assert UppercaseGraphQLDirective.resolve(12, {}, None, None, _info()) == "12"


class TestDefaultOnlyFiresOnNullOrEmptyString:
    """ "@default" must substitute only for None and the empty string.

    Guards defect (b): "if not value" also caught "0", "False" and "[]",
    replacing a legitimate value with the fallback string.
    """

    @pytest.mark.parametrize("value", [None, ""])
    def test_null_and_empty_string_get_the_fallback(self, value: Any) -> None:
        """None and "" must be replaced by the "to" argument.

        Args:
            value: The resolved field value under test.
        """
        assert (
            DefaultGraphQLDirective.resolve(
                value, {"to": "fallback"}, None, None, _info()
            )
            == "fallback"
        )

    @pytest.mark.parametrize("value", [0, 0.0, False, [], {}])
    def test_other_falsy_values_pass_through(self, value: Any) -> None:
        """A falsy but legitimate value must NOT be replaced.

        If this breaks, an empty list is replaced by the fallback string and
        the field hard-fails with "Expected Iterable, but did not find one".

        Args:
            value: The resolved field value under test.
        """
        result = DefaultGraphQLDirective.resolve(
            value, {"to": "fallback"}, None, None, _info()
        )
        assert result is value

    def test_truthy_value_passes_through(self) -> None:
        """A non-empty value must still pass through untouched.

        If this breaks, "@default" would clobber real data.
        """
        assert (
            DefaultGraphQLDirective.resolve("keep", {"to": "fb"}, None, None, _info())
            == "keep"
        )


class TestNumberAndCurrencyRespectTheFieldType:
    """ "@number" / "@currency" must not hand a string to a numeric field.

    Guards defect (c): both always returned a formatted string, which "Int" and
    "Float" fields cannot serialize, so every documented use nulled the field.
    """

    def test_number_on_int_field_returns_the_raw_value(self) -> None:
        """ "@number" on an Int field must return the value, not a string.

        If this breaks, "viewCount @number(as: ",.0f")" nulls the field with
        "Int cannot represent non-integer value: '1,234'".
        """
        result = NumberGraphQLDirective.resolve(
            1234, {"as": ",.2f"}, None, None, _info(GraphQLInt)
        )
        assert result == 1234

    def test_currency_on_float_field_returns_the_raw_value(self) -> None:
        """ "@currency" on a Float field must return the value, not a string.

        If this breaks, "price @currency" nulls the field with "Float cannot
        represent non numeric value: '$12.50'".
        """
        result = CurrencyGraphQLDirective.resolve(
            12.5, {"symbol": "$"}, None, None, _info(GraphQLFloat)
        )
        assert result == 12.5

    def test_number_on_string_field_still_formats(self) -> None:
        """ "@number" on a String field must keep formatting as documented.

        If this breaks, the directive stops doing its job on the field type it
        is meant for.
        """
        result = NumberGraphQLDirective.resolve(
            1234, {"as": ",.2f"}, None, None, _info(GraphQLString)
        )
        assert result == "1,234.00"

    def test_currency_on_string_field_still_formats(self) -> None:
        """ "@currency" on a String field must keep formatting as documented.

        If this breaks, currency formatting is lost on its own field type.
        """
        result = CurrencyGraphQLDirective.resolve(
            12.5, {"symbol": "$"}, None, None, _info(GraphQLString)
        )
        assert result == "$12.50"

    def test_oversized_spec_still_rejected_on_a_numeric_field(self) -> None:
        """The format-spec width cap must still fire on a numeric field.

        If this breaks, the field-type guard would short-circuit the
        memory-exhaustion check for hostile client-supplied specs.
        """
        from graphql import GraphQLError

        with pytest.raises(GraphQLError):
            NumberGraphQLDirective.resolve(
                1.5, {"as": "1000000.5f"}, None, None, _info(GraphQLInt)
            )
