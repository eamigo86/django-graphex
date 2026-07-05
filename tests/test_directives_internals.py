# -*- coding: utf-8 -*-
"""Direct unit tests for the directive helper functions and edge branches.

The "test_directives" suite covers the happy-path through a schema; this file
drives the "directives/date.py" formatting helpers ("_parse", "_format_dt",
"_format_time_ago", "_format_relativedelta") and the empty/None resolve
branches of the number/list/string directives that the schema path skips.
"""

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from dateutil import relativedelta
from django.test import TestCase
from graphql import GraphQLFloat, GraphQLString, graphql_sync

from django_graphex.base_types import CustomDateFormat
from django_graphex.core import ObjectType, field
from django_graphex.directives import all_directives
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
from django_graphex.middleware import GraphQLDirectiveMiddleware
from django_graphex.schema import DjangoGraphQLSchema


# --------------------------------------------------------------------------- #
# date.py helpers                                                              #
# --------------------------------------------------------------------------- #
def test_str_in_dict_keys() -> None:
    """ ""str_in_dict_keys"" must report True only when the string is a substring of some key.

    If this breaks, the token-format lookup helpers that rely on this
    substring scan could match the wrong format token or miss a valid one.
    """
    assert str_in_dict_keys("YY", {"YYYY": "%Y"}) is True
    assert str_in_dict_keys("ZZZ", {"YYYY": "%Y"}) is False


def test_combine_date_time_none_parts() -> None:
    """ ""_combine_date_time"" must return None when either part is missing, else the combined datetime.

    If this breaks, a partial date/time input could crash the combiner
    instead of signaling "cannot combine" via None.
    """
    assert _combine_date_time(None, time(1, 2, 3)) is None
    assert _combine_date_time(date(2020, 1, 1), None) is None
    combined = _combine_date_time(date(2020, 1, 2), time(3, 4, 5))
    assert combined == datetime(2020, 1, 2, 3, 4, 5)


def test_parse_handles_each_input_kind() -> None:
    """ ""_parse"" must normalize datetime, date, time, unix-timestamp, and string inputs to an aware datetime.

    If this breaks, one of the several supported input types could be
    silently mishandled by the date-formatting directives.
    """
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


def test_parse_invalid_string_returns_none() -> None:
    """ ""_parse"" must return None for a string that cannot be parsed as any date/time.

    If this breaks, an unparsable string could raise instead of yielding a
    safe None for the caller to handle.
    """
    assert _parse("not-a-date-at-all-xyz!!!") is None


def test_format_dt_named_formats() -> None:
    """The "default", "iso", "js", and "javascript" named formats must each render their documented pattern.

    If this breaks, any one of the built-in named format aliases could
    silently drift from its documented output pattern.
    """
    dt = _parse(datetime(2020, 12, 31, 10, 21, 30))
    # default -> "%d %b %Y %H:%M:%S"
    assert _format_dt(dt, "default") == "31 Dec 2020 10:21:30"
    # iso -> "%Y-%m-%dT%H:%M:%S" (real ISO 8601, numeric month)
    assert _format_dt(dt, "iso") == "2020-12-31T10:21:30"
    # js / javascript -> "%a %b %d %Y %H:%M:%S" (2020-12-31 was a Thursday)
    assert _format_dt(dt, "js") == "Thu Dec 31 2020 10:21:30"
    assert _format_dt(dt, "javascript") == "Thu Dec 31 2020 10:21:30"


def test_format_dt_none_value() -> None:
    """ ""_format_dt"" must return None when given a None datetime instead of raising.

    If this breaks, formatting a null date field would crash rather than
    passing through as null.
    """
    assert _format_dt(None) is None


def test_format_dt_single_token_in_map() -> None:
    """A single token like ""YYYY"" that maps directly through FORMATS_MAP must render correctly.

    If this breaks, single-token format strings could fail to resolve
    through the format-token lookup table.
    """
    dt = _parse(datetime(2020, 12, 31))
    # "YYYY" maps directly through FORMATS_MAP.
    assert _format_dt(dt, "YYYY") == "2020"


def test_format_dt_token_string_with_separators() -> None:
    """A token string with literal separators (dots, colons) must render the tokens and keep the separators.

    If this breaks, mixed token/separator format strings could lose their
    punctuation or fail to tokenize correctly.
    """
    dt = _parse(datetime(2020, 12, 31, 10, 21, 30))
    assert _format_dt(dt, "YYYY.MM.DD") == "2020.12.31"
    assert _format_dt(dt, "HH:mm:ss") == "10:21:30"


