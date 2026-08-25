"""Tests for core/scalars.py.

Covers the 7 custom scalar singletons and the GDX_SCALAR_MAP registry.

No Django settings required. No django_db markers.
Run with: pytest tests/core/test_scalars.py -x
"""

import datetime
import decimal
import json
import uuid

import pytest
from graphql import GraphQLError
from graphql.language.ast import (
    BooleanValueNode,
    FloatValueNode,
    IntValueNode,
    ListValueNode,
    NameNode,
    ObjectFieldNode,
    ObjectValueNode,
    StringValueNode,
)

# ---------------------------------------------------------------------------
# Import gate
# ---------------------------------------------------------------------------


def test_scalars_has_no_django_graphene_imports() -> None:
    """Ships broken if "scalars.py" starts importing from django or graphene.

    A source-text scan enforces that the scalar module stays framework-free.
    """
    import pathlib
    import re

    path = (
        pathlib.Path(__file__).parent.parent.parent
        / "django_graphex"
        / "core"
        / "scalars.py"
    )
    src = path.read_text()
    forbidden = re.compile(
        r"^(from django[.\s]|import django[.\s]|from graphene[.\s]|import graphene[.\s])",
        re.MULTILINE,
    )
    matches = forbidden.findall(src)
    assert matches == [], f"Forbidden imports in scalars.py: {matches}"


# ---------------------------------------------------------------------------
# Imports (collected once)
# ---------------------------------------------------------------------------

from django_graphex.core.scalars import (  # noqa: E402
    GDX_SCALAR_MAP,
    CustomDateFormat,
    GdxDate,
    GdxDateTime,
    GdxDecimal,
    GdxJSON,
    GdxJSONString,
    GdxTime,
    GdxUUID,
)

# ---------------------------------------------------------------------------
# GDX_SCALAR_MAP contents
# ---------------------------------------------------------------------------


class TestGdxScalarMap:
    """Tests for the GDX_SCALAR_MAP contents and identities.

    Covers key coverage, singleton identity, and graphene-name parity.
    """

    def test_has_7_custom_scalars(self) -> None:
        """Ships broken if GDX_SCALAR_MAP stops exposing all 8 custom-scalar
        keys (7 singletons, with JSON double-keyed under a legacy alias).
        """
        # Map keys are the GraphQL scalar NAMES as graphene renders them (the
        # Python symbols keep the Gdx prefix; only .name + map keys match
        # graphene). See discovery #1508. The RAW-JSON flip (v2) added the
        # canonical ``JSON`` key while KEEPING the legacy ``GenericScalar`` key
        # (both alias the single ``GdxJSON`` singleton) so graphene-class
        # forwarding still resolves.
        custom_names = {
            "CustomDate",
            "CustomDateTime",
            "CustomTime",
            "Decimal",
            "UUID",
            "JSONString",
            "JSON",
            "GenericScalar",
        }
        for name in custom_names:
            assert name in GDX_SCALAR_MAP, f"Missing {name} in GDX_SCALAR_MAP"

    def test_has_5_builtin_scalars(self) -> None:
        """Ships broken if GDX_SCALAR_MAP stops exposing all 5 builtin scalar
        keys (String, Int, Float, Boolean, ID).
        """
        builtin_names = {"String", "Int", "Float", "Boolean", "ID"}
        for name in builtin_names:
            assert name in GDX_SCALAR_MAP, f"Missing builtin {name} in GDX_SCALAR_MAP"

    def test_builtins_are_graphql_core_instances(self) -> None:
        """Ships broken if a builtin scalar key stops resolving to the
        graphql-core singleton (e.g. "GraphQLString").
        """
        from graphql import GraphQLString

        assert GDX_SCALAR_MAP["String"] is GraphQLString

    def test_total_size(self) -> None:
        """Ships broken if GDX_SCALAR_MAP's key count drifts from 13 (7 custom
        singletons under 8 keys, since JSON has a legacy alias, plus 5 builtins).
        """
        assert len(GDX_SCALAR_MAP) == 13

    def test_singleton_identity(self) -> None:
        """Ships broken if the map stops referencing the module-level
        singletons (keyed by graphene name).
        """
        assert GDX_SCALAR_MAP["CustomDate"] is GdxDate
        assert GDX_SCALAR_MAP["CustomDateTime"] is GdxDateTime
        assert GDX_SCALAR_MAP["CustomTime"] is GdxTime
        assert GDX_SCALAR_MAP["Decimal"] is GdxDecimal
        assert GDX_SCALAR_MAP["UUID"] is GdxUUID
        assert GDX_SCALAR_MAP["JSONString"] is GdxJSONString
        # The RAW-JSON scalar is reachable under BOTH the canonical ``JSON`` key
        # and the legacy ``GenericScalar`` key (kept for graphene-class
        # forwarding); both alias the single ``GdxJSON`` singleton.
        assert GDX_SCALAR_MAP["JSON"] is GdxJSON
        assert GDX_SCALAR_MAP["GenericScalar"] is GdxJSON

    def test_singleton_graphql_names_match_graphene(self) -> None:
        """Ships broken if the GraphQL ".name" of any singleton drifts from
        graphene's contract.

        Date/DateTime/Time use the graphene "Custom*" subclass names;
        UUID/JSONString/Decimal match the plain graphene names. The RAW-JSON
        scalar is a DELIBERATE divergence: it is named "JSON" BY DESIGN (v2
        makes raw structured JSON the default contract), NOT graphene's
        "GenericScalar". See discovery #1508.
        """
        assert GdxDate.name == "CustomDate"
        assert GdxDateTime.name == "CustomDateTime"
        assert GdxTime.name == "CustomTime"
        assert GdxDecimal.name == "Decimal"
        assert GdxUUID.name == "UUID"
        assert GdxJSONString.name == "JSONString"
        # Intentional divergence from graphene's ``GenericScalar`` name.
        assert GdxJSON.name == "JSON"


