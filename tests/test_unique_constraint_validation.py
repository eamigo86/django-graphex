# -*- coding: utf-8 -*-
"""Failing-first tests for UniqueConstraint validation in the native backend.

Covers:
- Single-field UniqueConstraint violation returns ErrorType (not IntegrityError)
- Multi-field UniqueConstraint violation returns ErrorType
- Conditional UniqueConstraint (with condition=) is skipped pre-save (DB-enforced)
- parent_link OneToOneField excluded from _fk_fields (MTI guard)
"""

from types import SimpleNamespace

from django.db import models
from django.db.models import Q
from django.test import TestCase

from django_graphex import DjangoModelType
from django_graphex.native.backend import PydanticBackend
from tests.models import DummyModel

# ---------------------------------------------------------------------------
# Models with UniqueConstraint (defined inline to avoid polluting tests/models.py)
# ---------------------------------------------------------------------------


class UCEmail(DummyModel):
    """Single-field UniqueConstraint via Meta.constraints."""

    email = models.EmailField()

    class Meta:
        app_label = "tests"
        constraints = [
            models.UniqueConstraint(fields=["email"], name="uc_email_unique"),
        ]


class UCArticle(DummyModel):
    """Multi-field UniqueConstraint (slug + language)."""

    slug = models.SlugField()
    language = models.CharField(max_length=5)

    class Meta:
        app_label = "tests"
        constraints = [
            models.UniqueConstraint(
                fields=["slug", "language"],
                name="uc_article_slug_lang",
            ),
        ]


class UCConditional(DummyModel):
    """UniqueConstraint with a condition — must NOT be pre-checked (left to DB)."""

    code = models.CharField(max_length=20)
    active = models.BooleanField(default=True)

    class Meta:
        app_label = "tests"
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(active=True),
                name="uc_conditional_code_active",
            ),
        ]


class UCAndUnique(DummyModel):
    """Field with both unique=True AND a UniqueConstraint — must not double-error."""

    code = models.CharField(max_length=10, unique=True)

    class Meta:
        app_label = "tests"
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uc_and_unique_code"),
        ]


# MTI parent/child pair to test parent_link exclusion from _fk_fields
class MTIParent(DummyModel):
    name = models.CharField(max_length=50)

    class Meta:
        app_label = "tests"


class MTIChild(MTIParent):
    extra = models.CharField(max_length=50, default="")

    class Meta:
        app_label = "tests"


# DjangoModelType registrations
class UCEmailType(DjangoModelType):
    class Meta:
        model = UCEmail


class UCArticleType(DjangoModelType):
    class Meta:
        model = UCArticle


class UCConditionalType(DjangoModelType):
    class Meta:
        model = UCConditional


class MTIChildType(DjangoModelType):
    class Meta:
        model = MTIChild


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _info():
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _create(type_cls, data):
    return type_cls.create(None, _info(), **{type_cls._meta.input_field_name: data})


def _update(type_cls, data):
    return type_cls.update(None, _info(), **{type_cls._meta.input_field_name: data})


# ---------------------------------------------------------------------------
# 1. Single-field UniqueConstraint
# ---------------------------------------------------------------------------


class SingleFieldUniqueConstraintTest(TestCase):
    def test_duplicate_email_returns_error_type(self):
        """UniqueConstraint on a single field surfaces as ErrorType, not 500."""
        UCEmail.objects.create(email="dupe@example.com")
        result = _create(UCEmailType, {"email": "dupe@example.com"})
        self.assertFalse(result.ok)
        error_fields = {e.field for e in result.errors}
        # Error should be on the offending field or non_field_errors
        self.assertTrue(
            error_fields & {"email", "non_field_errors"},
            msg=f"Expected error on 'email' or 'non_field_errors', got: {error_fields}",
        )

    def test_unique_email_creates_ok(self):
        """No constraint violation — create should succeed."""
        result = _create(UCEmailType, {"email": "unique@example.com"})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(UCEmail.objects.count(), 1)

    def test_update_same_instance_does_not_collide(self):
        """Re-saving the same value on the same row is allowed."""
        obj = UCEmail.objects.create(email="same@example.com")
        result = _update(UCEmailType, {"id": obj.pk, "email": "same@example.com"})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))


# ---------------------------------------------------------------------------
# 2. Multi-field UniqueConstraint
# ---------------------------------------------------------------------------


class MultiFieldUniqueConstraintTest(TestCase):
    def test_duplicate_slug_language_returns_error_type(self):
        """Multi-field UniqueConstraint surfaces as non_field_errors ErrorType."""
        UCArticle.objects.create(slug="hello", language="en")
        result = _create(UCArticleType, {"slug": "hello", "language": "en"})
        self.assertFalse(result.ok)
        error_fields = {e.field for e in result.errors}
        self.assertIn(
            "non_field_errors",
            error_fields,
            msg=f"Expected 'non_field_errors', got: {error_fields}",
        )

    def test_different_language_ok(self):
        """Same slug with different language is not a constraint violation."""
        UCArticle.objects.create(slug="hello", language="en")
        result = _create(UCArticleType, {"slug": "hello", "language": "fr"})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))

    def test_update_same_row_does_not_collide(self):
        """Updating a row without changing the constrained fields is allowed."""
        obj = UCArticle.objects.create(slug="hello", language="en")
        result = _update(
            UCArticleType, {"id": obj.pk, "slug": "hello", "language": "en"}
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))

    def test_error_message_mentions_constrained_fields(self):
        """The error message names the constrained fields."""
        UCArticle.objects.create(slug="boom", language="de")
        result = _create(UCArticleType, {"slug": "boom", "language": "de"})
        self.assertFalse(result.ok)
        msgs = [m for e in result.errors for m in e.messages]
        combined = " ".join(msgs)
        self.assertIn("slug", combined)
        self.assertIn("language", combined)


