"""Native GraphQL boundaries for absolute @date timezone conversion."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.test import override_settings
from django.utils import timezone as django_timezone
from graphql import GraphQLString, graphql_sync

from django_graphex.core import ObjectType, field
from django_graphex.core.scalars import GdxDate, GdxDateTime
from django_graphex.directives import all_directives
from django_graphex.directives import date as date_directive
from django_graphex.middleware import GraphQLDirectiveMiddleware
from django_graphex.schema import DjangoGraphQLSchema


class _Query(ObjectType):
    """Expose typed and textual values through the public directive."""

    aware = field(GdxDateTime)
    offset_text = field(GraphQLString)
    z_text = field(GraphQLString)
    naive_text = field(GraphQLString)
    naive_datetime = field(GdxDateTime)
    date_value = field(GdxDate)
    nullable_text = field(GraphQLString)
    invalid_text = field(GraphQLString)
    before_dst = field(GraphQLString)
    after_dst = field(GraphQLString)
    offset_with_abbreviation = field(GraphQLString)
    spaced_offset_with_abbreviation = field(GraphQLString)
    negative_offset_with_abbreviation = field(GraphQLString)
    date_only_text = field(GraphQLString)
    named_timezone_only_text = field(GraphQLString)
    trailing_year_offset_text = field(GraphQLString)
    trailing_year_zero_offset_text = field(GraphQLString)
    trailing_year_z_text = field(GraphQLString)
    trailing_year_named_utc_text = field(GraphQLString)
    trailing_year_named_gmt_text = field(GraphQLString)
    trailing_year_naive_text = field(GraphQLString)

    def resolve_aware(root: Any, info: Any) -> datetime:
        """Return an aware instant near a New York date boundary."""
        return datetime(2026, 1, 1, 1, 30, tzinfo=timezone.utc)

    def resolve_offset_text(root: Any, info: Any) -> str:
        """Return the same instant as text with an explicit numeric offset."""
        return "2026-01-01T03:30:00+02:00"

    def resolve_z_text(root: Any, info: Any) -> str:
        """Return the same instant with an explicit UTC designator."""
        return "2026-01-01T01:30:00Z"

    def resolve_naive_text(root: Any, info: Any) -> str:
        """Return text without an explicit offset despite an aware parse default."""
        return "2026-01-01T01:30:00"

    def resolve_naive_datetime(root: Any, info: Any) -> datetime:
        """Return a naive typed datetime."""
        return datetime(2026, 1, 1, 1, 30)

    def resolve_date_value(root: Any, info: Any) -> date:
        """Return a typed calendar date."""
        return date(2026, 1, 1)

    def resolve_nullable_text(root: Any, info: Any) -> None:
        """Return null without asking the directive to synthesize a date."""
        return None

    def resolve_invalid_text(root: Any, info: Any) -> str:
        """Return text that resembles an offset but cannot be parsed."""
        return "not a date +02:00"

    def resolve_before_dst(root: Any, info: Any) -> str:
        """Return an instant immediately before New York's DST jump."""
        return "2026-03-08T06:30:00Z"

    def resolve_after_dst(root: Any, info: Any) -> str:
        """Return an instant immediately after New York's DST jump."""
        return "2026-03-08T07:30:00Z"

    def resolve_offset_with_abbreviation(root: Any, info: Any) -> str:
        """Return an accepted offset followed by a timezone abbreviation."""
        return "2026-01-10 02:30:00+0200 (EET)"

    def resolve_spaced_offset_with_abbreviation(root: Any, info: Any) -> str:
        """Return an accepted spaced offset and timezone abbreviation."""
        return "2026-01-10 02:30:00 +0200 (EET)"

    def resolve_negative_offset_with_abbreviation(root: Any, info: Any) -> str:
        """Return an accepted negative offset and timezone abbreviation."""
        return "2026-01-10 02:30:00-0300 (BRT)"

    def resolve_date_only_text(root: Any, info: Any) -> str:
        """Return date-only text that must not imply an explicit offset."""
        return "2026-01-10"

    def resolve_named_timezone_only_text(root: Any, info: Any) -> str:
        """Return text with a timezone name but no numeric offset."""
        return "2026-01-10 02:30:00 UTC"

    def resolve_trailing_year_offset_text(root: Any, info: Any) -> str:
        """Return accepted text whose numeric offset precedes its year."""
        return "Sat Jan 10 02:30:00 +0200 2026"

    def resolve_trailing_year_zero_offset_text(root: Any, info: Any) -> str:
        """Return accepted text with a zero offset before its year."""
        return "Sat Jan 10 02:30:00 +0000 2026"

    def resolve_trailing_year_z_text(root: Any, info: Any) -> str:
        """Return accepted text with Z before its year."""
        return "Sat Jan 10 02:30:00 Z 2026"

    def resolve_trailing_year_named_utc_text(root: Any, info: Any) -> str:
        """Return a named UTC timezone without an explicit offset."""
        return "Sat Jan 10 02:30:00 UTC 2026"

    def resolve_trailing_year_named_gmt_text(root: Any, info: Any) -> str:
        """Return a named GMT timezone without an explicit offset."""
        return "Sat Jan 10 02:30:00 GMT 2026"

    def resolve_trailing_year_naive_text(root: Any, info: Any) -> str:
        """Return accepted trailing-year text without timezone information."""
        return "Sat Jan 10 02:30:00 2026"