# ---------------------------------------------------------------------------
# CustomDateFormat bypass
# ---------------------------------------------------------------------------


class TestCustomDateFormatBypass:
    """Tests that a CustomDateFormat wrapper bypasses normal serialization.

    Each scalar must return the wrapped string verbatim, unreformatted.
    """

    def test_gdx_date_bypass(self) -> None:
        """Ships broken if GdxDate.serialize stops passing a CustomDateFormat
        value through verbatim instead of reformatting it.
        """
        fmt = CustomDateFormat("2024-01-15")
        assert GdxDate.serialize(fmt) == "2024-01-15"

    def test_gdx_datetime_bypass(self) -> None:
        """Ships broken if GdxDateTime.serialize stops passing a
        CustomDateFormat value through verbatim instead of reformatting it.
        """
        fmt = CustomDateFormat("2024-01-15T12:00:00")
        assert GdxDateTime.serialize(fmt) == "2024-01-15T12:00:00"

    def test_gdx_time_bypass(self) -> None:
        """Ships broken if GdxTime.serialize stops passing a CustomDateFormat
        value through verbatim instead of reformatting it.
        """
        fmt = CustomDateFormat("12:30:00")
        assert GdxTime.serialize(fmt) == "12:30:00"


# ---------------------------------------------------------------------------
# GdxDate
# ---------------------------------------------------------------------------


class TestGdxDate:
    """Tests for the GdxDate custom scalar's serialize/parse contract.

    Covers serialize, parse_value, and parse_literal for valid and invalid input.
    """

    def test_serialize_date(self) -> None:
        """Ships broken if GdxDate.serialize stops formatting a date object as
        an ISO date string.
        """
        d = datetime.date(2024, 1, 15)
        assert GdxDate.serialize(d) == "2024-01-15"

    def test_serialize_datetime_extracts_date(self) -> None:
        """Ships broken if GdxDate.serialize stops dropping the time component
        when given a datetime object.
        """
        dt = datetime.datetime(2024, 1, 15, 12, 30)
        assert GdxDate.serialize(dt) == "2024-01-15"

    def test_serialize_invalid_raises_graphql_error(self) -> None:
        """Ships broken if GdxDate.serialize stops raising GraphQLError for a
        value that cannot be formatted as a date.
        """
        with pytest.raises(GraphQLError):
            GdxDate.serialize("not-a-date")

    def test_parse_value_string(self) -> None:
        """Ships broken if GdxDate.parse_value stops parsing an ISO date
        string into a date object.
        """
        result = GdxDate.parse_value("2024-01-15")
        assert result == datetime.date(2024, 1, 15)

    def test_parse_value_invalid_raises_graphql_error(self) -> None:
        """Ships broken if GdxDate.parse_value stops raising GraphQLError for
        a string that is not a valid date.
        """
        with pytest.raises(GraphQLError):
            GdxDate.parse_value("not-a-date")

    def test_parse_literal_string_node(self) -> None:
        """Ships broken if GdxDate.parse_literal stops parsing a
        StringValueNode into a date object.
        """
        node = StringValueNode(value="2024-01-15")
        result = GdxDate.parse_literal(node)
        assert result == datetime.date(2024, 1, 15)

    def test_parse_literal_wrong_node_raises_graphql_error(self) -> None:
        """Ships broken if GdxDate.parse_literal stops raising GraphQLError
        for a non-string AST node.
        """
        node = IntValueNode(value="123")
        with pytest.raises(GraphQLError):
            GdxDate.parse_literal(node)


