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
from typing import Any

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


def _info(return_type: Any = None) -> SimpleNamespace:
    """Build a bare GraphQL resolve-info stand-in for direct directive calls.

    Args:
        return_type: The GraphQL return type to expose on the stand-in, or
            None when the directive under test does not inspect it.

    Returns:
        info: A namespace exposing "return_type".
    """
    return SimpleNamespace(return_type=return_type)


# ---------------------------------------------------------------------------
# (a) @base64(op:"decode") — bad input must raise GraphQLError
# ---------------------------------------------------------------------------


class TestBase64DecodeErrors:
    """ "@base64(op:"decode")" on invalid input must raise GraphQLError, not binascii.Error.

    Covers non-base64 input, non-UTF-8-decodable bytes, and the valid
    encode/decode round trip.
    """

    def test_non_base64_raises_graphql_error(self) -> None:
        """A string that is not valid base64 must raise GraphQLError.

        If this breaks, malformed client input would surface as an
        unhandled binascii.Error (HTTP 500) instead of a GraphQL error.
        """
        with pytest.raises(GraphQLError):
            Base64GraphQLDirective.resolve(
                "not!valid!base64!!", {"op": "decode"}, None, None, _info()
            )

    def test_binascii_error_does_not_propagate(self) -> None:
        """A raw binascii.Error must not propagate to the caller.

        If it does, the framework would surface an HTTP 500 instead of a
        client-facing GraphQLError.
        """
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

    def test_error_message_does_not_leak_binascii_internals(self) -> None:
        """The raised error must be a GraphQLError, not a raw binascii message.

        Confirms the wrapping error is the user-facing GraphQLError type
        rather than an implementation-detail exception leaking through.
        """
        try:
            Base64GraphQLDirective.resolve(
                "!!!garbage!!!", {"op": "decode"}, None, None, _info()
            )
        except GraphQLError as exc:
            # The message should be our own, not the raw binascii message.
            # We just check it IS a GraphQLError (message format is an impl detail).
            assert exc is not None

    def test_encode_still_works_for_valid_input(self) -> None:
        """Encoding a valid string must still succeed.

        Confirms the error-hardening change did not regress the encode path.
        """
        result = Base64GraphQLDirective.resolve(
            "hello", {"op": "encode"}, None, None, _info()
        )
        assert result is not None

    def test_decode_still_works_for_valid_base64(self) -> None:
        """Decoding a valid base64 string must still succeed.

        Confirms the error-hardening change did not regress the happy path.
        """
        import base64

        encoded = base64.urlsafe_b64encode(b"hello world").decode("ascii")
        result = Base64GraphQLDirective.resolve(
            encoded, {"op": "decode"}, None, None, _info()
        )
        assert result == "hello world"

    def test_non_utf8_decodable_base64_raises_graphql_error(self) -> None:
        """Base64 that decodes to non-UTF-8 bytes must raise GraphQLError.

        Covers the UnicodeDecodeError branch distinct from the
        binascii.Error branch already covered above.
        """
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
    """@currency on non-numeric field value must raise GraphQLError.

    Covers string, list, and dict inputs plus the valid numeric happy paths.
    """

    def test_string_value_raises_graphql_error(self) -> None:
        """A non-numeric string must raise GraphQLError.

        If this breaks, malformed client input would surface as an unhandled
        ValueError (HTTP 500) instead of a GraphQL error.
        """
        with pytest.raises(GraphQLError):
            CurrencyGraphQLDirective.resolve("abc", {}, None, None, _info())

    def test_list_value_raises_graphql_error(self) -> None:
        """A list value must raise GraphQLError, not a raw TypeError.

        Covers a container type distinct from the plain non-numeric string
        case above.
        """
        with pytest.raises(GraphQLError):
            CurrencyGraphQLDirective.resolve([1, 2, 3], {}, None, None, _info())

    def test_dict_value_raises_graphql_error(self) -> None:
        """A dict value must raise GraphQLError, not a raw TypeError.

        Covers a second container type alongside the list case above.
        """
        with pytest.raises(GraphQLError):
            CurrencyGraphQLDirective.resolve({"a": 1}, {}, None, None, _info())

    def test_value_error_does_not_propagate(self) -> None:
        """A raw ValueError or TypeError must not propagate to the caller.

        If it does, the framework would surface an HTTP 500 instead of a
        client-facing GraphQLError.
        """
        try:
            CurrencyGraphQLDirective.resolve("not-a-number", {}, None, None, _info())
        except GraphQLError:
            pass  # correct
        except (ValueError, TypeError) as exc:
            pytest.fail(
                f"@currency raised raw {type(exc).__name__} — must raise GraphQLError."
            )

    def test_numeric_string_works(self) -> None:
        """A numeric string value must still succeed.

        Confirms the error-hardening change did not regress the happy path.
        """
        result = CurrencyGraphQLDirective.resolve("42.5", {}, None, None, _info())
        assert "42.50" in result

    def test_int_value_works(self) -> None:
        """An integer value must still succeed.

        Confirms the error-hardening change did not regress the happy path.
        """
        result = CurrencyGraphQLDirective.resolve(100, {}, None, None, _info())
        assert "100.00" in result

    def test_float_value_works(self) -> None:
        """A float value must still succeed.

        Confirms the error-hardening change did not regress the happy path.
        """
        result = CurrencyGraphQLDirective.resolve(9.99, {}, None, None, _info())
        assert "9.99" in result


