"""Lookup catalogs and per-type default lookup sets for native filtering.

These constants drive both schema generation (which input fields a
``<Field>Lookups`` input exposes) and translation (the ORM lookup suffix used
when building a ``Q`` object). They absorb the lookup
constants that previously lived in the removed ``filters`` package.
"""

from __future__ import annotations

from django_graphex.settings import graphql_api_settings

__all__ = (
    "ALL_LOOKUPS",
    "BASIC_LOOKUPS",
    "COMMON_LOOKUPS",
    "NUMBER_LOOKUPS",
    "DATETIME_LOOKUPS",
    "DATE_LOOKUPS",
    "TIME_LOOKUPS",
    "TEXT_LOOKUPS",
    "ORDERED_LOOKUPS",
    "DEFAULT_LOOKUPS",
    "default_lookups_for",
)


_all_lookups = (
    "isnull",
    "exact",
    "iexact",
    "contains",
    "icontains",
    "startswith",
    "istartswith",
    "endswith",
    "iendswith",
    "in",
    "gt",
    "gte",
    "lt",
    "lte",
    "range",
    "year",
    "month",
    "day",
    "week_day",
    "hour",
    "minute",
    "second",
)


#: Every lookup the catalog knows about.
ALL_LOOKUPS = _all_lookups
#: ``("exact", "icontains")`` -- the minimal text pair.
BASIC_LOOKUPS = _all_lookups[2:3] + _all_lookups[4:5]
#: Lookups shared by most scalar fields.
COMMON_LOOKUPS = _all_lookups[0:10]
#: Numeric comparison lookups.
NUMBER_LOOKUPS = _all_lookups[9:15]
#: Datetime lookups (numeric comparisons plus date/time parts).
DATETIME_LOOKUPS = _all_lookups[9:]
#: Date lookups (numeric comparisons plus date parts).
DATE_LOOKUPS = _all_lookups[9:19]
#: Time lookups (numeric comparisons plus time parts).
TIME_LOOKUPS = _all_lookups[9:15] + _all_lookups[19:]

#: Lookups added by default to text fields.
TEXT_LOOKUPS = ("icontains", "istartswith")
#: Lookups added by default to ordered (number/date/datetime) fields.
ORDERED_LOOKUPS = ("gt", "gte", "lt", "lte", "range")

#: The default lookup set every field receives (configurable via the
#: ``COMMON_FILTER_LOOKUPS`` setting).
DEFAULT_LOOKUPS = ("exact", "in", "isnull")


#: Django internal-type names treated as "text" for default-lookup purposes.
_TEXT_TYPES = frozenset(
    {
        "CharField",
        "TextField",
        "EmailField",
        "URLField",
        "SlugField",
        "FilePathField",
        "FileField",
        "ImageField",
        "GenericIPAddressField",
    }
)
#: Django internal-type names treated as "ordered" for default-lookup purposes.
_ORDERED_TYPES = frozenset(
    {
        "AutoField",
        "BigAutoField",
        "SmallAutoField",
        "IntegerField",
        "SmallIntegerField",
        "BigIntegerField",
        "PositiveIntegerField",
        "PositiveSmallIntegerField",
        "PositiveBigIntegerField",
        "FloatField",
        "DecimalField",
        "DurationField",
        "DateField",
        "DateTimeField",
        "TimeField",
    }
)


def default_lookups_for(internal_type: str) -> tuple[str, ...]:
    """Return the default lookup set for a field's Django internal type.

    The base set comes from the ``COMMON_FILTER_LOOKUPS`` setting (defaulting
    to :data:`DEFAULT_LOOKUPS`); text fields additionally get
    :data:`TEXT_LOOKUPS` and ordered fields :data:`ORDERED_LOOKUPS`.

    Args:
        internal_type: The field's ``get_internal_type()`` string.

    Returns:
        An ordered, de-duplicated tuple of lookup names.
    """
    base = graphql_api_settings.COMMON_FILTER_LOOKUPS
    lookups: list[str] = list(base if base is not None else DEFAULT_LOOKUPS)
    if internal_type in _TEXT_TYPES:
        lookups += TEXT_LOOKUPS
    elif internal_type in _ORDERED_TYPES:
        lookups += ORDERED_LOOKUPS

    seen: set[str] = set()
    ordered: list[str] = []
    for lookup in lookups:
        if lookup not in seen:
            seen.add(lookup)
            ordered.append(lookup)
    return tuple(ordered)
