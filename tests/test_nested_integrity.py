# -*- coding: utf-8 -*-
"""Integrity and safety tests for the nested-write layer (issue #62).

Four gaps fixed:
  (a) M2M non-existent pk -> structured ErrorType, not IntegrityError 500.
  (b) Reverse-FK child ownership check: cannot re-parent a child belonging
      to a different parent (steal prevention).
  (c) Reverse-O2O given a list of >1 -> clean _NestedError, not IntegrityError.
  (d) Forward FK/O2O given a multi-element list -> clean _NestedError.
"""

from types import SimpleNamespace

from django.test import TestCase

from django_graphex import DjangoModelType
from tests.models import Author, AuthorProfile, Post, Tag


def _info():
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _create(type_cls, data):
    kwargs = {type_cls._meta.input_field_name: data}
    return type_cls.create(None, _info(), **kwargs)


def _update(type_cls, data):
    kwargs = {type_cls._meta.input_field_name: data}
    return type_cls.update(None, _info(), **kwargs)


# ---------------------------------------------------------------------------
# (a) M2M non-existent pk -> ErrorType (not 500 / IntegrityError)
#
# The M2M bad-pk validation lives in the *parent* backend's _db_check_errors.
# It fires when tags are passed as raw pk ints directly (not as nested dicts
# via nested_fields).  The type below intentionally omits "tags" from
# nested_fields so tags arrive as raw pk lists through the Pydantic schema.
# ---------------------------------------------------------------------------


class PostM2MRawPkType(DjangoModelType):
    """Post type with NO nested_fields for tags — tags sent as raw pk lists."""

    class Meta:
        model = Post
        # tags NOT in nested_fields -> pks flow through Pydantic -> _db_check_errors
        nested_fields = {}


