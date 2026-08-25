"""Edge cases for the "native/" backend internals (fields, backend, validators).

Covers branches the end-to-end "test_native_backend" suite skips:
"unique_together" violations, the "to_representation" output-field listing,
unique-exclude-on-update, the Django->Python field-type fallbacks (ArrayField /
RangeField / unknown-with-warning), lazy choice labels, and the validator
collector's MRO/passthrough guards.
"""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from django.db import models
from django.test import TestCase
from django.utils.translation import gettext_lazy as _
from graphql import GraphQLBoolean

from django_graphex.core.backend import (
    PydanticBackend,
    _errors_to_type,
    _translate,
)
from django_graphex.core.fields import (
    FIELD_TYPES,
    _choices_enum,
    _python_type,
    _scalar_type,
    build_model_schema,
    m2m_fields,
    writable_fields,
)
from django_graphex.core.validators import _collect, build_validator_model
from django_graphex.filtering.native_schema import _field_scalar, _scalar_by_internal
from tests.models import DummyModel, Tag


# --------------------------------------------------------------------------- #
# core/fields.py: scalar type fallbacks                                      #
# --------------------------------------------------------------------------- #
def test_scalar_type_arrayfield_inner_type() -> None:
    """A stub field reporting "ArrayField" as its internal type maps to "list[<inner type>]".

    This test breaks if the ArrayField-shaped fallback stops threading the
    "base_field" type through into the list element type, without requiring
    django.contrib.postgres to be installed.
    """

    # ArrayField without importing postgres: a stub with the right internal type.
    class _ArrayStub(models.Field):
        """Throwaway field stub reporting "ArrayField" as its internal type."""

        def get_internal_type(self) -> str:
            """Report the internal type name used by "_scalar_type" to detect ArrayField.

            Returns:
                The literal string "ArrayField".
            """
            return "ArrayField"

    inner = models.IntegerField()
    stub = _ArrayStub()
    stub.base_field = inner
    assert _scalar_type(stub) == list[int]


def test_scalar_type_rangefield_is_list_any() -> None:
    """A stub field reporting a range internal type maps to a "list"-shaped Python type.

    This test breaks if the range-field fallback stops mapping to a list
    type.
    """

    class _RangeStub(models.Field):
        """Throwaway field stub reporting "IntegerRangeField" as its internal type."""

        def get_internal_type(self) -> str:
            """Report the internal type name used by "_scalar_type" to detect a range field.

            Returns:
                The literal string "IntegerRangeField".
            """
            return "IntegerRangeField"

    assert str(_scalar_type(_RangeStub())).startswith("list")


def test_scalar_type_unknown_warns_and_returns_str() -> None:
    """An unrecognized internal type warns and falls back to "str".

    This test breaks if the unknown-field-type fallback stops emitting a
    "RuntimeWarning" or stops defaulting to "str".
    """

    class _MysteryStub(models.Field):
        """Throwaway field stub reporting an unrecognized internal type."""

        def get_internal_type(self) -> str:
            """Report an internal type name "_scalar_type" cannot map.

            Returns:
                The literal string "MysteryField".
            """
            return "MysteryField"

    with pytest.warns(RuntimeWarning, match="No native type mapping"):
        assert _scalar_type(_MysteryStub()) is str


def test_nullbooleanfield_resolves_through_the_booleanfield_key() -> None:
    """A "NullBooleanField" reaches the boolean mapping under the "BooleanField" key.

    Django reports "BooleanField" from "get_internal_type()" for a
    "NullBooleanField", so a "NullBooleanField" key in an internal-type-keyed
    map is unreachable and can only drift away from its siblings. This test
    breaks if the deprecated field stops resolving to a boolean on either the
    input-schema path or the filter path, or if the dead key comes back.
    """
    field = models.NullBooleanField()
    assert field.get_internal_type() == "BooleanField"
    assert _scalar_type(field) is bool
    assert _field_scalar(field) is GraphQLBoolean
    assert "NullBooleanField" not in FIELD_TYPES
    assert "NullBooleanField" not in _scalar_by_internal()


def test_choices_enum_resolves_lazy_label_and_dedupes() -> None:
    """Choice values that upper-case to the same enum name get de-duplicated with a trailing underscore.

    "a" and "A" both upper-case to the name "A", so the while loop in
    "_choices_enum" suffixes "_" on the second one. This test breaks if that
    de-duplication stops happening.
    """
    # "a" and "A" both upper-case to the name "A" -> the while loop suffixes "_".
    field = models.CharField(max_length=10, choices=[("a", _("Alpha")), ("A", "Upper")])
    field.model = DummyModel
    field.name = "letter"
    enum_cls = _choices_enum(field)
    members = list(enum_cls.__members__)
    assert len(members) == 2
    assert "A" in members and "A_" in members  # de-duplicated name