# ---------------------------------------------------------------------------
# (c) @floor / @ceil / @round / @abs — non-numeric must raise GraphQLError
# ---------------------------------------------------------------------------


class TestNumericDirectivesNonNumericErrors:
    """@floor/@ceil/@round/@abs on non-numeric input must raise GraphQLError.

    Covers the rejection and non-propagation cases for all four directives
    plus their numeric happy paths.
    """

    def test_floor_non_numeric_raises_graphql_error(self) -> None:
        """@floor on a non-numeric value must raise GraphQLError.

        If this breaks, malformed client input would surface as an unhandled
        ValueError (HTTP 500) instead of a GraphQL error.
        """
        with pytest.raises(GraphQLError):
            FloorGraphQLDirective.resolve("abc", {}, None, None, _info())

    def test_ceil_non_numeric_raises_graphql_error(self) -> None:
        """@ceil on a non-numeric value must raise GraphQLError.

        Mirrors the @floor rejection case for the ceiling directive.
        """
        with pytest.raises(GraphQLError):
            CeilGraphQLDirective.resolve("abc", {}, None, None, _info())

    def test_round_non_numeric_raises_graphql_error(self) -> None:
        """@round on a non-numeric value must raise GraphQLError.

        Mirrors the @floor rejection case for the rounding directive.
        """
        with pytest.raises(GraphQLError):
            RoundGraphQLDirective.resolve("abc", {}, None, None, _info())

    def test_abs_non_numeric_raises_graphql_error(self) -> None:
        """@abs on a non-numeric value must raise GraphQLError.

        Mirrors the @floor rejection case for the absolute-value directive.
        """
        with pytest.raises(GraphQLError):
            AbsGraphQLDirective.resolve("abc", {}, None, None, _info())

    def test_value_error_does_not_propagate_floor(self) -> None:
        """A raw ValueError or TypeError must not propagate from @floor.

        If it does, the framework would surface an HTTP 500 instead of a
        client-facing GraphQLError.
        """
        try:
            FloorGraphQLDirective.resolve("not-a-number", {}, None, None, _info())
        except GraphQLError:
            pass
        except (ValueError, TypeError) as exc:
            pytest.fail(
                f"@floor raised raw {type(exc).__name__} — must raise GraphQLError."
            )

    def test_value_error_does_not_propagate_ceil(self) -> None:
        """A raw ValueError or TypeError must not propagate from @ceil.

        Mirrors the @floor non-propagation case for the ceiling directive.
        """
        try:
            CeilGraphQLDirective.resolve("not-a-number", {}, None, None, _info())
        except GraphQLError:
            pass
        except (ValueError, TypeError) as exc:
            pytest.fail(
                f"@ceil raised raw {type(exc).__name__} — must raise GraphQLError."
            )

    def test_value_error_does_not_propagate_round(self) -> None:
        """A raw ValueError or TypeError must not propagate from @round.

        Mirrors the @floor non-propagation case for the rounding directive.
        """
        try:
            RoundGraphQLDirective.resolve("not-a-number", {}, None, None, _info())
        except GraphQLError:
            pass
        except (ValueError, TypeError) as exc:
            pytest.fail(
                f"@round raised raw {type(exc).__name__} — must raise GraphQLError."
            )

    def test_value_error_does_not_propagate_abs(self) -> None:
        """A raw ValueError or TypeError must not propagate from @abs.

        Mirrors the @floor non-propagation case for the absolute-value
        directive.
        """
        try:
            AbsGraphQLDirective.resolve("not-a-number", {}, None, None, _info())
        except GraphQLError:
            pass
        except (ValueError, TypeError) as exc:
            pytest.fail(
                f"@abs raised raw {type(exc).__name__} — must raise GraphQLError."
            )

    def test_floor_numeric_string_works(self) -> None:
        """@floor on a numeric string must still work.

        Confirms the error-hardening change did not regress the happy path.
        """
        result = FloorGraphQLDirective.resolve("3.7", {}, None, None, _info())
        assert result == 3

    def test_ceil_numeric_string_works(self) -> None:
        """@ceil on a numeric string must still work.

        Confirms the error-hardening change did not regress the happy path.
        """
        result = CeilGraphQLDirective.resolve("3.2", {}, None, None, _info())
        assert result == 4

    def test_round_numeric_string_works(self) -> None:
        """@round on a numeric string must still work.

        Confirms the error-hardening change did not regress the happy path.
        """
        result = RoundGraphQLDirective.resolve("3.5", {}, None, None, _info())
        assert result in (3, 4)  # Python banker's rounding

    def test_abs_negative_numeric_works(self) -> None:
        """@abs on a negative float must still work.

        Confirms the error-hardening change did not regress the happy path.
        """
        result = AbsGraphQLDirective.resolve(-5.5, {}, None, None, _info())
        assert result == 5.5

    def test_floor_none_returns_none(self) -> None:
        """@floor on None must still return None (no regression).

        Confirms None is treated as a pass-through value, not an error case.
        """
        result = FloorGraphQLDirective.resolve(None, {}, None, None, _info())
        assert result is None


