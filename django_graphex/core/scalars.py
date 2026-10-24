"""Native GraphQL scalar singletons for the output compiler.

8 globally mapped "GraphQLScalarType" singletons, one direct-input-only
"IntOrString" singleton, plus "GDX_SCALAR_MAP".

CustomDateFormat bypass:
    All three date/time scalars honour a "CustomDateFormat" wrapper FIRST —
    if the value is an instance, "date_str" is returned verbatim without any
    ISO-format coercion. This is ported verbatim from
    "django_graphex.base_types" (lines 259, 289, 316).

Error contract:
    "serialize", "parse_value", and "parse_literal" raise "GraphQLError"
    (never "ValueError" / "AssertionError") on invalid input so callers
    never see a 500.

No imports from "django" or "graphene".
"""

from __future__ import annotations

import datetime
import decimal
import json
import re
import uuid as _uuid_module
from math import isfinite
from typing import Any

from graphql import (
    GraphQLBoolean,
    GraphQLError,
    GraphQLFloat,
    GraphQLID,
    GraphQLInt,
    GraphQLScalarType,
    GraphQLString,
    Undefined,
)
from graphql.language.ast import (
    BooleanValueNode,
    FloatValueNode,
    IntValueNode,
    ListValueNode,
    NameNode,
    NullValueNode,
    ObjectFieldNode,
    ObjectValueNode,
    StringValueNode,
    VariableNode,
)

# ---------------------------------------------------------------------------
# CustomDateFormat (owned here, no graphene import)
# ---------------------------------------------------------------------------


class CustomDateFormat:
    """Pre-formatted date/time string bypass wrapper.

    Ported verbatim from "django_graphex.base_types". When a scalar's
    "serialize" receives an instance of this class it returns "date_str"
    immediately, bypassing all ISO-format logic.
    """

    __slots__ = ("date_str",)

    def __init__(self, date: str) -> None:
        """Wrap a pre-formatted date/time string for serialize bypass.

        Args:
            date: The already-formatted date/time string a scalar's
                "serialize" returns verbatim (no ISO-format pass).
        """
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
    # GraphQL name MUST match graphene-django's historical output/input contract:
    # the rendered scalar name is ``CustomDate`` — NOT ``Date``. (See discovery
    # #1508.)
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
    # "f" keeps the stored scale but never switches to scientific notation
    # ("0E-8", "5.0E-7"), which str() does for small exponents.
    if isinstance(value, decimal.Decimal):
        return format(value, "f")
    try:
        return format(decimal.Decimal(value), "f")
    except (decimal.InvalidOperation, ValueError, TypeError) as exc:
        raise GraphQLError(f"Decimal cannot represent value: {value!r}") from exc


def _decimal_parse_value(value: Any) -> decimal.Decimal:
    try:
        parsed = decimal.Decimal(str(value))
    except (decimal.InvalidOperation, ValueError, TypeError) as exc:
        raise GraphQLError(f"Decimal cannot represent value: {value!r}") from exc
    # NaN and the infinities parse as Decimals but no column can hold them, and
    # reaching the ORM they surface as Django's unformatted validation message.
    if not parsed.is_finite():
        raise GraphQLError(f"Decimal cannot be a nonfinite Decimal: {value!r}")
    return parsed


def _decimal_parse_literal(ast: Any, variable_values: Any = None) -> decimal.Decimal:
    if isinstance(ast, (StringValueNode, IntValueNode, FloatValueNode)):
        return _decimal_parse_value(ast.value)
    raise GraphQLError(f"Decimal cannot represent non-numeric literal: {ast!r}")


GdxDecimal = GraphQLScalarType(
    # Share one Decimal scalar across automatically derived DecimalField output,
    # generated mutation input, and filter lookup values. Historical
    # graphene-django output used Float; the approved native output default
    # now serializes exact decimal text through this singleton.
    name="Decimal",
    description="Arbitrary-precision decimal scalar. Serializes as string.",
    serialize=_decimal_serialize,
    parse_value=_decimal_parse_value,
    parse_literal=_decimal_parse_literal,
)


