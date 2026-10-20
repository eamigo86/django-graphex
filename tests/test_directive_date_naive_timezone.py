"""Native GraphQL regressions for timezone-less text passed to @date."""

from __future__ import annotations

import warnings
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from dateutil.parser import UnknownTimezoneWarning
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
    """Expose a timezone-less text value through the public directive."""

    naive_text = field(GraphQLString)
    summer_text = field(GraphQLString)
    date_only = field(GraphQLString)
    time_only = field(GraphQLString)
    named_utc = field(GraphQLString)
    named_gmt = field(GraphQLString)
    unknown_name = field(GraphQLString)
    offset_text = field(GraphQLString)
    naive_datetime = field(GdxDateTime)
    date_value = field(GdxDate)
    nullable_text = field(GraphQLString)
    invalid_text = field(GraphQLString)

    def resolve_naive_text(root: Any, info: Any) -> str:
        """Return a wall clock without an explicit timezone."""
        return "2026-01-10 14:30"

    def resolve_summer_text(root: Any, info: Any) -> str:
        """Return a summer wall clock for active-zone offset checks."""
        return "2026-07-10 14:30"

    def resolve_date_only(root: Any, info: Any) -> str:
        """Return text with an omitted time."""
        return "2026-01-10"

    def resolve_time_only(root: Any, info: Any) -> str:
        """Return text with an omitted date and seconds."""
        return "14:30"

    def resolve_named_utc(root: Any, info: Any) -> str:
        """Return text naming UTC without a numeric offset."""
        return "2026-01-10 14:30 UTC"

    def resolve_named_gmt(root: Any, info: Any) -> str:
        """Return text naming GMT without a numeric offset."""
        return "2026-01-10 14:30 GMT"

    def resolve_unknown_name(root: Any, info: Any) -> str:
        """Return text with an unknown named timezone."""
        return "2026-01-10 14:30 XYZ"

    def resolve_offset_text(root: Any, info: Any) -> str:
        """Return text with an explicit numeric offset."""
        return "2026-01-10 14:30+0200"

    def resolve_naive_datetime(root: Any, info: Any) -> datetime:
        """Return a timezone-less Python datetime."""
        return datetime(2026, 1, 10, 14, 30)

    def resolve_date_value(root: Any, info: Any) -> date:
        """Return a typed date without a time."""
        return date(2026, 1, 10)

    def resolve_nullable_text(root: Any, info: Any) -> None:
        """Return a nullable text value."""
        return None

    def resolve_invalid_text(root: Any, info: Any) -> str:
        """Return text rejected by the existing date parser."""
        return "not a date +02:00"


_SCHEMA = DjangoGraphQLSchema(query=_Query, directives=list(all_directives))


@pytest.mark.parametrize(
    ("use_tz", "clock"),
    [
        (True, datetime(2026, 1, 10, 20, 30, tzinfo=timezone.utc)),
        (False, datetime(2026, 1, 10, 15, 30)),
    ],
)
def test_timezone_less_text_uses_active_zone_for_absolute_and_relative_formats(
    monkeypatch: pytest.MonkeyPatch, use_tz: bool, clock: datetime
) -> None:
    """Attach the active zone without converting the written wall clock."""
    monkeypatch.setattr(date_directive.timezone, "now", lambda: clock)
    query = """{
      custom: naiveText @date(format: "YYYY-MM-DD HH:mm ZZ")
      default: naiveText @date
      iso: naiveText @date(format: "iso")
      upperIso: naiveText @date(format: "ISO")
      js: naiveText @date(format: "javascript")
      shortJs: naiveText @date(format: "JS")
      ago: naiveText @date(format: "time ago")
      upperAgo: naiveText @date(format: "TIME AGO")
      ago2d: naiveText @date(format: "time ago 2d")
      upperAgo2d: naiveText @date(format: "TIME AGO 2D")
    }"""
    with override_settings(USE_TZ=use_tz, TIME_ZONE="UTC"):
        with django_timezone.override(ZoneInfo("America/New_York")):
            result = graphql_sync(
                _SCHEMA.graphql_schema,
                query,
                middleware=[GraphQLDirectiveMiddleware()],
            )
    assert result.errors is None
    assert result.data == {
        "custom": "2026-01-10 14:30 -0500",
        "default": "10 Jan 2026 14:30:00",
        "iso": "2026-01-10T14:30:00",
        "upperIso": "2026-01-10T14:30:00",
        "js": "Sat Jan 10 2026 14:30:00",
        "shortJs": "Sat Jan 10 2026 14:30:00",
        "ago": "1 hour ago",
        "upperAgo": "1 hour ago",
        "ago2d": "1 hour ago",
        "upperAgo2d": "1 hour ago",
    }