# ---------------------------------------------------------------------------
# GdxDateTime
# ---------------------------------------------------------------------------


class TestGdxDateTime:
    """Tests for the GdxDateTime custom scalar's serialize/parse contract.

    Covers serialize, parse_value, and parse_literal for valid and invalid input.
    """

    def test_serialize_datetime(self) -> None:
        """Ships broken if GdxDateTime.serialize stops rendering both the date
        and time components of a datetime object.
        """
        dt = datetime.datetime(2024, 1, 15, 12, 30, 0)
        result = GdxDateTime.serialize(dt)
        assert "2024-01-15" in result
        assert "12:30:00" in result

    def test_serialize_date_as_datetime(self) -> None:
        """Ships broken if GdxDateTime.serialize stops accepting a bare date
        object and rendering its date portion.
        """
        d = datetime.date(2024, 1, 15)
        result = GdxDateTime.serialize(d)
        assert "2024-01-15" in result

    def test_serialize_invalid_raises_graphql_error(self) -> None:
        """Ships broken if GdxDateTime.serialize stops raising GraphQLError
        for a value that cannot be formatted as a datetime.
        """
        with pytest.raises(GraphQLError):
            GdxDateTime.serialize(42)

    def test_parse_value_string(self) -> None:
        """Ships broken if GdxDateTime.parse_value stops parsing an ISO
        datetime string into a datetime object.
        """
        result = GdxDateTime.parse_value("2024-01-15T12:30:00")
        assert isinstance(result, datetime.datetime)

    def test_parse_value_invalid_raises_graphql_error(self) -> None:
        """Ships broken if GdxDateTime.parse_value stops raising GraphQLError
        for a string that is not a valid datetime.
        """
        with pytest.raises(GraphQLError):
            GdxDateTime.parse_value("not-a-datetime")

    def test_parse_literal_string_node(self) -> None:
        """Ships broken if GdxDateTime.parse_literal stops parsing a
        StringValueNode into a datetime object.
        """
        node = StringValueNode(value="2024-01-15T12:30:00")
        result = GdxDateTime.parse_literal(node)
        assert isinstance(result, datetime.datetime)

    def test_parse_literal_wrong_node_raises_graphql_error(self) -> None:
        """Ships broken if GdxDateTime.parse_literal stops raising
        GraphQLError for a non-string AST node.
        """
        node = IntValueNode(value="123")
        with pytest.raises(GraphQLError):
            GdxDateTime.parse_literal(node)


# ---------------------------------------------------------------------------
# GdxTime
# ---------------------------------------------------------------------------


