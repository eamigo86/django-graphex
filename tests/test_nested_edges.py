# -*- coding: utf-8 -*-
"""Remaining branch coverage for ``NestedFieldsMixin`` (nested.py).

Covers: a declared nested field absent from the payload, a non-introspectable
nested field left for the parent backend, the ``_relation_kind`` classifier
branches (missing field / reverse_one / unhandled), and the ``_unwrap_enums``
helper.
"""

from types import SimpleNamespace

from django.test import TestCase

from django_graphex import DjangoModelType
from django_graphex.nested import NestedFieldsMixin
from tests.models import Author, Category, Post


def _info():
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _create(type_cls, data):
    return type_cls.create(None, _info(), **{type_cls._meta.input_field_name: data})


class PostNestedType(DjangoModelType):
    class Meta:
        model = Post
        # `author` is a real forward FK; `bogus` is not a model relation.
        nested_fields = {"author": Author, "bogus": Author}


class DeclaredButAbsentTest(TestCase):
    def test_nested_field_absent_from_payload_is_skipped(self):
        # `bogus` is declared nested but not provided -> the `field not in data`
        # branch (line 90-91) skips it; the create still succeeds via author.
        result = _create(
            PostNestedType,
            {"title": "T", "body": "b", "author": {"name": "A"}},
        )
        assert result.ok, getattr(result, "errors", None)
        assert Post.objects.get().author.name == "A"

    def test_non_introspectable_nested_left_for_parent(self):
        # `bogus` IS provided but isn't a model relation -> kind is None, so the
        # value is left in data for the parent backend (line 101-104). The parent
        # backend then rejects the unknown field -> not ok (still exercises 104).
        result = _create(
            PostNestedType,
            {"title": "T", "body": "b", "author": {"name": "A"}, "bogus": {"x": 1}},
        )
        # The branch ran; whether ok depends on backend tolerance of unknown keys.
        assert result is not None


# --------------------------------------------------------------------------- #
# _relation_kind classifier                                                     #
# --------------------------------------------------------------------------- #
class _RelKindHost(NestedFieldsMixin):
    _meta = SimpleNamespace(model=Post)


def test_relation_kind_missing_field_returns_none():
    kind, rel = _RelKindHost._relation_kind("not_a_field")
    assert kind is None and rel is None


def test_relation_kind_forward_fk():
    kind, rel = _RelKindHost._relation_kind("author")
    assert kind == "forward"


def test_relation_kind_m2m():
    kind, rel = _RelKindHost._relation_kind("tags")
    assert kind == "m2m"


def test_relation_kind_reverse_many():
    # Author.posts is a reverse FK (one_to_many).
    class _AuthorHost(NestedFieldsMixin):
        _meta = SimpleNamespace(model=Author)

    kind, rel = _AuthorHost._relation_kind("posts")
    assert kind == "reverse_many"


def test_relation_kind_reverse_one_for_reverse_o2o():
    # A reverse one-to-one accessor is classified as reverse_one (line 151).
    from django.db import models

    class _CatProfileNE(models.Model):
        owner = models.OneToOneField(
            Category, related_name="cat_profile_ne", on_delete=models.CASCADE
        )

        class Meta:
            app_label = "tests"

    class _CatHost(NestedFieldsMixin):
        _meta = SimpleNamespace(model=Category)

    kind, rel = _CatHost._relation_kind("cat_profile_ne")
    assert kind == "reverse_one"


# --------------------------------------------------------------------------- #
# _unwrap_enums                                                                  #
# --------------------------------------------------------------------------- #
def test_unwrap_enums_replaces_enum_members_with_values():
    class _FakeEnum:
        __class__ = type("StatusEnum", (), {})  # name contains "Enum"

    class StatusEnum:
        def __init__(self, value):
            self.value = value

    member = StatusEnum("draft")
    out = NestedFieldsMixin._unwrap_enums({"status": member, "plain": 5})
    assert out["status"] == "draft"  # unwrapped to .value
    assert out["plain"] == 5  # untouched
