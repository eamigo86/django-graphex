# -*- coding: utf-8 -*-
"""Failing-first tests for UniqueConstraint validation in the native backend.

Covers:
- Single-field UniqueConstraint violation returns ErrorType (not IntegrityError)
- Multi-field UniqueConstraint violation returns ErrorType
- Conditional UniqueConstraint (with condition=) is skipped pre-save (DB-enforced)
- parent_link OneToOneField excluded from _fk_fields (MTI guard)
"""

from types import SimpleNamespace
from typing import Any

from django.db import models
from django.db.models import Q
from django.test import TestCase
from django.test.utils import isolate_apps

from django_graphex.core.backend import PydanticBackend
from django_graphex.types import DjangoModelType
from tests.models import DummyModel

# ---------------------------------------------------------------------------
# Models with UniqueConstraint (defined inline to avoid polluting tests/models.py)
# ---------------------------------------------------------------------------


class UCEmail(DummyModel):
    """Single-field UniqueConstraint via Meta.constraints.

    Used by the single-field constraint mutation and unit tests below.
    """

    email = models.EmailField()

    class Meta:
        """Declares a single-field UniqueConstraint on "email".

        No other Meta options are needed for these tests.
        """

        app_label = "tests"
        constraints = [
            models.UniqueConstraint(fields=["email"], name="uc_email_unique"),
        ]


class UCArticle(DummyModel):
    """Multi-field UniqueConstraint (slug + language).

    Used by the multi-field constraint mutation and unit tests below.
    """

    slug = models.SlugField()
    language = models.CharField(max_length=5)

    class Meta:
        """Declares a multi-field UniqueConstraint on "slug" and "language".

        No other Meta options are needed for these tests.
        """

        app_label = "tests"
        constraints = [
            models.UniqueConstraint(
                fields=["slug", "language"],
                name="uc_article_slug_lang",
            ),
        ]


class UCConditional(DummyModel):
    """UniqueConstraint with a condition — must NOT be pre-checked (left to DB).

    Used by "ConditionalConstraintNotCheckedTest" below.
    """

    code = models.CharField(max_length=20)
    active = models.BooleanField(default=True)

    class Meta:
        """Declares a conditional UniqueConstraint scoped to active rows.

        No other Meta options are needed for these tests.
        """

        app_label = "tests"
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(active=True),
                name="uc_conditional_code_active",
            ),
        ]


class UCAndUnique(DummyModel):
    """Field with both unique=True AND a UniqueConstraint.

    Pins that the two mechanisms do not double-report the same violation.
    """

    code = models.CharField(max_length=10, unique=True)

    class Meta:
        """Adds a redundant UniqueConstraint atop the field-level unique=True.

        No other Meta options are needed for these tests.
        """

        app_label = "tests"
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uc_and_unique_code"),
        ]


# MTI parent/child pair to test parent_link exclusion from _fk_fields
class MTIParent(DummyModel):
    """Base model of a multi-table-inheritance pair used for parent_link tests.

    Paired with "MTIChild" below.
    """

    name = models.CharField(max_length=50)

    class Meta:
        """Registers this model under the "tests" app label.

        No other Meta options are needed for these tests.
        """

        app_label = "tests"


class MTIChild(MTIParent):
    """Child model of a multi-table-inheritance pair used for parent_link tests.

    Inherits from "MTIParent", creating an auto parent_link OneToOneField.
    """

    extra = models.CharField(max_length=50, default="")

    class Meta:
        """Registers this model under the "tests" app label.

        No other Meta options are needed for these tests.
        """

        app_label = "tests"


# DjangoModelType registrations
class UCEmailType(DjangoModelType):
    """DjangoModelType binding for "UCEmail".

    Used by the single-field UniqueConstraint mutation tests above.
    """

    class Meta:
        """Binds this type to the "UCEmail" model.

        No additional Meta options are needed for these tests.
        """

        model = UCEmail


class UCArticleType(DjangoModelType):
    """DjangoModelType binding for "UCArticle".

    Used by the multi-field UniqueConstraint mutation tests above.
    """

    class Meta:
        """Binds this type to the "UCArticle" model.

        No additional Meta options are needed for these tests.
        """

        model = UCArticle


class UCConditionalType(DjangoModelType):
    """DjangoModelType binding for "UCConditional".

    Used by the conditional-constraint tests above.
    """

    class Meta:
        """Binds this type to the "UCConditional" model.

        No additional Meta options are needed for these tests.
        """

        model = UCConditional


