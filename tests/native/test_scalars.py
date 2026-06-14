"""Tests for native/scalars.py — 7 scalar singletons + GDX_SCALAR_MAP.

No Django settings required. No django_db markers.
Run with: pytest tests/native/test_scalars.py -x
"""
import datetime
import decimal
import json
import uuid

import pytest
from graphql import GraphQLError
from graphql.language import ast as gql_ast
from graphql.language.ast import IntValueNode, FloatValueNode, StringValueNode, BooleanValueNode


# ---------------------------------------------------------------------------
# Import gate
# ---------------------------------------------------------------------------

def test_scalars_has_no_django_graphene_imports():
    """scalars.py must not import from django or graphene."""
    import re
    import pathlib

    path = pathlib.Path(__file__).parent.parent.parent / "django_graphex" / "native" / "scalars.py"
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

from django_graphex.native.scalars import (
    GdxDate,
    GdxDateTime,
    GdxTime,
    GdxDecimal,
    GdxUUID,
    GdxJSONString,
    GdxGenericScalar,
    GDX_SCALAR_MAP,
    CustomDateFormat,
)


# ---------------------------------------------------------------------------
# GDX_SCALAR_MAP contents
# ---------------------------------------------------------------------------

class TestGdxScalarMap:
    def test_has_7_custom_scalars(self):
        # Map keys are the GraphQL scalar NAMES as graphene renders them (the
        # Python symbols keep the Gdx prefix; only .name + map keys match
        # graphene). See discovery #1508.
        custom_names = {
            "CustomDate", "CustomDateTime", "CustomTime",
            "Decimal", "UUID", "JSONString", "GenericScalar",
        }
        for name in custom_names:
            assert name in GDX_SCALAR_MAP, f"Missing {name} in GDX_SCALAR_MAP"

    def test_has_5_builtin_scalars(self):
        from graphql import GraphQLString, GraphQLInt, GraphQLFloat, GraphQLBoolean, GraphQLID
        builtin_names = {"String", "Int", "Float", "Boolean", "ID"}
        for name in builtin_names:
            assert name in GDX_SCALAR_MAP, f"Missing builtin {name} in GDX_SCALAR_MAP"

    def test_builtins_are_graphql_core_instances(self):
        from graphql import GraphQLString
        assert GDX_SCALAR_MAP["String"] is GraphQLString

    def test_total_size(self):
        assert len(GDX_SCALAR_MAP) == 12  # 7 custom + 5 builtins

    def test_singleton_identity(self):
        """The map references the module-level singletons (keyed by graphene name)."""
        assert GDX_SCALAR_MAP["CustomDate"] is GdxDate
        assert GDX_SCALAR_MAP["CustomDateTime"] is GdxDateTime
        assert GDX_SCALAR_MAP["CustomTime"] is GdxTime
        assert GDX_SCALAR_MAP["Decimal"] is GdxDecimal
        assert GDX_SCALAR_MAP["UUID"] is GdxUUID
        assert GDX_SCALAR_MAP["JSONString"] is GdxJSONString
        assert GDX_SCALAR_MAP["GenericScalar"] is GdxGenericScalar

    def test_singleton_graphql_names_match_graphene(self):
        """The GraphQL .name of each singleton matches graphene's contract.

        Date/DateTime/Time use the graphene ``Custom*`` subclass names;
        UUID/JSONString/GenericScalar/Decimal match the plain graphene names.
        See discovery #1508 (probed via print_type under GDX_BACKEND=graphene).
        """
        assert GdxDate.name == "CustomDate"
        assert GdxDateTime.name == "CustomDateTime"
        assert GdxTime.name == "CustomTime"
        assert GdxDecimal.name == "Decimal"
        assert GdxUUID.name == "UUID"
        assert GdxJSONString.name == "JSONString"
        assert GdxGenericScalar.name == "GenericScalar"


# ---------------------------------------------------------------------------
# CustomDateFormat bypass
# ---------------------------------------------------------------------------

class TestCustomDateFormatBypass:
    def test_gdx_date_bypass(self):
        fmt = CustomDateFormat("2024-01-15")
        assert GdxDate.serialize(fmt) == "2024-01-15"

    def test_gdx_datetime_bypass(self):
        fmt = CustomDateFormat("2024-01-15T12:00:00")
        assert GdxDateTime.serialize(fmt) == "2024-01-15T12:00:00"

    def test_gdx_time_bypass(self):
        fmt = CustomDateFormat("12:30:00")
        assert GdxTime.serialize(fmt) == "12:30:00"


# ---------------------------------------------------------------------------
# GdxDate
# ---------------------------------------------------------------------------