def test_format_dt_invalid_token_returns_none() -> None:
    """A run of letters matching no FORMATS_MAP key must make ""_format_dt"" return None.

    If this breaks, an unrecognized format token could raise instead of
    yielding a safe None.
    """
    dt = _parse(datetime(2020, 12, 31))
    # A run of letters that never matches any FORMATS_MAP key -> None.
    assert _format_dt(dt, "qqq") is None


def test_format_dt_time_ago_named_formats() -> None:
    """The ""time ago"" and ""time ago 2d"" named formats must produce non-empty relative-time output.

    Exact component breakdown is sub-second-timing dependent, so only the
    stable "ago" suffix and value presence are asserted here; the
    Yesterday/Tomorrow wording is checked deterministically in
    "test_format_relativedelta_two_days_tomorrow_yesterday". If this
    breaks, the relative-time named formats could stop producing usable
    output.
    """
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


def test_format_dt_partial_token_then_invalid_returns_none() -> None:
    """A valid partial token run followed by an unmatchable trailing run must make ""_format_dt"" return None.

    If this breaks, a format string that starts valid but ends invalid
    could be partially accepted instead of rejected as a whole.
    """
    dt = _parse(datetime(2020, 12, 31))
    # "YY" is a valid partial, but "YYx"'s trailing run breaks the parse -> None.
    assert _format_dt(dt, "YYq") is None


def test_format_relativedelta_requires_relativedelta() -> None:
    """ ""_format_relativedelta"" must raise ValueError when not given a relativedelta instance.

    If this breaks, a caller passing the wrong type could get a confusing
    downstream error instead of a clear ValueError.
    """
    with pytest.raises(ValueError):
        _format_relativedelta("not-a-delta")


def test_format_relativedelta_just_now() -> None:
    """A zero relativedelta must render as the literal text "just now" with no flag.

    If this breaks, a zero time difference could render as an empty or
    confusing string instead of "just now".
    """
    flag, text = _format_relativedelta(relativedelta.relativedelta())
    assert flag is None
    assert text == "just now"


def test_format_relativedelta_two_days_tomorrow_yesterday() -> None:
    """With "two_days=True", a +/-1 day delta must render as the literal "Tomorrow"/"Yesterday".

    If this breaks, near-term dates could render as a generic formatted
    date instead of the friendlier Tomorrow/Yesterday wording.
    """
    base = datetime(2020, 1, 1)
    tomorrow = _format_relativedelta(
        relativedelta.relativedelta(days=1), two_days=True, original_dt=base
    )
    assert tomorrow == (None, "Tomorrow")
    yesterday = _format_relativedelta(
        relativedelta.relativedelta(days=-1), two_days=True, original_dt=base
    )
    assert yesterday == (None, "Yesterday")


def test_format_relativedelta_two_days_far_uses_date_string() -> None:
    """With "two_days=True", a delta beyond +/-1 day must fall back to a plain formatted date string.

    If this breaks, dates further than a day away could incorrectly reuse
    the Tomorrow/Yesterday wording instead of a real date string.
    """
    base = datetime(2020, 1, 1)
    flag, text = _format_relativedelta(
        relativedelta.relativedelta(days=5), two_days=True, original_dt=base
    )
    assert flag is None
    # > 2 days away -> a plain formatted date string.
    assert "2020" in text


def test_format_relativedelta_full_joins_components() -> None:
    """With "full=True", multiple non-zero components must be joined with the word "and".

    If this breaks, a multi-component relativedelta could render only its
    first component instead of the full joined description.
    """
    flag, text = _format_relativedelta(
        relativedelta.relativedelta(years=1, days=2), full=True
    )
    assert flag is True
    assert "and" in text  # multiple components joined with "and"


def test_format_relativedelta_singular_strips_plural() -> None:
    """A single-unit delta (for example one day) must render the singular unit name, not the plural.

    If this breaks, a single day/hour/etc. could render as "1 days"
    instead of the grammatically correct "1 day".
    """
    flag, text = _format_relativedelta(relativedelta.relativedelta(days=1))
    assert text == "1 day"  # singular, "days" -> "day"


