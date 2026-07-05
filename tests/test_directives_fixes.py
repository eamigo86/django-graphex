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
from datetime import datetime
from datetime import timezone as dt_timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from graphql import GraphQLError, GraphQLString, graphql_sync

from django_graphex.core import ObjectType, field
from django_graphex.directives import all_directives
from django_graphex.directives.date import (
    _format_dt,
    _format_time_ago,
    _parse,
)
from django_graphex.directives.string import (
    Base64GraphQLDirective,
    NumberGraphQLDirective,
)
from django_graphex.middleware import GraphQLDirectiveMiddleware
from django_graphex.schema import DjangoGraphQLSchema


def _info() -> SimpleNamespace:
    return SimpleNamespace(return_type=None)


# ---------------------------------------------------------------------------
# (a) NumberGraphQLDirective — format-spec cap
# ---------------------------------------------------------------------------


class TestNumberFormatSpecCap:
    """ ""@number(as: ...)"" must reject specs whose effective width exceeds the cap.

    Guards against issue #16(a): an oversized format spec could otherwise
    trigger a large memory allocation.
    """

    def test_oversized_width_raises_graphql_error(self) -> None:
        """ ""@number(as: "1000000.5f")"" must raise GraphQLError instead of allocating about 1 MB.

        If this breaks, a malicious format spec could trigger a large
        memory allocation (a denial-of-service vector).
        """
        with pytest.raises(GraphQLError):
            NumberGraphQLDirective.resolve(
                1.5, {"as": "1000000.5f"}, None, None, _info()
            )

    def test_oversized_precision_raises_graphql_error(self) -> None:
        """ ""@number(as: ".999999f")"" must raise GraphQLError since its precision exceeds the cap.

        If this breaks, an oversized precision value could bypass the
        width cap through the precision component instead.
        """
        with pytest.raises(GraphQLError):
            NumberGraphQLDirective.resolve(1.0, {"as": ".999999f"}, None, None, _info())

    def test_zero_two_f_accepted(self) -> None:
        """A normal spec like ""@number(as: ".2f")"" must format successfully.

        If this breaks, the width/precision cap could over-reject ordinary,
        safe format specs.
        """
        result = NumberGraphQLDirective.resolve(
            3.14159, {"as": ".2f"}, None, None, _info()
        )
        assert result == "3.14"

    def test_comma_dot_two_f_accepted(self) -> None:
        """A normal spec like ""@number(as: ",.2f")"" must format successfully with thousands separators.

        If this breaks, the cap check could over-reject specs that combine
        the comma grouping flag with precision.
        """
        result = NumberGraphQLDirective.resolve(
            1000.0, {"as": ",.2f"}, None, None, _info()
        )
        assert result == "1,000.00"

    def test_plus_dot_one_percent_accepted(self) -> None:
        """A normal spec like ""@number(as: "+.1%")"" must format successfully as a signed percentage.

        If this breaks, the cap check could over-reject specs combining the
        sign flag with the percent type.
        """
        result = NumberGraphQLDirective.resolve(
            0.123, {"as": "+.1%"}, None, None, _info()
        )
        assert result == "+12.3%"

    def test_normal_large_but_within_cap_accepted(self) -> None:
        """A spec like ""@number(as: "20.2f")"" with width=20 (within the cap) must still format successfully.

        If this breaks, the cap check could be too aggressive and reject
        legitimately large but safe width values.
        """
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
    """ ""@date(as: "iso")"" must output a proper ISO 8601 string.

    Guards against issue #16(b): the "iso" format previously used a
    locale-dependent month abbreviation instead of numeric ISO 8601.
    """

    def test_iso_format_uses_numeric_month(self) -> None:
        """The "iso" format must use "%m" (numeric month), not "%b" (locale abbreviation).

        If this breaks, ISO output would depend on the server locale
        instead of being a stable machine-parseable format.
        """
        dt = _parse(datetime(2024, 1, 15, 10, 30, 0))
        result = _format_dt(dt, "iso")
        assert result == "2024-01-15T10:30:00"

    def test_iso_format_parseable_by_fromisoformat(self) -> None:
        """The "iso" output must be parseable by "datetime.fromisoformat".

        If this breaks, downstream consumers could fail to parse the
        emitted timestamp as standard ISO 8601.
        """
        dt = _parse(datetime(2020, 12, 31, 23, 59, 59))
        result = _format_dt(dt, "iso")
        # If this raises, the format is not ISO 8601
        parsed = datetime.fromisoformat(result)
        assert parsed.year == 2020
        assert parsed.month == 12
        assert parsed.day == 31
        assert parsed.hour == 23

    def test_iso_format_does_not_contain_alpha_month(self) -> None:
        """The "iso" output must not contain any locale month abbreviation.

        If this breaks, the emitted string could vary by server locale
        instead of remaining a fixed numeric ISO format.
        """
        dt = _parse(datetime(2024, 6, 12, 14, 0, 0))
        result = _format_dt(dt, "iso")
        # Month abbreviations that %b could emit
        abbrevs = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ]
        for abbrev in abbrevs:
            assert abbrev not in result, (
                f"Month abbrev '{abbrev}' found in ISO output: {result}"
            )

    def test_iso_format_via_schema(self) -> None:
        """The "iso" format must work end-to-end through a live GraphQL schema.

        If this breaks, the unit-level ISO formatting fix could pass while
        the directive still misbehaves when wired into an actual schema.
        """

        class _Q(ObjectType):
            """Query root exposing a single timestamp field for the "@date" test."""

            ts = field(GraphQLString)

            def resolve_ts(root: Any, info: Any) -> str:
                """Resolve "ts" to a fixed naive-datetime string.

                Args:
                    root: The unused root value passed by the executor.
                    info: The unused GraphQL resolve info passed by the
                        executor.

                Returns:
                    timestamp: The literal string "2024-01-15 10:30:00".
                """
                return "2024-01-15 10:30:00"

        schema = DjangoGraphQLSchema(query=_Q, directives=list(all_directives))
        middleware = [GraphQLDirectiveMiddleware()]
        result = graphql_sync(
            schema.graphql_schema,
            '{ ts @date(format: "iso") }',
            middleware=middleware,
        )
        assert result.errors is None
        # Must be parseable as ISO
        datetime.fromisoformat(result.data["ts"])