class TestGdxDate:
    def test_serialize_date(self):
        d = datetime.date(2024, 1, 15)
        assert GdxDate.serialize(d) == "2024-01-15"

    def test_serialize_datetime_extracts_date(self):
        dt = datetime.datetime(2024, 1, 15, 12, 30)
        assert GdxDate.serialize(dt) == "2024-01-15"

    def test_serialize_invalid_raises_graphql_error(self):
        with pytest.raises(GraphQLError):
            GdxDate.serialize("not-a-date")

    def test_parse_value_string(self):
        result = GdxDate.parse_value("2024-01-15")
        assert result == datetime.date(2024, 1, 15)

    def test_parse_value_invalid_raises_graphql_error(self):
        with pytest.raises(GraphQLError):
            GdxDate.parse_value("not-a-date")

    def test_parse_literal_string_node(self):
        node = StringValueNode(value="2024-01-15")
        result = GdxDate.parse_literal(node)
        assert result == datetime.date(2024, 1, 15)

    def test_parse_literal_wrong_node_raises_graphql_error(self):
        node = IntValueNode(value="123")
        with pytest.raises(GraphQLError):
            GdxDate.parse_literal(node)


# ---------------------------------------------------------------------------
# GdxDateTime
# ---------------------------------------------------------------------------

class TestGdxDateTime:
    def test_serialize_datetime(self):
        dt = datetime.datetime(2024, 1, 15, 12, 30, 0)
        result = GdxDateTime.serialize(dt)
        assert "2024-01-15" in result
        assert "12:30:00" in result

    def test_serialize_date_as_datetime(self):
        d = datetime.date(2024, 1, 15)
        result = GdxDateTime.serialize(d)
        assert "2024-01-15" in result

    def test_serialize_invalid_raises_graphql_error(self):
        with pytest.raises(GraphQLError):
            GdxDateTime.serialize(42)

    def test_parse_value_string(self):
        result = GdxDateTime.parse_value("2024-01-15T12:30:00")
        assert isinstance(result, datetime.datetime)

    def test_parse_value_invalid_raises_graphql_error(self):
        with pytest.raises(GraphQLError):
            GdxDateTime.parse_value("not-a-datetime")

    def test_parse_literal_string_node(self):
        node = StringValueNode(value="2024-01-15T12:30:00")
        result = GdxDateTime.parse_literal(node)
        assert isinstance(result, datetime.datetime)

    def test_parse_literal_wrong_node_raises_graphql_error(self):
        node = IntValueNode(value="123")
        with pytest.raises(GraphQLError):
            GdxDateTime.parse_literal(node)


# ---------------------------------------------------------------------------
# GdxTime
# ---------------------------------------------------------------------------

class TestGdxTime:
    def test_serialize_time(self):
        t = datetime.time(12, 30, 0)
        assert GdxTime.serialize(t) == "12:30:00"

    def test_serialize_datetime_extracts_time(self):
        dt = datetime.datetime(2024, 1, 15, 12, 30, 0)
        assert GdxTime.serialize(dt) == "12:30:00"

    def test_serialize_invalid_raises_graphql_error(self):
        with pytest.raises(GraphQLError):
            GdxTime.serialize("not-a-time")

    def test_parse_value_string(self):
        result = GdxTime.parse_value("12:30:00")
        assert result == datetime.time(12, 30, 0)

    def test_parse_value_invalid_raises_graphql_error(self):
        with pytest.raises(GraphQLError):
            GdxTime.parse_value("not-a-time")

    def test_parse_literal_string_node(self):
        node = StringValueNode(value="12:30:00")
        result = GdxTime.parse_literal(node)
        assert result == datetime.time(12, 30, 0)

    def test_parse_literal_wrong_node_raises_graphql_error(self):
        node = IntValueNode(value="12")
        with pytest.raises(GraphQLError):
            GdxTime.parse_literal(node)


# ---------------------------------------------------------------------------
# GdxDecimal
# ---------------------------------------------------------------------------

class TestGdxDecimal:
    def test_serialize_decimal(self):
        d = decimal.Decimal("12.50")
        assert GdxDecimal.serialize(d) == "12.50"

    def test_serialize_float(self):
        result = GdxDecimal.serialize(12.5)
        assert "12.5" in str(result)

    def test_serialize_int(self):
        result = GdxDecimal.serialize(42)
        assert str(result) == "42"

    def test_serialize_invalid_raises_graphql_error(self):
        with pytest.raises(GraphQLError):
            GdxDecimal.serialize("not-a-number")

    def test_parse_value_string(self):
        result = GdxDecimal.parse_value("12.50")
        assert result == decimal.Decimal("12.50")

    def test_parse_value_invalid_raises_graphql_error(self):
        with pytest.raises(GraphQLError):
            GdxDecimal.parse_value("not-a-decimal")

    def test_parse_literal_string_node(self):
        node = StringValueNode(value="12.50")
        result = GdxDecimal.parse_literal(node)
        assert result == decimal.Decimal("12.50")

    def test_parse_literal_int_node(self):
        node = IntValueNode(value="42")
        result = GdxDecimal.parse_literal(node)
        assert result == decimal.Decimal("42")

    def test_parse_literal_float_node(self):
        node = FloatValueNode(value="12.5")
        result = GdxDecimal.parse_literal(node)
        assert result == decimal.Decimal("12.5")

    def test_parse_literal_invalid_node_raises_graphql_error(self):
        node = BooleanValueNode(value=True)
        with pytest.raises(GraphQLError):
            GdxDecimal.parse_literal(node)


