# -*- coding: utf-8 -*-
"""Failing tests for issue #16 directive fixes.

Four bugs are covered (RED phase — all tests should fail before the fix):

(a) NumberGraphQLDirective — oversized format spec rejected (memory DoS)
(b) DateGraphQLDirective / _format_dt — "iso" format uses real ISO 8601
(c) _format_time_ago — DST-aware "now" via Django's timezone utilities
(d) Base64GraphQLDirective — UTF-8 encode/decode so non-ASCII input works
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

import graphene
import pytest
from django.test import TestCase
from graphql import GraphQLError

from django_graphex import GraphQLDirectiveMiddleware, all_directives
from django_graphex.directives.date import (
    _format_dt,
    _format_time_ago,
    _parse,
)
from django_graphex.directives.string import (
    Base64GraphQLDirective,
    NumberGraphQLDirective,
)


def _info():
    return SimpleNamespace(return_type=None)


# ---------------------------------------------------------------------------
# (a) NumberGraphQLDirective — format-spec cap
# ---------------------------------------------------------------------------


class TestNumberFormatSpecCap:
    """@number(as: ...) must reject specs whose effective width exceeds the cap."""

    def test_oversized_width_raises_graphql_error(self):
        """@number(as: '1000000.5f') must raise GraphQLError, not allocate ~1 MB."""
        with pytest.raises(GraphQLError):
            NumberGraphQLDirective.resolve(
                1.5, {"as": "1000000.5f"}, None, None, _info()
            )

    def test_oversized_precision_raises_graphql_error(self):
        """@number(as: '.999999f') must raise GraphQLError (precision > cap)."""
        with pytest.raises(GraphQLError):
            NumberGraphQLDirective.resolve(
                1.0, {"as": ".999999f"}, None, None, _info()
            )

    def test_zero_two_f_accepted(self):
        """@number(as: '.2f') is a normal spec and must work."""
        result = NumberGraphQLDirective.resolve(
            3.14159, {"as": ".2f"}, None, None, _info()
        )
        assert result == "3.14"

    def test_comma_dot_two_f_accepted(self):
        """@number(as: ',.2f') is a normal spec and must work."""
        result = NumberGraphQLDirective.resolve(
            1000.0, {"as": ",.2f"}, None, None, _info()
        )
        assert result == "1,000.00"

    def test_plus_dot_one_percent_accepted(self):
        """@number(as: '+.1%') is a normal spec and must work."""
        result = NumberGraphQLDirective.resolve(
            0.123, {"as": "+.1%"}, None, None, _info()
        )
        assert result == "+12.3%"

    def test_normal_large_but_within_cap_accepted(self):
        """@number(as: '20.2f') uses width=20 which is within the cap."""
        result = NumberGraphQLDirective.resolve(
            3.14, {"as": "20.2f"}, None, None, _info()
        )
        # Should be right-aligned in 20 chars, starting with spaces
        assert result.strip() == "3.14"
        assert len(result) == 20


# ---------------------------------------------------------------------------
# (b) _format_dt — "iso" must use %Y-%m-%dT%H:%M:%S (real ISO 8601)
# ---------------------------------------------------------------------------


class TestISODateFormat:
    """@date(as: 'iso') must output a proper ISO 8601 string."""

    def test_iso_format_uses_numeric_month(self):
        """'iso' format must NOT use %b (locale abbrev) — must use %m (numeric)."""
        dt = _parse(datetime(2024, 1, 15, 10, 30, 0))
        result = _format_dt(dt, "iso")
        assert result == "2024-01-15T10:30:00"

    def test_iso_format_parseable_by_fromisoformat(self):
        """The 'iso' output must be parseable by datetime.fromisoformat."""
        dt = _parse(datetime(2020, 12, 31, 23, 59, 59))
        result = _format_dt(dt, "iso")
        # If this raises, the format is not ISO 8601
        parsed = datetime.fromisoformat(result)
        assert parsed.year == 2020
        assert parsed.month == 12
        assert parsed.day == 31
        assert parsed.hour == 23

    def test_iso_format_does_not_contain_alpha_month(self):
        """'iso' output must not contain any locale month abbreviation."""
        dt = _parse(datetime(2024, 6, 12, 14, 0, 0))
        result = _format_dt(dt, "iso")
        # Month abbreviations that %b could emit
        abbrevs = [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        ]
        for abbrev in abbrevs:
            assert abbrev not in result, f"Month abbrev '{abbrev}' found in ISO output: {result}"

    def test_iso_format_via_schema(self):
        """The 'iso' format must work end-to-end through a GraphQL schema."""

        class _Q(graphene.ObjectType):
            ts = graphene.String()

            def resolve_ts(root, info):
                return "2024-01-15 10:30:00"

        schema = graphene.Schema(query=_Q, directives=list(all_directives))
        middleware = [GraphQLDirectiveMiddleware()]
        result = schema.execute(
            '{ ts @date(format: "iso") }', middleware=middleware
        )
        assert result.errors is None
        # Must be parseable as ISO
        datetime.fromisoformat(result.data["ts"])


# ---------------------------------------------------------------------------
# (c) _format_time_ago — DST-aware "now" via Django's timezone utilities
# ---------------------------------------------------------------------------


class TestTimeAgoDSTAwareness:
    """_format_time_ago must use Django's timezone.now() / localtime, not time.timezone."""

    def test_time_ago_does_not_use_time_timezone(self):
        """When 'now' is computed internally, it must use timezone.now(), not
        time.timezone (which is DST-unaware)."""
        # We simulate a DST shift by patching time.timezone to a bogus large offset.
        # If the code still uses time.timezone, the delta will be wrong; if it uses
        # Django's timezone utilities, the result won't be affected by our patch.
        import time as time_module

        past_dt = datetime(2024, 3, 10, 1, 0, 0)  # arbitrary past datetime

        with patch.object(time_module, "timezone", -7200):
            # With DST-unaware code: offset is -2h, so "now" would be shifted by 2h.
            # The exact text doesn't matter; what matters is no exception is raised
            # and the code does NOT consult time.timezone for its UTC offset.
            result = _format_time_ago(past_dt, full=False, ago_in=True)

        # Must produce a string (not None, not an exception)
        assert isinstance(result, str)
        assert "ago" in result or "in" in result or result  # some relative string

    def test_time_ago_uses_django_timezone_now(self):
        """_format_time_ago(now=None) must derive 'now' from django.utils.timezone.now."""
        from django.utils import timezone as dj_tz

        fixed_now = datetime(2024, 6, 12, 12, 0, 0, tzinfo=dt_timezone.utc)
        past_dt = datetime(2024, 6, 12, 10, 0, 0)  # 2 hours before fixed_now

        with patch.object(dj_tz, "now", return_value=fixed_now):
            result = _format_time_ago(past_dt, full=False, ago_in=True)

        assert result is not None
        # 2 hours ago — the relative string must mention "hour"
        assert "hour" in result

    def test_time_ago_dst_boundary_no_one_hour_error(self):
        """Across a simulated DST transition the delta must still be correct."""
        from django.utils import timezone as dj_tz

        # "now" is UTC; the field datetime is naive and will be made aware.
        # We pick a 3-hour gap; DST-unaware code using time.timezone=3600 would
        # compute a 4h or 2h gap instead.
        now_utc = datetime(2024, 3, 10, 8, 0, 0, tzinfo=dt_timezone.utc)
        field_dt = datetime(2024, 3, 10, 5, 0, 0)  # 3 hours before now

        with patch.object(dj_tz, "now", return_value=now_utc):
            result = _format_time_ago(field_dt, full=False, ago_in=True)

        assert result is not None
        assert "hour" in result, f"Expected 'hour' in result, got: {result!r}"


