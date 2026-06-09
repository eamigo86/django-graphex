# -*- coding: utf-8 -*-
"""Unit tests for the standalone helpers and custom scalars in ``base_types``.

Covers ``factory_type`` (output/input/list/unknown), ``DjangoListObjectBase``,
the GenericForeignKey ``resolver``, the ``Binary`` scalar, and the
``CustomTime`` / ``CustomDate`` / ``CustomDateTime`` serializers.
"""

import datetime
from types import SimpleNamespace

import pytest
from graphql.language import ast

from django_graphex.base_types import (
    Binary,
    CustomDate,
    CustomDateFormat,
    CustomDateTime,
    CustomTime,
    DjangoListObjectBase,
    factory_type,
    resolver,
)

from .models import BasicModel


# --------------------------------------------------------------------------- #
# factory_type                                                                 #
# --------------------------------------------------------------------------- #
def test_factory_type_output_builds_object_type():
    out = factory_type("output", object, model=BasicModel)
    assert out is not None
    # The generated class carries the model on its Meta.
    assert out.Meta.model is BasicModel


def test_factory_type_unknown_operation_returns_none():
    assert factory_type("nope", object, model=BasicModel) is None


# --------------------------------------------------------------------------- #
# DjangoListObjectBase                                                         #
# --------------------------------------------------------------------------- #
def test_list_object_base_to_dict():
    class _Row:
        def __init__(self, v):
            self.v = v

        def to_dict(self):
            return {"v": self.v}

    base = DjangoListObjectBase(results=[_Row(1), _Row(2)], count=2)
    out = base.to_dict()
    assert out["count"] == 2
    assert out["results"] == [{"v": 1}, {"v": 2}]


def test_list_object_base_custom_results_field_name():
    base = DjangoListObjectBase(results=[], count=0, results_field_name="rows")
    assert base.to_dict() == {"rows": [], "count": 0}


# --------------------------------------------------------------------------- #
# resolver (GenericForeignKey attribute resolution)                            #
# --------------------------------------------------------------------------- #
def test_resolver_reads_generic_fk_attributes():
    instance = SimpleNamespace(
        id=7,
        _meta=SimpleNamespace(
            app_label="tests", model=SimpleNamespace(__name__="Widget")
        ),
    )
    assert resolver("app_label", None, instance, None) == "tests"
    assert resolver("id", None, instance, None) == 7
    assert resolver("model_name", None, instance, None) == "Widget"
    # An unknown attribute name returns None.
    assert resolver("unknown", None, instance, None) is None


# --------------------------------------------------------------------------- #
# Binary scalar                                                                #
# --------------------------------------------------------------------------- #
def test_binary_serialize_and_parse_value():
    encoded = Binary.serialize(b"\x00\xff")
    assert encoded == "00ff"
    # parse_value mirrors serialize.
    assert Binary.parse_value(b"\x01") == "01"


def test_binary_parse_literal_string_node():
    # Regression: parse_literal used the removed ast.StringValue -> AttributeError.
    node = ast.StringValueNode(value=b"\x01\x02")
    assert Binary.parse_literal(node) == "0102"
    assert Binary.parse_literal(ast.IntValueNode(value="1")) is None


# --------------------------------------------------------------------------- #
# CustomTime / CustomDate / CustomDateTime serializers                         #
# --------------------------------------------------------------------------- #
def test_custom_time_serialize_variants():
    assert CustomTime.serialize(CustomDateFormat("custom")) == "custom"
    assert CustomTime.serialize(datetime.time(10, 20, 30)) == "10:20:30"
    # A datetime is reduced to its time component.
    assert CustomTime.serialize(datetime.datetime(2020, 1, 1, 1, 2, 3)) == "01:02:03"


def test_custom_time_serialize_invalid_raises():
    with pytest.raises(AssertionError):
        CustomTime.serialize("not-a-time")


def test_custom_date_serialize_variants():
    assert CustomDate.serialize(CustomDateFormat("custom")) == "custom"
    assert CustomDate.serialize(datetime.date(2020, 1, 2)) == "2020-01-02"
    # A datetime is reduced to its date component.
    assert CustomDate.serialize(datetime.datetime(2020, 1, 2, 3, 4, 5)) == "2020-01-02"


def test_custom_date_serialize_invalid_raises():
    with pytest.raises(AssertionError):
        CustomDate.serialize("not-a-date")


def test_custom_datetime_serialize_variants():
    assert CustomDateTime.serialize(CustomDateFormat("custom")) == "custom"
    out = CustomDateTime.serialize(datetime.datetime(2020, 1, 2, 3, 4, 5))
    assert out.startswith("2020-01-02T03:04:05")


def test_custom_datetime_serialize_invalid_raises():
    with pytest.raises(AssertionError):
        CustomDateTime.serialize("not-a-datetime")