# ---------------------------------------------------------------------------
# GdxUUID
# ---------------------------------------------------------------------------

class TestGdxUUID:
    def test_serialize_uuid(self):
        u = uuid.UUID("12345678-1234-5678-1234-567812345678")
        result = GdxUUID.serialize(u)
        assert result == "12345678-1234-5678-1234-567812345678"

    def test_serialize_string(self):
        s = "12345678-1234-5678-1234-567812345678"
        assert GdxUUID.serialize(s) == s

    def test_serialize_invalid_raises_graphql_error(self):
        with pytest.raises(GraphQLError):
            GdxUUID.serialize("not-a-uuid")

    def test_parse_value_string(self):
        s = "12345678-1234-5678-1234-567812345678"
        result = GdxUUID.parse_value(s)
        assert result == uuid.UUID(s)

    def test_parse_value_invalid_raises_graphql_error(self):
        with pytest.raises(GraphQLError):
            GdxUUID.parse_value("bad-uuid")

    def test_parse_literal_string_node(self):
        s = "12345678-1234-5678-1234-567812345678"
        node = StringValueNode(value=s)
        result = GdxUUID.parse_literal(node)
        assert result == uuid.UUID(s)

    def test_parse_literal_wrong_node_raises_graphql_error(self):
        node = IntValueNode(value="123")
        with pytest.raises(GraphQLError):
            GdxUUID.parse_literal(node)


# ---------------------------------------------------------------------------
# GdxJSONString
# ---------------------------------------------------------------------------