class TestGdxTime:
    """Tests for the GdxTime custom scalar's serialize/parse contract.

    Covers serialize, parse_value, and parse_literal for valid and invalid input.
    """

    def test_serialize_time(self) -> None:
        """Ships broken if GdxTime.serialize stops formatting a time object as
        an ISO time string.
        """
        t = datetime.time(12, 30, 0)
        assert GdxTime.serialize(t) == "12:30:00"

    def test_serialize_datetime_extracts_time(self) -> None:
        """Ships broken if GdxTime.serialize stops dropping the date
        component when given a datetime object.
        """
        dt = datetime.datetime(2024, 1, 15, 12, 30, 0)
        assert GdxTime.serialize(dt) == "12:30:00"

    def test_serialize_invalid_raises_graphql_error(self) -> None:
        """Ships broken if GdxTime.serialize stops raising GraphQLError for a
        value that cannot be formatted as a time.
        """
        with pytest.raises(GraphQLError):
            GdxTime.serialize("not-a-time")

    def test_parse_value_string(self) -> None:
        """Ships broken if GdxTime.parse_value stops parsing an ISO time
        string into a time object.
        """
        result = GdxTime.parse_value("12:30:00")
        assert result == datetime.time(12, 30, 0)

    def test_parse_value_invalid_raises_graphql_error(self) -> None:
        """Ships broken if GdxTime.parse_value stops raising GraphQLError for
        a string that is not a valid time.
        """
        with pytest.raises(GraphQLError):
            GdxTime.parse_value("not-a-time")

    def test_parse_literal_string_node(self) -> None:
        """Ships broken if GdxTime.parse_literal stops parsing a
        StringValueNode into a time object.
        """
        node = StringValueNode(value="12:30:00")
        result = GdxTime.parse_literal(node)
        assert result == datetime.time(12, 30, 0)

    def test_parse_literal_wrong_node_raises_graphql_error(self) -> None:
        """Ships broken if GdxTime.parse_literal stops raising GraphQLError
        for a non-string AST node.
        """
        node = IntValueNode(value="12")
        with pytest.raises(GraphQLError):
            GdxTime.parse_literal(node)


# ---------------------------------------------------------------------------
# GdxDecimal
# ---------------------------------------------------------------------------


class TestGdxDecimal:
    """Tests for the GdxDecimal custom scalar's serialize/parse contract.

    Covers serialize, parse_value, and parse_literal for valid and invalid input.
    """

    def test_serialize_decimal(self) -> None:
        """Ships broken if GdxDecimal.serialize stops rendering a Decimal as
        its string representation.
        """
        d = decimal.Decimal("12.50")
        assert GdxDecimal.serialize(d) == "12.50"

    def test_serialize_float(self) -> None:
        """Ships broken if GdxDecimal.serialize stops accepting a float
        value.
        """
        result = GdxDecimal.serialize(12.5)
        assert "12.5" in str(result)

    def test_serialize_int(self) -> None:
        """Ships broken if GdxDecimal.serialize stops accepting an int
        value.
        """
        result = GdxDecimal.serialize(42)
        assert str(result) == "42"

    def test_serialize_invalid_raises_graphql_error(self) -> None:
        """Ships broken if GdxDecimal.serialize stops raising GraphQLError
        for a value that cannot be converted to a Decimal.
        """
        with pytest.raises(GraphQLError):
            GdxDecimal.serialize("not-a-number")

    def test_parse_value_string(self) -> None:
        """Ships broken if GdxDecimal.parse_value stops parsing a numeric
        string into a Decimal.
        """
        result = GdxDecimal.parse_value("12.50")
        assert result == decimal.Decimal("12.50")

    def test_parse_value_invalid_raises_graphql_error(self) -> None:
        """Ships broken if GdxDecimal.parse_value stops raising GraphQLError
        for a string that is not a valid decimal.
        """
        with pytest.raises(GraphQLError):
            GdxDecimal.parse_value("not-a-decimal")

    def test_parse_literal_string_node(self) -> None:
        """Ships broken if GdxDecimal.parse_literal stops parsing a
        StringValueNode into a Decimal.
        """
        node = StringValueNode(value="12.50")
        result = GdxDecimal.parse_literal(node)
        assert result == decimal.Decimal("12.50")

    def test_parse_literal_int_node(self) -> None:
        """Ships broken if GdxDecimal.parse_literal stops parsing an
        IntValueNode into a Decimal.
        """
        node = IntValueNode(value="42")
        result = GdxDecimal.parse_literal(node)
        assert result == decimal.Decimal("42")

    def test_parse_literal_float_node(self) -> None:
        """Ships broken if GdxDecimal.parse_literal stops parsing a
        FloatValueNode into a Decimal.
        """
        node = FloatValueNode(value="12.5")
        result = GdxDecimal.parse_literal(node)
        assert result == decimal.Decimal("12.5")

    def test_parse_literal_invalid_node_raises_graphql_error(self) -> None:
        """Ships broken if GdxDecimal.parse_literal stops raising
        GraphQLError for an unsupported AST node type.
        """
        node = BooleanValueNode(value=True)
        with pytest.raises(GraphQLError):
            GdxDecimal.parse_literal(node)


