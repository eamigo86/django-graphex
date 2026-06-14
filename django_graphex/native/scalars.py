"""Native GraphQL scalar singletons for the output compiler.

7 owned ``GraphQLScalarType`` singletons + ``GDX_SCALAR_MAP``.

CustomDateFormat bypass:
    All three date/time scalars honour a ``CustomDateFormat`` wrapper FIRST —
    if the value is an instance, ``date_str`` is returned verbatim without any
    ISO-format coercion.  This is ported verbatim from
    ``django_graphex.base_types`` (lines 259, 289, 316).

Error contract:
    ``serialize``, ``parse_value``, and ``parse_literal`` raise ``GraphQLError``
    (never ``ValueError`` / ``AssertionError``) on invalid input so callers
    never see a 500.

No imports from ``django`` or ``graphene``.
"""

from __future__ import annotations

import datetime
import decimal
import json
import uuid as _uuid_module
from typing import Any

from graphql import (
    GraphQLBoolean,
    GraphQLError,
    GraphQLFloat,
    GraphQLID,
    GraphQLInt,
    GraphQLScalarType,
    GraphQLString,
)
from graphql.language.ast import (
    BooleanValueNode,
    FloatValueNode,
    IntValueNode,
    NullValueNode,
    StringValueNode,
)


# ---------------------------------------------------------------------------
# CustomDateFormat (owned here, no graphene import)
# ---------------------------------------------------------------------------

class CustomDateFormat:
    """Pre-formatted date/time string bypass wrapper.

    Ported verbatim from ``django_graphex.base_types``.
    When a scalar's ``serialize`` receives an instance of this class it returns
    ``date_str`` immediately, bypassing all ISO-format logic.
    """

    __slots__ = ("date_str",)

    def __init__(self, date: str) -> None:
        self.date_str = date


# ---------------------------------------------------------------------------
# GdxDate
# ---------------------------------------------------------------------------

def _date_serialize(value: Any) -> str:
    if isinstance(value, CustomDateFormat):
        return value.date_str
    try:
        if isinstance(value, datetime.datetime):
            value = value.date()
        if not isinstance(value, datetime.date):
            raise GraphQLError(f"Date cannot represent value: {value!r}")
        return value.isoformat()
    except (ValueError, TypeError) as exc:
        raise GraphQLError(f"Date cannot represent value: {value!r}") from exc


def _date_parse_value(value: Any) -> datetime.date:
    if not isinstance(value, str):
        raise GraphQLError(f"Date cannot represent non-string value: {value!r}")
    try:
        return datetime.date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise GraphQLError(f"Date cannot represent value: {value!r}") from exc


def _date_parse_literal(ast: Any, variable_values: Any = None) -> datetime.date:
    if not isinstance(ast, StringValueNode):
        raise GraphQLError(f"Date cannot represent non-string literal: {ast!r}")
    return _date_parse_value(ast.value)


GdxDate = GraphQLScalarType(
    # GraphQL name MUST match graphene-django's output/input contract. The
    # library uses the ``CustomDate`` graphene subclass (base_types.py), so the
    # rendered scalar name is ``CustomDate`` — NOT ``Date``. (See discovery
    # #1508: probed via print_type under GDX_BACKEND=graphene.)
    name="CustomDate",
    description="ISO 8601 date scalar (YYYY-MM-DD). Supports CustomDateFormat bypass.",
    serialize=_date_serialize,
    parse_value=_date_parse_value,
    parse_literal=_date_parse_literal,
)


# ---------------------------------------------------------------------------
# GdxDateTime
# ---------------------------------------------------------------------------

def _datetime_serialize(value: Any) -> str:
    if isinstance(value, CustomDateFormat):
        return value.date_str
    try:
        if not isinstance(value, (datetime.datetime, datetime.date)):
            raise GraphQLError(f"DateTime cannot represent value: {value!r}")
        return value.isoformat()
    except (ValueError, TypeError) as exc:
        raise GraphQLError(f"DateTime cannot represent value: {value!r}") from exc


def _datetime_parse_value(value: Any) -> datetime.datetime:
    if not isinstance(value, str):
        raise GraphQLError(f"DateTime cannot represent non-string value: {value!r}")
    try:
        return datetime.datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise GraphQLError(f"DateTime cannot represent value: {value!r}") from exc


def _datetime_parse_literal(ast: Any, variable_values: Any = None) -> datetime.datetime:
    if not isinstance(ast, StringValueNode):
        raise GraphQLError(f"DateTime cannot represent non-string literal: {ast!r}")
    return _datetime_parse_value(ast.value)


GdxDateTime = GraphQLScalarType(
    # Matches graphene-django's ``CustomDateTime`` subclass (see #1508).
    name="CustomDateTime",
    description="ISO 8601 datetime scalar. Supports CustomDateFormat bypass.",
    serialize=_datetime_serialize,
    parse_value=_datetime_parse_value,
    parse_literal=_datetime_parse_literal,
)


