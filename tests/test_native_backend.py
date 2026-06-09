# -*- coding: utf-8 -*-
"""Native (Pydantic) backend: Meta.model types, no DRF involved."""

import decimal
from types import SimpleNamespace

from django.db import models
from django.test import TestCase
from pydantic import BaseModel, field_validator

from django_graphex import DjangoModelType
from django_graphex.native.backend import PydanticBackend
from tests.models import DummyModel, Tag


class NativeCategory(DummyModel):
    name = models.CharField(max_length=50, unique=True)


class NativeProduct(DummyModel):
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
    class Meta:
        model = NativeProduct


def _info():
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _create(type_cls, data):
    return type_cls.create(None, _info(), **{type_cls._meta.input_field_name: data})


def _update(type_cls, data):
    return type_cls.update(None, _info(), **{type_cls._meta.input_field_name: data})


class BackendWiringTest(TestCase):
    def test_meta_model_selects_native_backend(self):
        self.assertIsInstance(NativeProductType._meta.backend, PydanticBackend)
        self.assertIs(NativeProductType._meta.model, NativeProduct)


class NativeCrudTest(TestCase):
    def test_create_valid(self):
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

    def test_default_applied(self):
        result = _create(NativeProductType, {"sku": "B1", "name": "n", "price": "1.0"})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(NativeProduct.objects.get().status, "draft")

    def test_max_length_error(self):
        result = _create(
            NativeProductType, {"sku": "TOOLONGSKU", "name": "n", "price": "1.0"}
        )
        # sku max_length is 10; "TOOLONGSKU" is exactly 10 -> ok. Use 11.
        result = _create(
            NativeProductType, {"sku": "TOOLONGSKU1", "name": "n", "price": "1.0"}
        )
        self.assertFalse(result.ok)
        self.assertIn("sku", {e.field for e in result.errors})

    def test_invalid_choice(self):
        result = _create(
            NativeProductType,
            {"sku": "C1", "name": "n", "price": "1.0", "status": "bogus"},
        )
        self.assertFalse(result.ok)
        self.assertIn("status", {e.field for e in result.errors})

    def test_fk_does_not_exist(self):
        result = _create(
            NativeProductType,
            {"sku": "E1", "name": "n", "price": "1.0", "category": 9999},
        )
        self.assertFalse(result.ok)
        self.assertIn("category", {e.field for e in result.errors})

    def test_unique_violation(self):
        NativeProduct.objects.create(sku="UNIQ", name="n", price=decimal.Decimal("1"))
        result = _create(
            NativeProductType, {"sku": "UNIQ", "name": "n2", "price": "2.0"}
        )
        self.assertFalse(result.ok)
        self.assertIn("sku", {e.field for e in result.errors})

    def test_required_missing(self):
        result = _create(NativeProductType, {"sku": "D1"})
        self.assertFalse(result.ok)
        self.assertLessEqual({"name", "price"}, {e.field for e in result.errors})

    def test_partial_update(self):
        obj = NativeProduct.objects.create(
            sku="F1", name="old", price=decimal.Decimal("1")
        )
        result = _update(NativeProductType, {"id": obj.id, "name": "new"})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        obj.refresh_from_db()
        self.assertEqual(obj.name, "new")
        self.assertEqual(obj.sku, "F1")

    def test_delete_missing(self):
        result = NativeProductType.delete(None, _info(), id=999)
        self.assertFalse(result.ok)
        self.assertIn("does not exist", result.errors[0].messages[0])


class ToRepresentationTest(TestCase):
    def test_output_dict(self):
        cat = NativeCategory.objects.create(name="c")
        obj = NativeProduct.objects.create(
            sku="G1", name="n", price=decimal.Decimal("3"), category=cat
        )
        data = PydanticBackend(NativeProduct).to_representation(obj)
        self.assertEqual(data["sku"], "G1")
        self.assertEqual(data["category"], cat.pk)
        self.assertEqual(data["tags"], [])


class CustomValidatorBase(BaseModel):
    # `sku` is added by the derived schema, so the base must not check_fields.
    @field_validator("sku", check_fields=False)
    @classmethod
    def _no_x(cls, value):
        if isinstance(value, str) and value.startswith("X"):
            raise ValueError("sku must not start with X")
        return value


class CustomValidatorType(DjangoModelType):
    class Meta:
        model = NativeProduct
        pydantic_model = CustomValidatorBase


class PydanticModelHookTest(TestCase):
    def test_custom_validator_runs(self):
        result = _create(
            CustomValidatorType, {"sku": "X9", "name": "n", "price": "1.0"}
        )
        self.assertFalse(result.ok)
        self.assertIn("sku", {e.field for e in result.errors})


# -- native nested writes (children declared as MODELS, no DRF) --------------- #
class NativeForwardType(DjangoModelType):
    class Meta:
        model = NativeProduct
        nested_fields = {"category": NativeCategory}  # native forward FK child


class NativeM2MType(DjangoModelType):
    class Meta:
        model = NativeProduct
        nested_fields = {"tags": Tag}  # native M2M child


class NativeReverseType(DjangoModelType):
    class Meta:
        model = NativeCategory
        nested_fields = {"products": NativeProduct}  # native reverse-FK children


class NativeNestedTest(TestCase):
    def test_forward_fk_creates_and_links(self):
        result = _create(
            NativeForwardType,
            {"sku": "P1", "name": "n", "price": "1.0", "category": {"name": "new-cat"}},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(NativeCategory.objects.count(), 1)
        self.assertEqual(NativeProduct.objects.get().category.name, "new-cat")

    def test_forward_fk_failure_rolls_back(self):
        # missing required name/price on the parent -> nothing persists.
        result = _create(NativeForwardType, {"category": {"name": "orphan"}})
        self.assertFalse(result.ok)
        self.assertEqual(NativeCategory.objects.count(), 0)
        self.assertEqual(NativeProduct.objects.count(), 0)

    def test_m2m_creates_and_adds(self):
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

    def test_reverse_fk_links_children_to_parent(self):
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