_SCHEMA = DjangoGraphQLSchema(query=_Query, directives=list(all_directives))
_CLOCK = datetime(2026, 4, 2, 8, 15, 21, tzinfo=timezone.utc)


def _execute(query: str) -> dict[str, str | None]:
    result = graphql_sync(
        _SCHEMA.graphql_schema,
        query,
        middleware=[GraphQLDirectiveMiddleware()],
    )
    assert result.errors is None
    assert result.data is not None
    return result.data


@pytest.mark.parametrize(
    ("format_name", "expected"),
    [
        ("default", "31 Dec 2025 20:30:00"),
        ("Default", "31 Dec 2025 20:30:00"),
        ("iso", "2025-12-31T20:30:00"),
        ("ISO", "2025-12-31T20:30:00"),
        ("js", "Wed Dec 31 2025 20:30:00"),
        ("JAVASCRIPT", "Wed Dec 31 2025 20:30:00"),
        ("YYYY-MM-DD HH:mm ZZ", "2025-12-31 20:30 -0500"),
    ],
)
def test_absolute_formats_localize_only_explicit_instants(
    monkeypatch: pytest.MonkeyPatch, format_name: str, expected: str
) -> None:
    """Aware Python and offset/Z text show the active zone's calendar date."""
    monkeypatch.setattr(date_directive.timezone, "now", lambda: _CLOCK)
    with django_timezone.override(ZoneInfo("America/New_York")):
        result = _execute(
            '{ aware @date(format: "' + format_name + '") '
            'offsetText @date(format: "' + format_name + '") '
            'zText @date(format: "' + format_name + '") }'
        )
    assert result == {"aware": expected, "offsetText": expected, "zText": expected}


def test_naive_text_and_typed_inputs_keep_existing_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inherited UTC tzinfo is not evidence of explicit text offset."""
    monkeypatch.setattr(date_directive.timezone, "now", lambda: _CLOCK)
    with django_timezone.override(ZoneInfo("America/New_York")):
        result = _execute(
            '{ naiveText @date(format: "iso") '
            'naiveDatetime @date(format: "iso") '
            'dateValue @date(format: "iso") '
            'nullableText @date(format: "iso") }'
        )
    assert result == {
        "naiveText": "2026-01-01T01:30:00",
        "naiveDatetime": "2026-01-01T01:30:00",
        "dateValue": "2026-01-01T00:00:00",
        "nullableText": None,
    }


@pytest.mark.parametrize("format_name", ["time ago", "time ago 2d"])
def test_relative_formats_keep_current_path(
    monkeypatch: pytest.MonkeyPatch, format_name: str
) -> None:
    """Relative rendering still consumes the parser result unchanged."""
    monkeypatch.setattr(date_directive.timezone, "now", lambda: _CLOCK)
    value = "2026-01-01T03:30:00+02:00"
    with django_timezone.override(ZoneInfo("America/New_York")):
        expected = date_directive._format_dt(date_directive._parse(value), format_name)
        result = _execute('{ offsetText @date(format: "' + format_name + '") }')
    assert result == {"offsetText": expected}


def test_active_zone_applies_to_aware_instants_with_use_tz_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active override converts aware inputs even when USE_TZ is false."""
    monkeypatch.setattr(date_directive.timezone, "now", lambda: datetime(2026, 4, 2, 8))
    with override_settings(USE_TZ=False, TIME_ZONE="UTC"):
        with django_timezone.override(ZoneInfo("Asia/Tokyo")):
            result = _execute(
                '{ aware @date(format: "iso") offsetText @date(format: "iso") '
                'naiveText @date(format: "iso") }'
            )
    assert result == {
        "aware": "2026-01-01T10:30:00",
        "offsetText": "2026-01-01T10:30:00",
        "naiveText": "2026-01-01T01:30:00",
    }


