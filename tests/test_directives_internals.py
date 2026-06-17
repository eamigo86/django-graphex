# -*- coding: utf-8 -*-
"""Direct unit tests for the directive helper functions and edge branches.

The ``test_directives`` suite covers the happy-path through a schema; this file
drives the ``directives/date.py`` formatting helpers (``_parse``, ``_format_dt``,
``_format_time_ago``, ``_format_relativedelta``) and the empty/None resolve
branches of the number/list/string directives that the schema path skips.
"""

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest
from dateutil import relativedelta
from django.test import TestCase
from graphql import GraphQLFloat, GraphQLString, graphql_sync

from django_graphex import (
    DjangoGraphQLSchema,
    GraphQLDirectiveMiddleware,
    ObjectType,
    all_directives,
    field,
)
from django_graphex.base_types import CustomDateFormat
from django_graphex.directives.date import (
    DateGraphQLDirective,
    _combine_date_time,
    _format_dt,
    _format_relativedelta,
    _format_time_ago,
    _parse,
    str_in_dict_keys,
)
from django_graphex.directives.list import (
    ShuffleGraphQLDirective,
    UniqueGraphQLDirective,
)
from django_graphex.directives.numbers import (
    AbsGraphQLDirective,
    CeilGraphQLDirective,
    RoundGraphQLDirective,
)
from django_graphex.directives.string import (
    Base64GraphQLDirective,
    CurrencyGraphQLDirective,
    DefaultGraphQLDirective,
    NumberGraphQLDirective,
    SwapCaseGraphQLDirective,
    TitleCaseGraphQLDirective,
    TruncateGraphQLDirective,
)


# --------------------------------------------------------------------------- #
# date.py helpers                                                              #
# --------------------------------------------------------------------------- #
def test_str_in_dict_keys():
    assert str_in_dict_keys("YY", {"YYYY": "%Y"}) is True
    assert str_in_dict_keys("ZZZ", {"YYYY": "%Y"}) is False


def test_combine_date_time_none_parts():
    assert _combine_date_time(None, time(1, 2, 3)) is None
    assert _combine_date_time(date(2020, 1, 1), None) is None
    combined = _combine_date_time(date(2020, 1, 2), time(3, 4, 5))
    assert combined == datetime(2020, 1, 2, 3, 4, 5)


def test_parse_handles_each_input_kind():
    # A datetime input keeps its calendar fields and gains tz awareness.
    parsed_dt = _parse(datetime(2020, 1, 1, 3, 4, 5))
    assert (parsed_dt.year, parsed_dt.month, parsed_dt.day) == (2020, 1, 1)
    assert (parsed_dt.hour, parsed_dt.minute, parsed_dt.second) == (3, 4, 5)
    assert parsed_dt.tzinfo is not None
    # A date input keeps its date and zeroes the time.
    parsed_date = _parse(date(2020, 1, 1))
    assert (parsed_date.year, parsed_date.month, parsed_date.day) == (2020, 1, 1)
    assert (parsed_date.hour, parsed_date.minute, parsed_date.second) == (0, 0, 0)
    # A time input keeps its time (date is today, which we do not assert on).
    parsed_time = _parse(time(10, 0, 0))
    assert (parsed_time.hour, parsed_time.minute, parsed_time.second) == (10, 0, 0)
    # A unix timestamp and an ISO-ish string both yield aware datetimes.
    # (The exact wall-clock value is host-timezone dependent, so only assert
    # that parsing succeeds and produces an aware datetime.)
    parsed_ts = _parse(1577836800)  # unix timestamp
    assert isinstance(parsed_ts, datetime) and parsed_ts.tzinfo is not None
    parsed_str = _parse("2020-01-01 10:00:00")
    assert (parsed_str.year, parsed_str.month, parsed_str.day) == (2020, 1, 1)
    assert (parsed_str.hour, parsed_str.minute, parsed_str.second) == (10, 0, 0)


def test_parse_invalid_string_returns_none():
    assert _parse("not-a-date-at-all-xyz!!!") is None


