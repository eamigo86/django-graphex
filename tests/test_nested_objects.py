"""Atomic, relation-aware nested create/update via NestedFieldsMixin."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from django.test import TestCase

from django_graphex.types import DjangoModelType
from tests.models import NestedObjAuthor, NestedObjPost, NestedObjTag

# NOTE: these DjangoModelType subclasses are built over DEDICATED models
# (NestedObjAuthor / NestedObjPost / NestedObjTag), not the shared Author /
# Post / Tag models. DjangoModelType always self-registers on the GLOBAL
# registry (it rejects both Meta.registry and Meta.skip_registry), so wrapping
# a shared model here would auto-derive globally-named companion output types
# that collide with same-named companions other test modules build over the
# same shared models. See tests/models.py for the dedicated model definitions.


class PostForwardType(DjangoModelType):
    """ "NestedObjPost" type exposing "author" as a nested forward-FK field.

    Used by the forward-FK create/update/rollback tests below.
    """

    class Meta:
        """Bind the type to "NestedObjPost" with "author" declared as nested.

        No extra options are needed for these forward-FK tests.
        """

        model = NestedObjPost
        nested_fields = {"author": NestedObjAuthor}


class PostM2MType(DjangoModelType):
    """ "NestedObjPost" type exposing "tags" as a nested many-to-many field.

    Used by the many-to-many create and empty-payload tests below.
    """

    class Meta:
        """Bind the type to "NestedObjPost" with "tags" declared as nested.

        No extra options are needed for these many-to-many tests.
        """

        model = NestedObjPost
        nested_fields = {"tags": NestedObjTag}


class AuthorReverseType(DjangoModelType):
    """ "NestedObjAuthor" type exposing "nested_obj_posts" as a nested reverse-FK field.

    Used by the reverse-FK create and rollback tests below.
    """

    class Meta:
        """Bind the type to "NestedObjAuthor" with "nested_obj_posts" declared as nested.

        No extra options are needed for these reverse-FK tests.
        """

        model = NestedObjAuthor
        nested_fields = {"nested_obj_posts": NestedObjPost}


def _info() -> SimpleNamespace:
    """Build a minimal resolve info exposing only what CRUD reads.

    Returns:
        An object shaped like a GraphQL resolve info, with a "context"
        carrying empty "META" and "FILES" (the only attributes CRUD reads).
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
    kwargs = {type_cls._meta.input_field_name: data}
    return type_cls.create(None, _info(), **kwargs)


def _update(type_cls: type[DjangoModelType], data: dict[str, Any]) -> Any:
    """Invoke the generated "update" mutation for a "DjangoModelType" subclass.

    Args:
        type_cls: The "DjangoModelType" subclass whose mutation is invoked.
        data: The input payload keyed by the type's input field name.

    Returns:
        The mutation result object (exposes "ok" and, on failure, "errors").
    """
    kwargs = {type_cls._meta.input_field_name: data}
    return type_cls.update(None, _info(), **kwargs)


