# -*- coding: utf-8 -*-
"""Edge cases for the ``native/`` backend internals (fields, backend, validators).

Covers branches the end-to-end ``test_native_backend`` suite skips:
``unique_together`` violations, the ``to_representation`` output-field listing,
unique-exclude-on-update, the Django->Python field-type fallbacks (ArrayField /
RangeField / unknown-with-warning), lazy choice labels, and the validator
collector's MRO/passthrough guards.
"""

import datetime

import pytest
from django.db import models
from django.test import TestCase
from django.utils.translation import gettext_lazy as _

from django_graphex.native.backend import (
    PydanticBackend,
    _errors_to_type,
    _translate,
)
from django_graphex.native.fields import (
    _choices_enum,
    _python_type,
    _scalar_type,
    build_model_schema,
    m2m_fields,
    writable_fields,
)
from django_graphex.native.validators import _collect, build_validator_model
from tests.models import DummyModel, Tag


# --------------------------------------------------------------------------- #
# native/fields.py: scalar type fallbacks                                      #
# --------------------------------------------------------------------------- #
def test_scalar_type_arrayfield_inner_type():
    # ArrayField without importing postgres: a stub with the right internal type.
    class _ArrayStub(models.Field):
        def get_internal_type(self):
            return "ArrayField"

    inner = models.IntegerField()
    stub = _ArrayStub()
    stub.base_field = inner
    assert _scalar_type(stub) == list[int]


def test_scalar_type_rangefield_is_list_any():
    class _RangeStub(models.Field):
        def get_internal_type(self):
            return "IntegerRangeField"

    assert str(_scalar_type(_RangeStub())).startswith("list")


def test_scalar_type_unknown_warns_and_returns_str():
    class _MysteryStub(models.Field):
        def get_internal_type(self):
            return "MysteryField"

    with pytest.warns(RuntimeWarning, match="No native type mapping"):
        assert _scalar_type(_MysteryStub()) is str


def test_choices_enum_resolves_lazy_label_and_dedupes():
    # "a" and "A" both upper-case to the name "A" -> the while loop suffixes "_".
    field = models.CharField(max_length=10, choices=[("a", _("Alpha")), ("A", "Upper")])
    field.model = DummyModel
    field.name = "letter"
    enum_cls = _choices_enum(field)
    members = list(enum_cls.__members__)
    assert len(members) == 2
    assert "A" in members and "A_" in members  # de-duplicated name


def test_choices_enum_empty_value_becomes_empty_name():
    field = models.CharField(max_length=10, choices=[("", "Blank")])
    field.model = DummyModel
    field.name = "blank"
    enum_cls = _choices_enum(field)
    assert "EMPTY" in enum_cls.__members__


def test_python_type_fk_uses_related_pk_type():
    class _FkModel(DummyModel):
        other = models.ForeignKey(Tag, on_delete=models.CASCADE)

        class Meta:
            app_label = "tests"

    fk = _FkModel._meta.get_field("other")
    assert _python_type(fk) is int  # Tag pk is an AutoField -> int


# --------------------------------------------------------------------------- #
# native/backend.py: unique_together, output_field_names, helpers             #
# --------------------------------------------------------------------------- #
class UTogModel(DummyModel):
    a = models.CharField(max_length=10)
    b = models.CharField(max_length=10)

    class Meta:
        app_label = "tests"
        unique_together = (("a", "b"),)


class UniqueTogetherTest(TestCase):
    def test_unique_together_violation_is_non_field_error(self):
        UTogModel.objects.create(a="x", b="y")
        backend = PydanticBackend(UTogModel)
        errors = backend._db_check_errors({"a": "x", "b": "y"}, instance=None)
        self.assertIn("non_field_errors", errors)
        self.assertIn("unique set", errors["non_field_errors"][0])

    def test_unique_together_ok_when_one_differs(self):
        UTogModel.objects.create(a="x", b="y")
        backend = PydanticBackend(UTogModel)
        errors = backend._db_check_errors({"a": "x", "b": "z"}, instance=None)
        self.assertEqual(errors, {})

    def test_unique_together_excludes_self_on_update(self):
        obj = UTogModel.objects.create(a="x", b="y")
        backend = PydanticBackend(UTogModel)
        # Updating the same row with the same set is not a collision.
        errors = backend._db_check_errors({"a": "x", "b": "y"}, instance=obj)
        self.assertEqual(errors, {})


class UniqueExcludeModel(DummyModel):
    code = models.CharField(max_length=10, unique=True)

    class Meta:
        app_label = "tests"


class UniqueExcludeOnUpdateTest(TestCase):
    def test_unique_excludes_self_on_update(self):
        obj = UniqueExcludeModel.objects.create(code="C1")
        backend = PydanticBackend(UniqueExcludeModel)
        # Re-saving the same value on the same instance is allowed.
        errors = backend._db_check_errors({"code": "C1"}, instance=obj)
        self.assertEqual(errors, {})
        # But a different existing instance collides.
        UniqueExcludeModel.objects.create(code="C2")
        errors = backend._db_check_errors({"code": "C2"}, instance=obj)
        self.assertIn("code", errors)