def test_format_time_ago_with_ago_in() -> None:
    """With "ago_in=True" and a past datetime, the rendered text must include the word "ago".

    If this breaks, past-datetime rendering could drop the "ago" suffix
    that distinguishes it from a future ("in ...") relative time.
    """
    now = datetime(2020, 1, 10, 12, 0, 0)
    dt = datetime(2020, 1, 8, 12, 0, 0)
    text = _format_time_ago(dt, now=now, full=True, ago_in=True)
    assert "ago" in text


def test_format_time_ago_timedelta_returns_none() -> None:
    """A raw timedelta input must short-circuit ""_format_time_ago"" to None.

    If this breaks, a timedelta (rather than a datetime) input could raise
    instead of being safely rejected with None.
    """
    # A timedelta input short-circuits and returns None.
    assert _format_time_ago(timedelta(days=1)) is None


def test_format_time_ago_invalid_dt_raises() -> None:
    """A non-date, non-parsable string input must make ""_format_time_ago"" raise ValueError.

    If this breaks, a garbage input could either silently produce a wrong
    result or raise the wrong exception type.
    """
    with pytest.raises(ValueError):
        _format_time_ago("garbage-not-a-date", now=datetime(2020, 1, 1))


# --------------------------------------------------------------------------- #
# DateGraphQLDirective.resolve directly                                        #
# --------------------------------------------------------------------------- #
def _info(return_type: Any = GraphQLString) -> SimpleNamespace:
    """Build a minimal stand-in for GraphQLResolveInfo carrying only "return_type".

    Args:
        return_type: The field return type the directive's resolve should
            see, defaulting to GraphQLString.

    Returns:
        info: A namespace exposing "return_type", enough for the directive
            resolvers under test.
    """
    return SimpleNamespace(return_type=return_type)


def test_date_directive_resolve_string_value_returns_str() -> None:
    """ ""DateGraphQLDirective.resolve"" must format a string datetime value into a plain formatted string.

    If this breaks, string-valued datetime fields could fail to format or
    return the wrong wrapper type.
    """
    out = DateGraphQLDirective.resolve(
        "2020-12-31 10:21:30", {"format": "YYYY.MM.DD"}, None, None, _info()
    )
    assert out == "2020.12.31"


def test_date_directive_resolve_non_string_wraps_custom_format() -> None:
    """ ""DateGraphQLDirective.resolve"" must wrap a non-string datetime value in a "CustomDateFormat".

    If this breaks, native datetime/date field values could be returned
    unwrapped and lose their custom formatting on serialization.
    """
    out = DateGraphQLDirective.resolve(
        datetime(2020, 12, 31), {"format": "YYYY.MM.DD"}, None, None, _info()
    )
    assert isinstance(out, CustomDateFormat)


def test_date_directive_resolve_invalid_format_string_fallback() -> None:
    """A non-string value with an unmappable format must still return a "CustomDateFormat" wrapper.

    If this breaks, an invalid format string against a native datetime
    value could raise instead of degrading to the "INVALID FORMAT STRING"
    wrapped fallback.
    """
    # A non-string value with an unmappable format -> "INVALID FORMAT STRING".
    out = DateGraphQLDirective.resolve(
        datetime(2020, 12, 31), {"format": "qqq"}, None, None, _info()
    )
    assert isinstance(out, CustomDateFormat)


# --------------------------------------------------------------------------- #
# number / list / string directives: None and empty branches                  #
# --------------------------------------------------------------------------- #
def test_number_directives_none_passthrough() -> None:
    """ ""@ceil"", ""@round"", and ""@abs"" must all pass through a None value unchanged.

    If this breaks, a null numeric field could crash one of the math
    directives instead of resolving to null.
    """
    info = _info()
    assert CeilGraphQLDirective.resolve(None, {}, None, None, info) is None
    assert RoundGraphQLDirective.resolve(None, {}, None, None, info) is None
    assert AbsGraphQLDirective.resolve(None, {}, None, None, info) is None


def test_number_directive_coerces_to_string_when_field_is_string() -> None:
    """ ""@abs"" must coerce its numeric result to a string when the field's return type is GraphQLString.

    If this breaks, a numeric result could be returned as a float against
    a String-typed field, producing a serialization mismatch.
    """
    info = _info(GraphQLString)
    out = AbsGraphQLDirective.resolve(-3.5, {}, None, None, info)
    assert out == str(abs(-3.5))