# ---------------------------------------------------------------------------
# GdxTime
# ---------------------------------------------------------------------------

def _time_serialize(value: Any) -> str:
    if isinstance(value, CustomDateFormat):
        return value.date_str
    try:
        if isinstance(value, datetime.datetime):
            value = value.time()
        if not isinstance(value, datetime.time):
            raise GraphQLError(f"Time cannot represent value: {value!r}")
        return value.isoformat()
    except (ValueError, TypeError) as exc:
        raise GraphQLError(f"Time cannot represent value: {value!r}") from exc


def _time_parse_value(value: Any) -> datetime.time:
    if not isinstance(value, str):
        raise GraphQLError(f"Time cannot represent non-string value: {value!r}")
    try:
        return datetime.time.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise GraphQLError(f"Time cannot represent value: {value!r}") from exc


def _time_parse_literal(ast: Any, variable_values: Any = None) -> datetime.time:
    if not isinstance(ast, StringValueNode):
        raise GraphQLError(f"Time cannot represent non-string literal: {ast!r}")
    return _time_parse_value(ast.value)


GdxTime = GraphQLScalarType(
    # Matches graphene-django's ``CustomTime`` subclass (see #1508).
    name="CustomTime",
    description="ISO 8601 time scalar (HH:MM:SS). Supports CustomDateFormat bypass.",
    serialize=_time_serialize,
    parse_value=_time_parse_value,
    parse_literal=_time_parse_literal,
)


# ---------------------------------------------------------------------------
# Filter-input date scalars (PLAIN names: Date / DateTime / Time)
# ---------------------------------------------------------------------------
#
# graphene-django is INTERNALLY INCONSISTENT on date scalar names (discovery
# #1509): its OUTPUT converter uses the ``CustomDate`` / ``CustomDateTime`` /
# ``CustomTime`` subclasses, but its FILTER-INPUT scalar map
# (filtering/schema.py) uses PLAIN ``graphene.Date`` / ``graphene.DateTime`` /
# ``graphene.Time`` (SDL names ``Date`` / ``DateTime`` / ``Time``). To match
# graphene PER-PATH for full-schema SDL parity (WU10), the native FILTER-INPUT
# map must reference these plain-named singletons — distinct from the
# ``CustomDate``-named OUTPUT singletons above. The serialize/parse behaviour is
# identical; only the GraphQL ``.name`` differs. Reusing the same coercers keeps
# a single source of truth for date/time round-tripping.

GdxFilterDate = GraphQLScalarType(
    name="Date",
    description="ISO 8601 date scalar (YYYY-MM-DD) for filter-input lookups.",
    serialize=_date_serialize,
    parse_value=_date_parse_value,
    parse_literal=_date_parse_literal,
)

GdxFilterDateTime = GraphQLScalarType(
    name="DateTime",
    description="ISO 8601 datetime scalar for filter-input lookups.",
    serialize=_datetime_serialize,
    parse_value=_datetime_parse_value,
    parse_literal=_datetime_parse_literal,
)

GdxFilterTime = GraphQLScalarType(
    name="Time",
    description="ISO 8601 time scalar (HH:MM:SS) for filter-input lookups.",
    serialize=_time_serialize,
    parse_value=_time_parse_value,
    parse_literal=_time_parse_literal,
)


# ---------------------------------------------------------------------------
# GdxDecimal
# ---------------------------------------------------------------------------

def _decimal_serialize(value: Any) -> str:
    if isinstance(value, decimal.Decimal):
        return str(value)
    try:
        return str(decimal.Decimal(value))
    except (decimal.InvalidOperation, ValueError, TypeError) as exc:
        raise GraphQLError(f"Decimal cannot represent value: {value!r}") from exc


def _decimal_parse_value(value: Any) -> decimal.Decimal:
    try:
        return decimal.Decimal(str(value))
    except (decimal.InvalidOperation, ValueError, TypeError) as exc:
        raise GraphQLError(f"Decimal cannot represent value: {value!r}") from exc


def _decimal_parse_literal(ast: Any, variable_values: Any = None) -> decimal.Decimal:
    if isinstance(ast, (StringValueNode, IntValueNode, FloatValueNode)):
        return _decimal_parse_value(ast.value)
    raise GraphQLError(f"Decimal cannot represent non-numeric literal: {ast!r}")


GdxDecimal = GraphQLScalarType(
    # graphene exposes a ``Decimal`` scalar (used by the filter/input path for
    # DecimalField lookups). On OUTPUT, graphene-django collapses DecimalField
    # to ``Float`` (converter.py convert_field_to_float), so this singleton is
    # NOT used by the output compiler — only the input/filter path. (See #1508.)
    name="Decimal",
    description="Arbitrary-precision decimal scalar. Serializes as string.",
    serialize=_decimal_serialize,
    parse_value=_decimal_parse_value,
    parse_literal=_decimal_parse_literal,
)