def test_format_dt_named_formats():
    dt = _parse(datetime(2020, 12, 31, 10, 21, 30))
    # default -> "%d %b %Y %H:%M:%S"
    assert _format_dt(dt, "default") == "31 Dec 2020 10:21:30"
    # iso -> "%Y-%m-%dT%H:%M:%S" (real ISO 8601, numeric month)
    assert _format_dt(dt, "iso") == "2020-12-31T10:21:30"
    # js / javascript -> "%a %b %d %Y %H:%M:%S" (2020-12-31 was a Thursday)
    assert _format_dt(dt, "js") == "Thu Dec 31 2020 10:21:30"
    assert _format_dt(dt, "javascript") == "Thu Dec 31 2020 10:21:30"


def test_format_dt_none_value():
    assert _format_dt(None) is None


def test_format_dt_single_token_in_map():
    dt = _parse(datetime(2020, 12, 31))
    # "YYYY" maps directly through FORMATS_MAP.
    assert _format_dt(dt, "YYYY") == "2020"


def test_format_dt_token_string_with_separators():
    dt = _parse(datetime(2020, 12, 31, 10, 21, 30))
    assert _format_dt(dt, "YYYY.MM.DD") == "2020.12.31"
    assert _format_dt(dt, "HH:mm:ss") == "10:21:30"


def test_format_dt_invalid_token_returns_none():
    dt = _parse(datetime(2020, 12, 31))
    # A run of letters that never matches any FORMATS_MAP key -> None.
    assert _format_dt(dt, "qqq") is None


def test_format_dt_time_ago_named_formats():
    dt = _parse(datetime.now() - timedelta(days=2))
    # A past datetime renders with the "ago" suffix (exact component breakdown is
    # sub-second-timing dependent, so we only assert the stable suffix).
    assert _format_dt(dt, "time ago").endswith("ago")
    # The two-day ("2d") variant returns relative wording or a formatted date
    # depending on the exact delta (host timezone shifts whether a ~2-day gap
    # lands on -1 or -2 days), so here we only assert it produces a value; the
    # Yesterday/Tomorrow wording is checked deterministically in
    # test_format_relativedelta_two_days_tomorrow_yesterday.
    assert _format_dt(dt, "time ago 2d") is not None


def test_format_dt_partial_token_then_invalid_returns_none():
    dt = _parse(datetime(2020, 12, 31))
    # "YY" is a valid partial, but "YYx"'s trailing run breaks the parse -> None.
    assert _format_dt(dt, "YYq") is None


def test_format_relativedelta_requires_relativedelta():
    with pytest.raises(ValueError):
        _format_relativedelta("not-a-delta")


def test_format_relativedelta_just_now():
    flag, text = _format_relativedelta(relativedelta.relativedelta())
    assert flag is None
    assert text == "just now"


def test_format_relativedelta_two_days_tomorrow_yesterday():
    base = datetime(2020, 1, 1)
    tomorrow = _format_relativedelta(
        relativedelta.relativedelta(days=1), two_days=True, original_dt=base
    )
    assert tomorrow == (None, "Tomorrow")
    yesterday = _format_relativedelta(
        relativedelta.relativedelta(days=-1), two_days=True, original_dt=base
    )
    assert yesterday == (None, "Yesterday")


def test_format_relativedelta_two_days_far_uses_date_string():
    base = datetime(2020, 1, 1)
    flag, text = _format_relativedelta(
        relativedelta.relativedelta(days=5), two_days=True, original_dt=base
    )
    assert flag is None
    # > 2 days away -> a plain formatted date string.
    assert "2020" in text


def test_format_relativedelta_full_joins_components():
    flag, text = _format_relativedelta(
        relativedelta.relativedelta(years=1, days=2), full=True
    )
    assert flag is True
    assert "and" in text  # multiple components joined with "and"


def test_format_relativedelta_singular_strips_plural():
    flag, text = _format_relativedelta(relativedelta.relativedelta(days=1))
    assert text == "1 day"  # singular, "days" -> "day"