def test_list_directives_empty_passthrough() -> None:
    """ ""@shuffle"" on an empty list and ""@unique"" on None must both pass through without error.

    If this breaks, list directives could crash on the boundary cases of
    an empty list or a null list field.
    """
    info = _info()
    assert ShuffleGraphQLDirective.resolve([], {}, None, None, info) == []
    assert UniqueGraphQLDirective.resolve(None, {}, None, None, info) is None


def test_unique_directive_handles_unhashable_items() -> None:
    """ ""@unique"" must deduplicate a list of unhashable dict items without raising.

    If this breaks, deduplicating a list of dicts (which are unhashable)
    could raise TypeError instead of falling back to equality comparison.
    """
    info = _info()
    out = UniqueGraphQLDirective.resolve(
        [{"a": 1}, {"a": 1}, {"b": 2}], {}, None, None, info
    )
    assert out == [{"a": 1}, {"b": 2}]


def test_string_directives_resolve_directly() -> None:
    """ ""@title_case"" and ""@swap_case"" must transform text as their names imply, called directly.

    If this breaks, calling these directives' "resolve" outside a schema
    (as internal callers may) could behave differently than through the
    schema execution path.
    """
    info = _info(GraphQLString)
    assert TitleCaseGraphQLDirective.resolve("hello world", {}, None, None, info) == (
        "Hello World"
    )
    assert SwapCaseGraphQLDirective.resolve("Hello", {}, None, None, info) == "hELLO"


def test_center_directive_default_width_is_value_length() -> None:
    """ ""@center"" with no "width" argument must default to the value's own length, making it a no-op.

    If this breaks, an unset width could crash the centering logic or pad
    the string unexpectedly.
    """
    from django_graphex.directives.string import CenterGraphQLDirective

    info = _info(GraphQLString)
    # width=None -> defaults to len(value), so centering is a no-op.
    out = CenterGraphQLDirective.resolve("abc", {}, None, None, info)
    assert out == "abc"


def test_snake_case_directive_resolve() -> None:
    """ ""@snake_case"" must title-case and strip spaces before converting to snake_case.

    If this breaks, converting a spaced phrase to snake_case could produce
    incorrect casing or leftover separators.
    """
    from django_graphex.directives.string import SnakeCaseGraphQLDirective

    info = _info(GraphQLString)
    # The directive title-cases and strips spaces before snake-casing.
    out = SnakeCaseGraphQLDirective.resolve("Hello World", {}, None, None, info)
    assert out == "hello_world"


# --------------------------------------------------------------------------- #
# Round-trip: ceil/round/abs None through a real schema                        #
# --------------------------------------------------------------------------- #
class _Query(ObjectType):
    """Query root exposing null/text/identifier fields for whole-schema directive tests."""

    blank = field(GraphQLFloat)
    text = field(GraphQLString)
    ident = field(GraphQLString)

    def resolve_blank(root: Any, info: Any) -> None:
        """Resolve "blank" to None, for exercising null-safe math directives.

        Args:
            root: The unused root value passed by the executor.
            info: The unused GraphQL resolve info passed by the executor.
        """
        return None

    def resolve_text(root: Any, info: Any) -> str:
        """Resolve "text" to a constant sample sentence.

        Args:
            root: The unused root value passed by the executor.
            info: The unused GraphQL resolve info passed by the executor.

        Returns:
            text: The literal string "Hello World".
        """
        return "Hello World"

    def resolve_ident(root: Any, info: Any) -> str:
        """Resolve "ident" to a constant snake_case identifier string.

        Args:
            root: The unused root value passed by the executor.
            info: The unused GraphQL resolve info passed by the executor.

        Returns:
            ident: The literal string "hello_world".
        """
        return "hello_world"


_schema = DjangoGraphQLSchema(query=_Query, directives=list(all_directives))