# ---------------------------------------------------------------------------
# GdxUUID
# ---------------------------------------------------------------------------

def _uuid_serialize(value: Any) -> str:
    if isinstance(value, _uuid_module.UUID):
        return str(value)
    try:
        # Validate by round-tripping through UUID
        return str(_uuid_module.UUID(str(value)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise GraphQLError(f"UUID cannot represent value: {value!r}") from exc


def _uuid_parse_value(value: Any) -> _uuid_module.UUID:
    try:
        return _uuid_module.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise GraphQLError(f"UUID cannot represent value: {value!r}") from exc


def _uuid_parse_literal(ast: Any, variable_values: Any = None) -> _uuid_module.UUID:
    if not isinstance(ast, StringValueNode):
        raise GraphQLError(f"UUID cannot represent non-string literal: {ast!r}")
    return _uuid_parse_value(ast.value)


GdxUUID = GraphQLScalarType(
    # Matches graphene's ``UUID`` scalar name (see #1508).
    name="UUID",
    description="UUID scalar. Serializes as lowercase hyphenated string.",
    serialize=_uuid_serialize,
    parse_value=_uuid_parse_value,
    parse_literal=_uuid_parse_literal,
)


# ---------------------------------------------------------------------------
# GdxJSONString
# ---------------------------------------------------------------------------

def _json_serialize(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise GraphQLError(f"JSONString cannot represent value: {value!r}") from exc


def _json_parse_value(value: Any) -> Any:
    if not isinstance(value, str):
        raise GraphQLError(f"JSONString cannot represent non-string value: {value!r}")
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise GraphQLError(f"JSONString cannot parse: {value!r}") from exc


def _json_parse_literal(ast: Any, variable_values: Any = None) -> Any:
    if not isinstance(ast, StringValueNode):
        raise GraphQLError(f"JSONString cannot represent non-string literal: {ast!r}")
    return _json_parse_value(ast.value)


GdxJSONString = GraphQLScalarType(
    # Matches graphene's ``JSONString`` scalar name (see #1508).
    name="JSONString",
    description="Arbitrary JSON scalar. Serializes Python objects as JSON strings.",
    serialize=_json_serialize,
    parse_value=_json_parse_value,
    parse_literal=_json_parse_literal,
)


# ---------------------------------------------------------------------------
# GdxGenericScalar
# ---------------------------------------------------------------------------

def _generic_serialize(value: Any) -> Any:
    return value


def _generic_parse_value(value: Any) -> Any:
    return value


def _generic_parse_literal(ast: Any, variable_values: Any = None) -> Any:
    if isinstance(ast, StringValueNode):
        return ast.value
    if isinstance(ast, IntValueNode):
        return int(ast.value)
    if isinstance(ast, FloatValueNode):
        return float(ast.value)
    if isinstance(ast, BooleanValueNode):
        return ast.value
    if isinstance(ast, NullValueNode):
        return None
    raise GraphQLError(f"GenericScalar cannot represent literal: {ast!r}")


GdxGenericScalar = GraphQLScalarType(
    # Matches graphene's ``GenericScalar`` name (see #1508).
    name="GenericScalar",
    description="Generic scalar: passes values through as-is. Accepts any JSON-compatible type.",
    serialize=_generic_serialize,
    parse_value=_generic_parse_value,
    parse_literal=_generic_parse_literal,
)


# ---------------------------------------------------------------------------
# GDX_SCALAR_MAP — 7 custom + 5 graphql-core builtins
# ---------------------------------------------------------------------------

# Keys are the GraphQL scalar NAMES as graphene renders them — this is what
# ``_unwrap_graphene_type`` looks up via ``gtype._meta.name`` and what the
# native compiler seeds into ``_TYPE_CACHE``. The Python symbol names keep the
# ``Gdx`` prefix (so callers importing ``GdxDate`` etc. are unaffected); only the
# GraphQL ``.name`` and these map KEYS match graphene. (See #1508.)
GDX_SCALAR_MAP: dict[str, GraphQLScalarType] = {
    # Custom singletons (keyed by graphene scalar name)
    "CustomDate": GdxDate,
    "CustomDateTime": GdxDateTime,
    "CustomTime": GdxTime,
    "Decimal": GdxDecimal,
    "UUID": GdxUUID,
    "JSONString": GdxJSONString,
    "GenericScalar": GdxGenericScalar,
    # graphql-core builtins
    "String": GraphQLString,
    "Int": GraphQLInt,
    "Float": GraphQLFloat,
    "Boolean": GraphQLBoolean,
    "ID": GraphQLID,
}