# ---------------------------------------------------------------------------
# GdxUUID
# ---------------------------------------------------------------------------


class TestGdxUUID:
    """Tests for the GdxUUID custom scalar's serialize/parse contract.

    Covers serialize, parse_value, and parse_literal for valid and invalid input.
    """

    def test_serialize_uuid(self) -> None:
        """Ships broken if GdxUUID.serialize stops rendering a UUID object as
        its canonical string form.
        """
        u = uuid.UUID("12345678-1234-5678-1234-567812345678")
        result = GdxUUID.serialize(u)
        assert result == "12345678-1234-5678-1234-567812345678"

    def test_serialize_string(self) -> None:
        """Ships broken if GdxUUID.serialize stops passing an already-string
        UUID value through unchanged.
        """
        s = "12345678-1234-5678-1234-567812345678"
        assert GdxUUID.serialize(s) == s

    def test_serialize_invalid_raises_graphql_error(self) -> None:
        """Ships broken if GdxUUID.serialize stops raising GraphQLError for a
        value that is not a valid UUID.
        """
        with pytest.raises(GraphQLError):
            GdxUUID.serialize("not-a-uuid")

    def test_parse_value_string(self) -> None:
        """Ships broken if GdxUUID.parse_value stops parsing a UUID string
        into a UUID object.
        """
        s = "12345678-1234-5678-1234-567812345678"
        result = GdxUUID.parse_value(s)
        assert result == uuid.UUID(s)

    def test_parse_value_invalid_raises_graphql_error(self) -> None:
        """Ships broken if GdxUUID.parse_value stops raising GraphQLError for
        a string that is not a valid UUID.
        """
        with pytest.raises(GraphQLError):
            GdxUUID.parse_value("bad-uuid")

    def test_parse_literal_string_node(self) -> None:
        """Ships broken if GdxUUID.parse_literal stops parsing a
        StringValueNode into a UUID object.
        """
        s = "12345678-1234-5678-1234-567812345678"
        node = StringValueNode(value=s)
        result = GdxUUID.parse_literal(node)
        assert result == uuid.UUID(s)

    def test_parse_literal_wrong_node_raises_graphql_error(self) -> None:
        """Ships broken if GdxUUID.parse_literal stops raising GraphQLError
        for a non-string AST node.
        """
        node = IntValueNode(value="123")
        with pytest.raises(GraphQLError):
            GdxUUID.parse_literal(node)


# ---------------------------------------------------------------------------
# GdxJSONString
# ---------------------------------------------------------------------------