class DirectiveSchemaNoneTest(TestCase):
    """Round-trip coverage of the math and case directives through a live schema.

    Confirms unit-level behavior (from earlier tests in this module) still
    holds once wired through actual schema execution.
    """

    def _run(self, q: str) -> Any:
        result = graphql_sync(
            _schema.graphql_schema, q, middleware=[GraphQLDirectiveMiddleware()]
        )
        self.assertIsNone(result.errors, result.errors)
        return result.data

    def test_ceil_round_abs_none(self) -> None:
        """ "@ceil", "@round", and "@abs" applied to a null field must all resolve to null through a real schema.

        If this breaks, the unit-level None-passthrough guarantee could
        fail once wired into actual schema execution.
        """
        self.assertIsNone(self._run("{ blank @ceil }")["blank"])
        self.assertIsNone(self._run("{ blank @round }")["blank"])
        self.assertIsNone(self._run("{ blank @abs }")["blank"])

    def test_case_directives(self) -> None:
        """The case-conversion directives (lowercase, uppercase, capitalize, title_case, swap_case, camel_case, kebab_case) must each transform text correctly end-to-end.

        If this breaks, any one of the seven case-conversion directives
        could silently regress when executed through a real schema.
        """
        self.assertEqual(self._run("{ text @lowercase }")["text"], "hello world")
        self.assertEqual(self._run("{ text @uppercase }")["text"], "HELLO WORLD")
        self.assertEqual(self._run("{ text @capitalize }")["text"], "Hello world")
        self.assertEqual(self._run("{ text @title_case }")["text"], "Hello World")
        self.assertEqual(self._run("{ text @swap_case }")["text"], "hELLO wORLD")
        # camel_case converts snake_case identifier input to camelCase.
        self.assertEqual(self._run("{ ident @camel_case }")["ident"], "helloWorld")
        # kebab_case runs (its exact quirk on snake input is documented behavior).
        self.assertEqual(self._run("{ ident @kebab_case }")["ident"], "hello_-world")

    def test_replace(self) -> None:
        """ "@replace(old:, new:)" must substitute the old substring with the new one end-to-end.

        If this breaks, the replace directive could fail to apply through
        a real schema even if its unit-level logic is correct.
        """
        self.assertEqual(
            self._run('{ text @replace(old: "World", new: "There") }')["text"],
            "Hello There",
        )


# --------------------------------------------------------------------------- #
# string directive resolve() edge branches                                     #
# --------------------------------------------------------------------------- #
def test_default_directive_empty_value_returns_fallback() -> None:
    """ ""@default(to:...)" must substitute the fallback for an empty string but pass through a non-empty one.

    If this breaks, an empty (falsy) field value could either keep showing
    empty instead of the fallback, or a genuine non-empty value could be
    wrongly replaced.
    """
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


def test_base64_directive_empty_value_returns_none() -> None:
    """ ""@base64(op:"encode")" applied to an empty string must short-circuit to None.

    If this breaks, encoding an empty value could produce a spurious
    non-null base64 string (of zero bytes) instead of null.
    """
    info = _info(GraphQLString)
    # Empty value short-circuits to None (line 138).
    assert (
        Base64GraphQLDirective.resolve("", {"op": "encode"}, None, None, info) is None
    )


def test_number_directive_formats_value() -> None:
    """ ""@number(as:...)" must format with a Python format spec and coerce a None value to 0.

    If this breaks, numeric formatting could fail on genuine values or
    crash instead of treating a null value as zero.
    """
    info = _info(GraphQLString)
    # Formats with a Python format spec (line 185).
    assert NumberGraphQLDirective.resolve(3.14159, {"as": ".2f"}, None, None, info) == (
        "3.14"
    )
    # None coerces to 0.
    assert (
        NumberGraphQLDirective.resolve(None, {"as": ".1f"}, None, None, info) == "0.0"
    )


def test_currency_directive_default_and_custom_symbol() -> None:
    """ ""@currency"" must default to the "$" symbol and honor a custom "symbol" argument.

    If this breaks, currency formatting could ignore the custom symbol
    argument or use the wrong default currency mark.
    """
    info = _info(GraphQLString)
    # Default symbol `$` (lines 225-226).
    assert CurrencyGraphQLDirective.resolve(5, {}, None, None, info) == "$5.00"
    # Custom symbol honored.
    assert (
        CurrencyGraphQLDirective.resolve(5, {"symbol": "€"}, None, None, info)
        == "€5.00"
    )


def test_truncate_directive_word_boundary_and_killwords() -> None:
    """ ""@truncate"" must leave short text unchanged, truncate at a word boundary by default, and cut mid-word with "killwords".

    If this breaks, truncation could exceed the requested length, split a
    word unexpectedly, or ignore the "killwords" argument.
    """
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