class OutputFieldNamesTest(TestCase):
    def test_output_field_names_lists_concrete_and_m2m(self):
        class OutModel(DummyModel):
            title = models.CharField(max_length=10)
            tags = models.ManyToManyField(Tag)

            class Meta:
                app_label = "tests"

        names = PydanticBackend(OutModel).output_field_names()
        self.assertIn("title", names)
        self.assertIn("tags", names)


class TranslateHelpersTest(TestCase):
    def test_translate_non_field_error_grouping(self):
        from pydantic import BaseModel, model_validator

        class M(BaseModel):
            x: int = 0

            @model_validator(mode="after")
            def _bad(self):
                raise ValueError("object level boom")

        try:
            M()
        except Exception as exc:  # pydantic.ValidationError
            mapping = _translate(exc)
        # An object-level error with no field loc lands under non_field_errors.
        self.assertIn("non_field_errors", mapping)

    def test_errors_to_type_shape(self):
        types = _errors_to_type({"f": ["msg1", "msg2"]})
        self.assertEqual(types[0].field, "f")
        self.assertEqual(types[0].messages, ["msg1", "msg2"])


# --------------------------------------------------------------------------- #
# native/validators.py guards                                                  #
# --------------------------------------------------------------------------- #
class _Base:
    def validate_name(self, value):
        return value

    def validate(self, data):
        return data


class _Derived(_Base):
    # Overrides validate_name; the base copy must NOT win (the `seen` guard).
    def validate_name(self, value):
        return value.upper()


def test_collect_most_derived_wins():
    field_fns, object_fn = _collect(_Derived)
    assert "name" in field_fns
    # The derived definition (upper) is the one collected.
    assert field_fns["name"](_Derived, "x") == "X"
    assert object_fn is not None


def test_build_validator_model_none_model_passes_through():
    sentinel = object
    assert build_validator_model(_Derived, None, sentinel) is sentinel


def test_build_validator_model_no_validators_returns_base():
    class _Empty:
        pass

    class _DummyForValidators(DummyModel):
        title = models.CharField(max_length=10)

        class Meta:
            app_label = "tests"

    assert build_validator_model(_Empty, _DummyForValidators, None) is None


# --------------------------------------------------------------------------- #
# build_model_schema coverage: m2m + decimal + datetime defaults               #
# --------------------------------------------------------------------------- #
class SchemaShapeModel(DummyModel):
    price = models.DecimalField(max_digits=6, decimal_places=2)
    when = models.DateTimeField(null=True)
    tags = models.ManyToManyField(Tag, blank=True)

    class Meta:
        app_label = "tests"


def test_build_model_schema_includes_m2m_and_constraints():
    schema = build_model_schema(SchemaShapeModel)
    fields = schema.model_fields
    assert "tags" in fields  # M2M as optional list of pks
    assert "price" in fields
    # writable_fields excludes M2M and auto pk.
    wf = {f.name for f in writable_fields(SchemaShapeModel)}
    assert "price" in wf and "tags" not in wf
    assert {f.name for f in m2m_fields(SchemaShapeModel)} == {"tags"}


def test_build_model_schema_exclude_drops_field():
    schema = build_model_schema(SchemaShapeModel, exclude={"price"})
    assert "price" not in schema.model_fields


def test_build_model_schema_partial_makes_all_optional():
    schema = build_model_schema(SchemaShapeModel, partial=True)
    inst = schema()  # no required field errors
    assert inst is not None


def _now():
    return datetime.datetime(2020, 1, 1)


class CallableDefaultModel(DummyModel):
    created = models.DateTimeField(default=_now)  # callable default -> factory
    note = models.CharField(max_length=10, editable=False, default="x")  # not editable

    class Meta:
        app_label = "tests"


def test_build_model_schema_callable_default_uses_factory():
    schema = build_model_schema(CallableDefaultModel)
    inst = schema()
    # default_factory ran -> the field carries the factory's value.
    assert inst.created == _now()


def test_writable_fields_excludes_non_editable():
    names = {f.name for f in writable_fields(CallableDefaultModel)}
    assert "created" in names
    assert "note" not in names  # editable=False is skipped


def test_build_model_schema_m2m_in_exclude_is_dropped():
    schema = build_model_schema(SchemaShapeModel, exclude={"tags"})
    assert "tags" not in schema.model_fields


def test_choices_enum_lazy_value_is_coerced():
    # The VALUE itself (not the label) is a lazy string -> coerced via str().
    field = models.CharField(max_length=10, choices=[(_("draft"), "Draft")])
    field.model = DummyModel
    field.name = "state"
    enum_cls = _choices_enum(field)
    assert list(enum_cls)[0].value == "draft"