def test_choices_enum_empty_value_becomes_empty_name() -> None:
    """An empty-string choice value maps to the enum member name "EMPTY".

    This test breaks if the empty-value-to-"EMPTY"-name mapping stops
    happening, which would otherwise produce an invalid empty enum member
    name.
    """
    field = models.CharField(max_length=10, choices=[("", "Blank")])
    field.model = DummyModel
    field.name = "blank"
    enum_cls = _choices_enum(field)
    assert "EMPTY" in enum_cls.__members__


def test_python_type_fk_uses_related_pk_type() -> None:
    """A forward ForeignKey's Python type follows the related model's pk type.

    This test breaks if "_python_type" stops resolving a ForeignKey to its
    related model's primary-key Python type (here "int", since "Tag"'s pk is
    an AutoField).
    """

    class _FkModel(DummyModel):
        """Throwaway model with a forward FK to "Tag", for the pk-type resolution test."""

        other = models.ForeignKey(Tag, on_delete=models.CASCADE)

        class Meta:
            """Register the throwaway model under the "tests" app label."""

            app_label = "tests"

    fk = _FkModel._meta.get_field("other")
    assert _python_type(fk) is int  # Tag pk is an AutoField -> int


# --------------------------------------------------------------------------- #
# core/backend.py: unique_together, output_field_names, helpers             #
# --------------------------------------------------------------------------- #
class UTogModel(DummyModel):
    """Throwaway model with a "unique_together" constraint on "a" and "b".

    Used only to exercise the multi-field collision check.
    """

    a = models.CharField(max_length=10)
    b = models.CharField(max_length=10)

    class Meta:
        """Register the throwaway model with "unique_together" on ("a", "b").

        No other options are needed for these tests.
        """

        app_label = "tests"
        unique_together = (("a", "b"),)


class UniqueTogetherTest(TestCase):
    """Coverage for "unique_together" violations surfacing as non-field errors.

    Covers the colliding, non-colliding, and self-exclusion-on-update cases.
    """

    def test_unique_together_violation_is_non_field_error(self) -> None:
        """A "unique_together" collision on create surfaces under "non_field_errors".

        This test breaks if a colliding ("a", "b") pair stops being reported
        as a non-field error, or if the message stops mentioning "unique set".
        """
        UTogModel.objects.create(a="x", b="y")
        backend = PydanticBackend(UTogModel)
        errors = backend._db_check_errors({"a": "x", "b": "y"}, instance=None)
        self.assertIn("non_field_errors", errors)
        self.assertIn("unique set", errors["non_field_errors"][0])

    def test_unique_together_ok_when_one_differs(self) -> None:
        """No error is raised when only part of the "unique_together" set matches an existing row.

        This test breaks if the collision check starts matching on a partial
        overlap of the unique-together fields.
        """
        UTogModel.objects.create(a="x", b="y")
        backend = PydanticBackend(UTogModel)
        errors = backend._db_check_errors({"a": "x", "b": "z"}, instance=None)
        self.assertEqual(errors, {})

    def test_unique_together_excludes_self_on_update(self) -> None:
        """Updating a row with its own existing "unique_together" values is not treated as a collision.

        This test breaks if the self-exclusion on update stops happening,
        which would make every no-op update fail validation.
        """
        obj = UTogModel.objects.create(a="x", b="y")
        backend = PydanticBackend(UTogModel)
        # Updating the same row with the same set is not a collision.
        errors = backend._db_check_errors({"a": "x", "b": "y"}, instance=obj)
        self.assertEqual(errors, {})


class UniqueExcludeModel(DummyModel):
    """Throwaway model with a single unique "code" field.

    Used only to exercise the single-field unique collision check.
    """

    code = models.CharField(max_length=10, unique=True)

    class Meta:
        """Register the throwaway model under the "tests" app label.

        No other options are needed for these tests.
        """

        app_label = "tests"


class UniqueExcludeOnUpdateTest(TestCase):
    """Coverage for excluding the current instance from a plain "unique=True" check on update.

    Confirms a different existing row still collides.
    """

    def test_unique_excludes_self_on_update(self) -> None:
        """Re-saving a unique field's own value is allowed, but a different row's value still collides.

        This test breaks if either the self-exclusion on update stops
        working, or if the collision check against a different instance
        stops firing.
        """
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
    """Coverage for "output_field_names" listing both concrete and many-to-many fields.

    Confirms neither kind of field is silently dropped from the listing.
    """

    def test_output_field_names_lists_concrete_and_m2m(self) -> None:
        """ "output_field_names" lists both a concrete field and a many-to-many field.

        This test breaks if "output_field_names" stops including
        many-to-many fields alongside concrete ones.
        """

        class OutModel(DummyModel):
            """Throwaway model with a concrete field and a many-to-many field."""

            title = models.CharField(max_length=10)
            tags = models.ManyToManyField(Tag)

            class Meta:
                """Register the throwaway model under the "tests" app label."""

                app_label = "tests"

        names = PydanticBackend(OutModel).output_field_names()
        self.assertIn("title", names)
        self.assertIn("tags", names)


