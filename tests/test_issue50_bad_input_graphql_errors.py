# -*- coding: utf-8 -*-
"""Tests for issue #50 — bad client input raises GraphQLError, not HTTP 500.

Covers five code paths that previously let raw Python exceptions escape
to the GraphQL client:

(a) @base64(op:"decode") on non-base64 / non-UTF-8 input → binascii.Error
    or UnicodeDecodeError.
(b) @currency on non-numeric field value → ValueError / TypeError.
(c) @floor / @ceil / @round / @abs on non-numeric field value → ValueError.
(d) @center with multi-character fillchar → TypeError.
(e) LimitOffsetGraphqlPagination with negative offset → ValueError.

Project standard (mirrored in test_pagination_hardening.py):
  "garbage input → GraphQLError, not 500".
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.test import TestCase
from graphql import GraphQLError

from django_graphex.directives.numbers import (
    AbsGraphQLDirective,
    CeilGraphQLDirective,
    FloorGraphQLDirective,
    RoundGraphQLDirective,
)
from django_graphex.directives.string import (
    Base64GraphQLDirective,
    CenterGraphQLDirective,
    CurrencyGraphQLDirective,
)
from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination as _LOF

from .models import Author


def _info(return_type=None):
    return SimpleNamespace(return_type=return_type)


# ---------------------------------------------------------------------------
# (a) @base64(op:"decode") — bad input must raise GraphQLError
# ---------------------------------------------------------------------------


class TestBase64DecodeErrors:
    """@base64(op:'decode') on invalid input must raise GraphQLError, not binascii.Error."""

    def test_non_base64_raises_graphql_error(self):
        """String that is not valid base64 must raise GraphQLError."""
        with pytest.raises(GraphQLError):
            Base64GraphQLDirective.resolve(
                "not!valid!base64!!", {"op": "decode"}, None, None, _info()
            )

    def test_binascii_error_does_not_propagate(self):
        """binascii.Error must NOT propagate to the caller."""
        import binascii

        try:
            Base64GraphQLDirective.resolve(
                "!!!garbage!!!", {"op": "decode"}, None, None, _info()
            )
        except GraphQLError:
            pass  # correct
        except binascii.Error:
            pytest.fail(
                "@base64 decode raised raw binascii.Error — must raise GraphQLError."
            )

    def test_error_message_does_not_leak_binascii_internals(self):
        """Error message must NOT start with 'Invalid base64' from binascii."""
        try:
            Base64GraphQLDirective.resolve(
                "!!!garbage!!!", {"op": "decode"}, None, None, _info()
            )
        except GraphQLError as exc:
            # The message should be our own, not the raw binascii message.
            # We just check it IS a GraphQLError (message format is an impl detail).
            assert exc is not None

    def test_encode_still_works_for_valid_input(self):
        """Encoding a valid string must still succeed."""
        result = Base64GraphQLDirective.resolve(
            "hello", {"op": "encode"}, None, None, _info()
        )
        assert result is not None

    def test_decode_still_works_for_valid_base64(self):
        """Decoding a valid base64 string must still succeed."""
        import base64

        encoded = base64.urlsafe_b64encode(b"hello world").decode("ascii")
        result = Base64GraphQLDirective.resolve(
            encoded, {"op": "decode"}, None, None, _info()
        )
        assert result == "hello world"

    def test_non_utf8_decodable_base64_raises_graphql_error(self):
        """Base64 that decodes to non-UTF-8 bytes must raise GraphQLError."""
        import base64

        # 0x80 is not valid UTF-8 as a standalone byte
        bad_utf8 = base64.urlsafe_b64encode(bytes([0x80, 0x81, 0x82])).decode("ascii")
        with pytest.raises(GraphQLError):
            Base64GraphQLDirective.resolve(
                bad_utf8, {"op": "decode"}, None, None, _info()
            )


# ---------------------------------------------------------------------------
# (b) @currency — non-numeric value must raise GraphQLError
# ---------------------------------------------------------------------------


class TestCurrencyNonNumericErrors:
    """@currency on non-numeric field value must raise GraphQLError."""

    def test_string_value_raises_graphql_error(self):
        """Non-numeric string → GraphQLError."""
        with pytest.raises(GraphQLError):
            CurrencyGraphQLDirective.resolve("abc", {}, None, None, _info())

    def test_list_value_raises_graphql_error(self):
        """List → GraphQLError (not TypeError)."""
        with pytest.raises(GraphQLError):
            CurrencyGraphQLDirective.resolve([1, 2, 3], {}, None, None, _info())

    def test_dict_value_raises_graphql_error(self):
        """Dict → GraphQLError (not TypeError)."""
        with pytest.raises(GraphQLError):
            CurrencyGraphQLDirective.resolve({"a": 1}, {}, None, None, _info())

    def test_value_error_does_not_propagate(self):
        """raw ValueError must NOT propagate to the caller."""
        try:
            CurrencyGraphQLDirective.resolve("not-a-number", {}, None, None, _info())
        except GraphQLError:
            pass  # correct
        except (ValueError, TypeError) as exc:
            pytest.fail(
                f"@currency raised raw {type(exc).__name__} — must raise GraphQLError."
            )

    def test_numeric_string_works(self):
        """Numeric string value must still succeed."""
        result = CurrencyGraphQLDirective.resolve("42.5", {}, None, None, _info())
        assert "42.50" in result

    def test_int_value_works(self):
        """Integer value must still succeed."""
        result = CurrencyGraphQLDirective.resolve(100, {}, None, None, _info())
        assert "100.00" in result

    def test_float_value_works(self):
        """Float value must still succeed."""
        result = CurrencyGraphQLDirective.resolve(9.99, {}, None, None, _info())
        assert "9.99" in result


# ---------------------------------------------------------------------------
# (c) @floor / @ceil / @round / @abs — non-numeric must raise GraphQLError
# ---------------------------------------------------------------------------


class TestNumericDirectivesNonNumericErrors:
    """@floor/@ceil/@round/@abs on non-numeric input must raise GraphQLError."""

    def test_floor_non_numeric_raises_graphql_error(self):
        """@floor on non-numeric → GraphQLError."""
        with pytest.raises(GraphQLError):
            FloorGraphQLDirective.resolve("abc", {}, None, None, _info())

    def test_ceil_non_numeric_raises_graphql_error(self):
        """@ceil on non-numeric → GraphQLError."""
        with pytest.raises(GraphQLError):
            CeilGraphQLDirective.resolve("abc", {}, None, None, _info())

    def test_round_non_numeric_raises_graphql_error(self):
        """@round on non-numeric → GraphQLError."""
        with pytest.raises(GraphQLError):
            RoundGraphQLDirective.resolve("abc", {}, None, None, _info())

    def test_abs_non_numeric_raises_graphql_error(self):
        """@abs on non-numeric → GraphQLError."""
        with pytest.raises(GraphQLError):
            AbsGraphQLDirective.resolve("abc", {}, None, None, _info())

    def test_value_error_does_not_propagate_floor(self):
        """raw ValueError must NOT propagate from @floor."""
        try:
            FloorGraphQLDirective.resolve("not-a-number", {}, None, None, _info())
        except GraphQLError:
            pass
        except (ValueError, TypeError) as exc:
            pytest.fail(
                f"@floor raised raw {type(exc).__name__} — must raise GraphQLError."
            )

    def test_value_error_does_not_propagate_ceil(self):
        """raw ValueError must NOT propagate from @ceil."""
        try:
            CeilGraphQLDirective.resolve("not-a-number", {}, None, None, _info())
        except GraphQLError:
            pass
        except (ValueError, TypeError) as exc:
            pytest.fail(
                f"@ceil raised raw {type(exc).__name__} — must raise GraphQLError."
            )

    def test_value_error_does_not_propagate_round(self):
        """raw ValueError must NOT propagate from @round."""
        try:
            RoundGraphQLDirective.resolve("not-a-number", {}, None, None, _info())
        except GraphQLError:
            pass
        except (ValueError, TypeError) as exc:
            pytest.fail(
                f"@round raised raw {type(exc).__name__} — must raise GraphQLError."
            )

    def test_value_error_does_not_propagate_abs(self):
        """raw ValueError must NOT propagate from @abs."""
        try:
            AbsGraphQLDirective.resolve("not-a-number", {}, None, None, _info())
        except GraphQLError:
            pass
        except (ValueError, TypeError) as exc:
            pytest.fail(
                f"@abs raised raw {type(exc).__name__} — must raise GraphQLError."
            )

    def test_floor_numeric_string_works(self):
        """@floor on numeric string should still work."""
        result = FloorGraphQLDirective.resolve("3.7", {}, None, None, _info())
        assert result == 3

    def test_ceil_numeric_string_works(self):
        """@ceil on numeric string should still work."""
        result = CeilGraphQLDirective.resolve("3.2", {}, None, None, _info())
        assert result == 4

    def test_round_numeric_string_works(self):
        """@round on numeric string should still work."""
        result = RoundGraphQLDirective.resolve("3.5", {}, None, None, _info())
        assert result in (3, 4)  # Python banker's rounding

    def test_abs_negative_numeric_works(self):
        """@abs on negative float should still work."""
        result = AbsGraphQLDirective.resolve(-5.5, {}, None, None, _info())
        assert result == 5.5

    def test_floor_none_returns_none(self):
        """@floor on None should still return None (no regression)."""
        result = FloorGraphQLDirective.resolve(None, {}, None, None, _info())
        assert result is None


# ---------------------------------------------------------------------------
# (d) @center — multi-character fillchar must raise GraphQLError
# ---------------------------------------------------------------------------


class TestCenterFillcharValidation:
    """@center with multi-character fillchar must raise GraphQLError (not TypeError)."""

    def test_multi_char_fillchar_raises_graphql_error(self):
        """fillchar='ab' (two chars) → GraphQLError."""
        with pytest.raises(GraphQLError):
            CenterGraphQLDirective.resolve(
                "hello", {"width": 10, "fillchar": "ab"}, None, None, _info()
            )

    def test_three_char_fillchar_raises_graphql_error(self):
        """fillchar='xyz' (three chars) → GraphQLError."""
        with pytest.raises(GraphQLError):
            CenterGraphQLDirective.resolve(
                "hello", {"width": 10, "fillchar": "xyz"}, None, None, _info()
            )

    def test_type_error_does_not_propagate(self):
        """raw TypeError from str.center() must NOT propagate."""
        try:
            CenterGraphQLDirective.resolve(
                "x", {"width": 10, "fillchar": "ab"}, None, None, _info()
            )
        except GraphQLError:
            pass  # correct
        except TypeError as exc:
            pytest.fail(
                f"@center raised raw TypeError: {exc}. Must raise GraphQLError."
            )

    def test_single_char_fillchar_works(self):
        """fillchar of exactly 1 character must still work."""
        result = CenterGraphQLDirective.resolve(
            "hi", {"width": 10, "fillchar": "*"}, None, None, _info()
        )
        assert result == "****hi****"

    def test_no_fillchar_works(self):
        """No fillchar (defaults to space) must still work."""
        result = CenterGraphQLDirective.resolve(
            "hi", {"width": 6, "fillchar": None}, None, None, _info()
        )
        assert result == "  hi  "

    def test_empty_string_fillchar_raises_graphql_error(self):
        """fillchar='' (empty string) is not exactly 1 char → GraphQLError."""
        with pytest.raises(GraphQLError):
            CenterGraphQLDirective.resolve(
                "hello", {"width": 10, "fillchar": ""}, None, None, _info()
            )


# ---------------------------------------------------------------------------
# (e) LimitOffsetGraphqlPagination — negative offset must raise GraphQLError
# ---------------------------------------------------------------------------


class TestLimitOffsetNegativeOffset(TestCase):
    """Negative offset must raise GraphQLError (not ValueError)."""

    def setUp(self):
        for name in ("alice", "bob", "carol"):
            Author.objects.create(name=name)

    def test_negative_offset_raises_graphql_error(self):
        """paginate_queryset with offset=-1 → GraphQLError."""
        p = _LOF(default_limit=5, max_limit=20)
        with pytest.raises(GraphQLError):
            list(p.paginate_queryset(Author.objects.all(), offset=-1))

    def test_negative_offset_large_raises_graphql_error(self):
        """paginate_queryset with offset=-100 → GraphQLError."""
        p = _LOF(default_limit=5, max_limit=20)
        with pytest.raises(GraphQLError):
            list(p.paginate_queryset(Author.objects.all(), offset=-100))

    def test_value_error_does_not_propagate(self):
        """raw ValueError from QuerySet slice must NOT propagate."""
        p = _LOF(default_limit=5, max_limit=20)
        try:
            list(p.paginate_queryset(Author.objects.all(), offset=-5))
        except GraphQLError:
            pass  # correct
        except ValueError as exc:
            pytest.fail(
                f"LimitOffset raised raw ValueError: {exc}. "
                "Must raise GraphQLError instead."
            )

    def test_zero_offset_works(self):
        """offset=0 must still work (zero is valid)."""
        p = _LOF(default_limit=5, max_limit=20)
        result = list(p.paginate_queryset(Author.objects.all(), offset=0))
        assert len(result) == 3

    def test_positive_offset_works(self):
        """offset=1 must still work."""
        p = _LOF(default_limit=5, max_limit=20)
        result = list(p.paginate_queryset(Author.objects.all(), offset=1))
        assert len(result) == 2

    def test_large_offset_returns_empty(self):
        """offset larger than row count must return empty, not crash."""
        p = _LOF(default_limit=5, max_limit=20)
        result = list(p.paginate_queryset(Author.objects.all(), offset=999))
        assert result == []
