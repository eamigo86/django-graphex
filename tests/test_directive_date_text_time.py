"""Regression tests for omitted time components in textual date values."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.test import override_settings
from django.utils import timezone as django_timezone
from graphql import GraphQLString, graphql_sync

from django_graphex.core import ObjectType, field
from django_graphex.directives import all_directives
from django_graphex.directives import date as date_directive
from django_graphex.middleware import GraphQLDirectiveMiddleware
from django_graphex.schema import DjangoGraphQLSchema


class _Query(ObjectType):
    """Expose text values through the registered public date directive."""

    iso_date = field(GraphQLString)
    named_date = field(GraphQLString)
    partial_datetime = field(GraphQLString)
    time_only = field(GraphQLString)
    full_datetime = field(GraphQLString)

    def resolve_iso_date(root: Any, info: Any) -> str:
        """Return an ISO date without a time.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            An ISO date string.
        """
        return "2026-01-10"

    def resolve_named_date(root: Any, info: Any) -> str:
        """Return a named-month date without a time.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            A named-month date string.
        """
        return "January 10, 2026"

    def resolve_partial_datetime(root: Any, info: Any) -> str:
        """Return an hour-and-minute timestamp.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            A timestamp missing seconds and microseconds.
        """
        return "2026-01-10 14:30"

    def resolve_time_only(root: Any, info: Any) -> str:
        """Return a time without a date or seconds.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            A time-only string.
        """
        return "14:30"

    def resolve_full_datetime(root: Any, info: Any) -> str:
        """Return a fully specified timestamp with an explicit offset.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            A timestamp with explicit seconds, microseconds, and offset.
        """
        return "2026-01-10T14:30:45.250000+02:00"


_SCHEMA = DjangoGraphQLSchema(query=_Query, directives=list(all_directives))
_CLOCKS = (
    datetime(2026, 4, 2, 8, 15, 21, 123456, tzinfo=timezone.utc),
    datetime(2026, 4, 2, 20, 45, 53, 654321, tzinfo=timezone.utc),
)


@pytest.mark.parametrize("clock", _CLOCKS)
def test_text_time_components_are_zero_in_native_graphql(
    monkeypatch: pytest.MonkeyPatch, clock: datetime
) -> None:
    """Native GraphQL output must not inherit clock time from partial text.

    Args:
        monkeypatch: Fixture replacing the date parser's reference clock.
        clock: The controlled current instant.
    """
    monkeypatch.setattr(date_directive.timezone, "now", lambda: clock)
    query = """{
      isoDate @date(format: "iso")
      namedDate @date(format: "iso")
      partialDatetime @date(format: "iso")
      timeOnly @date(format: "iso")
      fullDatetime @date(format: "iso")
    }"""
    result = graphql_sync(
        _SCHEMA.graphql_schema,
        query,
        middleware=[GraphQLDirectiveMiddleware()],
    )
    assert result.errors is None
    assert result.data == {
        "isoDate": "2026-01-10T00:00:00",
        "namedDate": "2026-01-10T00:00:00",
        "partialDatetime": "2026-01-10T14:30:00",
        "timeOnly": "2026-04-02T14:30:00",
        "fullDatetime": "2026-01-10T14:30:45",
    }


@pytest.mark.parametrize("clock", _CLOCKS)
def test_parser_zeros_microseconds_without_changing_explicit_or_nontext_values(
    monkeypatch: pytest.MonkeyPatch, clock: datetime
) -> None:
    """The parser changes omitted text time only, not typed inputs.

    Args:
        monkeypatch: Fixture replacing the date parser's reference clock.
        clock: The controlled current instant.
    """
    monkeypatch.setattr(date_directive.timezone, "now", lambda: clock)
    assert date_directive._parse("2026-01-10") == datetime(
        2026, 1, 10, tzinfo=timezone.utc
    )
    assert date_directive._parse("2026-01-10 14:30") == datetime(
        2026, 1, 10, 14, 30, tzinfo=timezone.utc
    )
    assert date_directive._parse("14:30") == datetime(
        2026, 4, 2, 14, 30, tzinfo=timezone.utc
    )
    assert date_directive._parse(
        "2026-01-10T14:30:45.250000+02:00"
    ) == datetime.fromisoformat("2026-01-10T14:30:45.250000+02:00")
    assert date_directive._parse(date(2026, 1, 10)) == datetime(
        2026, 1, 10, tzinfo=django_timezone.get_current_timezone()
    )
    assert date_directive._parse(bytes("2026-01-10", "ascii")) == clock.replace(
        month=1, day=10
    )
    assert date_directive._parse(time(14, 30)) is not None
    assert date_directive._parse(None) is None
    assert date_directive._parse("") is None
    assert date_directive._parse("not a date") is None


def test_text_time_only_keeps_current_date_across_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Date filling remains live while omitted time components are zero.

    Args:
        monkeypatch: Fixture replacing the date parser's reference clock.
    """
    for day in (2, 3):
        clock = datetime(2026, 4, day, 8, 15, 21, 123456, tzinfo=timezone.utc)
        monkeypatch.setattr(date_directive.timezone, "now", lambda: clock)
        assert date_directive._parse("14:30") == datetime(
            2026, 4, day, 14, 30, tzinfo=timezone.utc
        )


def test_text_default_preserves_active_timezone_with_use_tz_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Naive text still becomes aware in the active Django timezone.

    Args:
        monkeypatch: Fixture replacing the date parser's reference clock.
    """
    with override_settings(USE_TZ=False, TIME_ZONE="UTC"):
        with django_timezone.override(ZoneInfo("Asia/Tokyo")):
            monkeypatch.setattr(
                date_directive.timezone,
                "now",
                lambda: datetime(2026, 4, 2, 8, 15, 21, 123456),
            )
            assert date_directive._parse("2026-01-10") == datetime(
                2026, 1, 10, tzinfo=ZoneInfo("Asia/Tokyo")
            )
            assert date_directive._parse("2026-01-10 14:30") == datetime(
                2026, 1, 10, 14, 30, tzinfo=ZoneInfo("Asia/Tokyo")
            )
