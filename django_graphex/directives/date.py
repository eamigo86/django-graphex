"""Date formatting GraphQL directive."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from dateutil import parser, relativedelta
from django.utils import timezone
from graphql import GraphQLArgument, GraphQLString

from ..base_types import CustomDateFormat
from .base import BaseExtraGraphQLDirective

if TYPE_CHECKING:
    from graphql import GraphQLResolveInfo

__all__ = ("DateGraphQLDirective",)


DEFAULT_DATE_FORMAT = "%d %b %Y %H:%M:%S"
FORMATS_MAP = {
    # Year
    "YYYY": "%Y",
    "YY": "%y",
    # Week of year
    "WW": "%U",
    "W": "%W",
    # Day of Month
    # 'D': '%-d',  # Platform specific
    "DD": "%d",
    # Day of Year
    # 'DDD': '%-j',  # Platform specific
    "DDDD": "%j",
    # Day of Week
    "d": "%w",
    "ddd": "%a",
    "dddd": "%A",
    # Month
    # 'M': '%-m',  # Platform specific
    "MM": "%m",
    "MMM": "%b",
    "MMMM": "%B",
    # Hour
    # 'H': '%-H',  # Platform specific
    "HH": "%H",
    # 'h': '%-I',  # Platform specific
    "hh": "%I",
    # Minute
    # 'm': '%-M',  # Platform specific
    "mm": "%M",
    # Second
    # 's': '%-S',  # Platform specific
    "ss": "%S",
    # AM/PM
    # 'a': '',
    "A": "%p",
    # Timezone
    "ZZ": "%z",
    "z": "%Z",
}


def str_in_dict_keys(s: str, d: dict[str, Any]) -> bool:
    """Report whether a string is a substring of any key in a mapping.

    Args:
        s: The string to look for.
        d: The mapping whose keys are searched.

    Returns:
        True when "s" is contained in at least one key, else False.
    """
    for k in d:
        if s in k:
            return True
    return False


def _combine_date_time(d: date | None, t: time | None) -> datetime | None:
    """Combine a date and a time into a single datetime.

    Args:
        d: The date part, or None.
        t: The time part, or None.

    Returns:
        The combined datetime, or None when either part is None.
    """
    if (d is not None) and (t is not None):
        return datetime(d.year, d.month, d.day, t.hour, t.minute, t.second)
    return None


def _parse(partial_dt: Any) -> datetime | None:
    """Parse a partial datetime value into a complete datetime object.

    Args:
        partial_dt: A datetime, date, time, timestamp, or datetime string.

    Returns:
        A timezone-aware datetime, or None when parsing fails.
    """
    dt = None
    try:
        if isinstance(partial_dt, datetime):
            dt = partial_dt
        elif isinstance(partial_dt, date):
            dt = _combine_date_time(partial_dt, time(0, 0, 0))
        elif isinstance(partial_dt, time):
            dt = _combine_date_time(date.today(), partial_dt)
        elif isinstance(partial_dt, (int, float)):
            dt = datetime.fromtimestamp(partial_dt)
        elif isinstance(partial_dt, (str, bytes)):
            dt = parser.parse(partial_dt, default=timezone.now())

        if dt is not None and timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        return dt
    except ValueError:
        return None


def _format_relativedelta(
    rdelta: relativedelta.relativedelta,
    full: bool = False,
    two_days: bool = False,
    original_dt: datetime | None = None,
) -> tuple[bool | None, str | None]:
    """Render a relativedelta as a human-readable string.

    Args:
        rdelta: The relative delta to render.
        full: Whether to include every non-zero component.
        two_days: Whether to use "Tomorrow"/"Yesterday" wording.
        original_dt: The original datetime used for two-day wording.

    Returns:
        A tuple of a direction flag and the rendered string. The flag is
        True for future, False for past, and None when undirected.

    Raises:
        ValueError: If "rdelta" is not a relativedelta instance.
    """
    if not isinstance(rdelta, relativedelta.relativedelta):
        raise ValueError("rdelta must be a relativedelta instance")
    keys = ("years", "months", "days", "hours", "minutes", "seconds")
    result = []
    flag = None

    if two_days and original_dt:
        if rdelta.years == 0 and rdelta.months == 0:
            days = rdelta.days
            if days == 1:
                return None, "Tomorrow"
            if days == -1:
                return None, "Yesterday"
            if days == 0:
                full = False
            else:
                return None, original_dt.strftime("%b %d, %Y")
        else:
            return None, original_dt.strftime("%b %d, %Y")

    for k, v in rdelta.__dict__.items():
        if k in keys and v != 0:
            if flag is None:
                flag = True if v > 0 else False
            key = k
            abs_v = abs(v)
            if abs_v == 1:
                key = key[:-1]
            if not full:
                return flag, f"{abs_v} {key}"
            else:
                result.append(f"{abs_v} {key}")
    if len(result) == 0:
        return None, ("Now" if two_days else "just now")
    if len(result) > 1:
        temp = result.pop()
        result = f"{', '.join(result)} and {temp}"
    else:
        result = result[0]

    return flag, result


def _format_time_ago(
    dt: Any,
    now: Any = None,
    full: bool = False,
    ago_in: bool = False,
    two_days: bool = False,
) -> str | None:
    """Render the relative time between a datetime and now.

    Args:
        dt: The datetime, timedelta, or datetime string to compare.
        now: The reference datetime, defaulting to the current time.
        full: Whether to include every non-zero component.
        ago_in: Whether to prefix/suffix with "in"/"ago" wording.
        two_days: Whether to use "Tomorrow"/"Yesterday" wording.

    Returns:
        The rendered relative time string, or None when "dt" is a
        timedelta.

    Raises:
        ValueError: If "dt" or "now" cannot be parsed into a datetime.
    """
    if not isinstance(dt, timedelta):
        if now is None:
            current = timezone.now()
            # ``localtime`` rejects naive datetimes, which is what ``now()``
            # returns when the host project runs with ``USE_TZ = False``.
            if timezone.is_naive(current):
                now = current
            else:
                # Use Django's get_current_timezone() so that DST transitions
                # are handled correctly.  The old code used
                # ``time.timezone`` (a fixed, DST-unaware UTC offset) which
                # produced a wrong delta during daylight-saving periods.
                now = timezone.localtime(
                    current,
                    timezone=timezone.get_current_timezone(),
                )

        original_dt = dt
        dt = _parse(dt)
        now = _parse(now)

        if dt is None:
            raise ValueError(
                "The parameter `dt` should be datetime timedelta, or datetime formatted string."
            )
        if now is None:
            raise ValueError(
                "the parameter `now` should be datetime, or datetime formatted string."
            )

        result = relativedelta.relativedelta(dt, now)
        flag, result = _format_relativedelta(result, full, two_days, original_dt)
        if ago_in and flag is not None:
            result = f"in {result}" if flag else f"{result} ago"
        return result


def _format_dt(dt: Any, format: str = "default") -> str | None:
    """Format a datetime using a token-based or named format.

    Args:
        dt: The datetime to format.
        format: A named format or a token string mapped via "FORMATS_MAP".

    Returns:
        The formatted datetime string, or None when formatting fails.
    """
    if not dt:
        return None

    format_lowered = format.lower()

    if format_lowered == "default":
        return dt.strftime(DEFAULT_DATE_FORMAT)

    if format_lowered == "time ago":
        return _format_time_ago(dt, full=True, ago_in=True)

    if format_lowered == "time ago 2d":
        return _format_time_ago(dt, full=True, ago_in=True, two_days=True)

    if format_lowered == "iso":
        # ISO 8601: YYYY-MM-DDTHH:MM:SS  (numeric month, no locale abbreviation)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    if format_lowered in ("js", "javascript"):
        return dt.strftime("%a %b %d %Y %H:%M:%S")

    if format in FORMATS_MAP:
        return dt.strftime(FORMATS_MAP[format])

    else:
        temp_format = ""
        translate_format_list = []
        for char in format:
            if not char.isalpha():
                if temp_format != "":
                    translate_format_list.append(FORMATS_MAP.get(temp_format, ""))
                    temp_format = ""
                translate_format_list.append(char)
            else:
                if str_in_dict_keys(f"{temp_format}{char}", FORMATS_MAP):
                    temp_format = f"{temp_format}{char}"
                else:
                    if temp_format != "":
                        if temp_format in FORMATS_MAP:
                            translate_format_list.append(
                                FORMATS_MAP.get(temp_format, "")
                            )
                        else:
                            return None
                    if str_in_dict_keys(char, FORMATS_MAP):
                        temp_format = char
                    else:
                        return None

        if temp_format != "":
            if temp_format in FORMATS_MAP:
                translate_format_list.append(FORMATS_MAP.get(temp_format, ""))
            else:
                return None

        format_result = "".join(translate_format_list)
        if format_result:
            return dt.strftime("".join(translate_format_list))
        return None


class DateGraphQLDirective(BaseExtraGraphQLDirective):
    """Format a resolved date/datetime value using a supplied format.

    The optional "format" argument is either a named format ("default", "iso",
    "js", "time ago", "time ago 2d") or a token string built from the keys of
    "FORMATS_MAP" (dateutil-style tokens such as "YYYY-MM-DD"). String field
    values yield a plain string; other values are wrapped in a
    "CustomDateFormat" so the scalar can serialize them.
    """

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Get arguments for the date directive.

        Returns:
            A mapping of argument names to their definitions.
        """
        return {
            "format": GraphQLArgument(
                GraphQLString, description="A format given by dateutil module"
            )
        }

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Resolve the date formatting directive.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.

        Returns:
            The formatted date string for string values, otherwise a
            "CustomDateFormat" wrapping the formatted result.
        """
        custom_format = args.get("format") or "default"
        dt = _parse(value)
        try:
            result = _format_dt(dt, custom_format)
            if isinstance(value, str):
                return result or value
            return CustomDateFormat(result or "INVALID FORMAT STRING")
        except ValueError:
            return CustomDateFormat("INVALID FORMAT STRING")
