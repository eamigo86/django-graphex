"""Bounded-output contracts for the replace directive."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from graphql import GraphQLError, GraphQLNonNull, GraphQLString, graphql_sync

from django_graphex.core import ObjectType, field
from django_graphex.directives import all_directives
from django_graphex.directives.string import ReplaceGraphQLDirective
from django_graphex.middleware import GraphQLDirectiveMiddleware
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.settings import graphql_api_settings


class _Query(ObjectType):
    """Expose nullable and required strings for directive error propagation."""

    text = field(GraphQLString)
    other = field(GraphQLString)
    required = field(GraphQLNonNull(GraphQLString))


_SCHEMA = DjangoGraphQLSchema(query=_Query, directives=list(all_directives))


def _execute(query: str, text: str = "abc") -> Any:
    """Execute a replace selection with independently observable sibling data.

    Args:
        query: The GraphQL selection to execute.
        text: Source text for nullable and required fields.

    Returns:
        The GraphQL execution result.
    """
    return graphql_sync(
        _SCHEMA.graphql_schema,
        query,
        root_value={"text": text, "required": text, "other": "safe"},
        middleware=[GraphQLDirectiveMiddleware()],
    )


@override_settings(DJANGO_GRAPHEX={"MAX_REPLACE_OUTPUT_LENGTH": 8})
def test_replace_rejects_expansion_before_returning_result() -> None:
    """Oversized replace output becomes a field error while siblings survive.

    This is an actual GraphQL execution, not a direct helper invocation.
    """
    result = _execute('{ text @replace(old: "", new: "WXYZ") other }')
    assert result.data == {"text": None, "other": "safe"}
    assert result.errors and len(result.errors) == 1
    assert "@replace" in result.errors[0].message
    assert "8" in result.errors[0].message


@override_settings(DJANGO_GRAPHEX={"MAX_REPLACE_OUTPUT_LENGTH": 8})
def test_replace_nonnull_error_bubbles() -> None:
    """A required string field bubbles an over-cap error normally.

    GraphQL nulls the entire root when its required field fails.
    """
    result = _execute('{ required @replace(old: "", new: "WXYZ") other }')
    assert result.data is None
    assert result.errors and len(result.errors) == 1
    assert "@replace" in result.errors[0].message


def test_replace_limit_default_is_one_million() -> None:
    """The approved output cap is enabled by default.

    Reading the setting avoids allocating a million-character example.
    """
    assert graphql_api_settings.MAX_REPLACE_OUTPUT_LENGTH == 1_000_000


@pytest.mark.parametrize("value", [0, -1])
def test_replace_limit_rejects_nonpositive_values(value: int) -> None:
    """A nonpositive configured cap fails through the existing limit validator.

    Args:
        value: Invalid cap to inspect.
    """
    with override_settings(DJANGO_GRAPHEX={"MAX_REPLACE_OUTPUT_LENGTH": value}):
        with pytest.raises(ImproperlyConfigured, match="MAX_REPLACE_OUTPUT_LENGTH"):
            _ = graphql_api_settings.MAX_REPLACE_OUTPUT_LENGTH


@pytest.mark.parametrize("value", [True, False, "8", 8.0])
def test_replace_limit_rejects_noninteger_values(value: Any) -> None:
    """Boolean, floating and textual settings cannot masquerade as a cap.

    Args:
        value: Non-integer configuration value.
    """
    with override_settings(DJANGO_GRAPHEX={"MAX_REPLACE_OUTPUT_LENGTH": value}):
        with pytest.raises(ImproperlyConfigured, match="MAX_REPLACE_OUTPUT_LENGTH"):
            _ = graphql_api_settings.MAX_REPLACE_OUTPUT_LENGTH


def test_replace_limit_none_preserves_uncapped_behavior() -> None:
    """Explicit None keeps the legacy uncapped replacement behavior.

    The sample output is deliberately tiny despite the uncapped setting.
    """
    with override_settings(DJANGO_GRAPHEX={"MAX_REPLACE_OUTPUT_LENGTH": None}):
        result = _execute('{ text @replace(old: "", new: "WXYZ") }')
    assert result.errors is None
    assert result.data == {"text": "WXYZaWXYZbWXYZcWXYZ"}


@pytest.mark.parametrize(
    ("source", "old", "new", "count", "expected"),
    [
        ("😀a", "", "é", -1, "é😀éaé"),
        ("abc", "", "xy", 0, "abc"),
        ("abc", "", "xy", 2, "xyaxybc"),
        ("aaaa", "aa", "xyz", -1, "xyzxyz"),
        ("aaaa", "a", "", 2, "aa"),
        ("abc", "z", "LONG", -1, "abc"),
    ],
)
def test_replace_exact_python_semantics(
    source: str, old: str, new: str, count: int, expected: str
) -> None:
    """Small Unicode, count and nonoverlap cases match Python exactly.

    Args:
        source: Original text.
        old: Nonoverlapping match pattern.
        new: Replacement text.
        count: Maximum replacements, or negative for all.
        expected: Python replacement result.
    """
    assert source.replace(old, new, count) == expected
    with override_settings(DJANGO_GRAPHEX={"MAX_REPLACE_OUTPUT_LENGTH": len(expected)}):
        actual = ReplaceGraphQLDirective.resolve(
            source,
            {"old": old, "new": new, "count": count},
            None,
            None,
            SimpleNamespace(return_type=GraphQLString),
        )
    assert actual == expected


@override_settings(DJANGO_GRAPHEX={"MAX_REPLACE_OUTPUT_LENGTH": 2})
def test_replace_rejects_already_oversized_noop() -> None:
    """An unchanged result above the cap is still too large.

    Count zero and an absent match cannot bypass the resulting-string cap.
    """
    with pytest.raises(GraphQLError, match="@replace"):
        ReplaceGraphQLDirective.resolve(
            "abc",
            {"old": "z", "new": "xx", "count": 0},
            None,
            None,
            SimpleNamespace(return_type=GraphQLString),
        )


@override_settings(DJANGO_GRAPHEX={"MAX_REPLACE_OUTPUT_LENGTH": 8})
def test_replace_rejects_without_calling_replace() -> None:
    """The guard rejects a small predicted expansion before replacement.

    Raises:
        AssertionError: Only if replacement is called before the size guard.
    """

    class TrapString(str):
        """Detect whether replacement was attempted before the size check."""

        def replace(self, old: str, new: str, count: int = -1) -> str:
            """Fail if the bounded directive calls replacement.

            Args:
                old: Substring to replace.
                new: Replacement string.
                count: Replacement maximum.

            Raises:
                AssertionError: Unconditionally, because no allocation is allowed.
            """
            raise AssertionError("replace called before size check")

    with pytest.raises(GraphQLError, match="@replace"):
        ReplaceGraphQLDirective.resolve(
            TrapString("abc"),
            {"old": "", "new": "WXYZ"},
            None,
            None,
            SimpleNamespace(return_type=GraphQLString),
        )


@override_settings(DJANGO_GRAPHEX={"MAX_REPLACE_OUTPUT_LENGTH": 1})
def test_replace_preserves_null_field() -> None:
    """A null field bypasses replacement without introducing a size error.

    Null propagation remains the shared string-directive policy.
    """
    assert (
        ReplaceGraphQLDirective.resolve(
            None,
            {"old": "", "new": "long"},
            None,
            None,
            SimpleNamespace(return_type=GraphQLString),
        )
        is None
    )
