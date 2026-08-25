"""Parity between the nested-write path and the normal write path.

The nested writer ("NestedFieldsMixin") historically skipped controls the
ordinary single-object write path applies. This module pins the three that
belong to that family:

* the child type's inline "validate_*" methods and its "Meta.pydantic_model"
  must run on a nested write, exactly as they do on the child's own mutation,
* "DjangoModelMutation.update" / "delete" must resolve their target row
  through the same "get_queryset" / "filter_queryset" scoping hooks
  "DjangoModelType" uses, and must answer a malformed primary key with the
  error envelope instead of leaking Django's "ValueError",
* a nested FORWARD foreign-key payload carrying a primary key must not be able
  to rewrite an arbitrary row of the related table.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from django.db import models
from django.test import TestCase

from django_graphex.mutation import DjangoModelMutation
from django_graphex.types import DjangoModelType
from tests.models import DummyModel

# NOTE: these models and their DjangoModelType companions are DEDICATED to this
# module. DjangoModelType always self-registers on the GLOBAL registry, so
# wrapping a shared model here would derive globally-named companion output
# types that collide with the companions other modules build over the same
# shared models.


class ParityCategory(DummyModel):
    """A shared lookup row that many documents may point at.

    Stands in for the "global category" of the forward-foreign-key report: a
    row nobody owns, reachable from every tenant's document.
    """

    name = models.CharField(max_length=100)


class ParityTag(DummyModel):
    """A shared label many documents may link.

    Stands in for the lookup row of the many-to-many face of the link rule:
    every document may attach it, none of them owns it.
    """

    label = models.CharField(max_length=50)


class ParityDoc(DummyModel):
    """A tenant-scoped document carrying a forward FK to "ParityCategory".

    The "owner" column is the tenant marker the scoping hooks filter on, and
    "tags" gives the M2M face of the same link rule a target.
    """

    title = models.CharField(max_length=200)
    owner = models.CharField(max_length=50, default="")
    category = models.ForeignKey(
        ParityCategory, related_name="parity_docs", on_delete=models.CASCADE
    )
    tags = models.ManyToManyField(ParityTag, related_name="parity_docs", blank=True)


class ParityCategoryType(DjangoModelType):
    """The category's OWN type, carrying the inline validator under test.

    Its "validate_name" is the rule a nested write through "ParityDocType"
    must honour too.
    """

    class Meta:
        """Bind the type to "ParityCategory".

        No other options are needed; the inline validator lives on the class.
        """

        model = ParityCategory

    def validate_name(self, value: str) -> str:
        """Reject a category name that starts with the banned marker.

        Args:
            value: The raw name submitted by the caller.

        Returns:
            The name unchanged when it passes.

        Raises:
            ValueError: If the name starts with "BAD".
        """
        if value.startswith("BAD"):
            raise ValueError("name must not start with BAD")
        return value


class ParityDocType(DjangoModelType):
    """A document type nesting the forward FK to "ParityCategory".

    Drives the child-validator and forward-link cases below.
    """

    class Meta:
        """Bind the type to "ParityDoc" with "category" declared as nested.

        The nested value is the child MODEL, the documented spelling.
        """

        model = ParityDoc
        nested_fields = {"category": ParityCategory}


class ParityTagDocType(DjangoModelType):
    """A document type nesting the many-to-many relation to "ParityTag".

    Drives the many-to-many face of the link rule.
    """

    class Meta:
        """Bind the type to "ParityDoc" with "tags" declared as nested.

        Gives the M2M branch of the nested writer a target.
        """

        model = ParityDoc
        nested_fields = {"tags": ParityTag}


class ScopedDocType(DjangoModelType):
    """A document type scoped to a single tenant through "filter_queryset".

    Used as the reference behaviour the "DjangoModelMutation" sibling is
    compared against.
    """

    class Meta:
        """Bind the type to "ParityDoc" with no nested fields.

        The scoping lives in the "filter_queryset" override below.
        """

        model = ParityDoc

    @classmethod
    def filter_queryset(cls, qs: Any, info: Any, **kwargs: Any) -> Any:
        """Restrict every operation to the "mine" tenant.

        Args:
            qs: The queryset to scope.
            info: GraphQL resolve info for the current request.
            **kwargs: Extra resolver arguments, unused here.

        Returns:
            The queryset narrowed to the caller's tenant.
        """
        return qs.filter(owner="mine")


class ScopedDocMutation(DjangoModelMutation):
    """A "DjangoModelMutation" declaring the same tenant scope.

    The whole point of the class: the hook is spelled exactly as it is on
    "DjangoModelType", so it must have the same effect.
    """

    class Meta:
        """Bind the mutation to "ParityDoc".

        No projection is declared so the registered output type is reused.
        """

        model = ParityDoc

    @classmethod
    def filter_queryset(cls, qs: Any, info: Any, **kwargs: Any) -> Any:
        """Restrict every operation to the "mine" tenant.

        Args:
            qs: The queryset to scope.
            info: GraphQL resolve info for the current request.
            **kwargs: Extra resolver arguments, unused here.

        Returns:
            The queryset narrowed to the caller's tenant.
        """
        return qs.filter(owner="mine")


def _info() -> SimpleNamespace:
    """Build a bare GraphQL resolve-info stand-in for direct resolver calls.

    Returns:
        An object shaped like a GraphQL resolve info, with a "context"
        carrying empty "META" and "FILES".
    """
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _create(host: Any, data: dict[str, Any]) -> Any:
    """Invoke the generated "create" resolver of a type or mutation host.

    Args:
        host: The "DjangoModelType" or "DjangoModelMutation" class to call.
        data: The input payload, keyed by the host's input field name.

    Returns:
        The mutation result object (exposes "ok" and, on failure, "errors").
    """
    return host.create(None, _info(), **{host._meta.input_field_name: data})


def _update(host: Any, data: dict[str, Any]) -> Any:
    """Invoke the generated "update" resolver of a type or mutation host.

    Args:
        host: The "DjangoModelType" or "DjangoModelMutation" class to call.
        data: The input payload, keyed by the host's input field name.

    Returns:
        The mutation result object (exposes "ok" and, on failure, "errors").
    """
    return host.update(None, _info(), **{host._meta.input_field_name: data})


class NestedChildValidatorTest(TestCase):
    """The child type's own validators must run on the nested write path.

    Compares the child's own mutation with the same payload sent through the
    parent's nested field; the two must agree.
    """

    def test_child_mutation_rejects_the_value(self) -> None:
        """The child's own mutation rejects the banned name.

        Establishes the reference behaviour the nested path is compared
        against; it breaks if the inline validator stops running at all.
        """
        result = _create(ParityCategoryType, {"name": "BAD name"})
        self.assertFalse(result.ok)
        self.assertEqual(ParityCategory.objects.count(), 0)

    def test_nested_write_rejects_the_same_value(self) -> None:
        """The same banned name is rejected through the parent nested payload.

        This test breaks if a nested write is validated from the child MODEL
        alone, skipping the child type's inline validators.
        """
        result = _create(
            ParityDocType, {"title": "T", "category": {"name": "BAD name"}}
        )
        self.assertFalse(
            result.ok, msg="nested write accepted a value the child rejects"
        )
        self.assertEqual(ParityCategory.objects.count(), 0)
        self.assertEqual(ParityDoc.objects.count(), 0)

    def test_nested_write_still_accepts_a_valid_value(self) -> None:
        """A valid nested child payload keeps working once validators run.

        This test breaks if wiring the child validators into the nested path
        rejects payloads that should pass.
        """
        result = _create(ParityDocType, {"title": "T", "category": {"name": "fine"}})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(ParityCategory.objects.get().name, "fine")


class MutationScopingTest(TestCase):
    """ "DjangoModelMutation" writes must honour the same scoping as the type.

    Each case is run against both hosts so the two stay indistinguishable to a
    caller.
    """

    def setUp(self) -> None:
        """Create one in-scope and one out-of-scope document.

        The out-of-scope row is the one every scoping case targets.
        """
        self.category = ParityCategory.objects.create(name="c")
        self.mine = ParityDoc.objects.create(
            title="mine", owner="mine", category=self.category
        )
        self.theirs = ParityDoc.objects.create(
            title="theirs", owner="theirs", category=self.category
        )

    def test_type_update_is_scoped(self) -> None:
        """The reference: "DjangoModelType.update" hides the other tenant's row.

        This test breaks if the already-shipped scoping of the type's write
        path regresses.
        """
        result = _update(ScopedDocType, {"id": self.theirs.id, "title": "PWNED"})
        self.assertFalse(result.ok)
        self.theirs.refresh_from_db()
        self.assertEqual(self.theirs.title, "theirs")

    def test_mutation_update_is_scoped(self) -> None:
        """ "DjangoModelMutation.update" must hide the other tenant's row too.

        This test breaks if the mutation host resolves its target row on the
        bare model, ignoring a declared "filter_queryset".
        """
        result = _update(ScopedDocMutation, {"id": self.theirs.id, "title": "PWNED"})
        self.assertFalse(result.ok)
        self.theirs.refresh_from_db()
        self.assertEqual(self.theirs.title, "theirs")

    def test_mutation_delete_is_scoped(self) -> None:
        """ "DjangoModelMutation.delete" must hide the other tenant's row too.

        This test breaks if the mutation host deletes a row the declared
        scope excludes.
        """
        result = ScopedDocMutation.delete(None, _info(), id=self.theirs.id)
        self.assertFalse(result.ok)
        self.assertTrue(ParityDoc.objects.filter(pk=self.theirs.pk).exists())

    def test_mutation_update_in_scope_still_works(self) -> None:
        """An in-scope row is still writable through the mutation host.

        This test breaks if the new scoping hook rejects legitimate writes.
        """
        result = _update(ScopedDocMutation, {"id": self.mine.id, "title": "renamed"})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.title, "renamed")

    def test_mutation_delete_in_scope_still_works(self) -> None:
        """An in-scope row is still deletable through the mutation host.

        This test breaks if the new scoping hook rejects legitimate deletes.
        """
        result = ScopedDocMutation.delete(None, _info(), id=self.mine.id)
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertFalse(ParityDoc.objects.filter(pk=self.mine.pk).exists())


class MalformedPrimaryKeyTest(TestCase):
    """A non-numeric primary key must produce the error envelope, not a 500.

    Covers both hosts, since the two share the lookup helper that used to let
    the ORM error escape.
    """

    def test_mutation_delete_with_non_numeric_id(self) -> None:
        """ "DjangoModelMutation.delete" answers a garbage id cleanly.

        This test breaks if Django's "ValueError" escapes the resolver instead
        of being reported as a missing object.
        """
        result = ScopedDocMutation.delete(None, _info(), id="not-a-number")
        self.assertFalse(result.ok)
        self.assertEqual(result.errors[0].field, "id")

    def test_mutation_update_with_non_numeric_id(self) -> None:
        """ "DjangoModelMutation.update" answers a garbage id cleanly.

        This test breaks if Django's "ValueError" escapes the resolver instead
        of being reported as a missing object.
        """
        result = _update(ScopedDocMutation, {"id": "not-a-number", "title": "x"})
        self.assertFalse(result.ok)
        self.assertEqual(result.errors[0].field, "id")

    def test_type_delete_with_non_numeric_id(self) -> None:
        """ "DjangoModelType.delete" answers a garbage id cleanly.

        The sibling call site of the two above; it breaks if only the mutation
        host was patched.
        """
        result = ScopedDocType.delete(None, _info(), id="not-a-number")
        self.assertFalse(result.ok)
        self.assertEqual(result.errors[0].field, "id")

    def test_type_update_with_non_numeric_id(self) -> None:
        """ "DjangoModelType.update" answers a garbage id cleanly.

        The sibling call site of the two above; it breaks if only the mutation
        host was patched.
        """
        result = _update(ScopedDocType, {"id": "not-a-number", "title": "x"})
        self.assertFalse(result.ok)
        self.assertEqual(result.errors[0].field, "id")


class ForwardForeignKeyLinkTest(TestCase):
    """A nested forward-FK payload with a pk links, it does not rewrite.

    Pins both halves of the rule: the unrelated row is untouched but still
    attached, and the already-attached row stays updatable.
    """

    def setUp(self) -> None:
        """Create the shared lookup row and a document pointing at its own.

        The shared row is the one no scope hides and no ownership guard covers.
        """
        self.shared = ParityCategory.objects.create(name="GLOBAL CATEGORY")
        self.own = ParityCategory.objects.create(name="own")
        self.doc = ParityDoc.objects.create(
            title="doc", owner="mine", category=self.own
        )

    def test_unrelated_row_is_not_rewritten(self) -> None:
        """Updating a document must not rewrite an unrelated category row.

        This test breaks if a nested forward-FK payload carrying a pk keeps
        updating any row of the related table.
        """
        result = _update(
            ParityDocType,
            {
                "id": self.doc.id,
                "category": {"id": self.shared.id, "name": "OVERWRITTEN"},
            },
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.name, "GLOBAL CATEGORY")

    def test_unrelated_row_is_still_linked(self) -> None:
        """The document is re-pointed at the row named by the pk.

        Re-pointing a forward FK at an existing row stays a legitimate write;
        this test breaks if the link is dropped along with the field writes.
        """
        _update(
            ParityDocType,
            {
                "id": self.doc.id,
                "category": {"id": self.shared.id, "name": "OVERWRITTEN"},
            },
        )
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.category_id, self.shared.id)

    def test_currently_linked_row_is_still_updatable(self) -> None:
        """The category attached to the document is still updated in place.

        This is the documented use of a nested forward FK; the test breaks if
        the link rule swallows it.
        """
        result = _update(
            ParityDocType,
            {"id": self.doc.id, "category": {"id": self.own.id, "name": "renamed"}},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.own.refresh_from_db()
        self.assertEqual(self.own.name, "renamed")

    def test_payload_without_pk_still_creates(self) -> None:
        """A nested forward-FK payload with no pk still creates a new row.

        This test breaks if the link rule leaks into the create path.
        """
        result = _update(
            ParityDocType, {"id": self.doc.id, "category": {"name": "brand new"}}
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.category.name, "brand new")


class ManyToManyLinkTest(TestCase):
    """The M2M face of the same hole: a pk payload links, it does not rewrite.

    The many-to-many branch reaches rows through the link table instead of a
    column, so it needs its own coverage of the identical rule.
    """

    def setUp(self) -> None:
        """Create a shared tag, a document, and one already-linked tag.

        The shared tag is the row an unrelated parent must not be able to edit.
        """
        self.shared = ParityTag.objects.create(label="GLOBAL TAG")
        self.own = ParityTag.objects.create(label="own")
        self.doc = ParityDoc.objects.create(
            title="doc",
            owner="mine",
            category=ParityCategory.objects.create(name="c"),
        )
        self.doc.tags.add(self.own)

    def test_unlinked_row_is_not_rewritten(self) -> None:
        """A tag this document does not link must not be rewritten.

        This test breaks if a nested M2M payload carrying a pk keeps updating
        any row of the related table.
        """
        result = _update(
            ParityTagDocType,
            {
                "id": self.doc.id,
                "tags": [{"id": self.shared.id, "label": "OVERWRITTEN"}],
            },
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.label, "GLOBAL TAG")

    def test_unlinked_row_is_still_added(self) -> None:
        """The tag named by the pk is still linked to the document.

        Re-using an existing tag stays a legitimate write; this test breaks if
        the link is dropped along with the field writes.
        """
        _update(
            ParityTagDocType,
            {
                "id": self.doc.id,
                "tags": [{"id": self.shared.id, "label": "OVERWRITTEN"}],
            },
        )
        self.assertIn(self.shared, self.doc.tags.all())

    def test_already_linked_row_is_still_updatable(self) -> None:
        """A tag the document already links is still updated in place.

        This test breaks if the link rule swallows the documented upsert.
        """
        result = _update(
            ParityTagDocType,
            {"id": self.doc.id, "tags": [{"id": self.own.id, "label": "renamed"}]},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.own.refresh_from_db()
        self.assertEqual(self.own.label, "renamed")

    def test_payload_without_pk_still_creates(self) -> None:
        """A nested M2M payload with no pk still creates and links a new row.

        This test breaks if the link rule leaks into the create path.
        """
        result = _update(
            ParityTagDocType, {"id": self.doc.id, "tags": [{"label": "brand new"}]}
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertIn("brand new", set(self.doc.tags.values_list("label", flat=True)))

    def test_malformed_child_pk_does_not_leak_an_orm_error(self) -> None:
        """A garbage pk inside a nested child payload never raises.

        The link rule queries the relation by that pk, so this test breaks if
        an uncoercible value reaches the ORM as a raw error instead of being
        treated as a row that does not exist.
        """
        result = _update(
            ParityTagDocType,
            {"id": self.doc.id, "tags": [{"id": "not-a-number", "label": "x"}]},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))

    def test_malformed_forward_child_pk_is_a_clean_error(self) -> None:
        """A garbage pk on a nested forward FK is reported through the envelope.

        The link rule hands the pk to the parent for the FK write, so this test
        breaks if it surfaces as an ORM error rather than a field error.
        """
        result = _update(
            ParityDocType,
            {"id": self.doc.id, "category": {"id": "not-a-number", "name": "x"}},
        )
        self.assertFalse(result.ok)
        self.assertIn("category", {error.field for error in result.errors})