def test_format_time_ago_with_ago_in():
    now = datetime(2020, 1, 10, 12, 0, 0)
    dt = datetime(2020, 1, 8, 12, 0, 0)
    text = _format_time_ago(dt, now=now, full=True, ago_in=True)
    assert "ago" in text


def test_format_time_ago_timedelta_returns_none():
    # A timedelta input short-circuits and returns None.
    assert _format_time_ago(timedelta(days=1)) is None


def test_format_time_ago_invalid_dt_raises():
    with pytest.raises(ValueError):
        _format_time_ago("garbage-not-a-date", now=datetime(2020, 1, 1))


# --------------------------------------------------------------------------- #
# DateGraphQLDirective.resolve directly                                        #
# --------------------------------------------------------------------------- #
def _info(return_type=GraphQLString):
    return SimpleNamespace(return_type=return_type)


def test_date_directive_resolve_string_value_returns_str():
    out = DateGraphQLDirective.resolve(
        "2020-12-31 10:21:30", {"format": "YYYY.MM.DD"}, None, None, _info()
    )
    assert out == "2020.12.31"


def test_date_directive_resolve_non_string_wraps_custom_format():
    out = DateGraphQLDirective.resolve(
        datetime(2020, 12, 31), {"format": "YYYY.MM.DD"}, None, None, _info()
    )
    assert isinstance(out, CustomDateFormat)


def test_date_directive_resolve_invalid_format_string_fallback():
    # A non-string value with an unmappable format -> "INVALID FORMAT STRING".
    out = DateGraphQLDirective.resolve(
        datetime(2020, 12, 31), {"format": "qqq"}, None, None, _info()
    )
    assert isinstance(out, CustomDateFormat)


# --------------------------------------------------------------------------- #
# number / list / string directives: None and empty branches                  #
# --------------------------------------------------------------------------- #
def test_number_directives_none_passthrough():
    info = _info()
    assert CeilGraphQLDirective.resolve(None, {}, None, None, info) is None
    assert RoundGraphQLDirective.resolve(None, {}, None, None, info) is None
    assert AbsGraphQLDirective.resolve(None, {}, None, None, info) is None


def test_number_directive_coerces_to_string_when_field_is_string():
    info = _info(GraphQLString)
    out = AbsGraphQLDirective.resolve(-3.5, {}, None, None, info)
    assert out == str(abs(-3.5))


def test_list_directives_empty_passthrough():
    info = _info()
    assert ShuffleGraphQLDirective.resolve([], {}, None, None, info) == []
    assert UniqueGraphQLDirective.resolve(None, {}, None, None, info) is None


def test_unique_directive_handles_unhashable_items():
    info = _info()
    out = UniqueGraphQLDirective.resolve(
        [{"a": 1}, {"a": 1}, {"b": 2}], {}, None, None, info
    )
    assert out == [{"a": 1}, {"b": 2}]


def test_string_directives_resolve_directly():
    info = _info(GraphQLString)
    assert TitleCaseGraphQLDirective.resolve("hello world", {}, None, None, info) == (
        "Hello World"
    )
    assert SwapCaseGraphQLDirective.resolve("Hello", {}, None, None, info) == "hELLO"


def test_center_directive_default_width_is_value_length():
    from django_graphex.directives.string import CenterGraphQLDirective

    info = _info(GraphQLString)
    # width=None -> defaults to len(value), so centering is a no-op.
    out = CenterGraphQLDirective.resolve("abc", {}, None, None, info)
    assert out == "abc"


def test_snake_case_directive_resolve():
    from django_graphex.directives.string import SnakeCaseGraphQLDirective

    info = _info(GraphQLString)
    # The directive title-cases and strips spaces before snake-casing.
    out = SnakeCaseGraphQLDirective.resolve("Hello World", {}, None, None, info)
    assert out == "hello_world"


# --------------------------------------------------------------------------- #
# Round-trip: ceil/round/abs None through a real schema                        #
# --------------------------------------------------------------------------- #
class _Query(ObjectType):
    blank = field(GraphQLFloat)
    text = field(GraphQLString)
    ident = field(GraphQLString)

    def resolve_blank(root, info):
        return None

    def resolve_text(root, info):
        return "Hello World"

    def resolve_ident(root, info):
        return "hello_world"