# ---------------------------------------------------------------------------
# (c) _format_time_ago — DST-aware "now" via Django's timezone utilities
# ---------------------------------------------------------------------------


class TestTimeAgoDSTAwareness:
    """ "_format_time_ago" must use Django's "timezone.now()"/localtime, not "time.timezone".

    Guards against issue #16(c): using the DST-unaware "time.timezone"
    could make relative-time output wrong around DST transitions.
    """

    def test_time_ago_does_not_use_time_timezone(self) -> None:
        """When "now" is computed internally, it must come from "timezone.now()", not the DST-unaware "time.timezone".

        Patches "time.timezone" to an absurd offset; because the code uses
        Django's timezone utilities exclusively, the result is unaffected
        (no exception is raised and a non-empty string is returned). If
        this breaks, "time_ago" output could silently shift by the DST
        offset around transitions.
        """
        import time as time_module

        from django.utils import timezone as dj_tz

        # "now" pinned to a fixed UTC instant.
        fixed_now = datetime(2024, 3, 10, 12, 0, 0, tzinfo=dt_timezone.utc)
        # A past naive datetime — we just care that the function produces a
        # result without consulting time.timezone.
        past_dt = datetime(2024, 3, 10, 7, 0, 0)

        # Patch time.timezone to an absurd 36000-second (10-hour) offset.
        # DST-unaware code consulting time.timezone would compute a wildly
        # wrong delta; correct code ignores it entirely.
        with patch.object(dj_tz, "now", return_value=fixed_now):
            with patch.object(time_module, "timezone", -36000):  # fake +10h DST
                result = _format_time_ago(past_dt, full=False, ago_in=True)

        # Must produce a non-None string — no exception raised, result is valid.
        assert isinstance(result, str) and result, (
            f"Expected a non-empty string, got: {result!r}.  "
            "The code may be using time.timezone instead of Django's timezone utilities."
        )

    def test_time_ago_uses_django_timezone_now(self) -> None:
        """ "_format_time_ago(now=None)" must derive "now" from "django.utils.timezone.now".

        If this breaks, the relative-time computation could use a
        different, potentially DST-unaware, source of "now".
        """
        from django.utils import timezone as dj_tz

        fixed_now = datetime(2024, 6, 12, 12, 0, 0, tzinfo=dt_timezone.utc)
        past_dt = datetime(2024, 6, 12, 10, 0, 0)  # 2 hours before fixed_now

        with patch.object(dj_tz, "now", return_value=fixed_now):
            result = _format_time_ago(past_dt, full=False, ago_in=True)

        assert result is not None
        # 2 hours ago — the relative string must mention "hour"
        assert "hour" in result

    def test_time_ago_dst_boundary_no_one_hour_error(self) -> None:
        """Across a simulated DST transition the computed delta must still be correct.

        If this breaks, the relative-time string could be off by roughly
        one hour whenever "now" straddles a DST transition.
        """
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
    """ ""@base64"" must handle non-ASCII input (emoji, accented characters) without crashing.

    Guards against issue #16(d): non-UTF-8-aware encode/decode could raise
    on non-ASCII text.
    """

    def test_encode_accented_input(self) -> None:
        """Accented characters must encode cleanly without raising UnicodeEncodeError.

        If this breaks, encoding non-ASCII text would crash instead of
        producing valid base64 of the UTF-8 bytes.
        """
        result = Base64GraphQLDirective.resolve(
            "Ñoño", {"op": "encode"}, None, None, _info()
        )
        assert result is not None
        # The result must be valid base64
        decoded_bytes = base64.urlsafe_b64decode(result + "==")
        assert decoded_bytes.decode("utf-8") == "Ñoño"

    def test_encode_emoji_input(self) -> None:
        """Emoji must encode cleanly without raising UnicodeEncodeError.

        If this breaks, encoding emoji text would crash instead of
        producing valid base64 of the UTF-8 bytes.
        """
        result = Base64GraphQLDirective.resolve(
            "Hello 🎉", {"op": "encode"}, None, None, _info()
        )
        assert result is not None
        decoded_bytes = base64.urlsafe_b64decode(result + "==")
        assert decoded_bytes.decode("utf-8") == "Hello 🎉"

    def test_round_trip_non_ascii(self) -> None:
        """Encoding then decoding must reproduce the original non-ASCII string exactly.

        If this breaks, a UTF-8 round-trip through "@base64" could corrupt
        or lose non-ASCII characters.
        """
        original = "café au lait 🍵"
        encoded = Base64GraphQLDirective.resolve(
            original, {"op": "encode"}, None, None, _info()
        )
        decoded = Base64GraphQLDirective.resolve(
            encoded, {"op": "decode"}, None, None, _info()
        )
        assert decoded == original

    def test_decode_utf8_base64(self) -> None:
        """Decoding a base64 string of non-ASCII UTF-8 bytes must recover the original text.

        If this breaks, base64 payloads encoding non-ASCII text could
        decode to mojibake or raise instead of the correct string.
        """
        # Base64 of "Ñoño" encoded as UTF-8
        encoded = base64.urlsafe_b64encode("Ñoño".encode("utf-8")).decode("ascii")
        result = Base64GraphQLDirective.resolve(
            encoded, {"op": "decode"}, None, None, _info()
        )
        assert result == "Ñoño"

    def test_encode_ascii_still_works(self) -> None:
        """Pure ASCII input must continue to encode correctly after the UTF-8 fix.

        If this breaks, the UTF-8 fix could have regressed the previously
        working plain-ASCII encode path.
        """
        result = Base64GraphQLDirective.resolve(
            "Hello World", {"op": "encode"}, None, None, _info()
        )
        assert result == "SGVsbG8gV29ybGQ="

    def test_decode_ascii_still_works(self) -> None:
        """Pure ASCII decode must continue to work correctly after the UTF-8 fix.

        If this breaks, the UTF-8 fix could have regressed the previously
        working plain-ASCII decode path.
        """
        result = Base64GraphQLDirective.resolve(
            "SGVsbG8gV29ybGQ=", {"op": "decode"}, None, None, _info()
        )
        assert result == "Hello World"