class MTIChildType(DjangoModelType):
    """DjangoModelType binding for "MTIChild".

    Used by the parent_link exclusion tests above.
    """

    class Meta:
        """Binds this type to the "MTIChild" model.

        No additional Meta options are needed for these tests.
        """

        model = MTIChild


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _info() -> SimpleNamespace:
    """Build a minimal GraphQL resolve-info stub for mutation calls.

    Returns:
        info: A namespace exposing "context.META" and "context.FILES" as
            empty dicts, enough for the mutation code paths under test.
    """
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _create(type_cls: type[DjangoModelType], data: dict[str, Any]) -> DjangoModelType:
    """Invoke the type's "create" mutation with the given input payload.

    Args:
        type_cls: The "DjangoModelType" subclass to create through.
        data: The input field values, keyed as the type expects.

    Returns:
        result: The mutation payload instance ("ok"/"errors"/output field).
    """
    return type_cls.create(None, _info(), **{type_cls._meta.input_field_name: data})


def _update(type_cls: type[DjangoModelType], data: dict[str, Any]) -> DjangoModelType:
    """Invoke the type's "update" mutation with the given input payload.

    Args:
        type_cls: The "DjangoModelType" subclass to update through.
        data: The input field values, keyed as the type expects.

    Returns:
        result: The mutation payload instance ("ok"/"errors"/output field).
    """
    return type_cls.update(None, _info(), **{type_cls._meta.input_field_name: data})


# ---------------------------------------------------------------------------
# 1. Single-field UniqueConstraint
# ---------------------------------------------------------------------------


class SingleFieldUniqueConstraintTest(TestCase):
    """A single-field UniqueConstraint surfaces as a GraphQL ErrorType, not a 500.

    Covers creation conflicts, successful creation, and same-row updates.
    """

    def test_duplicate_email_returns_error_type(self) -> None:
        """Ship-broken contract: creating a row that violates a single-field
        UniqueConstraint must return an errored payload, not raise
        IntegrityError up to the caller.
        """
        UCEmail.objects.create(email="dupe@example.com")
        result = _create(UCEmailType, {"email": "dupe@example.com"})
        self.assertFalse(result.ok)
        error_fields = {e.field for e in result.errors}
        # Error should be on the offending field or non_field_errors
        self.assertTrue(
            error_fields & {"email", "non_field_errors"},
            msg=f"Expected error on 'email' or 'non_field_errors', got: {error_fields}",
        )

    def test_unique_email_creates_ok(self) -> None:
        """Ship-broken contract: a value with no constraint violation must
        create successfully.
        """
        result = _create(UCEmailType, {"email": "unique@example.com"})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(UCEmail.objects.count(), 1)

    def test_update_same_instance_does_not_collide(self) -> None:
        """Ship-broken contract: re-saving the same value on the same row
        must not be treated as a constraint violation against itself.
        """
        obj = UCEmail.objects.create(email="same@example.com")
        result = _update(UCEmailType, {"id": obj.pk, "email": "same@example.com"})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))


# ---------------------------------------------------------------------------
# 2. Multi-field UniqueConstraint
# ---------------------------------------------------------------------------