def test_dst_conversion_uses_each_instants_active_offset() -> None:
    """Absolute custom output follows the active zone through a DST jump."""
    with django_timezone.override(ZoneInfo("America/New_York")):
        result = _execute(
            '{ beforeDst @date(format: "YYYY-MM-DD HH:mm ZZ") '
            'afterDst @date(format: "YYYY-MM-DD HH:mm ZZ") }'
        )
    assert result == {
        "beforeDst": "2026-03-08 01:30 -0500",
        "afterDst": "2026-03-08 03:30 -0400",
    }


def test_explicit_offset_before_accepted_abbreviation_is_localized() -> None:
    """Trailing abbreviations do not hide an accepted numeric offset."""
    with django_timezone.override(ZoneInfo("America/New_York")):
        result = _execute(
            '{ offsetWithAbbreviation @date(format: "iso") '
            'spacedOffsetWithAbbreviation @date(format: "iso") '
            'negativeOffsetWithAbbreviation @date(format: "iso") '
            'dateOnlyText @date(format: "iso") '
            'namedTimezoneOnlyText @date(format: "iso") }'
        )
    assert result == {
        "offsetWithAbbreviation": "2026-01-09T19:30:00",
        "spacedOffsetWithAbbreviation": "2026-01-09T19:30:00",
        "negativeOffsetWithAbbreviation": "2026-01-10T00:30:00",
        "dateOnlyText": "2026-01-10T00:00:00",
        "namedTimezoneOnlyText": "2026-01-10T02:30:00",
    }


def test_explicit_offset_before_trailing_year_is_localized() -> None:
    """Parser-recognized offsets count even when the year follows them."""
    with django_timezone.override(ZoneInfo("America/New_York")):
        result = _execute(
            '{ trailingYearOffsetText @date(format: "iso") '
            'trailingYearZeroOffsetText @date(format: "iso") '
            'trailingYearZText @date(format: "iso") '
            'trailingYearNamedUtcText @date(format: "iso") '
            'trailingYearNamedGmtText @date(format: "iso") '
            'trailingYearNaiveText @date(format: "iso") '
            'dateOnlyText @date(format: "iso") }'
        )
    assert result == {
        "trailingYearOffsetText": "2026-01-09T19:30:00",
        "trailingYearZeroOffsetText": "2026-01-09T21:30:00",
        "trailingYearZText": "2026-01-09T21:30:00",
        "trailingYearNamedUtcText": "2026-01-10T02:30:00",
        "trailingYearNamedGmtText": "2026-01-10T02:30:00",
        "trailingYearNaiveText": "2026-01-10T02:30:00",
        "dateOnlyText": "2026-01-10T00:00:00",
    }


def test_public_helpers_and_other_input_kinds_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The parser, formatter and non-eligible kinds keep their old contracts."""
    monkeypatch.setattr(date_directive.timezone, "now", lambda: _CLOCK)
    with django_timezone.override(ZoneInfo("America/New_York")):
        parsed = date_directive._parse("2026-01-01T03:30:00+02:00")
        assert parsed == datetime(
            2026, 1, 1, 3, 30, tzinfo=timezone(timedelta(hours=2))
        )
        assert date_directive._format_dt(parsed, "iso") == "2026-01-01T03:30:00"
        assert date_directive._parse("2026-01-01T01:30:00") == datetime(
            2026, 1, 1, 1, 30, tzinfo=timezone.utc
        )
        assert date_directive._parse(date(2026, 1, 1)) == datetime(
            2026, 1, 1, tzinfo=django_timezone.get_current_timezone()
        )
        assert date_directive._parse(time(14, 30)) is not None
        assert date_directive._parse(bytes("2026-01-01", "ascii")) is not None
        assert date_directive._parse(0) is not None
        assert date_directive._parse(None) is None
        assert date_directive._parse("not a date") is None


def test_invalid_offset_text_keeps_string_fallback() -> None:
    """A failed original parse never enters offset-provenance detection."""
    assert _execute('{ invalidText @date(format: "iso") }') == {
        "invalidText": "not a date +02:00"
    }
