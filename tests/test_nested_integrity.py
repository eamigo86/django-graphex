"""Integrity and safety tests for the nested-write layer (issue #62).

Five gaps fixed:
  (a) M2M non-existent pk -> structured ErrorType, not IntegrityError 500.
  (b) Reverse-FK child ownership check: cannot re-parent a child belonging
      to a different parent (steal prevention).
  (c) Reverse-O2O given a list of >1 -> clean _NestedError, not IntegrityError.
  (d) Forward FK/O2O given a multi-element list -> clean _NestedError.
  (e) Reverse-O2O child ownership check: the same steal prevention as (b),
      plus per-kind coverage of every relation kind the nested writer
      supports.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from django.test import TestCase

from django_graphex.types import DjangoModelType
from tests.models import (
    NestedIntegrityAuthor,
    NestedIntegrityPost,
    NestedIntegrityProfile,
    NestedIntegrityTag,
)

# NOTE: these DjangoModelType subclasses are built over DEDICATED models
# (NestedIntegrityAuthor / NestedIntegrityPost / NestedIntegrityTag /
# NestedIntegrityProfile), not the shared Author / Post / Tag / AuthorProfile
# models. DjangoModelType always self-registers on the GLOBAL registry (it
# rejects both Meta.registry and Meta.skip_registry), so wrapping a shared
# model here would auto-derive globally-named companion output types that
# collide with same-named companions other test modules build over the same
# shared models. See tests/models.py for the dedicated model definitions.


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


# ---------------------------------------------------------------------------
# (a) M2M non-existent pk -> ErrorType (not 500 / IntegrityError)
#
# The M2M bad-pk validation lives in the *parent* backend's _db_check_errors.
# It fires when tags are passed as raw pk ints directly (not as nested dicts
# via nested_fields).  The type below intentionally omits "tags" from
# nested_fields so tags arrive as raw pk lists through the Pydantic schema.
# ---------------------------------------------------------------------------


class PostM2MRawPkType(DjangoModelType):
    """ "NestedIntegrityPost" type with no "nested_fields" for "tags" — tags sent as raw pk lists.

    Used to exercise the parent backend's pk-existence check rather than the
    nested-fields write path.
    """

    class Meta:
        """Bind the type to "NestedIntegrityPost" with an empty "nested_fields" mapping.

        "tags" is intentionally absent so pks flow through Pydantic straight
        into "_db_check_errors".
        """

        model = NestedIntegrityPost
        nested_fields = {}


class M2MBadPkTest(TestCase):
    """Sending a non-existent M2M pk must return a structured error, not 500.

    Also covers the existing-pk and mixed-pks companion cases.
    """

    def _make_author(self) -> NestedIntegrityAuthor:
        """Create a throwaway "NestedIntegrityAuthor" row for the M2M bad-pk tests.

        Returns:
            The newly created "NestedIntegrityAuthor" instance.
        """
        return NestedIntegrityAuthor.objects.create(name="Author")

    def test_m2m_nonexistent_pk_returns_error_type(self) -> None:
        """A non-existent tag pk in the M2M list yields a structured error, not a 500.

        This test breaks if an unknown many-to-many pk stops being caught by
        "_db_check_errors" and instead raises an uncaught "IntegrityError".
        """
        author = self._make_author()
        # tags=[9999] — tag pk 9999 does not exist; expect ErrorType not 500
        result = _create(
            PostM2MRawPkType,
            {"title": "T", "author": author.id, "tags": [9999]},
        )
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.errors)
        # Verify no post was created (transaction rolled back or validation caught it)
        self.assertEqual(NestedIntegrityPost.objects.count(), 0)

    def test_m2m_existing_pk_succeeds(self) -> None:
        """An existing tag pk in the M2M list succeeds and links the tag.

        This test breaks if the pk-existence check starts rejecting valid,
        pre-existing tag pks.
        """
        author = self._make_author()
        tag = NestedIntegrityTag.objects.create(label="real")
        result = _create(
            PostM2MRawPkType,
            {"title": "T", "author": author.id, "tags": [tag.id]},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(NestedIntegrityPost.objects.get().tags.count(), 1)

    def test_m2m_mixed_pks_returns_error_for_missing(self) -> None:
        """A mix of one valid and one non-existent tag pk fails the whole create.

        This test breaks if the presence of at least one valid pk causes the
        missing-pk check to be skipped for the rest of the list.
        """
        author = self._make_author()
        tag = NestedIntegrityTag.objects.create(label="real")
        # One real, one non-existent
        result = _create(
            PostM2MRawPkType,
            {"title": "T", "author": author.id, "tags": [tag.id, 9999]},
        )
        self.assertFalse(result.ok)
        self.assertEqual(NestedIntegrityPost.objects.count(), 0)


# ---------------------------------------------------------------------------
# (b) Reverse-FK ownership guard — child-steal prevention
# ---------------------------------------------------------------------------


class AuthorWithPostsType(DjangoModelType):
    """ "NestedIntegrityAuthor" type exposing "nested_integrity_posts" as a nested reverse-FK field.

    Used by the ownership-guard (child-steal prevention) tests below.
    """

    class Meta:
        """Bind the type to "NestedIntegrityAuthor" with "nested_integrity_posts" declared as nested.

        No extra options are needed for these ownership-guard tests.
        """

        model = NestedIntegrityAuthor
        nested_fields = {"nested_integrity_posts": NestedIntegrityPost}


class ReverseFKOwnershipTest(TestCase):
    """Upserting a reverse-FK child by pk must refuse to re-parent it.

    Refuses whenever that child already belongs to a different parent.
    """

    def setUp(self) -> None:
        """Create two authors and a post owned by the first author.

        Sets up the fixtures shared by the ownership-guard tests below.
        """
        self.author1 = NestedIntegrityAuthor.objects.create(name="Author1")
        self.author2 = NestedIntegrityAuthor.objects.create(name="Author2")
        self.post = NestedIntegrityPost.objects.create(
            title="Owned by 1", author=self.author1
        )

    def test_cannot_steal_child_from_another_parent(self) -> None:
        """Upserting another parent's reverse-FK child by pk is rejected.

        This test breaks if the ownership guard stops rejecting an attempt to
        re-parent "self.post" (owned by "author1") through "author2"'s update,
        silently allowing the child to be stolen.
        """
        # Try to upsert post (owned by author1) via author2's update
        result = _update(
            AuthorWithPostsType,
            {
                "id": self.author2.id,
                "nested_integrity_posts": [{"id": self.post.id, "title": "Stolen"}],
            },
        )
        self.assertFalse(result.ok)
        # The post must still belong to author1
        self.post.refresh_from_db()
        self.assertEqual(self.post.author_id, self.author1.id)
        self.assertEqual(self.post.title, "Owned by 1")

    def test_can_update_own_child(self) -> None:
        """Upserting a reverse-FK child that already belongs to the target parent succeeds.

        This test breaks if the ownership guard starts rejecting legitimate
        updates to a child the parent already owns.
        """
        # Upserting a child that already belongs to the target parent is fine
        result = _update(
            AuthorWithPostsType,
            {
                "id": self.author1.id,
                "nested_integrity_posts": [{"id": self.post.id, "title": "Updated"}],
            },
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.post.refresh_from_db()
        self.assertEqual(self.post.title, "Updated")
        self.assertEqual(self.post.author_id, self.author1.id)

    def test_can_create_new_reverse_child(self) -> None:
        """A reverse-FK child payload without a pk always creates a new child.

        This test breaks if the ownership guard incorrectly fires for
        pk-less (create) payloads, which can never collide with another
        parent's existing child.
        """
        # No pk -> always create, no ownership issue
        result = _update(
            AuthorWithPostsType,
            {
                "id": self.author1.id,
                "nested_integrity_posts": [{"title": "Brand new"}],
            },
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(self.author1.nested_integrity_posts.count(), 2)


# ---------------------------------------------------------------------------
# (c) Reverse-O2O given a list of >1 -> clean error
# ---------------------------------------------------------------------------


class AuthorWithProfileType(DjangoModelType):
    """ "NestedIntegrityAuthor" type exposing "author_profile" as a nested reverse-O2O field.

    Used by the reverse-one-to-one list-arity tests below.
    """

    class Meta:
        """Bind the type to "NestedIntegrityAuthor" with "author_profile" declared as nested.

        No extra options are needed for these reverse-O2O tests.
        """

        model = NestedIntegrityAuthor
        nested_fields = {"author_profile": NestedIntegrityProfile}


class ReverseO2OListTest(TestCase):
    """A reverse OneToOne field given a list of more than one item must raise cleanly.

    It must produce a structured error, not an "IntegrityError" 500.
    """

    def test_reverse_o2o_list_gt1_returns_error(self) -> None:
        """A reverse-O2O payload with two profile dicts is rejected cleanly.

        This test breaks if a multi-item list for a one-to-one relation stops
        being rejected up front and instead reaches the database, surfacing
        as an uncaught "IntegrityError".
        """
        result = _create(
            AuthorWithProfileType,
            {
                "name": "Writer",
                # Two profile dicts for a OneToOne -> must be rejected cleanly
                "author_profile": [{"bio": "bio1"}, {"bio": "bio2"}],
            },
        )
        self.assertFalse(result.ok)
        self.assertEqual(NestedIntegrityAuthor.objects.count(), 0)
        self.assertEqual(NestedIntegrityProfile.objects.count(), 0)

    def test_reverse_o2o_single_dict_succeeds(self) -> None:
        """A reverse-O2O payload given as a single dict succeeds.

        This test breaks if the scalar-dict form for a one-to-one relation
        stops being accepted.
        """
        result = _create(
            AuthorWithProfileType,
            {"name": "Writer", "author_profile": {"bio": "single bio"}},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(NestedIntegrityAuthor.objects.count(), 1)
        self.assertEqual(NestedIntegrityProfile.objects.count(), 1)

    def test_reverse_o2o_single_item_list_succeeds(self) -> None:
        """A reverse-O2O payload given as a single-item list is accepted like a scalar dict.

        This test breaks if a degenerate one-item list stops being treated
        as equivalent to a bare dict for a one-to-one relation.
        """
        # A list of exactly 1 is accepted (equivalent to a single dict)
        result = _create(
            AuthorWithProfileType,
            {"name": "Writer", "author_profile": [{"bio": "single bio"}]},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(NestedIntegrityProfile.objects.count(), 1)


# ---------------------------------------------------------------------------
# (d) Forward FK/O2O given a multi-element list -> clean error
# ---------------------------------------------------------------------------


class PostForwardNestedType(DjangoModelType):
    """ "NestedIntegrityPost" type exposing "author" as a nested forward-FK field.

    Used by the forward-FK list-arity tests below.
    """

    class Meta:
        """Bind the type to "NestedIntegrityPost" with "author" declared as nested.

        No extra options are needed for these forward-FK list-arity tests.
        """

        model = NestedIntegrityPost
        nested_fields = {"author": NestedIntegrityAuthor}


class ForwardFKListTest(TestCase):
    """A forward FK nested field given a list of more than one item must raise cleanly.

    It must not silently discard the extra items.
    """

    def test_forward_fk_list_gt1_returns_error(self) -> None:
        """A forward-FK payload with two author dicts is rejected cleanly.

        This test breaks if a multi-item list for a forward FK stops being
        rejected up front, e.g. by silently picking one item and discarding
        the rest, or by leaking a partially-created author.
        """
        result = _create(
            PostForwardNestedType,
            {
                "title": "T",
                # Two author dicts for a forward FK -> must be rejected cleanly
                "author": [{"name": "Alice"}, {"name": "Bob"}],
            },
        )
        self.assertFalse(result.ok)
        self.assertEqual(NestedIntegrityPost.objects.count(), 0)
        # No author should have been created (atomic rollback)
        self.assertEqual(NestedIntegrityAuthor.objects.count(), 0)

    def test_forward_fk_single_item_list_accepted(self) -> None:
        """A forward-FK payload given as a single-item list is accepted like a scalar dict.

        This test breaks if a degenerate one-item list stops being treated
        as equivalent to a bare dict for a forward FK relation.
        """
        # A list of exactly 1 is accepted (degenerate list == scalar)
        result = _create(
            PostForwardNestedType,
            {"title": "T", "author": [{"name": "Solo"}]},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(NestedIntegrityAuthor.objects.count(), 1)

    def test_forward_fk_scalar_dict_succeeds(self) -> None:
        """A forward-FK payload given as a plain dict succeeds.

        This test breaks if the baseline scalar-dict form for a forward FK
        relation stops being accepted.
        """
        result = _create(
            PostForwardNestedType,
            {"title": "T", "author": {"name": "Alice"}},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(NestedIntegrityAuthor.objects.count(), 1)


# ---------------------------------------------------------------------------
# (e) Reverse-O2O ownership guard + per-kind coverage
# ---------------------------------------------------------------------------


class PostM2MNestedType(DjangoModelType):
    """ "NestedIntegrityPost" type exposing "tags" as a nested M2M field.

    Used by the per-kind ownership coverage tests below.
    """

    class Meta:
        """Bind the type to "NestedIntegrityPost" with "tags" declared as nested.

        No extra options are needed for these M2M coverage tests.
        """

        model = NestedIntegrityPost
        nested_fields = {"tags": NestedIntegrityTag}


class ReverseO2OOwnershipTest(TestCase):
    """Upserting a reverse-O2O child by pk must refuse to re-parent it.

    The reverse one-to-one path must behave exactly like the reverse-FK path:
    a child that already belongs to another parent cannot be stolen, and the
    rejection is indistinguishable from the reverse-FK rejection.
    """

    def setUp(self) -> None:
        """Create two authors and a profile owned by the first author.

        Sets up the fixtures shared by the reverse-O2O ownership tests below.
        """
        self.author1 = NestedIntegrityAuthor.objects.create(name="Author1")
        self.author2 = NestedIntegrityAuthor.objects.create(name="Author2")
        self.profile = NestedIntegrityProfile.objects.create(
            author=self.author1, bio="Owned by 1"
        )

    def test_cannot_steal_reverse_o2o_child_from_another_parent(self) -> None:
        """Upserting another parent's reverse-O2O child by pk is rejected.

        This test breaks if the ownership guard skips the reverse one-to-one
        kind, letting "author2" silently re-parent "author1"'s profile.
        """
        result = _update(
            AuthorWithProfileType,
            {
                "id": self.author2.id,
                "author_profile": {"id": self.profile.id, "bio": "Stolen"},
            },
        )
        self.assertFalse(result.ok)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.author_id, self.author1.id)
        self.assertEqual(self.profile.bio, "Owned by 1")

    def test_cannot_steal_reverse_o2o_child_given_as_list(self) -> None:
        """The single-item-list form of a reverse-O2O steal is rejected too.

        This test breaks if the ownership guard is applied only to the scalar
        dict form, leaving the degenerate one-item list as a bypass.
        """
        result = _update(
            AuthorWithProfileType,
            {
                "id": self.author2.id,
                "author_profile": [{"id": self.profile.id, "bio": "Stolen"}],
            },
        )
        self.assertFalse(result.ok)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.author_id, self.author1.id)
        self.assertEqual(self.profile.bio, "Owned by 1")

    def test_reverse_o2o_rejection_matches_reverse_fk_rejection(self) -> None:
        """The reverse-O2O and reverse-FK steal rejections are indistinguishable.

        This test breaks if the two paths start reporting different message
        text, letting a client tell one relation kind from the other.
        """
        post = NestedIntegrityPost.objects.create(title="P", author=self.author1)
        o2o = _update(
            AuthorWithProfileType,
            {
                "id": self.author2.id,
                "author_profile": {"id": self.profile.id, "bio": "Stolen"},
            },
        )
        fk = _update(
            AuthorWithPostsType,
            {
                "id": self.author2.id,
                "nested_integrity_posts": [{"id": post.id, "title": "Stolen"}],
            },
        )
        self.assertFalse(o2o.ok)
        self.assertFalse(fk.ok)
        self.assertEqual(
            [
                message.replace(str(self.profile.pk), "<pk>")
                for message in o2o.errors[0].messages
            ],
            [
                message.replace(str(post.pk), "<pk>")
                for message in fk.errors[0].messages
            ],
        )
        self.assertEqual(
            o2o.errors[0].messages,
            [
                f"Object {self.profile.pk} does not belong to this NestedIntegrityAuthor."
            ],
        )

    def test_reverse_child_pk_that_does_not_exist_is_not_a_steal(self) -> None:
        """A reverse payload naming a non-existent pk has no owner to conflict with.

        There is no row to steal, so the guard stays out of the way and the
        payload falls through to the create path. This test breaks if a missing
        pk starts being treated as an ownership conflict (or the reverse).
        """
        result = _update(
            AuthorWithPostsType,
            {
                "id": self.author2.id,
                "nested_integrity_posts": [{"id": 9999, "title": "Ghost"}],
            },
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(self.author2.nested_integrity_posts.count(), 1)

    def test_can_update_own_reverse_o2o_child(self) -> None:
        """Upserting a reverse-O2O child the parent already owns still succeeds.

        This test breaks if the ownership guard starts rejecting legitimate
        updates to the parent's own one-to-one child.
        """
        result = _update(
            AuthorWithProfileType,
            {
                "id": self.author1.id,
                "author_profile": {"id": self.profile.id, "bio": "Updated"},
            },
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.bio, "Updated")
        self.assertEqual(self.profile.author_id, self.author1.id)


class NestedKindOwnershipCoverageTest(TestCase):
    """State, per relation kind, whether the ownership guard applies.

    The nested writer classifies every declared field as "forward",
    "reverse_one", "reverse_many", "m2m" or None. The ownership guard is
    meaningful only where the child row carries a single owning key back to
    the parent -- that is, the two reverse kinds. The remaining kinds are
    pinned here so a future change cannot quietly move a kind between the
    two groups.
    """

    def test_reverse_one_and_reverse_many_are_guarded(self) -> None:
        """Both reverse kinds route through the ownership guard.

        This test breaks if either reverse kind stops reaching the guard, the
        exact regression that let a reverse-O2O child be stolen.
        """
        author1 = NestedIntegrityAuthor.objects.create(name="A1")
        author2 = NestedIntegrityAuthor.objects.create(name="A2")
        post = NestedIntegrityPost.objects.create(title="P", author=author1)
        profile = NestedIntegrityProfile.objects.create(author=author1, bio="B")

        self.assertEqual(
            AuthorWithPostsType._relation_kind("nested_integrity_posts")[0],
            "reverse_many",
        )
        self.assertEqual(
            AuthorWithProfileType._relation_kind("author_profile")[0], "reverse_one"
        )
        self.assertFalse(
            _update(
                AuthorWithPostsType,
                {
                    "id": author2.id,
                    "nested_integrity_posts": [{"id": post.id, "title": "X"}],
                },
            ).ok
        )
        self.assertFalse(
            _update(
                AuthorWithProfileType,
                {"id": author2.id, "author_profile": {"id": profile.id, "bio": "X"}},
            ).ok
        )

    def test_forward_kind_is_not_guarded_by_design(self) -> None:
        """A forward FK/O2O child is not owned by the parent, so no guard applies.

        Many parents may point at the same forward child, so "belongs to this
        parent" has no meaning there: pointing a post at an author that other
        posts already reference is a legitimate write. This test breaks if an
        ownership guard is bolted onto the forward path.
        """
        author = NestedIntegrityAuthor.objects.create(name="Shared")
        NestedIntegrityPost.objects.create(title="First", author=author)

        self.assertEqual(PostForwardNestedType._relation_kind("author")[0], "forward")
        result = _create(
            PostForwardNestedType,
            {"title": "Second", "author": {"id": author.id, "name": "Shared"}},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(author.nested_integrity_posts.count(), 2)

    def test_m2m_kind_is_not_guarded_by_design(self) -> None:
        """An M2M child is shared by every parent that links it, so no guard applies.

        The link table has no single owner to compare against and the writer is
        additive, so re-using an existing tag is a legitimate write. This test
        breaks if an ownership guard is bolted onto the M2M path.
        """
        author = NestedIntegrityAuthor.objects.create(name="A")
        tag = NestedIntegrityTag.objects.create(label="shared")
        NestedIntegrityPost.objects.create(title="First", author=author).tags.add(tag)

        self.assertEqual(PostM2MNestedType._relation_kind("tags")[0], "m2m")
        result = _create(
            PostM2MNestedType,
            {"title": "Second", "author": author.id, "tags": [{"id": tag.id}]},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(tag.nested_integrity_posts.count(), 2)

    def test_unintrospectable_kind_writes_no_child_at_all(self) -> None:
        """A field that is not a model relation never reaches the child writer.

        Its payload is handed to the parent backend untouched, so there is no
        child row to own and nothing for the guard to check. This test breaks
        if an unknown nested field starts being classified as a relation.
        """
        self.assertEqual(
            AuthorWithPostsType._relation_kind("not_a_field"), (None, None)
        )