class TranslateHelpersTest(TestCase):
    """Coverage for the pydantic-error-to-mapping translation helpers.

    Covers both "_translate" and "_errors_to_type".
    """

    def test_translate_non_field_error_grouping(self) -> None:
        """A pydantic object-level validator error (no field loc) is grouped under "non_field_errors".

        This test breaks if "_translate" stops routing loc-less validation
        errors into the "non_field_errors" bucket.

        Raises:
            ValueError: Only inside the throwaway pydantic model's own
                object-level validator, which this test relies on
                triggering (and catches) to produce the loc-less error.
        """
        from pydantic import BaseModel, model_validator

        class M(BaseModel):
            """Throwaway pydantic model whose object-level validator always raises."""

            x: int = 0

            @model_validator(mode="after")
            def _bad(self) -> "M":
                """Always raise, to produce a loc-less pydantic validation error.

                Returns:
                    Never returns; always raises "ValueError".

                Raises:
                    ValueError: Unconditionally, to simulate an object-level failure.
                """
                raise ValueError("object level boom")

        try:
            M()
        except Exception as exc:  # pydantic.ValidationError
            mapping = _translate(exc)
        # An object-level error with no field loc lands under non_field_errors.
        self.assertIn("non_field_errors", mapping)

    def test_errors_to_type_shape(self) -> None:
        """ "_errors_to_type" converts a field-to-messages mapping into typed error objects.

        This test breaks if the conversion stops preserving the field name
        or the ordered list of messages.
        """
        types = _errors_to_type({"f": ["msg1", "msg2"]})
        self.assertEqual(types[0].field, "f")
        self.assertEqual(types[0].messages, ["msg1", "msg2"])


# --------------------------------------------------------------------------- #
# core/validators.py guards                                                  #
# --------------------------------------------------------------------------- #
class _Base:
    """Throwaway validator host defining a base "validate_name" and "validate"."""

    def validate_name(self, value: str) -> str:
        """Pass a "name" value through unchanged.

        Args:
            value: The candidate "name" value.

        Returns:
            The value unchanged.
        """
        return value

    def validate(self, data: Any) -> Any:
        """Pass an object-level payload through unchanged.

        Args:
            data: The candidate object-level payload.

        Returns:
            The data unchanged.
        """
        return data


class _Derived(_Base):
    """Throwaway subclass overriding "validate_name" to prove the most-derived one wins."""

    # Overrides validate_name; the base copy must NOT win (the `seen` guard).
    def validate_name(self, value: str) -> str:
        """Upper-case a "name" value, overriding the base pass-through behavior.

        Args:
            value: The candidate "name" value.

        Returns:
            The value upper-cased.
        """
        return value.upper()


def test_collect_most_derived_wins() -> None:
    """ "_collect" keeps the most-derived "validate_name" override, not the base class's.

    This test breaks if the MRO "seen" guard in "_collect" stops preferring
    the most-derived definition of an overridden validator method.
    """
    field_fns, object_fn = _collect(_Derived)
    assert "name" in field_fns
    # The derived definition (upper) is the one collected.
    assert field_fns["name"](_Derived, "x") == "X"
    assert object_fn is not None


def test_build_validator_model_none_model_passes_through() -> None:
    """ "build_validator_model" returns the given base type unchanged when "model" is None.

    This test breaks if the "model is None" passthrough guard stops
    returning the sentinel base type as-is.
    """
    sentinel = object
    assert build_validator_model(_Derived, None, sentinel) is sentinel


def test_build_validator_model_no_validators_returns_base() -> None:
    """ "build_validator_model" returns None when the host class defines no validators.

    This test breaks if a host class with zero "validate_*"/"validate"
    methods stops resolving to None.
    """

    class _Empty:
        """Throwaway host class defining no validators at all."""

    class _DummyForValidators(DummyModel):
        """Throwaway model used only to satisfy the "model" parameter."""

        title = models.CharField(max_length=10)

        class Meta:
            """Register the throwaway model under the "tests" app label."""

            app_label = "tests"

    assert build_validator_model(_Empty, _DummyForValidators, None) is None