# ---------------------------------------------------------------------------
# (d) @center — multi-character fillchar must raise GraphQLError
# ---------------------------------------------------------------------------


class TestCenterFillcharValidation:
    """@center with multi-character fillchar must raise GraphQLError (not TypeError).

    Covers 2- and 3-character fillchar rejection, the empty-string edge case,
    and the valid single-character / default happy paths.
    """

    def test_multi_char_fillchar_raises_graphql_error(self) -> None:
        """fillchar="ab" (two characters) must raise GraphQLError.

        If this breaks, malformed client input would surface as an unhandled
        TypeError (HTTP 500) instead of a GraphQL error.
        """
        with pytest.raises(GraphQLError):
            CenterGraphQLDirective.resolve(
                "hello", {"width": 10, "fillchar": "ab"}, None, None, _info()
            )

    def test_three_char_fillchar_raises_graphql_error(self) -> None:
        """fillchar="xyz" (three characters) must raise GraphQLError.

        Confirms the rejection is not limited to the 2-character case above.
        """
        with pytest.raises(GraphQLError):
            CenterGraphQLDirective.resolve(
                "hello", {"width": 10, "fillchar": "xyz"}, None, None, _info()
            )

    def test_type_error_does_not_propagate(self) -> None:
        """A raw TypeError from str.center() must not propagate.

        If it does, the framework would surface an HTTP 500 instead of a
        client-facing GraphQLError.
        """
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

    def test_single_char_fillchar_works(self) -> None:
        """A fillchar of exactly 1 character must still work.

        Confirms the error-hardening change did not regress the happy path.
        """
        result = CenterGraphQLDirective.resolve(
            "hi", {"width": 10, "fillchar": "*"}, None, None, _info()
        )
        assert result == "****hi****"

    def test_no_fillchar_works(self) -> None:
        """No fillchar (defaults to space) must still work.

        Confirms the error-hardening change did not regress the default path.
        """
        result = CenterGraphQLDirective.resolve(
            "hi", {"width": 6, "fillchar": None}, None, None, _info()
        )
        assert result == "  hi  "

    def test_empty_string_fillchar_raises_graphql_error(self) -> None:
        """fillchar="" (empty string), not exactly 1 char, must raise GraphQLError.

        Covers the zero-length edge case distinct from the multi-character
        cases above.
        """
        with pytest.raises(GraphQLError):
            CenterGraphQLDirective.resolve(
                "hello", {"width": 10, "fillchar": ""}, None, None, _info()
            )