@pytest.mark.parametrize(
    ("active_zone", "expected_offset"),
    [("Europe/Madrid", "+0200"), ("UTC", "+0000")],
)
def test_timezone_less_summer_text_uses_each_active_zone(
    active_zone: str, expected_offset: str
) -> None:
    """The original summer hour stays fixed as the active zone changes."""
    with override_settings(USE_TZ=True, TIME_ZONE="America/New_York"):
        with django_timezone.override(ZoneInfo(active_zone)):
            result = graphql_sync(
                _SCHEMA.graphql_schema,
                '{ summerText @date(format: "YYYY-MM-DD HH:mm ZZ") }',
                middleware=[GraphQLDirectiveMiddleware()],
            )
    assert result.errors is None
    assert result.data == {"summerText": f"2026-07-10 14:30 {expected_offset}"}


def test_missing_components_keep_the_parser_default_across_midnight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active-zone date rollover must not change omitted DATE filling."""
    clock = datetime(2026, 1, 10, 23, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(date_directive.timezone, "now", lambda: clock)
    query = """{
      dateOnly @date(format: "YYYY-MM-DD HH:mm:ss ZZ")
      timeOnly @date(format: "YYYY-MM-DD HH:mm:ss ZZ")
      naiveText @date(format: "YYYY-MM-DD HH:mm:ss ZZ")
      naiveDatetime @date(format: "YYYY-MM-DD HH:mm ZZ")
      dateValue @date(format: "YYYY-MM-DD HH:mm ZZ")
      nullableText @date(format: "iso")
      invalidText @date(format: "iso")
    }"""
    with override_settings(USE_TZ=True, TIME_ZONE="UTC"):
        with django_timezone.override(ZoneInfo("Asia/Tokyo")):
            assert django_timezone.localtime(clock).date() == date(2026, 1, 11)
            result = graphql_sync(
                _SCHEMA.graphql_schema,
                query,
                middleware=[GraphQLDirectiveMiddleware()],
            )
    assert result.errors is None
    assert result.data == {
        "dateOnly": "2026-01-10 00:00:00 +0900",
        "timeOnly": "2026-01-10 14:30:00 +0900",
        "naiveText": "2026-01-10 14:30:00 +0900",
        "naiveDatetime": "2026-01-10 14:30 +0900",
        "dateValue": "2026-01-10 00:00 +0900",
        "nullableText": None,
        "invalidText": "not a date +02:00",
    }


def test_named_unknown_and_numeric_offset_text_keep_previous_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only genuinely timezone-less text enters the new attachment path."""
    monkeypatch.setattr(
        date_directive.timezone,
        "now",
        lambda: datetime(2026, 1, 10, 20, 30, tzinfo=timezone.utc),
    )
    query = """{
      namedUtc @date(format: "YYYY-MM-DD HH:mm ZZ")
      namedGmt @date(format: "YYYY-MM-DD HH:mm ZZ")
      namedAgo: namedUtc @date(format: "time ago")
      unknownName @date(format: "YYYY-MM-DD HH:mm ZZ")
      unknownAgo: unknownName @date(format: "time ago")
      offsetText @date(format: "YYYY-MM-DD HH:mm ZZ")
      offsetAgo: offsetText @date(format: "time ago")
    }"""
    with override_settings(USE_TZ=True, TIME_ZONE="UTC"):
        with django_timezone.override(ZoneInfo("America/New_York")):
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("always", UnknownTimezoneWarning)
                result = graphql_sync(
                    _SCHEMA.graphql_schema,
                    query,
                    middleware=[GraphQLDirectiveMiddleware()],
                )
    assert result.errors is None
    assert result.data == {
        "namedUtc": "2026-01-10 14:30 +0000",
        "namedGmt": "2026-01-10 14:30 +0000",
        "namedAgo": "6 hours ago",
        "unknownName": "2026-01-10 14:30 +0000",
        "unknownAgo": "6 hours ago",
        "offsetText": "2026-01-10 07:30 -0500",
        "offsetAgo": "8 hours ago",
    }
    assert sum(issubclass(w.category, UnknownTimezoneWarning) for w in captured) == 2


def test_original_explicit_offset_helper_retains_its_boolean_contract() -> None:
    """The existing private offset check remains callable and selective."""
    for value, expected in (
        ("2026-01-10 14:30+0200", True),
        ("2026-01-10 14:30Z", True),
        ("2026-01-10 14:30", False),
        ("2026-01-10 14:30 UTC", False),
    ):
        parsed = date_directive._parse(value)
        assert parsed is not None
        assert date_directive._text_has_explicit_offset(value, parsed) is expected