class MultiFieldUniqueConstraintTest(TestCase):
    """A multi-field UniqueConstraint surfaces as a non_field_errors ErrorType.

    Covers creation conflicts, partial matches, updates, and the error message.
    """

    def test_duplicate_slug_language_returns_error_type(self) -> None:
        """Ship-broken contract: violating a multi-field UniqueConstraint
        must surface as a "non_field_errors" entry, not raise or 500.
        """
        UCArticle.objects.create(slug="hello", language="en")
        result = _create(UCArticleType, {"slug": "hello", "language": "en"})
        self.assertFalse(result.ok)
        error_fields = {e.field for e in result.errors}
        self.assertIn(
            "non_field_errors",
            error_fields,
            msg=f"Expected 'non_field_errors', got: {error_fields}",
        )

    def test_different_language_ok(self) -> None:
        """Ship-broken contract: the same slug with a different language must
        not be treated as a constraint violation.
        """
        UCArticle.objects.create(slug="hello", language="en")
        result = _create(UCArticleType, {"slug": "hello", "language": "fr"})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))

    def test_update_same_row_does_not_collide(self) -> None:
        """Ship-broken contract: updating a row without changing its
        constrained fields must not be treated as a violation against itself.
        """
        obj = UCArticle.objects.create(slug="hello", language="en")
        result = _update(
            UCArticleType, {"id": obj.pk, "slug": "hello", "language": "en"}
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))

    def test_error_message_mentions_constrained_fields(self) -> None:
        """Ship-broken contract: the violation error message must name both
        constrained fields, not a generic message.
        """
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
    """A UniqueConstraint with a "condition" is left to the DB (no pre-check).

    Pins that conditional constraints are excluded from the pre-save check.
    """

    def test_conditional_constraint_is_not_pre_checked(self) -> None:
        """Ship-broken contract: "_db_check_errors" must skip a conditional
        UniqueConstraint entirely, leaving its enforcement to the database.
        """
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
    """Multi-table-inheritance "parent_link" fields are excluded from "_fk_fields".

    Also covers that a regular (non-MTI) OneToOneField remains included.
    """

    def test_parent_link_excluded_from_fk_fields(self) -> None:
        """Ship-broken contract: the auto-created MTI "parent_link"
        OneToOneField must not appear in "_fk_fields", since it is not a
        regular foreign key the mutation layer should validate.
        """
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

    @isolate_apps("tests")
    def test_non_parent_link_oto_still_included(self) -> None:
        """Ship-broken contract: a regular (non-MTI) OneToOneField must still
        appear in "_fk_fields", so the parent_link exclusion is not
        over-broad.
        """
        from tests.models import Author

        # ``isolate_apps`` keeps this throwaway model OUT of the global Django app
        # registry. Without it, ``WithOTO`` stays registered for the whole process
        # but has NO table (no migration), so a later ``transaction=True`` test
        # that introspects every model (e.g. the native subscription e2e) hits
        # ``no such table: tests_withoto`` once the full suite runs together.
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
    """Direct unit coverage of "PydanticBackend._db_check_errors" for UniqueConstraint.

    Covers single-field, multi-field, self-exclusion, and double-error cases.
    """

    def test_single_field_constraint_detected_by_db_check(self) -> None:
        """Ship-broken contract: a single-field constraint violation must be
        detected directly by "_db_check_errors".
        """
        UCEmail.objects.create(email="unit@example.com")
        backend = PydanticBackend(UCEmail)
        errors = backend._db_check_errors({"email": "unit@example.com"}, instance=None)
        self.assertTrue(
            errors, "Expected at least one error from UniqueConstraint check"
        )

    def test_single_field_constraint_ok_when_unique(self) -> None:
        """Ship-broken contract: a non-colliding value must produce no
        errors from "_db_check_errors".
        """
        backend = PydanticBackend(UCEmail)
        errors = backend._db_check_errors(
            {"email": "brand-new@example.com"}, instance=None
        )
        self.assertEqual(errors, {})

    def test_multi_field_constraint_detected_by_db_check(self) -> None:
        """Ship-broken contract: a multi-field constraint violation must be
        reported under "non_field_errors" naming both constrained fields.
        """
        UCArticle.objects.create(slug="x", language="en")
        backend = PydanticBackend(UCArticle)
        errors = backend._db_check_errors(
            {"slug": "x", "language": "en"}, instance=None
        )
        self.assertIn("non_field_errors", errors)
        self.assertIn("slug", errors["non_field_errors"][0])
        self.assertIn("language", errors["non_field_errors"][0])

    def test_multi_field_constraint_partial_match_is_ok(self) -> None:
        """Ship-broken contract: matching only one field of a multi-field
        constraint must not be treated as a violation.
        """
        UCArticle.objects.create(slug="x", language="en")
        backend = PydanticBackend(UCArticle)
        errors = backend._db_check_errors(
            {"slug": "x", "language": "fr"}, instance=None
        )
        self.assertEqual(errors, {})

    def test_unique_constraint_excludes_self_on_update(self) -> None:
        """Ship-broken contract: passing the existing instance must exclude
        it from the uniqueness check, so re-saving its own value is allowed.
        """
        obj = UCEmail.objects.create(email="self@example.com")
        backend = PydanticBackend(UCEmail)
        errors = backend._db_check_errors({"email": "self@example.com"}, instance=obj)
        self.assertEqual(errors, {})

    def test_no_double_error_when_field_also_has_unique_true(self) -> None:
        """Ship-broken contract: a single-field UniqueConstraint on a field
        that also has unique=True must not produce duplicate errors for the
        same field.
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