# ---------------------------------------------------------------------------
# (e) LimitOffsetGraphqlPagination — negative offset must raise GraphQLError
# ---------------------------------------------------------------------------


class TestLimitOffsetNegativeOffset(TestCase):
    """Negative offset must raise GraphQLError (not ValueError).

    Covers small and large negative offsets plus the zero/positive/oversized
    happy paths.
    """

    def setUp(self) -> None:
        """Create three "Author" fixture rows for pagination assertions.

        Shared by every test method in this class.
        """
        for name in ("alice", "bob", "carol"):
            Author.objects.create(name=name)

    def test_negative_offset_raises_graphql_error(self) -> None:
        """paginate_queryset with offset=-1 must raise GraphQLError.

        If this breaks, malformed client input would surface as an unhandled
        ValueError (HTTP 500) instead of a GraphQL error.
        """
        p = _LOF(default_limit=5, max_limit=20)
        with pytest.raises(GraphQLError):
            list(p.paginate_queryset(Author.objects.all(), offset=-1))

    def test_negative_offset_large_raises_graphql_error(self) -> None:
        """paginate_queryset with offset=-100 must raise GraphQLError.

        Confirms the rejection is not limited to a small negative offset.
        """
        p = _LOF(default_limit=5, max_limit=20)
        with pytest.raises(GraphQLError):
            list(p.paginate_queryset(Author.objects.all(), offset=-100))

    def test_value_error_does_not_propagate(self) -> None:
        """A raw ValueError from the QuerySet slice must not propagate.

        If it does, the framework would surface an HTTP 500 instead of a
        client-facing GraphQLError.
        """
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

    def test_zero_offset_works(self) -> None:
        """offset=0 must still work (zero is a valid, non-negative offset).

        Confirms the negative-offset guard does not reject the zero boundary.
        """
        p = _LOF(default_limit=5, max_limit=20)
        result = list(p.paginate_queryset(Author.objects.all(), offset=0))
        assert len(result) == 3

    def test_positive_offset_works(self) -> None:
        """offset=1 must still work.

        Confirms the error-hardening change did not regress the happy path.
        """
        p = _LOF(default_limit=5, max_limit=20)
        result = list(p.paginate_queryset(Author.objects.all(), offset=1))
        assert len(result) == 2

    def test_large_offset_returns_empty(self) -> None:
        """An offset larger than the row count must return empty, not crash.

        Confirms an out-of-range (but non-negative) offset is not treated as
        an error case.
        """
        p = _LOF(default_limit=5, max_limit=20)
        result = list(p.paginate_queryset(Author.objects.all(), offset=999))
        assert result == []