# ---------------------------------------------------------------------------
# GdxBigInt
# ---------------------------------------------------------------------------


_BIGINT_MIN = -(1 << 63)
_BIGINT_MAX = (1 << 63) - 1


def _bigint_serialize(value: Any) -> str:
    """Serialize a signed 64-bit integer as a canonical decimal string.

    Args:
        value: Python integer returned by a Django BigInteger field.

    Returns:
        The exact decimal string used on the GraphQL wire.

    Raises:
        GraphQLError: If the value is not a signed 64-bit integer.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise GraphQLError(f"BigInt cannot represent value: {value!r}")
    if not _BIGINT_MIN <= value <= _BIGINT_MAX:
        raise GraphQLError(f"BigInt cannot represent out-of-range value: {value!r}")
    return str(value)


def _bigint_parse_value(value: Any) -> int:
    """Parse a bounded canonical ASCII decimal string to a Python integer.

    Args:
        value: GraphQL variable or string literal value.

    Returns:
        The exact signed 64-bit Python integer.

    Raises:
        GraphQLError: If the value is non-string, malformed, or out of range.
    """
    if not isinstance(value, str) or not 1 <= len(value) <= 20:
        raise GraphQLError("BigInt requires a decimal string of at most 20 characters")
    digits = value[1:] if value.startswith("-") else value
    if (
        not digits
        or any(char < "0" or char > "9" for char in digits)
        or (len(digits) > 1 and digits.startswith("0"))
        or value == "-0"
    ):
        raise GraphQLError(f"BigInt requires a canonical decimal string: {value!r}")
    parsed = int(value)
    if not _BIGINT_MIN <= parsed <= _BIGINT_MAX:
        raise GraphQLError(f"BigInt is outside the signed 64-bit range: {value!r}")
    return parsed


def _bigint_parse_literal(ast: Any, variable_values: Any = None) -> int:
    """Parse only GraphQL string literals, never numeric literals.

    Args:
        ast: GraphQL value node supplied by the query document.
        variable_values: Unused GraphQL parser compatibility argument.

    Returns:
        The exact signed 64-bit Python integer.

    Raises:
        GraphQLError: If the node is not a valid BigInt string literal.
    """
    if not isinstance(ast, StringValueNode):
        raise GraphQLError(f"BigInt requires a string literal: {ast!r}")
    return _bigint_parse_value(ast.value)


GdxBigInt = GraphQLScalarType(
    name="BigInt",
    description="Signed 64-bit integer serialized and parsed as a decimal string.",
    serialize=_bigint_serialize,
    parse_value=_bigint_parse_value,
    parse_literal=_bigint_parse_literal,
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
        # Passthrough ONLY for text that is already valid JSON; a plain string
        # ("hello") must be encoded, otherwise the scalar emits something its
        # own ``parse_value`` cannot decode.
        try:
            json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass
        else:
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
# GdxJSON — RAW structured-JSON scalar (the v2 default JSON contract)
# ---------------------------------------------------------------------------


def _reject_nonfinite_json_input(value: Any) -> Any:
    """Reject non-finite floats in raw JSON input without copying it.

    Only built-in JSON containers are traversed. Other native Python values
    retain the scalar's existing input identity behavior.

    Args:
        value: Raw input value to inspect.

    Returns:
        The original value when no non-finite float is found.

    Raises:
        GraphQLError: If the input is or contains a non-finite float.
    """
    pending = [value]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if isinstance(current, float) and not isfinite(current):
            raise GraphQLError("JSON cannot represent non-finite numbers")
        if type(current) is list or type(current) is dict:
            identity = id(current)
            if identity in visited:
                continue
            visited.add(identity)
            pending.extend(current.values() if type(current) is dict else current)
    return value


def _json_raw_serialize(value: Any) -> Any:
    """Return an output value unchanged unless it holds a non-finite float.

    NaN and the infinities have no JSON representation, so emitting them would
    make the whole response invalid for strict parsers.

    Args:
        value: The resolved value to serialize.

    Returns:
        The original value.

    Raises:
        GraphQLError: If the value is or contains a non-finite float.
    """
    return _reject_nonfinite_json_input(value)


def _json_raw_parse_value(value: Any) -> Any:
    return _reject_nonfinite_json_input(value)


def _json_raw_parse_literal(ast: Any, variable_values: Any = None) -> Any:
    """Parse a GraphQL literal AST node into its raw Python JSON value.

    Recurses "ObjectValueNode" / "ListValueNode" so an inline object or list
    literal ("{a: 1, nested: [1, 2]}") becomes a real "dict" / "list" —
    mirroring graphene's "GenericScalar.parse_literal" semantics. Nested
    "VariableNode" references resolve against "variable_values".

    An unavailable nested variable returns graphql "Undefined" rather than
    raising, so validation without variable values does not reject a valid
    document. Inside a list, that sentinel becomes None to preserve the list
    slot as JSON null. Inside an object, its field is omitted instead. A
    top-level unavailable variable still returns "Undefined" to its caller.

    Args:
        ast: The GraphQL literal AST node to convert.
        variable_values: Mapping of variable name to value, or None when the
            caller (e.g. validation) has no variables available.

    Returns:
        The raw Python JSON value for "ast", or graphql "Undefined" when "ast"
        is itself a variable whose value is unavailable.

    Raises:
        GraphQLError: If the literal is unsupported or contains a non-finite float.
    """
    if isinstance(ast, StringValueNode):
        return ast.value
    if isinstance(ast, IntValueNode):
        return int(ast.value)
    if isinstance(ast, FloatValueNode):
        return _reject_nonfinite_json_input(float(ast.value))
    if isinstance(ast, BooleanValueNode):
        return ast.value
    if isinstance(ast, NullValueNode):
        return None
    if isinstance(ast, ListValueNode):
        values = []
        for item in ast.values:
            value = _json_raw_parse_literal(item, variable_values)
            values.append(None if value is Undefined else value)
        return values
    if isinstance(ast, ObjectValueNode):
        # An unavailable variable OMITS its field (graphql-core's own
        # ``value_from_ast`` does the same), so the ``Undefined`` sentinel never
        # reaches a resolver or the JSON encoder.
        parsed = (
            (field.name.value, _json_raw_parse_literal(field.value, variable_values))
            for field in ast.fields
        )
        return {key: value for key, value in parsed if value is not Undefined}
    if isinstance(ast, VariableNode):
        name = ast.name.value
        if variable_values is None or name not in variable_values:
            return Undefined
        return _reject_nonfinite_json_input(variable_values[name])
    raise GraphQLError(f"JSON cannot represent literal: {ast!r}")


_GRAPHQL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _json_raw_value_to_literal(value: Any) -> Any:
    """Represent a JSON value as a GraphQL literal when possible.

    Args:
        value: Value to represent without changing the original object.

    Returns:
        A constant value node, or None for an ineligible value.
    """
    active: set[int] = set()

    def convert(item: Any) -> Any:
        if item is None:
            return NullValueNode()
        if type(item) is bool:
            return BooleanValueNode(value=item)
        if type(item) is str:
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                return None
            return StringValueNode(value=item)
        if type(item) is int:
            try:
                return IntValueNode(value=str(item))
            except ValueError:
                return None
        if type(item) is float:
            return FloatValueNode(value=str(item)) if isfinite(item) else None
        if type(item) not in (list, dict):
            return None
        identity = id(item)
        if identity in active:
            return None
        active.add(identity)
        try:
            if type(item) is list:
                values = [convert(child) for child in item]
                if any(child is None for child in values):
                    return None
                return ListValueNode(values=tuple(values))
            fields = []
            for key, child in item.items():
                if type(key) is not str or _GRAPHQL_NAME.fullmatch(key) is None:
                    return None
                node = convert(child)
                if node is None:
                    return None
                fields.append(ObjectFieldNode(name=NameNode(value=key), value=node))
            return ObjectValueNode(fields=tuple(fields))
        finally:
            active.remove(identity)

    try:
        return convert(value)
    except (RecursionError, OverflowError):
        return None


GdxJSON = GraphQLScalarType(
    # The RAW structured-JSON scalar. v2 renders model ``JSONField``s (and the
    # default ``JSONField()`` descriptor) as this by design — objects / lists /
    # scalars pass through structurally, WITHOUT the string-encoding of the
    # ``JSONString`` escape hatch. The SDL name is DELIBERATELY ``JSON`` (a
    # documented divergence from graphene's ``GenericScalar``; see #1508).
    name="JSON",
    description=(
        "Arbitrary JSON value. Objects, lists, and scalars are passed through "
        "structurally (no string encoding)."
    ),
    serialize=_json_raw_serialize,
    parse_value=_json_raw_parse_value,
    parse_literal=_json_raw_parse_literal,
    value_to_literal=_json_raw_value_to_literal,
)


def _int_or_string_parse_value(value: Any) -> int | str:
    """Accept an unconverted native integer or string input.

    Args:
        value: Supplied GraphQL variable value.

    Returns:
        The original integer or string.

    Raises:
        GraphQLError: If the value is not an Int32 integer or string.
    """
    if type(value) is str or (type(value) is int and -(2**31) <= value < 2**31):
        return value
    raise GraphQLError(f"IntOrString cannot represent value: {value!r}")


def _int_or_string_parse_literal(ast: Any, variable_values: Any = None) -> int | str:
    """Parse only native GraphQL integer and string literal nodes.

    Args:
        ast: Supplied GraphQL literal node.
        variable_values: Unused variable values supplied by graphql-core.

    Returns:
        The parsed integer or string without cross-branch conversion.

    Raises:
        GraphQLError: If the literal has an unsupported kind or integer range.
    """
    if isinstance(ast, StringValueNode):
        return ast.value
    if isinstance(ast, IntValueNode):
        return _int_or_string_parse_value(int(ast.value))
    raise GraphQLError(f"IntOrString cannot represent literal: {ast!r}")


IntOrString = GraphQLScalarType(
    name="IntOrString",
    description="A string or signed 32-bit integer, without implicit conversion.",
    serialize=_int_or_string_parse_value,
    parse_value=_int_or_string_parse_value,
    parse_literal=_int_or_string_parse_literal,
)


# ---------------------------------------------------------------------------
# GDX_SCALAR_MAP — 8 custom singletons (9 keys: JSON has a legacy alias) + 5
# graphql-core builtins
# ---------------------------------------------------------------------------

# Keys are the GraphQL scalar NAMES as graphene renders them — this is what
# ``_unwrap_graphql_type`` looks up via ``gtype._meta.name`` and what the
# native compiler seeds into ``_TYPE_CACHE``. The Python symbol names keep the
# ``Gdx`` prefix (so callers importing ``GdxDate`` etc. are unaffected); only the
# GraphQL ``.name`` and these map KEYS match graphene. (See #1508.)
GDX_SCALAR_MAP: dict[str, GraphQLScalarType] = {
    # Custom singletons (keyed by graphene scalar name)
    "CustomDate": GdxDate,
    "CustomDateTime": GdxDateTime,
    "CustomTime": GdxTime,
    "Decimal": GdxDecimal,
    "BigInt": GdxBigInt,
    "UUID": GdxUUID,
    "JSONString": GdxJSONString,
    # The RAW JSON scalar is reachable under BOTH keys: the canonical ``JSON``
    # key AND the legacy ``GenericScalar`` key (kept so graphene-class forwarding
    # via ``schema.py`` — which looks up by the old graphene ``.name`` — keeps
    # resolving). Both alias the single ``GdxJSON`` singleton (SDL name ``JSON``).
    "JSON": GdxJSON,
    "GenericScalar": GdxJSON,
    # graphql-core builtins
    "String": GraphQLString,
    "Int": GraphQLInt,
    "Float": GraphQLFloat,
    "Boolean": GraphQLBoolean,
    "ID": GraphQLID,
}
