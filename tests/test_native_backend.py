"""Native (Pydantic) backend: Meta.model types, no DRF involved."""

from __future__ import annotations

import decimal
import enum
from types import SimpleNamespace
from typing import Any

from django.db import models
from django.test import TestCase
from pydantic import BaseModel, field_validator

from django_graphex.core.backend import PydanticBackend
from django_graphex.types import DjangoModelType
from tests.models import DummyModel, Tag


class NativeCategory(DummyModel):
    """Throwaway category model with a unique "name", for the native-backend suite.

    Also the target of "NativeProduct"'s forward FK.
    """

    name = models.CharField(max_length=50, unique=True)


class NativeProduct(DummyModel):
    """Throwaway product model with a forward FK, an M2M, and a choices field.

    Used across the native CRUD, representation, and nested-write tests.
    """

    sku = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    status = models.CharField(
        max_length=10, choices=[("draft", "Draft"), ("live", "Live")], default="draft"
    )
    category = models.ForeignKey(
        NativeCategory,
        null=True,
        blank=True,
        related_name="products",
        on_delete=models.SET_NULL,
    )
    tags = models.ManyToManyField(Tag, blank=True)


class NativeProductType(DjangoModelType):
    """Plain "NativeProduct" type with no nested fields, for the native CRUD suite.

    Used by "BackendWiringTest" and "NativeCrudTest".
    """

    class Meta:
        """Bind the type to "NativeProduct" with no extra options.

        No nested fields or custom pydantic base are needed here.
        """

        model = NativeProduct


def _info() -> SimpleNamespace:
    """Build a fake GraphQL "info" with an empty multipart-upload context.

    Returns:
        An object shaped like a GraphQL resolve info, with a "context"
        carrying empty "META" and "FILES".
    """
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _create(type_cls: type[DjangoModelType], data: dict[str, Any]) -> Any:
    """Invoke the generated "create" mutation for a "DjangoModelType" subclass.

    Args:
        type_cls: The "DjangoModelType" subclass whose mutation is invoked.
        data: The input payload keyed by the type's input field name.

    Returns:
        The mutation result object (exposes "ok" and, on failure, "errors").
    """
    return type_cls.create(None, _info(), **{type_cls._meta.input_field_name: data})


def _update(type_cls: type[DjangoModelType], data: dict[str, Any]) -> Any:
    """Invoke the generated "update" mutation for a "DjangoModelType" subclass.

    Args:
        type_cls: The "DjangoModelType" subclass whose mutation is invoked.
        data: The input payload keyed by the type's input field name.

    Returns:
        The mutation result object (exposes "ok" and, on failure, "errors").
    """
    return type_cls.update(None, _info(), **{type_cls._meta.input_field_name: data})


class BackendWiringTest(TestCase):
    """Coverage confirming a plain "Meta.model" type selects the native Pydantic backend.

    A basic sanity check ahead of the deeper CRUD suite below.
    """

    def test_meta_model_selects_native_backend(self) -> None:
        """A "DjangoModelType" with "Meta.model" wires up "PydanticBackend" bound to that model.

        This test breaks if the native backend selection or model binding
        regresses.
        """
        self.assertIsInstance(NativeProductType._meta.backend, PydanticBackend)
        self.assertIs(NativeProductType._meta.model, NativeProduct)