class ForwardFKTest(TestCase):
    """Coverage for creating and validating a nested forward-FK child.

    Covers the happy path, parent-failure rollback, and error prefixing.
    """

    def test_creates_and_links_forward_fk_child(self) -> None:
        """Creating a parent with a nested forward-FK payload persists and links the child.

        This test breaks if the forward-FK nested create stops persisting the
        child "author" row or stops linking it to the parent "post".
        """
        result = _create(
            PostForwardType, {"title": "Hello", "author": {"name": "Neil"}}
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(NestedObjAuthor.objects.count(), 1)
        post = NestedObjPost.objects.get()
        self.assertEqual(post.title, "Hello")
        self.assertEqual(post.author.name, "Neil")

    def test_parent_failure_rolls_back_child(self) -> None:
        """A required-field failure on the parent rolls back the already-persisted child.

        "title" is required, so the parent is invalid; this test breaks if the
        forward-FK child ("author") is left persisted despite the parent
        create failing, i.e. if the operation stops being atomic.
        """
        result = _create(PostForwardType, {"author": {"name": "Orphan"}})
        self.assertFalse(result.ok)
        self.assertEqual(NestedObjAuthor.objects.count(), 0)
        self.assertEqual(NestedObjPost.objects.count(), 0)

    def test_nested_validation_error_is_prefixed(self) -> None:
        """A validation error on a nested child is reported under a "author.name"-prefixed field.

        This test breaks if nested-child validation errors stop being
        prefixed with the parent field name, making it impossible to tell
        which nested object failed.
        """
        result = _create(PostForwardType, {"title": "x", "author": {"name": "a" * 200}})
        self.assertFalse(result.ok)
        fields = {e.field for e in result.errors}
        self.assertIn("author.name", fields)
        self.assertEqual(NestedObjAuthor.objects.count(), 0)


class M2MTest(TestCase):
    """Coverage for creating and linking nested many-to-many children.

    Confirms every child in the list is persisted and linked to the parent.
    """

    def test_creates_and_adds_m2m_children(self) -> None:
        """Creating a parent with a nested many-to-many payload persists and links every child.

        This test breaks if nested many-to-many children stop being created
        or stop being added to the parent's relation manager.
        """
        author = NestedObjAuthor.objects.create(name="A")
        result = _create(
            PostM2MType,
            {
                "title": "Tagged",
                "author": author.id,
                "tags": [{"label": "django"}, {"label": "graphql"}],
            },
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(NestedObjTag.objects.count(), 2)
        post = NestedObjPost.objects.get()
        self.assertEqual(
            set(post.tags.values_list("label", flat=True)), {"django", "graphql"}
        )


class ReverseFKTest(TestCase):
    """Coverage for creating and validating nested reverse-FK children.

    Covers the happy path and the atomic rollback on child validation failure.
    """

    def test_creates_reverse_fk_children_linked_to_parent(self) -> None:
        """Creating a parent with a nested reverse-FK payload persists and links every child.

        This test breaks if nested reverse-FK children stop being created or
        stop being linked back to the newly created parent.
        """
        result = _create(
            AuthorReverseType,
            {
                "name": "Writer",
                "nested_obj_posts": [{"title": "P1"}, {"title": "P2"}],
            },
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        author = NestedObjAuthor.objects.get()
        self.assertEqual(author.nested_obj_posts.count(), 2)
        self.assertEqual(
            set(author.nested_obj_posts.values_list("title", flat=True)),
            {"P1", "P2"},
        )

    def test_reverse_child_failure_rolls_back_parent(self) -> None:
        """A validation failure on one reverse-FK child rolls back the whole create, including the parent.

        This test breaks if the operation stops being atomic, i.e. if the
        parent "author" (or a sibling "post") remains persisted despite one
        nested child failing validation.
        """
        result = _create(
            AuthorReverseType,
            {
                "name": "Writer",
                "nested_obj_posts": [{"title": "ok"}, {"body": "no title"}],
            },
        )
        self.assertFalse(result.ok)
        self.assertEqual(NestedObjAuthor.objects.count(), 0)
        self.assertEqual(NestedObjPost.objects.count(), 0)


class UpsertTest(TestCase):
    """Coverage for updating an existing nested child by its primary key.

    Confirms an "id" in the nested payload updates in place instead of
    creating a duplicate.
    """

    def test_update_with_child_pk_updates_existing_child(self) -> None:
        """Updating a parent with a nested child payload carrying an "id" updates that child in place.

        This test breaks if supplying a child "id" in the nested payload
        stops updating the existing row and instead creates a duplicate.
        """
        author = NestedObjAuthor.objects.create(name="Old")
        post = NestedObjPost.objects.create(title="T", author=author)

        result = _update(
            PostForwardType,
            {"id": post.id, "author": {"id": author.id, "name": "New"}},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(NestedObjAuthor.objects.count(), 1)  # no new author
        author.refresh_from_db()
        self.assertEqual(author.name, "New")


class EmptyPayloadTest(TestCase):
    """Coverage for an empty nested many-to-many payload.

    Confirms an empty list is a genuine no-op, not an error or a placeholder
    create.
    """

    def test_empty_m2m_payload_is_noop(self) -> None:
        """An empty "tags" list creates the parent without creating or linking any tags.

        This test breaks if an empty nested many-to-many list stops being a
        no-op, e.g. by raising or by unexpectedly creating placeholder rows.
        """
        author = NestedObjAuthor.objects.create(name="A")
        result = _create(
            PostM2MType, {"title": "NoTags", "author": author.id, "tags": []}
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(NestedObjTag.objects.count(), 0)
        self.assertEqual(NestedObjPost.objects.get().tags.count(), 0)