# ---------------------------------------------------------------------------
# 3. Conditional UniqueConstraint — must NOT be pre-checked
# ---------------------------------------------------------------------------


class ConditionalConstraintNotCheckedTest(TestCase):
    def test_conditional_constraint_is_not_pre_checked(self):
        """A UniqueConstraint with condition= is left to the DB (no pre-check)."""
        backend = PydanticBackend(UCConditional)
        # Prime the DB with one row — but the conditional constraint means we
        # can't cheaply replicate whether a second row would violate it.
        # What we assert: _db_check_errors does NOT return an error for a
        # code duplicate when the constraint is conditional.
        UCConditional.objects.create(code="A1", active=True)
        errors = backend._db_check_errors({"code": "A1", "active": True}, instance=None)
        # The conditional constraint must be SKIPPED by _db_check_errors.
        self.assertEqual(
            errors,
            {},
            msg=(
                "_db_check_errors should skip conditional UniqueConstraints; "
                f"got errors: {errors}"
            ),
        )


# ---------------------------------------------------------------------------
# 4. _fk_fields excludes MTI parent_link
# ---------------------------------------------------------------------------


class MTIParentLinkExclusionTest(TestCase):
    def test_parent_link_excluded_from_fk_fields(self):
        """parent_link OneToOneField must not appear in _fk_fields."""
        backend = PydanticBackend(MTIChild)
        fk_names = set(backend._fk_fields().keys())
        # The auto-created parent_link (mtiparent_ptr) must NOT be present.
        parent_link_name = MTIChild._meta.parents[MTIParent].name
        self.assertNotIn(
            parent_link_name,
            fk_names,
            msg=(
                f"parent_link field '{parent_link_name}' should be excluded "
                f"from _fk_fields(), but was found in: {fk_names}"
            ),
        )

    def test_non_parent_link_oto_still_included(self):
        """A regular (non-MTI) OneToOneField SHOULD still appear in _fk_fields."""
        from tests.models import Author

        class WithOTO(DummyModel):
            author = models.OneToOneField(Author, on_delete=models.CASCADE)

            class Meta:
                app_label = "tests"

        backend = PydanticBackend(WithOTO)
        fk_names = set(backend._fk_fields().keys())
        self.assertIn("author", fk_names)


# ---------------------------------------------------------------------------
# 5. _db_check_errors: direct unit tests for the UniqueConstraint path
# ---------------------------------------------------------------------------


class UniqueConstraintUnitTest(TestCase):
    def test_single_field_constraint_detected_by_db_check(self):
        UCEmail.objects.create(email="unit@example.com")
        backend = PydanticBackend(UCEmail)
        errors = backend._db_check_errors({"email": "unit@example.com"}, instance=None)
        self.assertTrue(
            errors, "Expected at least one error from UniqueConstraint check"
        )

    def test_single_field_constraint_ok_when_unique(self):
        backend = PydanticBackend(UCEmail)
        errors = backend._db_check_errors(
            {"email": "brand-new@example.com"}, instance=None
        )
        self.assertEqual(errors, {})

    def test_multi_field_constraint_detected_by_db_check(self):
        UCArticle.objects.create(slug="x", language="en")
        backend = PydanticBackend(UCArticle)
        errors = backend._db_check_errors(
            {"slug": "x", "language": "en"}, instance=None
        )
        self.assertIn("non_field_errors", errors)
        self.assertIn("slug", errors["non_field_errors"][0])
        self.assertIn("language", errors["non_field_errors"][0])

    def test_multi_field_constraint_partial_match_is_ok(self):
        """Only one field of a multi-field constraint matching is fine."""
        UCArticle.objects.create(slug="x", language="en")
        backend = PydanticBackend(UCArticle)
        errors = backend._db_check_errors(
            {"slug": "x", "language": "fr"}, instance=None
        )
        self.assertEqual(errors, {})

    def test_unique_constraint_excludes_self_on_update(self):
        obj = UCEmail.objects.create(email="self@example.com")
        backend = PydanticBackend(UCEmail)
        errors = backend._db_check_errors({"email": "self@example.com"}, instance=obj)
        self.assertEqual(errors, {})

    def test_no_double_error_when_field_also_has_unique_true(self):
        """A single-field UniqueConstraint on a field that also has unique=True
        must not produce duplicate errors for the same field.
        """
        UCAndUnique.objects.create(code="dup")
        backend = PydanticBackend(UCAndUnique)
        errors = backend._db_check_errors({"code": "dup"}, instance=None)
        # Should have an error, but it should not appear twice.
        self.assertTrue(errors)
        all_msgs = [m for msgs in errors.values() for m in msgs]
        self.assertEqual(
            len(all_msgs),
            1,
            msg=f"Expected exactly 1 error message, got {len(all_msgs)}: {all_msgs}",
        )