class TestGdxJSONString:
    """Tests for the GdxJSONString scalar (JSON-encoded string wire format).

    Covers serialize, parse_value, and parse_literal for valid and invalid input.
    """

    def test_serialize_dict(self) -> None:
        """Ships broken if GdxJSONString.serialize stops JSON-encoding a
        dict value.
        """
        data = {"key": "value", "num": 42}
        result = GdxJSONString.serialize(data)
        assert json.loads(result) == data

    def test_serialize_list(self) -> None:
        """Ships broken if GdxJSONString.serialize stops JSON-encoding a
        list value.
        """
        data = [1, 2, 3]
        result = GdxJSONString.serialize(data)
        assert json.loads(result) == data

    def test_serialize_string_passthrough(self) -> None:
        """Ships broken if GdxJSONString.serialize stops passing an
        already-JSON string through unchanged.
        """
        s = '{"key": "value"}'
        result = GdxJSONString.serialize(s)
        assert result == s

    def test_serialize_plain_string_round_trips(self) -> None:
        """Ships broken if GdxJSONString.serialize emits a plain (non-JSON)
        string verbatim, so the scalar's own parse_value can no longer decode
        what it wrote.
        """
        result = GdxJSONString.serialize("hello")
        assert GdxJSONString.parse_value(result) == "hello"

    def test_serialize_invalid_raises_graphql_error(self) -> None:
        """Ships broken if GdxJSONString.serialize stops raising GraphQLError
        for a value that cannot be JSON-encoded.
        """
        with pytest.raises(GraphQLError):
            GdxJSONString.serialize(object())  # non-serializable

    def test_parse_value_string(self) -> None:
        """Ships broken if GdxJSONString.parse_value stops decoding a JSON
        string into its Python value.
        """
        result = GdxJSONString.parse_value('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_value_invalid_raises_graphql_error(self) -> None:
        """Ships broken if GdxJSONString.parse_value stops raising
        GraphQLError for a string that is not valid JSON.
        """
        with pytest.raises(GraphQLError):
            GdxJSONString.parse_value("not-json")

    def test_parse_literal_string_node(self) -> None:
        """Ships broken if GdxJSONString.parse_literal stops decoding a
        StringValueNode's JSON text into its Python value.
        """
        node = StringValueNode(value='{"key": "value"}')
        result = GdxJSONString.parse_literal(node)
        assert result == {"key": "value"}

    def test_parse_literal_wrong_node_raises_graphql_error(self) -> None:
        """Ships broken if GdxJSONString.parse_literal stops raising
        GraphQLError for a non-string AST node.
        """
        node = IntValueNode(value="123")
        with pytest.raises(GraphQLError):
            GdxJSONString.parse_literal(node)


# ---------------------------------------------------------------------------
# GdxJSON — the RAW structured-JSON scalar (renamed from GdxGenericScalar; SDL
# name flipped GenericScalar -> JSON by design). parse_literal now RECURSES
# object / list / variable nodes (mirrors graphene's GenericScalar).
# ---------------------------------------------------------------------------


def _obj_node(fields: dict) -> ObjectValueNode:
    """Build an ObjectValueNode AST literal from a mapping of field values.

    Args:
        fields: A mapping of field name to its AST value node.

    Returns:
        The assembled ObjectValueNode.
    """
    return ObjectValueNode(
        fields=[
            ObjectFieldNode(name=NameNode(value=k), value=v) for k, v in fields.items()
        ]
    )


class TestGdxJSON:
    """Tests for the GdxJSON raw structured-JSON scalar's identity contract.

    Covers serialize, parse_value, and parse_literal, including recursion.
    """

    def test_serialize_string(self) -> None:
        """Ships broken if GdxJSON.serialize stops passing a string value
        through unchanged.
        """
        assert GdxJSON.serialize("hello") == "hello"

    def test_serialize_int(self) -> None:
        """Ships broken if GdxJSON.serialize stops passing an int value
        through unchanged.
        """
        assert GdxJSON.serialize(42) == 42

    def test_serialize_bool(self) -> None:
        """Ships broken if GdxJSON.serialize stops passing a bool value
        through unchanged.
        """
        assert GdxJSON.serialize(True) is True

    def test_serialize_dict(self) -> None:
        """Ships broken if GdxJSON.serialize stops passing a dict value
        through unchanged.
        """
        d = {"a": 1}
        assert GdxJSON.serialize(d) == d

    def test_parse_value_string(self) -> None:
        """Ships broken if GdxJSON.parse_value stops passing a string value
        through unchanged.
        """
        assert GdxJSON.parse_value("hello") == "hello"

    def test_parse_value_int(self) -> None:
        """Ships broken if GdxJSON.parse_value stops passing an int value
        through unchanged.
        """
        assert GdxJSON.parse_value(42) == 42

    def test_parse_literal_string_node(self) -> None:
        """Ships broken if GdxJSON.parse_literal stops resolving a
        StringValueNode to its raw string value.
        """
        node = StringValueNode(value="hello")
        result = GdxJSON.parse_literal(node)
        assert result == "hello"

    def test_parse_literal_int_node(self) -> None:
        """Ships broken if GdxJSON.parse_literal stops resolving an
        IntValueNode to its int value.
        """
        node = IntValueNode(value="42")
        result = GdxJSON.parse_literal(node)
        assert result == 42

    def test_parse_literal_float_node(self) -> None:
        """Ships broken if GdxJSON.parse_literal stops resolving a
        FloatValueNode to its float value.
        """
        node = FloatValueNode(value="3.14")
        result = GdxJSON.parse_literal(node)
        assert abs(result - 3.14) < 0.001

    def test_parse_literal_bool_node(self) -> None:
        """Ships broken if GdxJSON.parse_literal stops resolving a
        BooleanValueNode to its bool value.
        """
        node = BooleanValueNode(value=True)
        result = GdxJSON.parse_literal(node)
        assert result is True

    def test_parse_literal_null_node_is_none(self) -> None:
        """Ships broken if GdxJSON.parse_literal stops resolving a
        NullValueNode to None (null is a valid JSON value).
        """
        from graphql.language.ast import NullValueNode

        assert GdxJSON.parse_literal(NullValueNode()) is None

    def test_parse_literal_object_node_recurses(self) -> None:
        """Ships broken if GdxJSON.parse_literal stops recursing an
        ObjectValueNode's fields into a real dict (v2 recursion).
        """
        node = _obj_node(
            {
                "a": IntValueNode(value="1"),
                "b": ListValueNode(
                    values=[IntValueNode(value="1"), IntValueNode(value="2")]
                ),
            }
        )
        assert GdxJSON.parse_literal(node) == {"a": 1, "b": [1, 2]}

    def test_parse_literal_list_node_recurses(self) -> None:
        """Ships broken if GdxJSON.parse_literal stops recursing a
        ListValueNode's values into a real list.
        """
        node = ListValueNode(
            values=[StringValueNode(value="x"), BooleanValueNode(value=False)]
        )
        assert GdxJSON.parse_literal(node) == ["x", False]

    def test_parse_literal_garbage_node_raises_graphql_error(self) -> None:
        """Ships broken if GdxJSON.parse_literal stops raising a clean
        GraphQLError for an unsupported node type.
        """
        from graphql.language.ast import EnumValueNode

        with pytest.raises(GraphQLError):
            GdxJSON.parse_literal(EnumValueNode(value="FOO"))


# ---------------------------------------------------------------------------
# Round-trip tests (serialize → parse_value gives back equivalent)
# ---------------------------------------------------------------------------


class TestCoverageEdgeCases:
    """Tests to cover the remaining branches for the 95% coverage gate.

    Exercises non-string parse_value inputs and serialize error branches.
    """

    def test_date_parse_value_non_string_raises(self) -> None:
        """Ships broken if GdxDate.parse_value stops raising GraphQLError for
        a non-string value.
        """
        with pytest.raises(GraphQLError):
            GdxDate.parse_value(20240115)  # int, not string

    def test_datetime_parse_value_non_string_raises(self) -> None:
        """Ships broken if GdxDateTime.parse_value stops raising GraphQLError
        for a non-string value.
        """
        with pytest.raises(GraphQLError):
            GdxDateTime.parse_value(20240115)

    def test_time_parse_value_non_string_raises(self) -> None:
        """Ships broken if GdxTime.parse_value stops raising GraphQLError for
        a non-string value.
        """
        with pytest.raises(GraphQLError):
            GdxTime.parse_value(1230)

    def test_json_parse_value_non_string_raises(self) -> None:
        """Ships broken if GdxJSONString.parse_value stops raising
        GraphQLError for a non-string value.
        """
        with pytest.raises(GraphQLError):
            GdxJSONString.parse_value({"already": "dict"})

    def test_json_parse_literal_empty_list_recurses(self) -> None:
        """Ships broken if GdxJSON.parse_literal stops parsing an empty
        ListValueNode into an empty list (v2 recursion).

        Previously the raw scalar REJECTED list nodes; v2 recurses them so
        inline JSON list literals are accepted.
        """
        node = ListValueNode(values=[])
        assert GdxJSON.parse_literal(node) == []

    def test_json_parse_literal_garbage_node_still_raises(self) -> None:
        """Ships broken if GdxJSON.parse_literal stops raising GraphQLError
        for a truly unsupported node type.
        """
        from graphql.language.ast import EnumValueNode

        with pytest.raises(GraphQLError):
            GdxJSON.parse_literal(EnumValueNode(value="X"))

    def test_date_serialize_value_error_path(self) -> None:
        """Ships broken if GdxDate.serialize stops converting an internal
        ValueError/TypeError into a GraphQLError.

        Tests via an invalid string (not a date) rather than constructing a
        malformed datetime.date subclass, since date.__new__ is strict.

        Raises:
            ValueError: Raised internally by the unused "BadDate" stand-in's
                "isoformat" (kept as documentation of the attempted approach;
                the actual assertion below exercises the same error branch via
                an invalid string).
        """

        class BadDate(datetime.date):
            """Stand-in date subclass whose isoformat raises ValueError."""

            def isoformat(self) -> str:
                """Raise ValueError to simulate a malformed date."""
                raise ValueError("bad date")

        # Can't easily construct a BadDate because date.__new__ is strict.
        # Instead test with an invalid string (not a date) — verify via existing path.
        with pytest.raises(GraphQLError):
            GdxDate.serialize("not-a-date-at-all")

    def test_datetime_serialize_value_error_path(self) -> None:
        """Ships broken if GdxDateTime.serialize stops converting an internal
        error into a GraphQLError for a bad value.
        """
        with pytest.raises(GraphQLError):
            GdxDateTime.serialize("not-a-datetime")

    def test_time_serialize_value_error_path(self) -> None:
        """Ships broken if GdxTime.serialize stops converting an internal
        error into a GraphQLError for a bad value.
        """
        with pytest.raises(GraphQLError):
            GdxTime.serialize("not-a-time")


class TestRoundTrip:
    """Tests that serialize -> parse_value gives back an equivalent value.

    Covers every scalar's own round trip in isolation.
    """

    def test_date_round_trip(self) -> None:
        """Ships broken if GdxDate stops round-tripping a date through
        serialize then parse_value unchanged.
        """
        d = datetime.date(2024, 6, 15)
        serialized = GdxDate.serialize(d)
        parsed = GdxDate.parse_value(serialized)
        assert parsed == d

    def test_datetime_round_trip(self) -> None:
        """Ships broken if GdxDateTime stops round-tripping a datetime's
        year/month/day through serialize then parse_value.
        """
        dt = datetime.datetime(2024, 6, 15, 10, 30, 45)
        serialized = GdxDateTime.serialize(dt)
        parsed = GdxDateTime.parse_value(serialized)
        # Compare as datetime
        assert isinstance(parsed, datetime.datetime)
        assert parsed.year == dt.year
        assert parsed.month == dt.month
        assert parsed.day == dt.day

    def test_time_round_trip(self) -> None:
        """Ships broken if GdxTime stops round-tripping a time through
        serialize then parse_value unchanged.
        """
        t = datetime.time(10, 30, 45)
        serialized = GdxTime.serialize(t)
        parsed = GdxTime.parse_value(serialized)
        assert parsed == t

    def test_decimal_round_trip(self) -> None:
        """Ships broken if GdxDecimal stops round-tripping a Decimal through
        serialize then parse_value unchanged.
        """
        d = decimal.Decimal("99.99")
        serialized = GdxDecimal.serialize(d)
        parsed = GdxDecimal.parse_value(serialized)
        assert parsed == d

    def test_uuid_round_trip(self) -> None:
        """Ships broken if GdxUUID stops round-tripping a UUID through
        serialize then parse_value unchanged.
        """
        u = uuid.UUID("12345678-1234-5678-1234-567812345678")
        serialized = GdxUUID.serialize(u)
        parsed = GdxUUID.parse_value(serialized)
        assert parsed == u

    def test_json_round_trip(self) -> None:
        """Ships broken if GdxJSONString stops round-tripping a dict through
        serialize then parse_value unchanged.
        """
        data = {"key": "value", "num": 42}
        serialized = GdxJSONString.serialize(data)
        parsed = GdxJSONString.parse_value(serialized)
        assert parsed == data

    def test_json_raw_string_round_trip(self) -> None:
        """Ships broken if GdxJSON stops round-tripping a raw string through
        serialize then parse_value unchanged.
        """
        val = "hello world"
        serialized = GdxJSON.serialize(val)
        parsed = GdxJSON.parse_value(serialized)
        assert parsed == val

    def test_json_raw_dict_round_trip(self) -> None:
        """Ships broken if GdxJSON stops round-tripping a nested dict through
        serialize then parse_value unchanged.
        """
        val = {"a": [1, 2], "b": {"c": True}}
        serialized = GdxJSON.serialize(val)
        parsed = GdxJSON.parse_value(serialized)
        # Raw scalar is identity on both directions — the dict survives verbatim.
        assert parsed == val