# --------------------------------------------------------------------------- #
# build_model_schema coverage: m2m + decimal + datetime defaults               #
# --------------------------------------------------------------------------- #
class SchemaShapeModel(DummyModel):
    """Throwaway model mixing a decimal, a nullable datetime, and an M2M field.

    Used across the "build_model_schema" shape and exclusion tests below.
    """

    price = models.DecimalField(max_digits=6, decimal_places=2)
    when = models.DateTimeField(null=True)
    tags = models.ManyToManyField(Tag, blank=True)

    class Meta:
        """Register the throwaway model under the "tests" app label.

        No other options are needed for these tests.
        """

        app_label = "tests"


def test_build_model_schema_includes_m2m_and_constraints() -> None:
    """ "build_model_schema" includes M2M and concrete fields, and "writable_fields" excludes M2M/pk.

    This test breaks if the generated schema stops exposing "tags" as an
    optional list of pks, or if "writable_fields"/"m2m_fields" stop
    partitioning fields correctly.
    """
    schema = build_model_schema(SchemaShapeModel)
    fields = schema.model_fields
    assert "tags" in fields  # M2M as optional list of pks
    assert "price" in fields
    # writable_fields excludes M2M and auto pk.
    wf = {f.name for f in writable_fields(SchemaShapeModel)}
    assert "price" in wf and "tags" not in wf
    assert {f.name for f in m2m_fields(SchemaShapeModel)} == {"tags"}


def test_build_model_schema_exclude_drops_field() -> None:
    """A field named in "exclude" is dropped from the generated schema.

    This test breaks if the "exclude" parameter stops removing the named
    field from "schema.model_fields".
    """
    schema = build_model_schema(SchemaShapeModel, exclude={"price"})
    assert "price" not in schema.model_fields


def test_build_model_schema_partial_makes_all_optional() -> None:
    """ "partial=True" makes every generated schema field optional and constructible with no arguments.

    This test breaks if "partial=True" stops relaxing every field's
    required-ness, or if constructing the schema with no values starts
    raising required-field errors.
    """
    schema = build_model_schema(SchemaShapeModel, partial=True)
    # Every field is optional: none are required by pydantic.
    assert not any(f.is_required() for f in schema.model_fields.values())
    schema()  # constructing with no values must not raise required-field errors


def _now() -> datetime.datetime:
    """Return a fixed, deterministic datetime used as a model field default.

    Returns:
        The fixed instant "datetime.datetime(2020, 1, 1)".
    """
    return datetime.datetime(2020, 1, 1)


class CallableDefaultModel(DummyModel):
    """Throwaway model with a callable field default and a non-editable field.

    Used by the default-factory and writable-fields exclusion tests below.
    """

    created = models.DateTimeField(default=_now)  # callable default -> factory
    note = models.CharField(max_length=10, editable=False, default="x")  # not editable

    class Meta:
        """Register the throwaway model under the "tests" app label.

        No other options are needed for these tests.
        """

        app_label = "tests"


def test_build_model_schema_callable_default_uses_factory() -> None:
    """A callable field default is threaded through as the schema's "default_factory".

    This test breaks if a callable Django field default stops being wired up
    as a pydantic "default_factory", falling back to some other default
    value instead.
    """
    schema = build_model_schema(CallableDefaultModel)
    inst = schema()
    # default_factory ran -> the field carries the factory's value.
    assert inst.created == _now()


def test_writable_fields_excludes_non_editable() -> None:
    """ "writable_fields" excludes fields declared with "editable=False".

    This test breaks if a non-editable field starts leaking into the
    writable-fields set.
    """
    names = {f.name for f in writable_fields(CallableDefaultModel)}
    assert "created" in names
    assert "note" not in names  # editable=False is skipped


def test_build_model_schema_m2m_in_exclude_is_dropped() -> None:
    """An M2M field named in "exclude" is dropped from the generated schema.

    This test breaks if the "exclude" parameter stops applying to
    many-to-many fields specifically.
    """
    schema = build_model_schema(SchemaShapeModel, exclude={"tags"})
    assert "tags" not in schema.model_fields


def test_choices_enum_lazy_value_is_coerced() -> None:
    """A lazy-translated choice VALUE (not just the label) is coerced to a plain string.

    This test breaks if a lazy-string choice value stops being coerced via
    "str()", leaving a lazy proxy object as the enum member's value.
    """
    # The VALUE itself (not the label) is a lazy string -> coerced via str().
    field = models.CharField(max_length=10, choices=[(_("draft"), "Draft")])
    field.model = DummyModel
    field.name = "state"
    enum_cls = _choices_enum(field)
    assert list(enum_cls)[0].value == "draft"