class M2MBadPkTest(TestCase):
    """Sending a non-existent M2M pk must return a structured error, not 500."""

    def _make_author(self):
        return Author.objects.create(name="Author")

    def test_m2m_nonexistent_pk_returns_error_type(self):
        author = self._make_author()
        # tags=[9999] — tag pk 9999 does not exist; expect ErrorType not 500
        result = _create(
            PostM2MRawPkType,
            {"title": "T", "author": author.id, "tags": [9999]},
        )
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.errors)
        # Verify no post was created (transaction rolled back or validation caught it)
        self.assertEqual(Post.objects.count(), 0)

    def test_m2m_existing_pk_succeeds(self):
        author = self._make_author()
        tag = Tag.objects.create(label="real")
        result = _create(
            PostM2MRawPkType,
            {"title": "T", "author": author.id, "tags": [tag.id]},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(Post.objects.get().tags.count(), 1)

    def test_m2m_mixed_pks_returns_error_for_missing(self):
        author = self._make_author()
        tag = Tag.objects.create(label="real")
        # One real, one non-existent
        result = _create(
            PostM2MRawPkType,
            {"title": "T", "author": author.id, "tags": [tag.id, 9999]},
        )
        self.assertFalse(result.ok)
        self.assertEqual(Post.objects.count(), 0)


# ---------------------------------------------------------------------------
# (b) Reverse-FK ownership guard — child-steal prevention
# ---------------------------------------------------------------------------


class AuthorWithPostsType(DjangoModelType):
    class Meta:
        model = Author
        nested_fields = {"posts": Post}


class ReverseFKOwnershipTest(TestCase):
    """Upserting a reverse-FK child by pk must refuse if that child belongs
    to a different parent."""

    def setUp(self):
        self.author1 = Author.objects.create(name="Author1")
        self.author2 = Author.objects.create(name="Author2")
        self.post = Post.objects.create(title="Owned by 1", author=self.author1)

    def test_cannot_steal_child_from_another_parent(self):
        # Try to upsert post (owned by author1) via author2's update
        result = _update(
            AuthorWithPostsType,
            {
                "id": self.author2.id,
                "posts": [{"id": self.post.id, "title": "Stolen"}],
            },
        )
        self.assertFalse(result.ok)
        # The post must still belong to author1
        self.post.refresh_from_db()
        self.assertEqual(self.post.author_id, self.author1.id)
        self.assertEqual(self.post.title, "Owned by 1")

    def test_can_update_own_child(self):
        # Upserting a child that already belongs to the target parent is fine
        result = _update(
            AuthorWithPostsType,
            {
                "id": self.author1.id,
                "posts": [{"id": self.post.id, "title": "Updated"}],
            },
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.post.refresh_from_db()
        self.assertEqual(self.post.title, "Updated")
        self.assertEqual(self.post.author_id, self.author1.id)

    def test_can_create_new_reverse_child(self):
        # No pk -> always create, no ownership issue
        result = _update(
            AuthorWithPostsType,
            {
                "id": self.author1.id,
                "posts": [{"title": "Brand new"}],
            },
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(self.author1.posts.count(), 2)


# ---------------------------------------------------------------------------
# (c) Reverse-O2O given a list of >1 -> clean error
# ---------------------------------------------------------------------------


class AuthorWithProfileType(DjangoModelType):
    class Meta:
        model = Author
        nested_fields = {"author_profile": AuthorProfile}


class ReverseO2OListTest(TestCase):
    """A reverse OneToOne field given a list of more than one item must raise a
    clean error, not an IntegrityError 500."""

    def test_reverse_o2o_list_gt1_returns_error(self):
        result = _create(
            AuthorWithProfileType,
            {
                "name": "Writer",
                # Two profile dicts for a OneToOne -> must be rejected cleanly
                "author_profile": [{"bio": "bio1"}, {"bio": "bio2"}],
            },
        )
        self.assertFalse(result.ok)
        self.assertEqual(Author.objects.count(), 0)
        self.assertEqual(AuthorProfile.objects.count(), 0)

    def test_reverse_o2o_single_dict_succeeds(self):
        result = _create(
            AuthorWithProfileType,
            {"name": "Writer", "author_profile": {"bio": "single bio"}},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(Author.objects.count(), 1)
        self.assertEqual(AuthorProfile.objects.count(), 1)

    def test_reverse_o2o_single_item_list_succeeds(self):
        # A list of exactly 1 is accepted (equivalent to a single dict)
        result = _create(
            AuthorWithProfileType,
            {"name": "Writer", "author_profile": [{"bio": "single bio"}]},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(AuthorProfile.objects.count(), 1)


# ---------------------------------------------------------------------------
# (d) Forward FK/O2O given a multi-element list -> clean error
# ---------------------------------------------------------------------------


class PostForwardNestedType(DjangoModelType):
    class Meta:
        model = Post
        nested_fields = {"author": Author}


class ForwardFKListTest(TestCase):
    """Forward FK nested field given a list of >1 must raise a clean error,
    not silently discard extra items."""

    def test_forward_fk_list_gt1_returns_error(self):
        result = _create(
            PostForwardNestedType,
            {
                "title": "T",
                # Two author dicts for a forward FK -> must be rejected cleanly
                "author": [{"name": "Alice"}, {"name": "Bob"}],
            },
        )
        self.assertFalse(result.ok)
        self.assertEqual(Post.objects.count(), 0)
        # No author should have been created (atomic rollback)
        self.assertEqual(Author.objects.count(), 0)

    def test_forward_fk_single_item_list_accepted(self):
        # A list of exactly 1 is accepted (degenerate list == scalar)
        result = _create(
            PostForwardNestedType,
            {"title": "T", "author": [{"name": "Solo"}]},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(Author.objects.count(), 1)

    def test_forward_fk_scalar_dict_succeeds(self):
        result = _create(
            PostForwardNestedType,
            {"title": "T", "author": {"name": "Alice"}},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(Author.objects.count(), 1)
