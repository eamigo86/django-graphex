"""Remaining branch coverage for "NestedFieldsMixin" (nested.py).

Covers: a declared nested field absent from the payload, a non-introspectable
nested field left for the parent backend, the "_relation_kind" classifier
branches (missing field / reverse_one / unhandled), and the "_unwrap_enums"
helper.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from django.test import TestCase

from django_graphex.nested import NestedFieldsMixin
from django_graphex.types import DjangoModelType
from tests.models import Author, Category, Post


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


class PostNestedType(DjangoModelType):
    """Nested-fields type declaring one real relation and one bogus one.

    "author" is a real forward FK; "bogus" is not a model relation, so it
    exercises the non-introspectable-nested-field branch below.
    """

    class Meta:
        """Bind the type to "Post" with a mix of valid and bogus nested fields.

        "bogus" has no corresponding model relation on purpose.
        """

        model = Post
        nested_fields = {"author": Author, "bogus": Author}


class DeclaredButAbsentTest(TestCase):
    """Coverage for nested fields declared but absent from, or unmapped in, the payload.

    Exercises both the "field not in data" skip and the non-introspectable
    (non-relation) nested-key pass-through.
    """

    def test_nested_field_absent_from_payload_is_skipped(self) -> None:
        """A declared nested field missing from the payload is silently skipped.

        This test breaks if the "field not in data" guard stops short-circuiting,
        which would raise instead of letting the create proceed via "author".
        """
        result = _create(
            PostNestedType,
            {"title": "T", "body": "b", "author": {"name": "A"}},
        )
        assert result.ok, getattr(result, "errors", None)
        assert Post.objects.get().author.name == "A"

    def test_non_introspectable_nested_left_for_parent(self) -> None:
        """A nested key that is not a model relation is left in data for the parent backend.

        This test breaks if a non-relation nested key ("bogus") stops being
        passed through untouched, since the parent backend relies on silently
        ignoring unknown keys instead of the nested mixin failing on them.
        """
        result = _create(
            PostNestedType,
            {"title": "T", "body": "b", "author": {"name": "A"}, "bogus": {"x": 1}},
        )
        assert result.ok, getattr(result, "errors", None)
        post = Post.objects.get()
        assert post.title == "T"
        assert post.author.name == "A"


# --------------------------------------------------------------------------- #
# _relation_kind classifier                                                     #
# --------------------------------------------------------------------------- #
class _RelKindHost(NestedFieldsMixin):
    """Bare "NestedFieldsMixin" host bound to "Post", for classifier-only tests."""

    _meta = SimpleNamespace(model=Post)


def test_relation_kind_missing_field_returns_none() -> None:
    """A field name that does not exist on the model classifies as (None, None).

    This test breaks if the missing-field guard in "_relation_kind" stops
    returning a safe (None, None) pair and raises or misclassifies instead.
    """
    kind, rel = _RelKindHost._relation_kind("not_a_field")
    assert kind is None and rel is None


def test_relation_kind_forward_fk() -> None:
    """A forward ForeignKey field classifies as "forward".

    This test breaks if the forward-FK branch of "_relation_kind" stops
    being recognized correctly.
    """
    kind, rel = _RelKindHost._relation_kind("author")
    assert kind == "forward"


def test_relation_kind_m2m() -> None:
    """A many-to-many field classifies as "m2m".

    This test breaks if the many-to-many branch of "_relation_kind" stops
    being recognized correctly.
    """
    kind, rel = _RelKindHost._relation_kind("tags")
    assert kind == "m2m"


def test_relation_kind_reverse_many() -> None:
    """A reverse foreign key accessor classifies as "reverse_many".

    This test breaks if the one-to-many reverse-accessor branch of
    "_relation_kind" stops being recognized correctly ("Author.posts" is a
    reverse FK).
    """

    class _AuthorHost(NestedFieldsMixin):
        """Bare "NestedFieldsMixin" host bound to "Author" for this test."""

        _meta = SimpleNamespace(model=Author)

    kind, rel = _AuthorHost._relation_kind("posts")
    assert kind == "reverse_many"


def test_relation_kind_reverse_one_for_reverse_o2o() -> None:
    """A reverse one-to-one accessor classifies as "reverse_one".

    This test breaks if the reverse-one-to-one branch of "_relation_kind"
    stops being recognized correctly.
    """
    from django.db import models

    class _CatProfileNE(models.Model):
        """Throwaway model declaring a reverse one-to-one onto "Category"."""

        owner = models.OneToOneField(
            Category, related_name="cat_profile_ne", on_delete=models.CASCADE
        )

        class Meta:
            """Register the throwaway model under the "tests" app label."""

            app_label = "tests"

    class _CatHost(NestedFieldsMixin):
        """Bare "NestedFieldsMixin" host bound to "Category" for this test."""

        _meta = SimpleNamespace(model=Category)

    kind, rel = _CatHost._relation_kind("cat_profile_ne")
    assert kind == "reverse_one"


# --------------------------------------------------------------------------- #
# _unwrap_enums                                                                  #
# --------------------------------------------------------------------------- #
def test_unwrap_enums_replaces_enum_members_with_values() -> None:
    """ "_unwrap_enums" replaces enum members with their ".value" and leaves plain values untouched.

    This test breaks if enum members stop being unwrapped to their raw value,
    or if non-enum values get mutated in the process.
    """
    import enum

    class StatusEnum(enum.Enum):
        """Throwaway status enum used only to exercise unwrapping."""

        DRAFT = "draft"
        PUBLISHED = "published"

    member = StatusEnum.DRAFT
    out = NestedFieldsMixin._unwrap_enums({"status": member, "plain": 5})
    assert out["status"] == "draft"  # unwrapped to .value
    assert out["plain"] == 5  # untouched