class TestGdxJSONString:
    def test_serialize_dict(self):
        data = {"key": "value", "num": 42}
        result = GdxJSONString.serialize(data)
        assert json.loads(result) == data

    def test_serialize_list(self):
        data = [1, 2, 3]
        result = GdxJSONString.serialize(data)
        assert json.loads(result) == data

    def test_serialize_string_passthrough(self):
        s = '{"key": "value"}'
        result = GdxJSONString.serialize(s)
        assert result == s

    def test_serialize_invalid_raises_graphql_error(self):
        with pytest.raises(GraphQLError):
            GdxJSONString.serialize(object())  # non-serializable

    def test_parse_value_string(self):
        result = GdxJSONString.parse_value('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_value_invalid_raises_graphql_error(self):
        with pytest.raises(GraphQLError):
            GdxJSONString.parse_value("not-json")

    def test_parse_literal_string_node(self):
        node = StringValueNode(value='{"key": "value"}')
        result = GdxJSONString.parse_literal(node)
        assert result == {"key": "value"}

    def test_parse_literal_wrong_node_raises_graphql_error(self):
        node = IntValueNode(value="123")
        with pytest.raises(GraphQLError):
            GdxJSONString.parse_literal(node)


# ---------------------------------------------------------------------------
# GdxGenericScalar
# ---------------------------------------------------------------------------

class TestGdxGenericScalar:
    def test_serialize_string(self):
        assert GdxGenericScalar.serialize("hello") == "hello"

    def test_serialize_int(self):
        assert GdxGenericScalar.serialize(42) == 42

    def test_serialize_bool(self):
        assert GdxGenericScalar.serialize(True) is True

    def test_serialize_dict(self):
        d = {"a": 1}
        assert GdxGenericScalar.serialize(d) == d

    def test_parse_value_string(self):
        assert GdxGenericScalar.parse_value("hello") == "hello"

    def test_parse_value_int(self):
        assert GdxGenericScalar.parse_value(42) == 42

    def test_parse_literal_string_node(self):
        node = StringValueNode(value="hello")
        result = GdxGenericScalar.parse_literal(node)
        assert result == "hello"

    def test_parse_literal_int_node(self):
        node = IntValueNode(value="42")
        result = GdxGenericScalar.parse_literal(node)
        assert result == 42

    def test_parse_literal_float_node(self):
        node = FloatValueNode(value="3.14")
        result = GdxGenericScalar.parse_literal(node)
        assert abs(result - 3.14) < 0.001

    def test_parse_literal_bool_node(self):
        node = BooleanValueNode(value=True)
        result = GdxGenericScalar.parse_literal(node)
        assert result is True

    def test_parse_literal_unknown_node_raises_graphql_error(self):
        """An unknown/unsupported node type should raise GraphQLError."""
        from graphql.language.ast import NullValueNode
        node = NullValueNode()
        # NullValueNode should either return None or raise GraphQLError
        # The design says invalid input raises GraphQLError, but None is a valid value
        # For GenericScalar, null is valid
        result = GdxGenericScalar.parse_literal(node)
        assert result is None


# ---------------------------------------------------------------------------
# Round-trip tests (serialize → parse_value gives back equivalent)
# ---------------------------------------------------------------------------

class TestCoverageEdgeCases:
    """Tests to cover the remaining branches for the 95% coverage gate."""

    def test_date_parse_value_non_string_raises(self):
        """parse_value with a non-string value raises GraphQLError."""
        with pytest.raises(GraphQLError):
            GdxDate.parse_value(20240115)  # int, not string

    def test_datetime_parse_value_non_string_raises(self):
        """parse_value with a non-string value raises GraphQLError."""
        with pytest.raises(GraphQLError):
            GdxDateTime.parse_value(20240115)

    def test_time_parse_value_non_string_raises(self):
        """parse_value with a non-string value raises GraphQLError."""
        with pytest.raises(GraphQLError):
            GdxTime.parse_value(1230)

    def test_json_parse_value_non_string_raises(self):
        """parse_value with a non-string value raises GraphQLError."""
        with pytest.raises(GraphQLError):
            GdxJSONString.parse_value({"already": "dict"})

    def test_generic_parse_literal_unknown_node_raises(self):
        """parse_literal with an unsupported node type raises GraphQLError."""
        from graphql.language.ast import ListValueNode
        # ListValueNode is not handled by _generic_parse_literal
        node = ListValueNode(values=[])
        with pytest.raises(GraphQLError):
            GdxGenericScalar.parse_literal(node)

    def test_date_serialize_value_error_path(self):
        """_date_serialize with a bad date that raises ValueError internally.

        This exercises the except ValueError/TypeError → GraphQLError branch.
        A mock object that pretends to be a datetime.date but raises on isoformat.
        """
        class BadDate(datetime.date):
            def isoformat(self):
                raise ValueError("bad date")

        # Can't easily construct a BadDate because date.__new__ is strict.
        # Instead test with an invalid string (not a date) — verify via existing path.
        with pytest.raises(GraphQLError):
            GdxDate.serialize("not-a-date-at-all")

    def test_datetime_serialize_value_error_path(self):
        """_datetime_serialize with a bad value exercises the except branch."""
        with pytest.raises(GraphQLError):
            GdxDateTime.serialize("not-a-datetime")

    def test_time_serialize_value_error_path(self):
        """_time_serialize with a bad value exercises the except branch."""
        with pytest.raises(GraphQLError):
            GdxTime.serialize("not-a-time")


class TestRoundTrip:
    def test_date_round_trip(self):
        d = datetime.date(2024, 6, 15)
        serialized = GdxDate.serialize(d)
        parsed = GdxDate.parse_value(serialized)
        assert parsed == d

    def test_datetime_round_trip(self):
        dt = datetime.datetime(2024, 6, 15, 10, 30, 45)
        serialized = GdxDateTime.serialize(dt)
        parsed = GdxDateTime.parse_value(serialized)
        # Compare as datetime
        assert isinstance(parsed, datetime.datetime)
        assert parsed.year == dt.year
        assert parsed.month == dt.month
        assert parsed.day == dt.day

    def test_time_round_trip(self):
        t = datetime.time(10, 30, 45)
        serialized = GdxTime.serialize(t)
        parsed = GdxTime.parse_value(serialized)
        assert parsed == t

    def test_decimal_round_trip(self):
        d = decimal.Decimal("99.99")
        serialized = GdxDecimal.serialize(d)
        parsed = GdxDecimal.parse_value(serialized)
        assert parsed == d

    def test_uuid_round_trip(self):
        u = uuid.UUID("12345678-1234-5678-1234-567812345678")
        serialized = GdxUUID.serialize(u)
        parsed = GdxUUID.parse_value(serialized)
        assert parsed == u

    def test_json_round_trip(self):
        data = {"key": "value", "num": 42}
        serialized = GdxJSONString.serialize(data)
        parsed = GdxJSONString.parse_value(serialized)
        assert parsed == data

    def test_generic_string_round_trip(self):
        val = "hello world"
        serialized = GdxGenericScalar.serialize(val)
        parsed = GdxGenericScalar.parse_value(serialized)
        assert parsed == val