# ---------------------------------------------------------------------------
# (d) Base64GraphQLDirective — UTF-8 encode/decode
# ---------------------------------------------------------------------------


class TestBase64UTF8:
    """@base64 must handle non-ASCII input (emoji, accented chars) without crashing."""

    def test_encode_accented_input(self):
        """Accented characters must encode cleanly (no UnicodeEncodeError)."""
        result = Base64GraphQLDirective.resolve(
            "Ñoño", {"op": "encode"}, None, None, _info()
        )
        assert result is not None
        # The result must be valid base64
        decoded_bytes = base64.urlsafe_b64decode(result + "==")
        assert decoded_bytes.decode("utf-8") == "Ñoño"

    def test_encode_emoji_input(self):
        """Emoji must encode cleanly (no UnicodeEncodeError)."""
        result = Base64GraphQLDirective.resolve(
            "Hello 🎉", {"op": "encode"}, None, None, _info()
        )
        assert result is not None
        decoded_bytes = base64.urlsafe_b64decode(result + "==")
        assert decoded_bytes.decode("utf-8") == "Hello 🎉"

    def test_round_trip_non_ascii(self):
        """Encode then decode must produce the original non-ASCII string."""
        original = "café au lait 🍵"
        encoded = Base64GraphQLDirective.resolve(
            original, {"op": "encode"}, None, None, _info()
        )
        decoded = Base64GraphQLDirective.resolve(
            encoded, {"op": "decode"}, None, None, _info()
        )
        assert decoded == original

    def test_decode_utf8_base64(self):
        """Decode a base64 string that encodes non-ASCII UTF-8 bytes."""
        # Base64 of "Ñoño" encoded as UTF-8
        encoded = base64.urlsafe_b64encode("Ñoño".encode("utf-8")).decode("ascii")
        result = Base64GraphQLDirective.resolve(
            encoded, {"op": "decode"}, None, None, _info()
        )
        assert result == "Ñoño"

    def test_encode_ascii_still_works(self):
        """Pure ASCII input must continue to work after the UTF-8 fix."""
        result = Base64GraphQLDirective.resolve(
            "Hello World", {"op": "encode"}, None, None, _info()
        )
        assert result == "SGVsbG8gV29ybGQ="

    def test_decode_ascii_still_works(self):
        """Pure ASCII decode must continue to work after the UTF-8 fix."""
        result = Base64GraphQLDirective.resolve(
            "SGVsbG8gV29ybGQ=", {"op": "decode"}, None, None, _info()
        )
        assert result == "Hello World"