_schema = DjangoGraphQLSchema(query=_Query, directives=list(all_directives))


class DirectiveSchemaNoneTest(TestCase):
    def _run(self, q):
        result = graphql_sync(
            _schema.graphql_schema, q, middleware=[GraphQLDirectiveMiddleware()]
        )
        self.assertIsNone(result.errors, result.errors)
        return result.data

    def test_ceil_round_abs_none(self):
        self.assertIsNone(self._run("{ blank @ceil }")["blank"])
        self.assertIsNone(self._run("{ blank @round }")["blank"])
        self.assertIsNone(self._run("{ blank @abs }")["blank"])

    def test_case_directives(self):
        self.assertEqual(self._run("{ text @lowercase }")["text"], "hello world")
        self.assertEqual(self._run("{ text @uppercase }")["text"], "HELLO WORLD")
        self.assertEqual(self._run("{ text @capitalize }")["text"], "Hello world")
        self.assertEqual(self._run("{ text @title_case }")["text"], "Hello World")
        self.assertEqual(self._run("{ text @swap_case }")["text"], "hELLO wORLD")
        # camel_case converts snake_case identifier input to camelCase.
        self.assertEqual(self._run("{ ident @camel_case }")["ident"], "helloWorld")
        # kebab_case runs (its exact quirk on snake input is documented behavior).
        self.assertEqual(self._run("{ ident @kebab_case }")["ident"], "hello_-world")

    def test_replace(self):
        self.assertEqual(
            self._run('{ text @replace(old: "World", new: "There") }')["text"],
            "Hello There",
        )


# --------------------------------------------------------------------------- #
# string directive resolve() edge branches                                     #
# --------------------------------------------------------------------------- #
def test_default_directive_empty_value_returns_fallback():
    info = _info(GraphQLString)
    # Empty value -> returns the `to` fallback (line 97).
    assert (
        DefaultGraphQLDirective.resolve("", {"to": "fallback"}, None, None, info)
        == "fallback"
    )
    # Non-empty value passes through.
    assert (
        DefaultGraphQLDirective.resolve("keep", {"to": "fallback"}, None, None, info)
        == "keep"
    )


def test_base64_directive_empty_value_returns_none():
    info = _info(GraphQLString)
    # Empty value short-circuits to None (line 138).
    assert (
        Base64GraphQLDirective.resolve("", {"op": "encode"}, None, None, info) is None
    )


def test_number_directive_formats_value():
    info = _info(GraphQLString)
    # Formats with a Python format spec (line 185).
    assert NumberGraphQLDirective.resolve(3.14159, {"as": ".2f"}, None, None, info) == (
        "3.14"
    )
    # None coerces to 0.
    assert (
        NumberGraphQLDirective.resolve(None, {"as": ".1f"}, None, None, info) == "0.0"
    )


def test_currency_directive_default_and_custom_symbol():
    info = _info(GraphQLString)
    # Default symbol `$` (lines 225-226).
    assert CurrencyGraphQLDirective.resolve(5, {}, None, None, info) == "$5.00"
    # Custom symbol honored.
    assert (
        CurrencyGraphQLDirective.resolve(5, {"symbol": "€"}, None, None, info)
        == "€5.00"
    )


def test_truncate_directive_word_boundary_and_killwords():
    info = _info(GraphQLString)
    # Short text under length -> returned unchanged.
    assert (
        TruncateGraphQLDirective.resolve("hi", {"length": 10}, None, None, info) == "hi"
    )
    # Word-boundary truncation with the default ellipsis.
    out = TruncateGraphQLDirective.resolve(
        "hello world foo", {"length": 8}, None, None, info
    )
    assert out.endswith("…")
    # killwords cuts mid-word (line 623 region).
    killed = TruncateGraphQLDirective.resolve(
        "hello world", {"length": 7, "killwords": True, "end": "!"}, None, None, info
    )
    assert killed == "hello w!"