class NativeCrudTest(TestCase):
    """Coverage for the native backend's create/update/delete CRUD paths.

    Covers the happy path plus every validation-error branch.
    """

    def test_create_valid(self) -> None:
        """A fully-valid create payload persists every field, including the FK and M2M.

        This test breaks if any of the scalar, decimal, choice, FK, or M2M
        fields stop being persisted correctly on create.
        """
        cat = NativeCategory.objects.create(name="c1")
        t1 = Tag.objects.create(label="t1")
        result = _create(
            NativeProductType,
            {
                "sku": "A1",
                "name": "Widget",
                "price": "9.99",
                "status": "live",
                "category": cat.pk,
                "tags": [t1.pk],
            },
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        obj = NativeProduct.objects.get()
        self.assertEqual(obj.sku, "A1")
        self.assertEqual(obj.price, decimal.Decimal("9.99"))
        self.assertEqual(obj.status, "live")
        self.assertEqual(obj.category_id, cat.pk)
        self.assertEqual(list(obj.tags.values_list("pk", flat=True)), [t1.pk])

    def test_default_applied(self) -> None:
        """A create payload omitting "status" falls back to the model's default value.

        This test breaks if the field default stops being applied when the
        payload omits the field.
        """
        result = _create(NativeProductType, {"sku": "B1", "name": "n", "price": "1.0"})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(NativeProduct.objects.get().status, "draft")

    def test_max_length_error(self) -> None:
        """A "sku" value exceeding "max_length" fails validation on the "sku" field.

        This test breaks if the max_length constraint stops being enforced,
        or if the error stops being attributed to the "sku" field.
        """
        result = _create(
            NativeProductType, {"sku": "TOOLONGSKU", "name": "n", "price": "1.0"}
        )
        # sku max_length is 10; "TOOLONGSKU" is exactly 10 -> ok. Use 11.
        result = _create(
            NativeProductType, {"sku": "TOOLONGSKU1", "name": "n", "price": "1.0"}
        )
        self.assertFalse(result.ok)
        self.assertIn("sku", {e.field for e in result.errors})

    def test_invalid_choice(self) -> None:
        """A "status" value outside the declared choices fails validation on the "status" field.

        This test breaks if the choices constraint stops being enforced.
        """
        result = _create(
            NativeProductType,
            {"sku": "C1", "name": "n", "price": "1.0", "status": "bogus"},
        )
        self.assertFalse(result.ok)
        self.assertIn("status", {e.field for e in result.errors})

    def test_fk_does_not_exist(self) -> None:
        """A "category" pk that does not exist fails validation on the "category" field.

        This test breaks if a non-existent FK target stops being caught and
        reported under the "category" field.
        """
        result = _create(
            NativeProductType,
            {"sku": "E1", "name": "n", "price": "1.0", "category": 9999},
        )
        self.assertFalse(result.ok)
        self.assertIn("category", {e.field for e in result.errors})

    def test_unique_violation(self) -> None:
        """Creating a second row with a duplicate "sku" fails validation on the "sku" field.

        This test breaks if the unique constraint on "sku" stops being
        enforced at the backend level.
        """
        NativeProduct.objects.create(sku="UNIQ", name="n", price=decimal.Decimal("1"))
        result = _create(
            NativeProductType, {"sku": "UNIQ", "name": "n2", "price": "2.0"}
        )
        self.assertFalse(result.ok)
        self.assertIn("sku", {e.field for e in result.errors})

    def test_required_missing(self) -> None:
        """Omitting required fields ("name", "price") fails validation on both fields.

        This test breaks if the required-field check stops reporting every
        missing required field.
        """
        result = _create(NativeProductType, {"sku": "D1"})
        self.assertFalse(result.ok)
        self.assertLessEqual({"name", "price"}, {e.field for e in result.errors})

    def test_partial_update(self) -> None:
        """An update payload with only some fields leaves the omitted fields unchanged.

        This test breaks if a partial update stops preserving fields absent
        from the payload, e.g. by resetting "sku" to a default value.
        """
        obj = NativeProduct.objects.create(
            sku="F1", name="old", price=decimal.Decimal("1")
        )
        result = _update(NativeProductType, {"id": obj.id, "name": "new"})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        obj.refresh_from_db()
        self.assertEqual(obj.name, "new")
        self.assertEqual(obj.sku, "F1")

    def test_delete_missing(self) -> None:
        """Deleting a non-existent id returns a not-ok result with a "does not exist" message.

        This test breaks if deleting a missing row stops returning a
        graceful error instead of raising.
        """
        result = NativeProductType.delete(None, _info(), id=999)
        self.assertFalse(result.ok)
        self.assertIn("does not exist", result.errors[0].messages[0])


class ToRepresentationTest(TestCase):
    """Coverage for "PydanticBackend.to_representation" producing the output dict.

    Confirms relation fields serialize to plain pks/lists, not model instances.
    """

    def test_output_dict(self) -> None:
        """ "to_representation" surfaces scalar, FK-pk, and empty-M2M fields correctly.

        This test breaks if the FK field stops being represented as its pk,
        or if an empty M2M relation stops being represented as an empty list.
        """
        cat = NativeCategory.objects.create(name="c")
        obj = NativeProduct.objects.create(
            sku="G1", name="n", price=decimal.Decimal("3"), category=cat
        )
        data = PydanticBackend(NativeProduct).to_representation(obj)
        self.assertEqual(data["sku"], "G1")
        self.assertEqual(data["category"], cat.pk)
        self.assertEqual(data["tags"], [])


class CustomValidatorBase(BaseModel):
    """Throwaway pydantic base carrying a custom "sku" validator.

    The derived schema adds "sku" itself, so this base must declare its
    validator with "check_fields=False".
    """

    # `sku` is added by the derived schema, so the base must not check_fields.
    @field_validator("sku", check_fields=False)
    @classmethod
    def _no_x(cls, value: Any) -> Any:
        """Reject "sku" values starting with "X".

        Args:
            value: The candidate "sku" value.

        Returns:
            The value unchanged, when valid.

        Raises:
            ValueError: When the value is a string starting with "X".
        """
        if isinstance(value, str) and value.startswith("X"):
            raise ValueError("sku must not start with X")
        return value


class CustomValidatorType(DjangoModelType):
    """ "NativeProduct" type using a custom pydantic base with an extra "sku" validator.

    Used to prove custom "pydantic_model" bases participate in validation.
    """

    class Meta:
        """Bind the type to "NativeProduct" with "CustomValidatorBase" as the pydantic base.

        No nested fields are needed here.
        """

        model = NativeProduct
        pydantic_model = CustomValidatorBase


class PydanticModelHookTest(TestCase):
    """Coverage confirming a custom "pydantic_model" base's validators run.

    A single failing-case test is sufficient to prove the hook fires.
    """

    def test_custom_validator_runs(self) -> None:
        """The custom "sku" validator on "CustomValidatorBase" fires during create.

        This test breaks if a custom "pydantic_model" base's validators stop
        being invoked by the generated schema.
        """
        result = _create(
            CustomValidatorType, {"sku": "X9", "name": "n", "price": "1.0"}
        )
        self.assertFalse(result.ok)
        self.assertIn("sku", {e.field for e in result.errors})


# -- native nested writes (children declared as MODELS, no DRF) --------------- #
class NativeForwardType(DjangoModelType):
    """ "NativeProduct" type exposing "category" as a nested native forward-FK field.

    Used by the forward-FK nested-write tests below.
    """

    class Meta:
        """Bind the type to "NativeProduct" with "category" declared as nested.

        No other options are needed for these forward-FK tests.
        """

        model = NativeProduct
        nested_fields = {"category": NativeCategory}  # native forward FK child


class NativeM2MType(DjangoModelType):
    """ "NativeProduct" type exposing "tags" as a nested native M2M field.

    Used by the many-to-many nested-write test below.
    """

    class Meta:
        """Bind the type to "NativeProduct" with "tags" declared as nested.

        No other options are needed for this M2M test.
        """

        model = NativeProduct
        nested_fields = {"tags": Tag}  # native M2M child


class NativeReverseType(DjangoModelType):
    """ "NativeCategory" type exposing "products" as a nested native reverse-FK field.

    Used by the reverse-FK nested-write test below.
    """

    class Meta:
        """Bind the type to "NativeCategory" with "products" declared as nested.

        No other options are needed for this reverse-FK test.
        """

        model = NativeCategory
        nested_fields = {"products": NativeProduct}  # native reverse-FK children


class NativeNestedTest(TestCase):
    """Coverage for native (model-declared, no-DRF) nested writes across relation kinds.

    Covers forward FK, many-to-many, and reverse FK.
    """

    def test_forward_fk_creates_and_links(self) -> None:
        """A nested forward-FK payload creates and links the child "category" under the native backend.

        This test breaks if the native forward-FK nested-write path stops
        persisting or linking the child.
        """
        result = _create(
            NativeForwardType,
            {"sku": "P1", "name": "n", "price": "1.0", "category": {"name": "new-cat"}},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(NativeCategory.objects.count(), 1)
        self.assertEqual(NativeProduct.objects.get().category.name, "new-cat")

    def test_forward_fk_failure_rolls_back(self) -> None:
        """A parent validation failure rolls back the already-persisted nested forward-FK child.

        This test breaks if the native nested-write path stops being atomic
        on parent failure.
        """
        # missing required name/price on the parent -> nothing persists.
        result = _create(NativeForwardType, {"category": {"name": "orphan"}})
        self.assertFalse(result.ok)
        self.assertEqual(NativeCategory.objects.count(), 0)
        self.assertEqual(NativeProduct.objects.count(), 0)

    def test_m2m_creates_and_adds(self) -> None:
        """A nested M2M payload creates and links every child "tag" under the native backend.

        This test breaks if the native M2M nested-write path stops
        persisting or linking every child.
        """
        result = _create(
            NativeM2MType,
            {
                "sku": "P2",
                "name": "n",
                "price": "1.0",
                "tags": [{"label": "a"}, {"label": "b"}],
            },
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(Tag.objects.count(), 2)
        self.assertEqual(
            set(NativeProduct.objects.get().tags.values_list("label", flat=True)),
            {"a", "b"},
        )

    def test_reverse_fk_links_children_to_parent(self) -> None:
        """A nested reverse-FK payload creates and links every child "product" under the native backend.

        This test breaks if the native reverse-FK nested-write path stops
        persisting or linking every child to the newly created parent.
        """
        result = _create(
            NativeReverseType,
            {
                "name": "cat",
                "products": [
                    {"sku": "R1", "name": "n1", "price": "1"},
                    {"sku": "R2", "name": "n2", "price": "2"},
                ],
            },
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        cat = NativeCategory.objects.get()
        self.assertEqual(cat.products.count(), 2)
        self.assertEqual(set(cat.products.values_list("sku", flat=True)), {"R1", "R2"})


# --------------------------------------------------------------------------- #
# Audit rank 11: list-of-enum unwrap, end-to-end. A field typed as a LIST of   #
# an Enum (e.g. a multi-select choice) must arrive at the DB as RAW values,    #
# never as Enum members. This exercises BOTH unwrap sites:                     #
#   * native/backend.py PydanticBackend.save_object inline ``_unwrap`` — runs  #
#     on validated.model_dump(), where a ``list[Enum]`` field yields a list of #
#     Enum MEMBERS; the inline _unwrap recurses the list to raw values.        #
#   * nested.py NestedMutationMixin._unwrap_enums — runs on each nested child  #
#     payload, recursing list/tuple values so multi-valued choice fields land  #
#     with plain Python values before the child save.                          #
# --------------------------------------------------------------------------- #
class _ColorEnum(str, enum.Enum):
    """Throwaway three-member string enum used to exercise list-of-enum unwrapping."""

    RED = "red"
    BLUE = "blue"
    GREEN = "green"


class EnumListModel(DummyModel):
    """A model with a JSON-backed list field that stores raw choice values.

    Used to exercise the backend's inline list-of-enum unwrap.
    """

    name = models.CharField(max_length=50)
    colors = models.JSONField(default=list)


class _EnumListPydantic(BaseModel):
    """Types "colors" as a list[Enum] so model_dump yields Enum MEMBERS.

    This forces the backend inline "_unwrap" to recurse and produce raw
    values.
    """

    name: str
    colors: list[_ColorEnum] = []


class EnumListType(DjangoModelType):
    """ "EnumListModel" type using "_EnumListPydantic" so "colors" is typed as list[Enum].

    Used by "BackendListOfEnumUnwrapTest".
    """

    class Meta:
        """Bind the type to "EnumListModel" with "_EnumListPydantic" as the pydantic base.

        No nested fields are needed here.
        """

        model = EnumListModel
        pydantic_model = _EnumListPydantic


class BackendListOfEnumUnwrapTest(TestCase):
    """Coverage for the backend's inline list-of-enum unwrap in "save_object".

    Covers both the create-mutation path and a direct "save_object" call.
    """

    def test_backend_inline_unwrap_list_of_enum_saves_raw_values(self) -> None:
        """A "list[Enum]" save payload lands as raw strings via the backend's inline "_unwrap".

        This test breaks if list-of-enum values stop being unwrapped to raw
        strings before the database write (native/backend.py).
        """
        result = _create(
            EnumListType,
            {"name": "palette", "colors": ["red", "blue", "green"]},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        obj = EnumListModel.objects.get()
        # Stored values are RAW strings — never ``_ColorEnum`` members.
        self.assertEqual(obj.colors, ["red", "blue", "green"])
        for value in obj.colors:
            self.assertIsInstance(value, str)
            self.assertNotIsInstance(value, enum.Enum)

    def test_backend_save_object_unwraps_enum_member_list_directly(self) -> None:
        """ "PydanticBackend.save_object" recurses a list of Enum members to raw values before saving.

        Directly drives "save_object" with a payload whose "colors" is a
        list of Enum MEMBERS (as model_dump produces): the inline "_unwrap"
        must recurse the list to raw values before the DB write. This test
        breaks if that recursion regresses.
        """
        backend = PydanticBackend(EnumListModel)
        # Simulate exactly what validated.model_dump() yields for list[Enum].
        ok, result = backend.save_object(
            None,
            None,
            _info(),
            {"name": "members", "colors": [_ColorEnum.RED, _ColorEnum.BLUE]},
        )
        self.assertTrue(ok, msg=result)
        obj = EnumListModel.objects.get(name="members")
        self.assertEqual(obj.colors, ["red", "blue"])
        for value in obj.colors:
            self.assertNotIsInstance(value, enum.Enum)


# Nested parent whose child carries the list-of-enum field — exercises the
# nested.py ``_unwrap_enums`` recursion on the child payload end-to-end.
class EnumListParent(DummyModel):
    """Throwaway parent model whose nested children carry a list-of-enum field.

    Used by "NestedListOfEnumUnwrapTest".
    """

    title = models.CharField(max_length=50)


class EnumListChild(DummyModel):
    """Throwaway child model with a reverse FK to "EnumListParent" and a list-of-enum field.

    Exercises the nested-write "_unwrap_enums" recursion end-to-end.
    """

    parent = models.ForeignKey(
        EnumListParent, related_name="swatches", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=50)
    colors = models.JSONField(default=list)


class _EnumListChildPydantic(BaseModel):
    """Pydantic base typing the child's "colors" field as list[Enum]."""

    name: str
    colors: list[_ColorEnum] = []


class EnumListChildType(DjangoModelType):
    """ "EnumListChild" type using "_EnumListChildPydantic" so "colors" is typed as list[Enum].

    Used as the nested child type in "EnumListParentType".
    """

    class Meta:
        """Bind the type to "EnumListChild" with "_EnumListChildPydantic" as the pydantic base.

        No nested fields of its own are needed here.
        """

        model = EnumListChild
        pydantic_model = _EnumListChildPydantic


class EnumListParentType(DjangoModelType):
    """ "EnumListParent" type exposing "swatches" as a nested reverse-FK field.

    Used by "NestedListOfEnumUnwrapTest".
    """

    class Meta:
        """Bind the type to "EnumListParent" with "swatches" declared as nested.

        No other options are needed here.
        """

        model = EnumListParent
        nested_fields = {"swatches": EnumListChild}


class NestedListOfEnumUnwrapTest(TestCase):
    """Coverage for the nested-write list-of-enum unwrap on child payloads.

    Confirms the fix lives correctly in the nested-write layer, not just the
    top-level backend.
    """

    def test_nested_child_list_of_enum_persists_raw_values(self) -> None:
        """A nested reverse-FK create whose children have list[Enum] fields persists raw values.

        Exercises "_unwrap_enums" plus the backend inline unwrap end-to-end
        through a real reverse-FK nested create. This test breaks if either
        unwrap site regresses, leaving Enum members in the persisted
        payload.
        """
        result = _create(
            EnumListParentType,
            {
                "title": "deck",
                "swatches": [
                    {"name": "warm", "colors": ["red", "green"]},
                    {"name": "cool", "colors": ["blue"]},
                ],
            },
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        parent = EnumListParent.objects.get()
        self.assertEqual(parent.swatches.count(), 2)
        warm = parent.swatches.get(name="warm")
        cool = parent.swatches.get(name="cool")
        self.assertEqual(warm.colors, ["red", "green"])
        self.assertEqual(cool.colors, ["blue"])
        for child in (warm, cool):
            for value in child.colors:
                self.assertIsInstance(value, str)
                self.assertNotIsInstance(value, enum.Enum)
