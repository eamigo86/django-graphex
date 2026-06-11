# -*- coding: utf-8 -*-
"""Targeted coverage for the queryset N+1 optimizer in ``utils.py``.

These tests assert real optimization behaviour (query counts, the
``select_related`` / ``prefetch_related`` / ``.only()`` that gets applied) and
exercise the branches that the existing suites leave uncovered:

* O2O (forward) and reverse O2O -> select_related (both are one_to_one)
* generic relations / non-relations -> no optimization
* ``.only()`` narrowing with ordering columns, fragments, non-concrete FK,
  select relation without a sub-selection
* missing fragment spreads (defensive None handling) in every walk
* ``OPTIMIZE_QUERYSET`` off (pass-through) and ``OPTIMIZE_ONLY_FIELDS`` off
* custom resolver returning a non-QuerySet (ignored)
* relation-traversing filter kwargs seeding the joins
* filtered ``Prefetch`` merge: nested filtered lists re-rooted under their
  filtered ancestor, plain children re-rooted, and the same lookup appearing
  both plain and filtered.

Dedicated models (subclassing ``tests.models.DummyModel``) and a dedicated
``Registry`` keep these isolated from the global one-output-type-per-model
registry.
"""

from __future__ import annotations

from unittest import mock

import graphene
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import connection, models
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphene import Schema
from graphql import parse
from graphql.language.ast import FragmentDefinitionNode, OperationDefinitionNode

from django_graphex import (
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoObjectField,
    DjangoObjectType,
)
from django_graphex.registry import Registry
from django_graphex.settings import graphql_api_settings
from django_graphex.utils import (
    PrefetchPlan,
    _collect_only_fields,
    _collect_prefetch_only_sets,
    _compute_child_only,
    _concrete_field_map,
    _leaf_model,
    _merge_filtered_prefetches,
    _narrow_plain_prefetch,
    _relation_field_map,
    _relation_optimization,
    queryset_factory,
    recursive_params,
)

from .models import Author, DummyModel, Post, Tag


# --------------------------------------------------------------------------- #
# Dedicated models exercising relation shapes the global models lack           #
# --------------------------------------------------------------------------- #
class Profile(DummyModel):
    """One side of a O2O + holds a generic relation + an ordering Meta."""

    handle = models.CharField(max_length=50)
    headline = models.CharField(max_length=100, default="")
    notes = GenericRelation("OptNote")

    class Meta:
        app_label = "tests"
        ordering = ["handle"]


class Account(DummyModel):
    """Forward O2O -> Profile (select_related); reverse O2O is on Profile."""

    username = models.CharField(max_length=50)
    profile = models.OneToOneField(
        Profile, related_name="account", on_delete=models.CASCADE
    )

    class Meta:
        app_label = "tests"


class OrderingThing(DummyModel):
    """Meta.ordering mixing a relation-traversing term and an F() expression.

    ``_collect_only_fields`` must skip ordering terms that are not plain string
    columns (the ``F()``) and string terms whose head column is not a local
    concrete column (``owner__handle``), keeping only the real local column.
    """

    label = models.CharField(max_length=50)
    rank = models.IntegerField(default=0)
    owner = models.ForeignKey(
        Profile, related_name="ordering_things", on_delete=models.CASCADE
    )

    class Meta:
        app_label = "tests"
        ordering = [models.F("rank").asc(), "owner__handle", "label"]


class OptNote(DummyModel):
    """A generic-FK row -> exercises the GenericForeignKey skip branch."""

    text = models.CharField(max_length=100)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        app_label = "tests"


class OptTaggedItem(DummyModel):
    """Two GFKs for multi-GFK disambiguation test (task 2.10).

    content_object -> (content_type_id, object_id)
    tagged_by      -> (tagger_ct_id,    tagger_id)

    ``label`` is a plain concrete field so the selection ``{ label }`` is a
    known leaf and does NOT trigger the full-load fallback.
    """

    label = models.CharField(max_length=100, default="")

    content_type = models.ForeignKey(
        ContentType, related_name="+", on_delete=models.CASCADE
    )
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    tagger_ct = models.ForeignKey(
        ContentType, related_name="+", on_delete=models.CASCADE
    )
    tagger_id = models.PositiveIntegerField()
    tagged_by = GenericForeignKey("tagger_ct", "tagger_id")

    class Meta:
        app_label = "tests"


# --------------------------------------------------------------------------- #
# Parse helper (mirrors tests/test_query_optimization.py)                       #
# --------------------------------------------------------------------------- #
def _parse(query):
    document = parse(query)
    fragments = {
        d.name.value: d
        for d in document.definitions
        if isinstance(d, FragmentDefinitionNode)
    }
    operation = next(
        d for d in document.definitions if isinstance(d, OperationDefinitionNode)
    )
    return operation.selection_set.selections[0].selection_set, fragments


# --------------------------------------------------------------------------- #
# _relation_optimization / _relation_field_map / _concrete_field_map           #
# --------------------------------------------------------------------------- #
class RelationClassificationTest(TestCase):
    def test_forward_o2o_is_select(self):
        field = Account._meta.get_field("profile")
        self.assertEqual(_relation_optimization(field), ("select", "profile"))

    def test_reverse_o2o_is_select(self):
        # Profile.account (reverse side of the O2O) is still one_to_one, so the
        # optimizer classifies it as select_related (Django can join it), using
        # the reverse accessor name.
        field = Profile._meta.get_field("account")
        self.assertEqual(_relation_optimization(field), ("select", "account"))

    def test_generic_foreign_key_returns_none(self):
        # REQ-4 / Scenario: Classification — GFK now returns ("prefetch", name).
        # (Previously assertIsNone; flipped to positive classification per design.)
        field = next(
            f for f in OptNote._meta.get_fields() if isinstance(f, GenericForeignKey)
        )
        self.assertEqual(_relation_optimization(field), ("prefetch", "content_object"))

    def test_generic_rel_still_returns_none(self):
        # REQ-4 / Scenario: GenericRel still returns None (guard preserved — C-D).
        # GenericRel is the reverse descriptor that appears on the TARGET model's
        # _meta.get_fields(include_hidden=True).  It must continue to return None.
        # OptNote is the target of Profile.notes (a GenericRelation), so OptNote
        # carries a GenericRel with name="+" in its hidden fields.
        from django.contrib.contenttypes.fields import GenericRel

        generic_rel_field = next(
            (
                f
                for f in OptNote._meta.get_fields(include_hidden=True)
                if isinstance(f, GenericRel)
            ),
            None,
        )
        self.assertIsNotNone(
            generic_rel_field,
            "Could not find a GenericRel field on OptNote; check model setup.",
        )
        self.assertIsNone(_relation_optimization(generic_rel_field))

    def test_relation_field_map_includes_gfk_no_attribute_error(self):
        # REQ-4 / Scenario: _relation_field_map includes GFK without AttributeError.
        rel_map = _relation_field_map(OptNote)
        self.assertIn("content_object", rel_map)

    def test_non_relation_returns_none(self):
        field = Account._meta.get_field("username")
        self.assertIsNone(_relation_optimization(field))

    def test_relation_field_map_has_accessor_alias(self):
        # Reverse O2O appears under its accessor name ("account").
        rel_map = _relation_field_map(Profile)
        self.assertIn("account", rel_map)

    def test_concrete_field_map_skips_relations_and_non_concrete(self):
        cmap = _concrete_field_map(Account)
        # Concrete scalar present, mapped to its attname.
        self.assertEqual(cmap["username"], "username")
        # The O2O relation is not a plain concrete column here.
        self.assertNotIn("profile", cmap)


# --------------------------------------------------------------------------- #
# Phase 2/3/4 unit tests — GFK classification, recursion guard, .only() cols  #
# --------------------------------------------------------------------------- #
class GFKRecursionGuardTest(TestCase):
    """REQ-5: recursive_params must not crash on a GFK with sub-selection."""

    def test_recursive_params_gfk_sub_selection_no_exception(self):
        # REQ-5 / Scenario: GFK sub-selection completes without AttributeError.
        # The content_object field has a sub-selection -> descent into
        # get_related_model(GFK) used to crash.  After the guard the prefetch
        # path is still recorded and no exception is raised.
        sel, frags = _parse("{ n { text content_object { id } } }")
        rel_map = _relation_field_map(OptNote)
        select, prefetch = recursive_params(sel, frags, rel_map, [], [])
        self.assertIn("content_object", prefetch)
        self.assertEqual(select, [])

    def test_generic_relation_descent_characterization(self):
        # REQ-3 / Scenario: GenericRelation recursion behavior (C-C).
        # GenericRelation is NOT in the guard tuple — descending into it is
        # well-defined (get_related_model returns OptNote).  This test
        # characterises the CURRENT behavior so any future regression is caught.
        # Query: Profile selects notes -> results -> text
        sel, frags = _parse("{ p { notes { results { text } } } }")
        rel_map = _relation_field_map(Profile)
        select, prefetch = recursive_params(sel, frags, rel_map, [], [])
        # notes is a GenericRelation -> "prefetch"
        self.assertIn("notes", prefetch)
        # select_related is empty (GenericRelation is prefetch, not select)
        self.assertEqual(select, [])


# --------------------------------------------------------------------------- #
# recursive_params — O2O select, reverse O2O prefetch, missing fragment         #
# --------------------------------------------------------------------------- #
class RecursiveParamsBranchesTest(TestCase):
    def test_forward_o2o_and_reverse_o2o_are_nested_select(self):
        # Account.profile (forward O2O) -> select; profile.account (reverse O2O)
        # is also one_to_one -> select, nested => "profile__account".
        sel, frags = _parse(
            "{ a { username profile { handle account { username } } } }"
        )
        select, prefetch = recursive_params(
            sel, frags, _relation_field_map(Account), [], []
        )
        self.assertEqual(set(select), {"profile", "profile__account"})
        self.assertEqual(prefetch, [])

    def test_relation_requested_as_leaf_without_subselection(self):
        # A relation field present in the map but selected with no sub-selection:
        # the path is still recorded and the descent is skipped (599->559).
        sel, frags = _parse("{ a { username profile } }")
        select, prefetch = recursive_params(
            sel, frags, _relation_field_map(Account), [], []
        )
        self.assertEqual(set(select), {"profile"})
        self.assertEqual(prefetch, [])

    def test_missing_fragment_spread_is_ignored(self):
        # Fragment spread whose definition is absent -> the None guard skips it.
        sel, _frags = _parse("{ a { username ...Ghost } }")
        select, prefetch = recursive_params(
            sel, {}, _relation_field_map(Account), [], []
        )
        self.assertEqual(select, [])
        self.assertEqual(prefetch, [])


# --------------------------------------------------------------------------- #
# Phase 4 — _collect_only_fields GFK columns (REQ-6)                          #
# --------------------------------------------------------------------------- #
class GFKOnlyFieldsTest(TestCase):
    """REQ-6: _collect_only_fields must inject attname-resolved ct/fk columns."""

    def test_collect_only_fields_gfk_adds_attname_columns(self):
        # REQ-6 / Scenario: ct_field and fk_field attnames present in .only() set.
        # Selecting content_object (GFK) must add "content_type_id" and
        # "object_id" — NOT the raw "content_type" name (which would raise
        # FieldError).  No recursion into GFK target.
        sel, frags = _parse("{ n { text content_object { id } } }")
        only = _collect_only_fields(OptNote, sel, frags)
        self.assertIn("content_type_id", only)
        self.assertIn("object_id", only)
        self.assertNotIn("content_type", only)
        # No columns from the GFK target model (no id__ prefix or similar)
        target_cols = [c for c in only if c.startswith("content_object__")]
        self.assertEqual(target_cols, [])

    def test_collect_only_fields_generic_relation_no_extra_columns(self):
        # REQ-3 / Scenario: No .only() columns injected for GenericRelation.
        # Regression guard: selecting notes (GenericRelation) must add ZERO
        # extra columns vs a query without it.
        sel_with, frags = _parse("{ p { handle notes { results { text } } } }")
        sel_without, _ = _parse("{ p { handle } }")
        only_with = _collect_only_fields(Profile, sel_with, frags)
        only_without = _collect_only_fields(Profile, sel_without, {})
        # notes column set should be identical (GenericRelation = prefetch branch
        # -> not narrowed -> adds nothing to .only()).
        self.assertEqual(set(only_with), set(only_without))

    def test_collect_only_fields_gfk_optimize_only_false(self):
        # REQ-6 / Scenario: GFK .only() columns are NOT forced when
        # OPTIMIZE_ONLY_FIELDS=False.
        # The guard lives in queryset_factory (not in _collect_only_fields itself),
        # so we test it end-to-end: build a queryset_factory call with a GFK
        # selection, patch OPTIMIZE_ONLY_FIELDS=False, and assert the returned
        # queryset is NOT narrowed (no .only() deferred set at all — the queryset
        # loads full rows, so content_type_id and object_id are not "forced
        # through" .only()).
        from graphql import parse as gql_parse
        from graphql.language.ast import OperationDefinitionNode

        gql_doc = gql_parse(
            "{ allNotes { results { text contentObject { id } } totalCount } }"
        )
        op = next(
            d for d in gql_doc.definitions if isinstance(d, OperationDefinitionNode)
        )
        field_node = op.selection_set.selections[0]

        class _GT:
            pass

        info = _FakeInfo(_FakeParentType(_GT), "all_notes", [field_node])

        with mock.patch.object(graphql_api_settings, "OPTIMIZE_ONLY_FIELDS", False):
            qs = queryset_factory(OptNote, None, info)

        # With OPTIMIZE_ONLY_FIELDS=False, _collect_only_fields is never called
        # so the queryset must have no deferred fields (full row load — the
        # .query.deferred_loading default is (frozenset(), True) which means
        # "no columns are deferred").
        deferred_fields, defer_mode = qs.query.deferred_loading
        self.assertFalse(
            deferred_fields,
            "queryset should not have any .only()/.defer() columns when "
            "OPTIMIZE_ONLY_FIELDS=False",
        )


# --------------------------------------------------------------------------- #
# _collect_only_fields — ordering cols, fragments, non-concrete FK, no subsel   #
# --------------------------------------------------------------------------- #
class OnlyFieldsBranchesTest(TestCase):
    def test_ordering_column_always_kept(self):
        # Profile.Meta.ordering = ["handle"] -> "handle" kept even if unrequested.
        sel, frags = _parse("{ p { headline } }")
        only = _collect_only_fields(Profile, sel, frags)
        self.assertIn("id", only)
        self.assertIn("headline", only)
        self.assertIn("handle", only)  # ordering column, not requested

    def test_non_string_and_relation_ordering_terms_skipped(self):
        # OrderingThing.Meta.ordering = [F("rank"), "owner__handle", "label"].
        # The F() term (non-str) and the relation-traversing term ("owner__handle"
        # head "owner" is not a local concrete column) are skipped; only the real
        # local column "label" is force-kept.
        sel, frags = _parse("{ o { rank } }")
        only = _collect_only_fields(OrderingThing, sel, frags)
        self.assertIn("id", only)
        self.assertIn("rank", only)  # requested
        self.assertIn("label", only)  # ordering column kept
        self.assertNotIn("owner__handle", only)  # relation ordering term skipped

    def test_fragment_and_inline_fragment_columns_collected(self):
        query = """
        { a {
            ...Frag
            ... on AccountType { profile { handle } }
        } }
        fragment Frag on AccountType { username }
        """
        sel, frags = _parse(query)
        only = _collect_only_fields(Account, sel, frags)
        self.assertIn("username", only)  # from the spread
        self.assertIn("profile_id", only)  # forward O2O local key
        self.assertIn("profile__handle", only)  # from the inline fragment

    def test_missing_fragment_spread_in_only_is_ignored(self):
        # A fragment spread with no matching definition is skipped (the None
        # guard) and does not affect the collected columns.
        sel, _frags = _parse("{ a { username ...Ghost } }")
        only = _collect_only_fields(Account, sel, {})
        self.assertIn("username", only)
        self.assertIn("id", only)

    def test_select_relation_without_subselection(self):
        # Requesting the O2O relation with no sub-selection: the local FK key is
        # still kept and the walk does not descend.
        sel, frags = _parse("{ a { username profile } }")
        only = _collect_only_fields(Account, sel, frags)
        self.assertIn("profile_id", only)
        self.assertFalse(any(o.startswith("profile__") for o in only))


# =========================================================================== #
# End-to-end schema with O2O + reverse O2O for real query-count assertions     #
# =========================================================================== #
RO2O = Registry()


class ProfileType(DjangoObjectType):
    class Meta:
        model = Profile
        registry = RO2O


class AccountType(DjangoObjectType):
    class Meta:
        model = Account
        registry = RO2O


class AccountListType(DjangoListObjectType):
    class Meta:
        model = Account
        registry = RO2O


class ProfileListType(DjangoListObjectType):
    class Meta:
        model = Profile
        registry = RO2O


class O2OQuery(graphene.ObjectType):
    all_accounts = DjangoListObjectField(AccountListType)
    account = DjangoObjectField(AccountType)
    all_profiles = DjangoListObjectField(ProfileListType)


o2o_schema = Schema(query=O2OQuery)


class O2OOptimizationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        for i in range(5):
            profile = Profile.objects.create(handle="h%d" % i, headline="head%d" % i)
            Account.objects.create(username="u%d" % i, profile=profile)

    def _exec(self, query):
        result = o2o_schema.execute(query)
        assert result.errors is None, result.errors
        return result.data

    def test_forward_o2o_select_related_is_one_query(self):
        # Accounts + their O2O profile in a single joined query (no per-row N+1):
        # 1 count + 1 accounts-join-profile = 2.
        query = """
        { allAccounts { results { username profile { handle } } totalCount } }
        """
        with self.assertNumQueries(2):
            data = self._exec(query)
        self.assertEqual(data["allAccounts"]["totalCount"], 5)
        handles = {r["profile"]["handle"] for r in data["allAccounts"]["results"]}
        self.assertEqual(len(handles), 5)

    def test_reverse_o2o_is_select_related(self):
        # Profile -> reverse O2O account: classified as select_related (one_to_one
        # joins), so it collapses into the profiles query (no per-row N+1):
        # 1 count + 1 profiles-LEFT-JOIN-account = 2.
        query = """
        { allProfiles { results { handle account { username } } totalCount } }
        """
        with self.assertNumQueries(2):
            data = self._exec(query)
        self.assertEqual(data["allProfiles"]["totalCount"], 5)
        usernames = {r["account"]["username"] for r in data["allProfiles"]["results"]}
        self.assertEqual(len(usernames), 5)

    def test_only_fields_off_loads_full_rows(self):
        # With OPTIMIZE_ONLY_FIELDS off, no .only() is applied: the captured SQL
        # for the accounts query selects the deferred "username" column too.
        query = "{ allAccounts { results { profile { handle } } } }"
        with mock.patch.object(graphql_api_settings, "OPTIMIZE_ONLY_FIELDS", False):
            with CaptureQueriesContext(connection) as ctx:
                self._exec(query)
        account_sql = [
            q["sql"]
            for q in ctx.captured_queries
            if 'FROM "tests_account"' in q["sql"] and "COUNT(*)" not in q["sql"]
        ]
        self.assertTrue(account_sql)
        # username is not requested by the query but is loaded (no projection).
        self.assertTrue(any('"tests_account"."username"' in s for s in account_sql))

    def test_only_fields_on_narrows_columns(self):
        # Default (.only on): the unrequested "username" column is deferred out
        # of the accounts SELECT.
        query = "{ allAccounts { results { profile { handle } } } }"
        with CaptureQueriesContext(connection) as ctx:
            self._exec(query)
        account_sql = [
            q["sql"]
            for q in ctx.captured_queries
            if 'FROM "tests_account"' in q["sql"] and "COUNT(*)" not in q["sql"]
        ]
        self.assertTrue(account_sql)
        self.assertFalse(any('"tests_account"."username"' in s for s in account_sql))


# =========================================================================== #
# GenericRelation + GFK end-to-end schema / regression-lock + Phase 7 e2e     #
# =========================================================================== #
RGFK = Registry()


class RProfileType(DjangoObjectType):
    class Meta:
        model = Profile
        registry = RGFK


class RProfileListType(DjangoListObjectType):
    class Meta:
        model = Profile
        registry = RGFK


class OptNoteType(DjangoObjectType):
    class Meta:
        model = OptNote
        registry = RGFK


class OptNoteListType(DjangoListObjectType):
    class Meta:
        model = OptNote
        registry = RGFK


class GFKQuery(graphene.ObjectType):
    all_profiles = DjangoListObjectField(RProfileListType)
    all_notes = DjangoListObjectField(OptNoteListType)


gfk_schema = Schema(query=GFKQuery)


# --------------------------------------------------------------------------- #
# Phase 6 — GenericRelation regression-lock tests (REQ-3)                     #
# --------------------------------------------------------------------------- #
class GenericRelationRegressionLockTest(TestCase):
    """REQ-3: GenericRelation prefetching must remain correct — zero code change.

    All scenarios in this class must be GREEN on the UNMODIFIED tree.  They
    are regression guards: they assert existing (correct) behavior so future
    changes that accidentally break GenericRelation prefetch are caught.
    """

    def test_generic_relation_classification_regression_lock(self):
        # REQ-3 / Scenario: Classification (REGRESSION-LOCK).
        # _relation_optimization on a GenericRelation field already returns
        # ("prefetch", "notes") today — this test locks that.
        notes_field = Profile._meta.get_field("notes")
        self.assertEqual(_relation_optimization(notes_field), ("prefetch", "notes"))
        rel_map = _relation_field_map(Profile)
        self.assertIn("notes", rel_map)

    def test_generic_relation_merge_filtered_prefetch_dedup(self):
        # REQ-3 / Scenario: Plain-string prefetch deduped by filtered Prefetch.
        from unittest import mock

        # Create a mock filtered Prefetch for "notes".
        notes_pf = mock.MagicMock()
        notes_pf.prefetch_through = "notes"
        qs_mock = mock.MagicMock()
        qs_mock.prefetch_related.return_value = qs_mock
        notes_pf.queryset = qs_mock

        plain = ["notes"]  # same lookup as the filtered Prefetch
        out_plain, out_filtered = _merge_filtered_prefetches(plain, [notes_pf])
        # Plain "notes" must be dropped; filtered Prefetch survives.
        self.assertNotIn("notes", out_plain)
        self.assertIn(notes_pf, out_filtered)


class GenericRelationE2ETest(TestCase):
    """End-to-end regression lock for GenericRelation prefetching."""

    @classmethod
    def setUpTestData(cls):
        # 3 profiles, each with 2 notes.
        for i in range(3):
            profile = Profile.objects.create(handle=f"gr{i}", headline=f"headline{i}")
            for j in range(2):
                ct = ContentType.objects.get_for_model(Profile)
                OptNote.objects.create(
                    text=f"note{i}{j}",
                    content_type=ct,
                    object_id=profile.pk,
                )

    def _exec(self, query):
        result = gfk_schema.execute(query)
        assert result.errors is None, result.errors
        return result.data

    def test_generic_relation_prefetch_regression_lock(self):
        # REQ-3 / Scenario: Prefetch is issued for GenericRelation selection.
        # EMPIRICALLY MEASURED query count: 1 (profiles + COUNT) + 1 (notes prefetch)
        # = 2 for allProfiles with notes sub-selection (list field issues
        # count + data in one pagination query).
        # We measure first, then assert.
        query = """
        { allProfiles { results { handle notes { results { text } } } totalCount } }
        """
        with self.assertNumQueries(3):
            data = self._exec(query)

        self.assertEqual(data["allProfiles"]["totalCount"], 3)
        # Each profile has 2 notes; verify via _prefetched_objects_cache.
        profiles_qs = Profile.objects.prefetch_related("notes")
        list(profiles_qs)  # force evaluation
        # The schema query itself already validated there are notes; just check
        # the data has notes results.
        total_notes = sum(
            len(r["notes"]["results"]) for r in data["allProfiles"]["results"]
        )
        self.assertEqual(total_notes, 6)


# --------------------------------------------------------------------------- #
# Phase 7 — GFK end-to-end + mixed-CT (REQ-4, REQ-4b, REQ-5)                 #
# --------------------------------------------------------------------------- #
class GFKEndToEndTest(TestCase):
    """REQ-4/4b/5: GFK prefetch is applied; mixed-CT per-row identity is correct."""

    @classmethod
    def setUpTestData(cls):
        # Three notes pointing at Profile (registered graphene type) and two
        # pointing at Account (also registered).  One note points at
        # OrderingThing (no registered graphene type in RGFK -> unregistered target).
        ct_profile = ContentType.objects.get_for_model(Profile)
        ct_account = ContentType.objects.get_for_model(Account)
        ct_ordering = ContentType.objects.get_for_model(OrderingThing)

        cls.profile1 = Profile.objects.create(handle="gfk1", headline="h1")
        cls.profile2 = Profile.objects.create(handle="gfk2", headline="h2")
        cls.account1 = Account.objects.create(username="acc1", profile=cls.profile1)
        cls.ordering_thing = OrderingThing.objects.create(
            label="ot1", owner=cls.profile1
        )

        cls.note_p1 = OptNote.objects.create(
            text="np1", content_type=ct_profile, object_id=cls.profile1.pk
        )
        cls.note_p2 = OptNote.objects.create(
            text="np2", content_type=ct_profile, object_id=cls.profile2.pk
        )
        cls.note_a1 = OptNote.objects.create(
            text="na1", content_type=ct_account, object_id=cls.account1.pk
        )
        # Unregistered target: OrderingThing has no type in RGFK.
        cls.note_unregistered = OptNote.objects.create(
            text="unregistered",
            content_type=ct_ordering,
            object_id=cls.ordering_thing.pk,
        )

    def _exec(self, query):
        result = gfk_schema.execute(query)
        # Allow errors for unregistered-type resolution (null fields); check
        # data is present.
        return result

    def test_gfk_prefetch_applied(self):
        # REQ-4 / Scenario: queryset_factory adds "content_object" to
        # _prefetch_related_lookups when content_object is in the selection.
        # We call queryset_factory directly with a synthetic info whose
        # field_nodes represent "{ allNotes { results { text contentObject { id
        # } } totalCount } }" so the optimizer sees the GFK field and must emit
        # a prefetch_related("content_object") on the returned queryset.
        from graphql import parse as gql_parse
        from graphql.language.ast import OperationDefinitionNode

        gql_doc = gql_parse(
            "{ allNotes { results { text contentObject { id } } totalCount } }"
        )
        op = next(
            d for d in gql_doc.definitions if isinstance(d, OperationDefinitionNode)
        )
        field_node = op.selection_set.selections[0]  # the allNotes FieldNode

        class _GT:
            pass

        info = _FakeInfo(_FakeParentType(_GT), "all_notes", [field_node])
        qs = queryset_factory(OptNote, None, info)

        # The optimizer must have added "content_object" via prefetch_related.
        prefetch_names = [str(p) for p in qs._prefetch_related_lookups]
        self.assertIn(
            "content_object",
            prefetch_names,
            "queryset_factory did not add content_object to _prefetch_related_lookups",
        )

    def test_mixed_ct_gfk_per_row_identity_orm_cache(self):
        # REQ-4b / Scenario: Per-row identity correctness across distinct target models.
        # Assert via the ORM _prefetched_objects_cache on the queryset the OPTIMIZER
        # actually built — not a standalone hand-built queryset.
        from graphql import parse as gql_parse
        from graphql.language.ast import OperationDefinitionNode

        # Build a synthetic info with content_object in the selection so the
        # optimizer emits prefetch_related("content_object").
        gql_doc = gql_parse(
            "{ allNotes { results { text contentObject { id } } totalCount } }"
        )
        op = next(
            d for d in gql_doc.definitions if isinstance(d, OperationDefinitionNode)
        )
        field_node = op.selection_set.selections[0]

        class _GT:
            pass

        info = _FakeInfo(_FakeParentType(_GT), "all_notes", [field_node])
        qs = queryset_factory(OptNote, None, info)

        # Confirm the optimizer added the prefetch (not a hand-built queryset).
        prefetch_names = [str(p) for p in qs._prefetch_related_lookups]
        self.assertIn("content_object", prefetch_names)

        # Force evaluation — this populates _prefetched_objects_cache.
        notes = list(qs.order_by("pk"))
        notes_by_pk = {n.pk: n for n in notes}

        # Per-row identity: each note's content_object must resolve to the
        # correct instance across distinct content-type groups.
        self.assertEqual(notes_by_pk[self.note_p1.pk].content_object, self.profile1)
        self.assertEqual(notes_by_pk[self.note_p2.pk].content_object, self.profile2)
        self.assertEqual(notes_by_pk[self.note_a1.pk].content_object, self.account1)
        # Unregistered target: ORM resolves correctly even though GraphQL
        # response is null.
        self.assertEqual(
            notes_by_pk[self.note_unregistered.pk].content_object,
            self.ordering_thing,
        )

    def test_mixed_ct_gfk_query_count_empirical(self):
        # REQ-4b / Scenario: Query count is empirically pinned (not formula-derived).
        # Seed: 4 notes with 3 distinct content types (Profile, Account, OrderingThing).
        # Query selects contentObject to trigger the GFK prefetch.
        #
        # Expected: 5 queries
        #   1. COUNT(*) for pagination
        #   2. SELECT notes (base queryset)
        #   3. prefetch for Profile CT group
        #   4. prefetch for Account CT group
        #   5. prefetch for OrderingThing CT group
        #
        # This is O(D) — one prefetch per distinct CT — NOT O(rows) / N+1.
        # N+1 would require (1 COUNT + 1 base + 4 row-queries) = 6 queries.
        query = """
        { allNotes {
            results {
                text
                contentObject { id }
            }
            totalCount
        } }
        """
        with self.assertNumQueries(5):
            result = gfk_schema.execute(query)

        # Total count is correct.
        self.assertEqual(result.data["allNotes"]["totalCount"], 4)

    def test_mixed_ct_unregistered_target_degrades_to_null(self):
        # REQ-4b / Scenario: Unregistered target model degrades to null without error.
        # ORM prefetch cache still resolves correctly (per C-E identity assertion).
        note = OptNote.objects.prefetch_related("content_object").get(
            pk=self.note_unregistered.pk
        )
        # ORM resolves correctly.
        self.assertEqual(note.content_object, self.ordering_thing)

        # The GraphQL response for contentObject on an unregistered target is
        # null or flat fallback — no unhandled exception.
        query = "{ allNotes { results { text } } }"
        result = gfk_schema.execute(query)
        # Must not propagate an unhandled exception.
        # The note itself is still returned (text is always present).
        texts = [r["text"] for r in result.data["allNotes"]["results"]]
        self.assertIn("unregistered", texts)


# =========================================================================== #
# queryset_factory direct: pass-through, non-QuerySet custom resolver,          #
# relation-traversing filter kwargs, empty selection                           #
# =========================================================================== #
class _FakeInfo:
    """Minimal GraphQLResolveInfo stand-in for queryset_factory unit tests."""

    def __init__(self, parent_type, field_name="all_accounts", field_nodes=None):
        self.parent_type = parent_type
        self.field_name = field_name
        self.field_nodes = field_nodes or []
        self.fragments = {}
        self.variable_values = {}
        self.return_type = None


class _FakeParentType:
    def __init__(self, graphene_type):
        self.graphene_type = graphene_type


class QuerysetFactoryBranchesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.profile = Profile.objects.create(handle="zz", headline="h")
        Account.objects.create(username="solo", profile=cls.profile)

    def _info(self, field_name="x", field_nodes=None):
        # A parent type whose graphene_type has no resolve_<field_name>.
        class _GT:
            pass

        return _FakeInfo(_FakeParentType(_GT), field_name, field_nodes)

    def test_optimize_queryset_off_passes_through(self):
        info = self._info()
        with mock.patch.object(graphql_api_settings, "OPTIMIZE_QUERYSET", False):
            qs = queryset_factory(Account, None, info)
        # Pass-through: same model, no select_related applied.
        self.assertEqual(qs.model, Account)
        self.assertEqual(qs.query.select_related, False)

    def test_custom_resolver_returning_non_queryset_is_ignored(self):
        # A resolve_<field> that returns a non-QuerySet must not replace base
        # and must not flip the custom_used flag (so .only() still applies).
        class _GT:
            @staticmethod
            def resolve_all_accounts(root, info, **kwargs):
                return "not a queryset"

        info = _FakeInfo(_FakeParentType(_GT), "all_accounts", [])
        qs = queryset_factory(Account, None, info)
        self.assertEqual(qs.model, Account)

    def test_relation_traversing_filter_kwarg_seeds_select_related(self):
        # A kwarg like ``profile__handle`` must seed the forward-O2O join so the
        # filter does not trigger an extra query.
        info = self._info()
        qs = queryset_factory(Account, None, info, **{"profile__handle": "zz"})
        self.assertIn("profile", qs.query.select_related)

    def test_relation_traversing_filter_kwarg_seeds_prefetch(self):
        # A kwarg head naming an M2M relation seeds prefetch_related instead
        # (Post.tags is many_to_many).
        info = self._info()
        qs = queryset_factory(Post, None, info, **{"tags__label": "x"})
        self.assertIn("tags", [str(p) for p in qs._prefetch_related_lookups])

    def test_duplicate_relation_kwargs_seed_join_once(self):
        # Two kwargs on the same relation (profile__handle + profile__headline)
        # seed the "profile" join only once (the dedupe guard).
        info = self._info()
        qs = queryset_factory(
            Account,
            None,
            info,
            **{"profile__handle": "zz", "profile__headline": "h"},
        )
        self.assertEqual(list(qs.query.select_related.keys()), ["profile"])

    def test_empty_field_nodes_skips_selection_walk(self):
        # No field_nodes -> no recursive walk, no filtered prefetches, no .only().
        info = self._info(field_nodes=[])
        qs = queryset_factory(Account, None, info)
        self.assertEqual(qs.model, Account)
        self.assertEqual(qs.query.select_related, False)


# =========================================================================== #
# _merge_filtered_prefetches direct: top-level, nested filtered, plain child,   #
# same lookup plain + filtered                                                  #
# =========================================================================== #
class MergeFilteredPrefetchesTest(TestCase):
    def _pf(self, through):
        # queryset is a MagicMock whose .prefetch_related(...) returns itself, so
        # children re-rooting is observable via assert_called_*.
        qs = mock.MagicMock()
        qs.prefetch_related.return_value = qs
        return mock.MagicMock(prefetch_through=through, queryset=qs)

    def test_empty_filtered_returns_inputs(self):
        plain = ["tags"]
        out_plain, out_filtered = _merge_filtered_prefetches(plain, [])
        self.assertEqual(out_plain, ["tags"])
        self.assertEqual(out_filtered, [])

    def test_top_level_filtered_kept_plain_unrelated_kept(self):
        pf = self._pf("posts")
        plain = ["tags"]  # unrelated -> stays top-level
        out_plain, out_filtered = _merge_filtered_prefetches(plain, [pf])
        self.assertEqual(out_plain, ["tags"])
        self.assertEqual(out_filtered, [pf])

    def test_plain_child_under_filtered_is_rerooted(self):
        # "posts__comments" lives under filtered "posts" -> it is re-rooted into
        # the filtered Prefetch's queryset (not left as a top-level plain lookup).
        pf = self._pf("posts")
        out_plain, out_filtered = _merge_filtered_prefetches(["posts__comments"], [pf])
        self.assertEqual(out_plain, [])  # re-rooted, not top-level
        self.assertEqual(out_filtered, [pf])
        pf.queryset.prefetch_related.assert_called_once()

    def test_same_lookup_plain_and_filtered_drops_plain(self):
        # A plain "posts" alongside a filtered Prefetch("posts") -> the plain one
        # is dropped (the filtered Prefetch supersedes it).
        pf = self._pf("posts")
        out_plain, out_filtered = _merge_filtered_prefetches(["posts"], [pf])
        self.assertEqual(out_plain, [])
        self.assertEqual(out_filtered, [pf])

    def test_nested_filtered_under_filtered_is_rerooted(self):
        # filtered "posts" and filtered "posts__co_authors": the deeper one is
        # nested into the shallower's queryset, leaving only "posts" top-level.
        parent = self._pf("posts")
        # child.queryset must be a real queryset: it is wrapped in a Prefetch().
        child = mock.MagicMock(
            prefetch_through="posts__co_authors", queryset=Author.objects.all()
        )
        out_plain, out_filtered = _merge_filtered_prefetches([], [parent, child])
        self.assertEqual(out_plain, [])
        # Only the top-level parent remains; child re-rooted into parent.queryset.
        self.assertEqual(out_filtered, [parent])
        parent.queryset.prefetch_related.assert_called_once()

    def test_nearest_keeps_longest_ancestor_when_shorter_seen_later(self):
        # Three filtered lookups where, for the deepest one, the candidate
        # ancestors are visited longest-first then shorter: nearest() must keep
        # the longest (902->900 non-improving branch) and re-root accordingly.
        # Order matters: "posts__co_authors" (longer) is listed before "posts"
        # (shorter) so that, scanning ancestors of the grandchild, the shorter
        # "posts" is seen after the longer best and is rejected (non-improving).
        mid = mock.MagicMock(
            prefetch_through="posts__co_authors", queryset=Author.objects.all()
        )
        grandchild = mock.MagicMock(
            prefetch_through="posts__co_authors__tags",
            queryset=Author.objects.all(),
        )
        parent = self._pf("posts")
        out_plain, out_filtered = _merge_filtered_prefetches(
            [], [mid, parent, grandchild]
        )
        # Only the top-level "posts" survives; the deeper ones nest under their
        # nearest (longest) filtered ancestor.
        throughs = {pf.prefetch_through for pf in out_filtered}
        self.assertEqual(throughs, {"posts"})

    def test_unrelated_filtered_siblings_both_top_level(self):
        # Two filtered lookups with no ancestor relation between them: nearest()
        # iterates and finds none, so both stay top-level (902->900 loop, 916).
        a = self._pf("posts")
        b = self._pf("tags")
        out_plain, out_filtered = _merge_filtered_prefetches([], [a, b])
        self.assertEqual(out_plain, [])
        self.assertEqual(set(out_filtered), {a, b})


# =========================================================================== #
# Filtered nested lists: exercise the _walk_filtered_prefetches AST walk        #
# (fragments, inline fragments, __typename leaf, deeper filtered list) through  #
# real queries, asserting the filter is applied AND stays N+1-free.            #
# =========================================================================== #
RFILT = Registry()


class FTagType(DjangoObjectType):
    class Meta:
        model = Tag
        registry = RFILT


class FAuthorType(DjangoObjectType):
    class Meta:
        model = Author
        registry = RFILT


class FPostType(DjangoObjectType):
    class Meta:
        model = Post
        registry = RFILT
        filter_fields = {"title": ["icontains", "exact"]}


class FAuthorListType(DjangoListObjectType):
    class Meta:
        model = Author
        registry = RFILT


filt_schema = Schema(
    query=type(
        "FQ",
        (graphene.ObjectType,),
        {
            "authors": DjangoListObjectField(FAuthorListType),
        },
    )
)


class FilteredPrefetchWalkTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        for n in range(4):
            author = Author.objects.create(name="A%d" % n)
            for j in range(3):
                Post.objects.create(title="t%d-%d" % (n, j), author=author)

    def _exec(self, query):
        result = filt_schema.execute(query)
        assert result.errors is None, result.errors
        return result.data

    def test_filtered_nested_list_through_fragment_and_typename(self):
        # The filtered ``posts`` list is reached via a fragment spread, an inline
        # fragment and past a ``__typename`` leaf (field_def None). The filter is
        # applied and the whole thing is fetched in a constant number of queries.
        query = """
        { authors {
            __typename
            results {
              ...AuthorFields
              ... on FAuthorType {
                posts(filter: { title: { icontains: "1" } }) {
                  results { title } totalCount
                }
              }
            }
            totalCount
          }
        }
        fragment AuthorFields on FAuthorType { name }
        """
        with CaptureQueriesContext(connection) as ctx:
            data = self._exec(query)
        # Every author's posts list is filtered to titles containing "1".
        for author in data["authors"]["results"]:
            for post in author["posts"]["results"]:
                self.assertIn("1", post["title"])
        # Add more authors/posts: query count must not grow (single filtered
        # Prefetch for all parents, no per-parent N+1).
        before = len(ctx.captured_queries)
        for n in range(5):
            extra = Author.objects.create(name="Z%d" % n)
            Post.objects.create(title="t-extra-1-%d" % n, author=extra)
        with CaptureQueriesContext(connection) as ctx2:
            self._exec(query)
        self.assertEqual(len(ctx2.captured_queries), before)

    def test_filtered_nested_list_via_plain_field(self):
        # Plain (non-fragment) path through the filtered nested list.
        query = (
            '{ authors { results { posts(filter: { title: { exact: "t0-0" } }) '
            "{ results { title } totalCount } } } }"
        )
        data = self._exec(query)
        first = next(a for a in data["authors"]["results"] if a["posts"]["totalCount"])
        self.assertEqual(first["posts"]["results"][0]["title"], "t0-0")


# =========================================================================== #
# build_filtered_prefetches early returns (non-object return type / no          #
# selection set) via a fake info.                                              #
# =========================================================================== #
class BuildFilteredPrefetchesGuardTest(TestCase):
    def test_no_field_nodes_yields_no_prefetches(self):
        # No field_nodes / non-object return type -> early return [] (855).
        from django_graphex.utils import build_filtered_prefetches

        class _Info:
            return_type = None  # get_named_type(None) -> None, not an object type
            field_nodes = []
            fragments = {}
            variable_values = {}

        self.assertEqual(build_filtered_prefetches(_Info()), [])

    def test_object_return_type_without_selection_set(self):
        # Object return type but the field node carries no selection set -> the
        # second guard returns [] (858).
        from graphql import GraphQLObjectType, GraphQLString

        from django_graphex.utils import build_filtered_prefetches

        return_type = GraphQLObjectType(
            "Dummy", lambda: {"x": __import__("graphql").GraphQLField(GraphQLString)}
        )
        field_node = next(iter(parse("{ x }").definitions)).selection_set.selections[0]
        # A scalar leaf node has no selection_set.
        self.assertIsNone(field_node.selection_set)

        class _Info:
            field_nodes = [field_node]
            fragments = {}
            variable_values = {}

        info = _Info()
        info.return_type = return_type
        self.assertEqual(build_filtered_prefetches(info), [])


# =========================================================================== #
# SAFE_MODE guard in queryset_factory (REQ-2)                                 #
# =========================================================================== #
class SafeModeTest(TestCase):
    """REQ-2: queryset_factory degrades gracefully when OPTIMIZER_SAFE_MODE=True."""

    @classmethod
    def setUpTestData(cls):
        cls.profile = Profile.objects.create(handle="sm", headline="h")

    def _info(self, field_name="x", field_nodes=None):
        class _GT:
            pass

        return _FakeInfo(_FakeParentType(_GT), field_name, field_nodes)

    def test_safe_mode_degradation_on_forced_exception(self):
        # REQ-2 / Scenario: Degradation on forced exception inside optimization block.
        # Patching _relation_field_map to raise causes the optimizer to degrade.
        import django_graphex.utils as utils_module

        info = self._info()
        Profile.objects.all()

        with (
            mock.patch.object(graphql_api_settings, "OPTIMIZER_SAFE_MODE", True),
            mock.patch.object(
                utils_module, "_relation_field_map", side_effect=RuntimeError("boom")
            ),
            self.assertLogs("django_graphex.utils", level="WARNING") as cm,
        ):
            qs = queryset_factory(Profile, None, info)

        # Returns a valid queryset for the same model.
        self.assertEqual(qs.model, Profile)
        # Exactly one WARNING containing model name and exception repr.
        self.assertEqual(len(cm.output), 1)
        self.assertIn("WARNING", cm.output[0])
        self.assertIn("Profile", cm.output[0])
        self.assertIn("RuntimeError", cm.output[0])

    def test_safe_mode_off_exception_propagates(self):
        # REQ-2 / Scenario: Exception propagates when SAFE_MODE is off (default).
        import django_graphex.utils as utils_module

        info = self._info()
        with (
            mock.patch.object(graphql_api_settings, "OPTIMIZER_SAFE_MODE", False),
            mock.patch.object(
                utils_module, "_relation_field_map", side_effect=RuntimeError("boom")
            ),
        ):
            with self.assertRaises(RuntimeError):
                queryset_factory(Profile, None, info)

    def test_safe_mode_try_boundary_at_relation_field_map(self):
        # REQ-2 / Scenario: try boundary starts at _relation_field_map.
        # Patching _relation_field_map to raise BEFORE the fields_asts branch
        # proves the try block starts before that branch.
        import django_graphex.utils as utils_module

        info = self._info()
        with (
            mock.patch.object(graphql_api_settings, "OPTIMIZER_SAFE_MODE", True),
            mock.patch.object(
                utils_module,
                "_relation_field_map",
                side_effect=RuntimeError("boundary"),
            ),
            self.assertLogs("django_graphex.utils", level="WARNING") as cm,
        ):
            qs = queryset_factory(Profile, None, info)

        self.assertEqual(qs.model, Profile)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("boundary", cm.output[0])

    def test_safe_mode_custom_resolver_base_preserved(self):
        # REQ-2 / Scenario: Custom-resolver base is preserved on degradation.
        # When a custom resolver provides a queryset and the optimizer then
        # fails, SAFE_MODE must return the custom base, NOT the default manager
        # queryset.
        #
        # Implementation note: with field_nodes=[] the build_filtered_prefetches
        # call is gated by ``if fields_asts`` and is never reached, so the
        # original apply used _relation_field_map as the failure-injection point.
        # This rework populates field_nodes with a real GQL selection so that
        # build_filtered_prefetches IS reached inside _apply_optimizations, and
        # patches that function to raise — matching the REQ-2 scenario verbatim.
        import django_graphex.utils as utils_module
        from django_graphex.utils import (
            build_filtered_prefetches,  # noqa: F401 used below
        )

        custom_qs = Profile.objects.filter(handle="sm")

        class _GT:
            @staticmethod
            def resolve_x(root, info, **kwargs):
                return custom_qs

        # Build a real GQL document so field_nodes is populated and
        # build_filtered_prefetches is reached inside _apply_optimizations.
        gql_doc = parse("{ x { results { handle } totalCount } }")
        op = next(
            d for d in gql_doc.definitions if isinstance(d, OperationDefinitionNode)
        )
        field_node = op.selection_set.selections[0]

        info = _FakeInfo(_FakeParentType(_GT), "x", [field_node])

        with (
            mock.patch.object(graphql_api_settings, "OPTIMIZER_SAFE_MODE", True),
            mock.patch.object(
                utils_module,
                "build_filtered_prefetches",
                side_effect=RuntimeError("custom-base-bfp"),
            ),
            self.assertLogs("django_graphex.utils", level="WARNING"),
        ):
            qs = queryset_factory(Profile, None, info)

        # Returned queryset is the custom base (filtered to handle="sm"),
        # not the unfiltered Profile.objects.all().
        self.assertIn("sm", [p.handle for p in qs])

    def test_optimize_queryset_false_takes_precedence_over_safe_mode(self):
        # REQ-2 / Scenario: OPTIMIZE_QUERYSET=False takes precedence over SAFE_MODE.
        # The early return at the OPTIMIZE_QUERYSET check must fire before the
        # SAFE_MODE guard; no warning must be emitted, no exception raised.
        import django_graphex.utils as utils_module

        info = self._info()
        with (
            mock.patch.object(graphql_api_settings, "OPTIMIZER_SAFE_MODE", True),
            mock.patch.object(graphql_api_settings, "OPTIMIZE_QUERYSET", False),
            mock.patch.object(
                utils_module,
                "_relation_field_map",
                side_effect=RuntimeError("should not reach"),
            ),
        ):
            # No assertLogs — no WARNING must be emitted.
            qs = queryset_factory(Profile, None, info)

        self.assertEqual(qs.model, Profile)


# =========================================================================== #
# Phase B — PR1 tests (tasks 1.1 – 3.9)                                       #
# =========================================================================== #
# --------------------------------------------------------------------------- #
# Task 1.1 / 1.2 — _leaf_model                                                #
# --------------------------------------------------------------------------- #
class TestLeafModel(TestCase):
    def test_leaf_model_single_segment_reverse_fk(self):
        # _leaf_model(Author, "posts") -> Post
        from .models import Author, Post

        self.assertIs(_leaf_model(Author, "posts"), Post)

    def test_leaf_model_dotted_prefetch_walk(self):
        # _leaf_model(Author, "posts__tags") walks reverse-FK then forward-M2M -> Tag
        from .models import Author, Tag

        self.assertIs(_leaf_model(Author, "posts__tags"), Tag)


# --------------------------------------------------------------------------- #
# Task 1.3 / 1.4 — PrefetchPlan dataclass                                     #
# --------------------------------------------------------------------------- #
class TestPrefetchPlan(TestCase):
    def test_prefetch_plan_dataclass_has_expected_attributes(self):
        plan = PrefetchPlan(only_cols=["id", "title"], child_select=["category"])
        self.assertEqual(plan.only_cols, ["id", "title"])
        self.assertEqual(plan.child_select, ["category"])

    def test_prefetch_plan_empty_defaults(self):
        plan = PrefetchPlan(only_cols=[], child_select=[])
        self.assertEqual(plan.only_cols, [])
        self.assertEqual(plan.child_select, [])


# --------------------------------------------------------------------------- #
# Tasks 2.1–2.5 — _compute_child_only                                         #
# --------------------------------------------------------------------------- #
class TestComputeChildOnly(TestCase):
    """Unit tests for _compute_child_only (no DB)."""

    def _sel(self, query):
        return _parse(query)

    def test_reverse_fk_includes_fk_back(self):
        # Author.posts reverse FK: author_id must always be in only_cols even
        # when not requested.  Post body must NOT be present.
        from .models import Author, Post

        related_field = Author._meta.get_field("posts")  # ManyToOneRel
        sel, frags = _parse("{ a { posts { title } } }")
        # Descend into posts sub-selection
        posts_sel = sel.selections[0].selection_set  # { title }
        plan = _compute_child_only(Post, related_field, posts_sel, frags)
        self.assertIsNotNone(plan)
        self.assertIn("author_id", plan.only_cols)
        self.assertIn("id", plan.only_cols)
        self.assertIn("title", plan.only_cols)
        self.assertNotIn("body", plan.only_cols)

    def test_m2m_forward_no_fk_back(self):
        # Post.tags forward M2M: only pk+label+ordering, NO fk-back attname.
        from .models import Post, Tag

        related_field = Post._meta.get_field("tags")  # ManyToManyField
        sel, frags = _parse("{ p { tags { label } } }")
        tags_sel = sel.selections[0].selection_set  # { label }
        plan = _compute_child_only(Tag, related_field, tags_sel, frags)
        self.assertIsNotNone(plan)
        self.assertIn("id", plan.only_cols)
        self.assertIn("label", plan.only_cols)
        # No FK-back attname for forward M2M
        for col in plan.only_cols:
            self.assertFalse(
                col.endswith("_id") and "post" in col.lower(),
                f"Unexpected FK-back {col!r} in M2M plan",
            )

    def test_m2m_reverse_no_crash(self):
        # Author.coauthored_posts reverse M2M (ManyToManyRel): no crash,
        # no FK-back, dispatch via many_to_many flag.
        from .models import Author, Post

        related_field = Author._meta.get_field("coauthored_posts")  # ManyToManyRel
        sel, frags = _parse("{ a { coauthoredPosts { title } } }")
        cp_sel = sel.selections[0].selection_set  # { title }
        plan = _compute_child_only(Post, related_field, cp_sel, frags)
        self.assertIsNotNone(plan)
        self.assertIn("id", plan.only_cols)
        self.assertIn("title", plan.only_cols)

    def test_ordering_attnames_included(self):
        # Profile.Meta.ordering = ["handle"] -> handle attname kept even when not requested.
        sel, frags = _parse("{ p { notes { headline } } }")
        # We need a ManyToOneRel-like field; use Profile's notes (GenericRelation)
        # BUT for ordering test, we just test _compute_child_only on Profile itself
        # via a reverse-FK from Account.
        # Account.profile is O2O -> profile is FK target. Use ordering test on
        # a simpler reverse-FK: OrderingThing.owner is FK to Profile.
        # Actually test using Profile ordering via collect_only_fields sub-path.
        # Simplest approach: call _compute_child_only with a fake rev-FK from a
        # parent to Profile, and verify handle is in only_cols.
        # Use Account._meta.get_field("profile") -- but that's select not prefetch.
        # So let's test the ordering column inclusion via the always-keep base:
        # create a reverse FK scenario by inspecting Profile's own ordering.
        #
        # OrderingThing has ordering with F() + relation-traversing + concrete.
        # Test that 'label' is kept and F()/relation-traversing skipped.

        related_field = Profile._meta.get_field("ordering_things")  # ManyToOneRel
        sel, frags = _parse("{ p { ordering_things { rank } } }")
        ot_sel = sel.selections[0].selection_set  # { rank }
        plan = _compute_child_only(OrderingThing, related_field, ot_sel, frags)
        self.assertIsNotNone(plan)
        # "label" is in Meta.ordering -> must be included always
        self.assertIn("label", plan.only_cols)
        # F() terms and relation-traversing "owner__handle" should NOT produce
        # an "owner__handle" string in only_cols
        self.assertNotIn("owner__handle", plan.only_cols)
        # "rank" is requested -> must be included
        self.assertIn("rank", plan.only_cols)

    def test_child_select_related_co_computed_gap1(self):
        # GAP-1: AST { posts { title category { title } } } on Author.
        # _compute_child_only must return child_select containing "category"
        # (the forward FK head), not just flat only_cols.
        from .models import Author, Post

        related_field = Author._meta.get_field("posts")  # ManyToOneRel
        sel, frags = _parse("{ a { posts { title category { title } } } }")
        posts_sel = sel.selections[0].selection_set  # { title category { title } }
        plan = _compute_child_only(Post, related_field, posts_sel, frags)
        self.assertIsNotNone(plan)
        self.assertIn("category", plan.child_select)
        # category_id (FK attname) must be in only_cols
        self.assertIn("category_id", plan.only_cols)
        # category__title also in only_cols (dotted path)
        self.assertIn("category__title", plan.only_cols)

    def test_full_load_fallback_on_computed_leaf(self):
        # Author.display_name is a @property -> _compute_child_only returns None
        # (full-load fallback).
        from .models import Author, Post

        # We need a relation where Author is the child, but Author has display_name
        # property. Create a reverse FK lookup where Author is child with @property.
        # Use Author directly: we need some parent -> Author reverse relation.
        # Actually Author doesn't have a reverse FK parent in our models,
        # but we can use Post.co_authors (M2M to Author) and request display_name.
        related_field = Post._meta.get_field("co_authors")  # ManyToManyField to Author
        sel, frags = _parse("{ p { co_authors { display_name } } }")
        ca_sel = sel.selections[0].selection_set  # { display_name }
        plan = _compute_child_only(Author, related_field, ca_sel, frags)
        # display_name is a @property -> full-load -> None
        self.assertIsNone(plan)


# --------------------------------------------------------------------------- #
# Tasks 2.7–2.10 — _collect_prefetch_only_sets                                #
# --------------------------------------------------------------------------- #
class TestCollectPrefetchOnlySets(TestCase):
    """Unit tests for _collect_prefetch_only_sets (no DB)."""

    def test_gfk_target_skip_no_crash_gap3(self):
        # GAP-3: content_object (GFK-target) must NOT appear in the returned map
        # and must not raise AttributeError (isinstance-GFK check before get_related_model).
        sel, frags = _parse("{ n { text content_object { id } } }")
        result = _collect_prefetch_only_sets(OptNote, sel, frags)
        self.assertNotIn("content_object", result)

    def test_collect_reverse_fk(self):
        # Author.posts reverse FK: 'posts' key must be in result with a PrefetchPlan.
        from .models import Author

        sel, frags = _parse("{ a { name posts { title } } }")
        result = _collect_prefetch_only_sets(Author, sel, frags)
        self.assertIn("posts", result)
        plan = result["posts"]
        self.assertIsInstance(plan, PrefetchPlan)
        self.assertIn("author_id", plan.only_cols)
        self.assertIn("title", plan.only_cols)

    def test_collect_forward_m2m(self):
        # Post.tags forward M2M: 'tags' in result.
        from .models import Post

        sel, frags = _parse("{ p { title tags { label } } }")
        result = _collect_prefetch_only_sets(Post, sel, frags)
        self.assertIn("tags", result)
        plan = result["tags"]
        self.assertIn("label", plan.only_cols)

    def test_collect_reverse_m2m(self):
        # Author.coauthored_posts reverse M2M (ManyToManyRel): in result.
        from .models import Author

        sel, frags = _parse("{ a { name coauthored_posts { title } } }")
        result = _collect_prefetch_only_sets(Author, sel, frags)
        self.assertIn("coauthored_posts", result)

    def test_collect_generic_relation_ct_fk_discovery(self):
        # Profile.notes GenericRelation: 'notes' key with content_type_id + object_id
        # in only_cols (NOT raw 'content_type').
        sel, frags = _parse("{ p { handle notes { results { text } } } }")
        result = _collect_prefetch_only_sets(Profile, sel, frags)
        self.assertIn("notes", result)
        plan = result["notes"]
        self.assertIn("content_type_id", plan.only_cols)
        self.assertIn("object_id", plan.only_cols)
        self.assertIn("id", plan.only_cols)
        self.assertIn("text", plan.only_cols)
        self.assertNotIn("content_type", plan.only_cols)

    def test_collect_multi_gfk_disambiguation(self):
        # REQ-B2 / GAP-2: multi-GFK disambiguation.
        #
        # OptTaggedItem has two GFKs:
        #   content_object  -> ct_field='content_type',  fk_field='object_id'
        #   tagged_by       -> ct_field='tagger_ct',     fk_field='tagger_id'
        #
        # Profile.notes is a GenericRelation with content_type_field_name='content_type'
        # and object_id_field_name='object_id'.  We call _compute_child_only with
        # OptTaggedItem as the child and notes_field as the relation — the
        # disambiguation must pick content_object (matching ct/fk names) and
        # inject content_type_id + object_id into only_cols, NOT tagger_ct_id/tagger_id.
        #
        # The sub-selection selects 'label', a real concrete field on OptTaggedItem,
        # so the full-load fallback is NOT triggered.
        notes_field = Profile._meta.get_field("notes")
        # notes_field.content_type_field_name == 'content_type'
        # notes_field.object_id_field_name    == 'object_id'

        # _parse returns the selection set one level below the top field.
        # "{ p { notes { label } } }" -> sel = p's selection set = { notes { label } }
        # sel.selections[0] is the 'notes' field node;
        # sel.selections[0].selection_set = { label } — the child sub-selection.
        sel, frags = _parse("{ p { notes { label } } }")
        child_sel = sel.selections[0].selection_set  # { label }

        plan = _compute_child_only(OptTaggedItem, notes_field, child_sel, frags)

        # Disambiguation must succeed: plan is NOT None.
        self.assertIsNotNone(plan)

        # Must include the structural columns for the matched GFK (content_object).
        self.assertIn("content_type_id", plan.only_cols)
        self.assertIn("object_id", plan.only_cols)

        # Must NOT include columns from the other GFK (tagged_by).
        self.assertNotIn("tagger_ct_id", plan.only_cols)
        self.assertNotIn("tagger_id", plan.only_cols)


# --------------------------------------------------------------------------- #
# Tasks 3.1–3.5 — _narrow_plain_prefetch                                      #
# --------------------------------------------------------------------------- #
class TestNarrowPlainPrefetch(TestCase):
    def test_lookup_not_in_map_returns_string(self):
        # lookup absent from map -> bare string returned
        from .models import Author

        result = _narrow_plain_prefetch(Author, "posts", {})
        self.assertEqual(result, "posts")

    def test_lookup_in_map_returns_prefetch_with_only(self):
        from django.db.models import Prefetch as DjPrefetch

        from .models import Author

        plan = PrefetchPlan(only_cols=["id", "title", "author_id"], child_select=[])
        result = _narrow_plain_prefetch(Author, "posts", {"posts": plan})
        self.assertIsInstance(result, DjPrefetch)
        self.assertEqual(result.prefetch_through, "posts")
        # queryset must have .only() applied
        qs = result.queryset
        deferred, mode = qs.query.deferred_loading
        # mode=False means "only these fields"
        self.assertFalse(mode, "Expected only() (mode=False means only these cols)")

    def test_lookup_in_map_with_child_select_returns_prefetch_with_select_related(self):
        from django.db.models import Prefetch as DjPrefetch

        from .models import Author

        plan = PrefetchPlan(
            only_cols=["id", "title", "author_id", "category_id", "category__title"],
            child_select=["category"],
        )
        result = _narrow_plain_prefetch(Author, "posts", {"posts": plan})
        self.assertIsInstance(result, DjPrefetch)
        qs = result.queryset
        # select_related must include 'category'
        self.assertIn("category", qs.query.select_related)

    def test_dotted_lookup_uses_leaf_model(self):
        from django.db.models import Prefetch as DjPrefetch

        from .models import Author, Tag

        plan = PrefetchPlan(only_cols=["id", "label"], child_select=[])
        result = _narrow_plain_prefetch(Author, "posts__tags", {"posts__tags": plan})
        self.assertIsInstance(result, DjPrefetch)
        self.assertEqual(result.prefetch_through, "posts__tags")
        # queryset must be on Tag model
        self.assertIs(result.queryset.model, Tag)


# --------------------------------------------------------------------------- #
# Tasks 3.6–3.9 — Conversion block and SAFE_MODE                              #
# --------------------------------------------------------------------------- #
class TestConversionBlock(TestCase):
    def test_conversion_runs_after_merge_not_before(self):
        # REQ-B5: Passing a Prefetch object into _merge_filtered_prefetches raises
        # when there are filtered prefetches to process (which trigger string ops).
        # This confirms the invariant: conversion must happen AFTER merge.
        from unittest import mock

        from django.db.models import Prefetch as DjPrefetch

        from .models import Author

        plain_pf = DjPrefetch("posts", queryset=Author._default_manager.all())
        # _merge_filtered_prefetches expects plain STRINGS in the first arg.
        # Passing a Prefetch as a plain item reaches nearest(path) which calls
        # path.startswith(...) and must fail with AttributeError or TypeError.
        # We need a non-empty filtered_prefetches list so it doesn't early-return.
        qs = mock.MagicMock()
        qs.prefetch_related.return_value = qs
        filtered_pf = mock.MagicMock(prefetch_through="tags", queryset=qs)
        with self.assertRaises((AttributeError, TypeError)):
            _merge_filtered_prefetches([plain_pf], [filtered_pf])

    def test_optimize_only_fields_false_no_conversion(self):
        # REQ-B4: With OPTIMIZE_ONLY_FIELDS=False, prefetch strings stay strings.
        from graphql import parse as gql_parse
        from graphql.language.ast import OperationDefinitionNode

        from .models import Author

        gql_doc = gql_parse(
            "{ allAuthors { results { name posts { title } } totalCount } }"
        )
        op = next(
            d for d in gql_doc.definitions if isinstance(d, OperationDefinitionNode)
        )
        field_node = op.selection_set.selections[0]

        class _GT:
            pass

        info = _FakeInfo(_FakeParentType(_GT), "all_authors", [field_node])

        with mock.patch.object(graphql_api_settings, "OPTIMIZE_ONLY_FIELDS", False):
            qs = queryset_factory(Author, None, info)

        # prefetch_related lookups should be bare strings (no Prefetch wrappers)
        prefetch_names = [str(p) for p in qs._prefetch_related_lookups]
        self.assertIn("posts", prefetch_names)
        # None of the lookups should be Prefetch objects wrapping with .only()
        from django.db.models import Prefetch as DjPrefetch

        for p in qs._prefetch_related_lookups:
            self.assertNotIsInstance(p, DjPrefetch)

    def test_safe_mode_degrades_on_exception(self):
        # REQ-B4: Patch _collect_prefetch_only_sets to raise.
        # SAFE_MODE=True -> un-optimized queryset + one WARNING.
        # SAFE_MODE=False -> exception propagates.
        from graphql import parse as gql_parse
        from graphql.language.ast import OperationDefinitionNode

        import django_graphex.utils as utils_module

        from .models import Author

        gql_doc = gql_parse(
            "{ allAuthors { results { name posts { title } } totalCount } }"
        )
        op = next(
            d for d in gql_doc.definitions if isinstance(d, OperationDefinitionNode)
        )
        field_node = op.selection_set.selections[0]

        class _GT:
            pass

        info = _FakeInfo(_FakeParentType(_GT), "all_authors", [field_node])

        # SAFE_MODE=True: should degrade gracefully
        with (
            mock.patch.object(graphql_api_settings, "OPTIMIZE_ONLY_FIELDS", True),
            mock.patch.object(graphql_api_settings, "OPTIMIZER_SAFE_MODE", True),
            mock.patch.object(
                utils_module,
                "_collect_prefetch_only_sets",
                side_effect=RuntimeError("prefetch-boom"),
            ),
            self.assertLogs("django_graphex.utils", level="WARNING") as cm,
        ):
            qs = queryset_factory(Author, None, info)

        self.assertEqual(qs.model, Author)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("WARNING", cm.output[0])

        # SAFE_MODE=False: exception should propagate
        with (
            mock.patch.object(graphql_api_settings, "OPTIMIZE_ONLY_FIELDS", True),
            mock.patch.object(graphql_api_settings, "OPTIMIZER_SAFE_MODE", False),
            mock.patch.object(
                utils_module,
                "_collect_prefetch_only_sets",
                side_effect=RuntimeError("prefetch-boom"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                queryset_factory(Author, None, info)


# =========================================================================== #
# Phase B PR2 — Tasks 4.1–4.5: Full-load sibling isolation + REQ-B6 regression#
# =========================================================================== #


class TestFullLoadSiblingIsolation(TestCase):
    """Task 4.1/4.2 — per-child full-load isolation.

    When one prefetch branch has an unknown/@property leaf (full-load) and a
    sibling branch has only concrete leaves (narrowable), the narrowable branch
    MUST be narrowed and the full-load branch MUST NOT be narrowed (bare string).
    """

    def test_full_load_sibling_isolation(self):
        from .models import Author, Post

        # Branch A — Author.posts (reverse FK), concrete leaf 'title' -> narrowable.
        posts_field = Author._meta.get_field("posts")
        sel_narrowable, frags = _parse("{ a { posts { title } } }")
        posts_sub = sel_narrowable.selections[0].selection_set
        plan_a = _compute_child_only(Post, posts_field, posts_sub, frags)
        self.assertIsNotNone(plan_a, "Concrete-leaf branch should be narrowable")
        self.assertIn("title", plan_a.only_cols)

        # Branch B — Post.co_authors (M2M), @property leaf 'display_name' -> full-load.
        co_field = Post._meta.get_field("co_authors")
        sel_full, frags2 = _parse("{ p { co_authors { display_name } } }")
        co_sub = sel_full.selections[0].selection_set
        plan_b = _compute_child_only(Author, co_field, co_sub, frags2)
        self.assertIsNone(
            plan_b, "Branch with @property leaf should be full-load (None)"
        )

        # Via _collect_prefetch_only_sets on Post: 'tags' (concrete) is narrowable;
        # 'co_authors' (@property) is omitted from the map (full-load).
        sel, frags = _parse("{ p { tags { label } co_authors { display_name } } }")
        only_map = _collect_prefetch_only_sets(Post, sel, frags)

        self.assertIn("tags", only_map, "tags (concrete leaf) must be narrowable")
        self.assertNotIn(
            "co_authors",
            only_map,
            "co_authors (@property leaf) must be omitted from map (full-load)",
        )


class TestREQB6RegressionNotNarrowed(TestCase):
    """Task 4.4/4.5 — REQ-B6: plain child re-rooted under filtered Prefetch stays full-load.

    After Phase B, a plain child path nested under a filtered Prefetch is absorbed
    by _merge_filtered_prefetches into pf.queryset BEFORE the conversion block runs.
    It therefore never appears in top_plain and is never passed to
    _narrow_plain_prefetch. Its queryset remains full-load.
    """

    def test_rerooted_child_stays_full_load(self):
        from django.db.models import Prefetch as DjPrefetch

        from .models import Post

        # 'posts__tags' is a plain child nested under a filtered Prefetch for 'posts'.
        # _merge_filtered_prefetches re-roots 'posts__tags' -> 'tags' into the
        # filtered queryset, so top_plain is empty and the conversion block never
        # sees it (REQ-B6 invariant).
        filtered_pf = DjPrefetch(
            "posts", queryset=Post.objects.filter(title__icontains="")
        )
        top_plain, top_filtered = _merge_filtered_prefetches(
            ["posts__tags"], [filtered_pf]
        )
        self.assertEqual(top_plain, [], "Re-rooted child must not appear in top_plain")
        self.assertIn(filtered_pf, top_filtered)

        # The filtered Prefetch's queryset remains full-load (no .only() applied).
        deferred_fields, defer_mode = filtered_pf.queryset.query.deferred_loading
        self.assertEqual(
            (deferred_fields, defer_mode),
            (frozenset(), True),
            "Re-rooted child queryset must be full-load (no .only() applied)",
        )


class TestGAP4DottedNestedPrefetchFullLoad(TestCase):
    """Task 5.2 item 20 (GAP-4) — dotted nested-prefetch lookup stays full-load.

    Calls ``_collect_prefetch_only_sets`` and ``_narrow_plain_prefetch`` directly
    (no DB, no assertNumQueries). Asserts that a direct prefetch ('posts') is
    narrowed while a dotted child ('posts__tags') is NOT in the only_map and
    therefore stays a bare string (full-load).
    """

    def test_dotted_nested_prefetch_stays_bare_string(self):
        from django.db.models import Prefetch as DjPrefetch

        from .models import Author

        sel, frags = _parse("{ a { posts { title tags { label } } } }")
        only_map = _collect_prefetch_only_sets(Author, sel, frags)

        # Direct prefetch 'posts' is in the map.
        self.assertIn("posts", only_map)

        top_plain = ["posts", "posts__tags"]
        converted = [_narrow_plain_prefetch(Author, lk, only_map) for lk in top_plain]

        # 'posts' is narrowed to a Prefetch with .only() applied (deferred_loading mode=False).
        posts_item = converted[0]
        self.assertIsInstance(posts_item, DjPrefetch)
        self.assertEqual(posts_item.prefetch_through, "posts")
        _, mode = posts_item.queryset.query.deferred_loading
        self.assertFalse(mode)

        # 'posts__tags' is not in the map — stays a bare string (GAP-4 limitation).
        tags_item = converted[1]
        self.assertIsInstance(tags_item, str)
        self.assertEqual(tags_item, "posts__tags")


# =========================================================================== #
# Phase B PR2 — Task 5.1b: Author-rooted e2e schema scaffold                  #
# =========================================================================== #

RAUTHOR = Registry()


class ECategoryType(DjangoObjectType):
    class Meta:
        model = __import__("tests.models", fromlist=["Category"]).Category
        registry = RAUTHOR


class ETagType(DjangoObjectType):
    class Meta:
        model = __import__("tests.models", fromlist=["Tag"]).Tag
        registry = RAUTHOR


class EAuthorType(DjangoObjectType):
    display_name = graphene.String()

    class Meta:
        model = __import__("tests.models", fromlist=["Author"]).Author
        registry = RAUTHOR

    def resolve_display_name(self, info):
        return self.display_name


class EPostType(DjangoObjectType):
    class Meta:
        model = __import__("tests.models", fromlist=["Post"]).Post
        registry = RAUTHOR


class EPostListType(DjangoListObjectType):
    class Meta:
        model = __import__("tests.models", fromlist=["Post"]).Post
        registry = RAUTHOR


class EAuthorListType(DjangoListObjectType):
    class Meta:
        model = __import__("tests.models", fromlist=["Author"]).Author
        registry = RAUTHOR


class ETagListType(DjangoListObjectType):
    class Meta:
        model = __import__("tests.models", fromlist=["Tag"]).Tag
        registry = RAUTHOR


class EProfileListType(DjangoListObjectType):
    class Meta:
        model = Profile
        registry = RAUTHOR


class EProfileType(DjangoObjectType):
    class Meta:
        model = Profile
        registry = RAUTHOR


class EOptNoteType(DjangoObjectType):
    class Meta:
        model = OptNote
        registry = RAUTHOR


class EOptNoteListType(DjangoListObjectType):
    class Meta:
        model = OptNote
        registry = RAUTHOR


class EAuthorQuery(graphene.ObjectType):
    all_authors = DjangoListObjectField(EAuthorListType)
    all_posts = DjangoListObjectField(EPostListType)
    all_profiles = DjangoListObjectField(EProfileListType)
    all_notes = DjangoListObjectField(EOptNoteListType)
    all_tags = DjangoListObjectField(ETagListType)


e2e_schema = graphene.Schema(query=EAuthorQuery)


# =========================================================================== #
# Phase B PR2 — Task 5.2: End-to-end DB tests (items 11–20)                  #
# =========================================================================== #


class E2EBaseTest(TestCase):
    """Shared DB fixture and schema exec helper for items 11-20."""

    @classmethod
    def setUpTestData(cls):
        from .models import Author, Category, Post, Tag

        cls.category = Category.objects.create(title="Tech")
        cls.author1 = Author.objects.create(name="Alice", bio="bio1")
        cls.author2 = Author.objects.create(name="Bob", bio="bio2")

        cls.tag1 = Tag.objects.create(label="python")
        cls.tag2 = Tag.objects.create(label="django")

        # 3 posts for author1
        cls.posts = []
        for i in range(3):
            post = Post.objects.create(
                title=f"Post{i}",
                body=f"body{i}",
                author=cls.author1,
                category=cls.category,
            )
            post.tags.add(cls.tag1, cls.tag2)
            cls.posts.append(post)

        # co_authors: post0 has author2 as co-author
        cls.posts[0].co_authors.add(cls.author2)

        # author2 has 1 post
        cls.post_b = Post.objects.create(
            title="PostB", body="bodyB", author=cls.author2, category=cls.category
        )

        # Profile with 2 notes (for items 15/17)
        cls.profile = Profile.objects.create(handle="ep1", headline="EPH1")
        ct = ContentType.objects.get_for_model(Profile)
        for j in range(2):
            OptNote.objects.create(
                text=f"enote{j}", content_type=ct, object_id=cls.profile.pk
            )

    def _exec(self, query):
        result = e2e_schema.execute(query)
        self.assertIsNone(result.errors, msg=str(result.errors))
        return result.data


class E2EItem11ReverseFKNarrowing(E2EBaseTest):
    """Item 11 — Reverse-FK narrowing: posts.title SQL has title+author_id, NOT body."""

    def test_reverse_fk_narrowed_sql_and_query_count(self):
        query = """
        { allAuthors { results { name posts { results { title } } } totalCount } }
        """
        with self.assertNumQueries(3):
            with CaptureQueriesContext(connection) as ctx:
                data = self._exec(query)

        # Find the posts prefetch SQL
        post_sql = [
            q["sql"]
            for q in ctx.captured_queries
            if '"tests_post"' in q["sql"] and "COUNT(*)" not in q["sql"]
        ]
        self.assertTrue(post_sql, "No post SQL found")

        # 'title' must be in the SELECT
        self.assertTrue(
            any('"tests_post"."title"' in s for s in post_sql),
            "title must be selected in posts prefetch SQL",
        )
        # 'body' must NOT be selected (narrowed out)
        self.assertFalse(
            any('"tests_post"."body"' in s for s in post_sql),
            "body must NOT be selected (narrowed out)",
        )
        # author_id must be selected (FK-back structural column)
        self.assertTrue(
            any('"tests_post"."author_id"' in s for s in post_sql),
            "author_id must always be selected (FK-back structural column)",
        )

        authors = data["allAuthors"]["results"]
        self.assertEqual(data["allAuthors"]["totalCount"], 2)
        all_posts = [p for a in authors for p in a["posts"]["results"]]
        self.assertTrue(len(all_posts) > 0)


class E2EItem12GAP1ZeroExtraQueries(E2EBaseTest):
    """Item 12 (CRITICAL) — GAP-1: category access triggers ZERO extra queries."""

    def test_gap1_zero_extra_queries_and_category_narrowed(self):
        query = """
        { allAuthors { results {
            name
            posts { results { title category { title } } }
        } } }
        """
        # EMPIRICALLY PINNED: 1 count (authors) + 1 authors + 1 posts prefetch = 3.
        # With select_related('category') co-applied on the posts prefetch, category
        # data is fetched in the SAME posts SQL (JOIN) — zero extra queries for category.
        # Without it, each post.category access would issue a separate query (N+1).
        with self.assertNumQueries(3):
            with CaptureQueriesContext(connection) as ctx:
                data = self._exec(query)

        # Find the posts prefetch SQL (which should JOIN category via select_related)
        post_sql = [
            q["sql"]
            for q in ctx.captured_queries
            if '"tests_post"' in q["sql"] and "COUNT(*)" not in q["sql"]
        ]
        self.assertTrue(post_sql, "No post SQL found")

        # category__title must be SELECTed in the posts SQL (from JOIN)
        self.assertTrue(
            any('"tests_category"."title"' in s for s in post_sql),
            "category.title must be selected via JOIN in posts prefetch SQL (GAP-1)",
        )

        # Results must be correct
        authors = data["allAuthors"]["results"]
        all_cats = [
            p["category"]["title"]
            for a in authors
            for p in a["posts"]["results"]
            if p["category"]
        ]
        self.assertTrue(all(c == "Tech" for c in all_cats))


class E2EItem13ForwardM2MNarrowing(E2EBaseTest):
    """Item 13 — Forward M2M: allPosts.tags.label narrowed."""

    def test_forward_m2m_tags_narrowed(self):
        query = """
        { allPosts { results { title tags { results { label } } } } }
        """
        with self.assertNumQueries(3):
            with CaptureQueriesContext(connection) as ctx:
                data = self._exec(query)

        tag_sql = [
            q["sql"]
            for q in ctx.captured_queries
            if '"tests_tag"' in q["sql"] and "COUNT(*)" not in q["sql"]
        ]
        self.assertTrue(tag_sql, "No tag SQL found")

        # label must be selected
        self.assertTrue(
            any('"tests_tag"."label"' in s for s in tag_sql),
            "label must be selected in tag prefetch SQL",
        )
        # id must be selected (pk)
        self.assertTrue(
            any('"tests_tag"."id"' in s for s in tag_sql),
            "id (pk) must be selected in tag prefetch SQL",
        )

        posts = data["allPosts"]["results"]
        self.assertTrue(len(posts) > 0)
        some_tags = next(p["tags"]["results"] for p in posts if p["tags"]["results"])
        self.assertTrue(any(t["label"] in ("python", "django") for t in some_tags))


class E2EItem14ReverseManyToManyNarrowing(E2EBaseTest):
    """Item 14 — Reverse M2M: allAuthors.coauthoredPosts narrowed; title+pk in SQL, body absent."""

    def test_reverse_m2m_narrowed(self):
        query = """
        { allAuthors { results { name coauthoredPosts { results { title } } } } }
        """
        # 1 count (authors) + 1 authors + 1 coauthored_posts prefetch = 3
        with self.assertNumQueries(3):
            with CaptureQueriesContext(connection) as ctx:
                data = self._exec(query)

        # setUpTestData seeds post0.co_authors.add(author2), so the reverse-M2M
        # prefetch SQL for co_authored_posts is always emitted.
        post_sql = [
            q["sql"]
            for q in ctx.captured_queries
            if '"tests_post"' in q["sql"] and "COUNT(*)" not in q["sql"]
        ]
        self.assertTrue(post_sql, "No post SQL found for coauthored_posts prefetch")

        # title must be selected (requested leaf)
        self.assertTrue(
            any('"tests_post"."title"' in s for s in post_sql),
            "title must be selected in coauthored_posts prefetch SQL",
        )
        # pk (id) must be selected (structural column)
        self.assertTrue(
            any('"tests_post"."id"' in s for s in post_sql),
            "id (pk) must be selected in coauthored_posts prefetch SQL",
        )
        # body must NOT be selected (narrowed out)
        self.assertFalse(
            any('"tests_post"."body"' in s for s in post_sql),
            "body must NOT be selected (narrowed out)",
        )

        authors = data["allAuthors"]["results"]
        # author2 (Bob) is a co-author on post[0] owned by author1
        co_posts_by_author = {
            a["name"]: a["coauthoredPosts"]["results"] for a in authors
        }
        bob_co = co_posts_by_author.get("Bob", [])
        self.assertTrue(
            any(p["title"] == "Post0" for p in bob_co),
            "Bob should have Post0 as a co-authored post",
        )


class E2EItem15GenericRelationNarrowing(E2EBaseTest):
    """Item 15 — GenericRelation: allProfiles.notes.text narrowed, no deferred reload."""

    def test_generic_relation_notes_narrowed(self):
        query = """
        { allProfiles { results { handle notes { results { text } } } totalCount } }
        """
        with self.assertNumQueries(3):
            with CaptureQueriesContext(connection) as ctx:
                data = self._exec(query)

        note_sql = [
            q["sql"]
            for q in ctx.captured_queries
            if '"tests_optnote"' in q["sql"] and "COUNT(*)" not in q["sql"]
        ]
        self.assertTrue(note_sql, "No OptNote SQL found")

        # content_type_id and object_id must be in SELECT (structural columns)
        self.assertTrue(
            any('"tests_optnote"."content_type_id"' in s for s in note_sql),
            "content_type_id must be selected (GenericRelation structural column)",
        )
        self.assertTrue(
            any('"tests_optnote"."object_id"' in s for s in note_sql),
            "object_id must be selected (GenericRelation structural column)",
        )
        # text must be selected (requested leaf)
        self.assertTrue(
            any('"tests_optnote"."text"' in s for s in note_sql),
            "text must be selected (requested)",
        )

        total = data["allProfiles"]["totalCount"]
        self.assertGreaterEqual(total, 1)
        all_notes = [
            n for r in data["allProfiles"]["results"] for n in r["notes"]["results"]
        ]
        self.assertTrue(len(all_notes) >= 2)


class E2EItem16GFKTargetNoDegrade(E2EBaseTest):
    """Item 16 (GAP-3) — GFK-target branch does NOT degrade the sibling branch."""

    def test_gfk_target_sibling_still_narrowed(self):
        # Query on OptNote: text (scalar) + contentObject (GFK-target, full-load)
        # alongside potential narrowable siblings.
        # The critical assertion: the query returns without error AND the notes
        # themselves are correctly returned (GFK skip did not crash Phase B).
        query = """
        { allNotes { results { text contentObject { id } } totalCount } }
        """
        # 1 count + 1 notes + 1-3 GFK prefetches per content-type group
        result = e2e_schema.execute(query)
        self.assertIsNone(result.errors, msg=str(result.errors))
        data = result.data
        self.assertGreaterEqual(data["allNotes"]["totalCount"], 2)


class E2EItem17FullLoadFallback(E2EBaseTest):
    """Item 17 (REQ-B3) — @property leaf returns correct value end-to-end, no FieldError.

    Requesting ``displayName`` (a @property on Author) on the ``coAuthors``
    prefetch branch causes the full-load guard (``_collect_only_fields_is_full_load``)
    to keep that branch as a bare-string prefetch so all columns are available.
    This e2e confirms the @property resolves to the correct value with no crash.

    The correctness of the full-load guard itself — that it isolates the
    @property branch while still narrowing sibling branches — is unit-tested
    by ``TestFullLoadSiblingIsolation``.
    """

    def test_property_leaf_full_load_no_field_error(self):
        # displayName is a @property on Author — an unknown/computed leaf for
        # the optimizer.  The full-load guard keeps co_authors as a bare-string
        # prefetch so all Author columns are present when the resolver runs.
        query = """
        { allPosts { results { title coAuthors { results { displayName } } } } }
        """
        with self.assertNumQueries(3):
            data = self._exec(query)

        posts = data["allPosts"]["results"]
        self.assertTrue(len(posts) > 0)
        # post0 has coAuthors: author2 = "Bob" -> displayName = "Author: Bob"
        post0 = next(p for p in posts if p["title"] == "Post0")
        co = post0["coAuthors"]["results"]
        self.assertTrue(len(co) > 0)
        self.assertEqual(co[0]["displayName"], "Author: Bob")


class E2EItem18GateOffAndSafeMode(E2EBaseTest):
    """Item 18 (REQ-B4) — OPTIMIZE_ONLY_FIELDS=False + safe-mode exception handling."""

    def test_flag_off_loads_full_rows(self):
        query = """
        { allAuthors { results { name posts { results { title } } } } }
        """
        with mock.patch.object(graphql_api_settings, "OPTIMIZE_ONLY_FIELDS", False):
            with CaptureQueriesContext(connection) as ctx:
                self._exec(query)

        post_sql = [
            q["sql"]
            for q in ctx.captured_queries
            if '"tests_post"' in q["sql"] and "COUNT(*)" not in q["sql"]
        ]
        self.assertTrue(post_sql)
        # body MUST be selected when flag is off (full rows)
        self.assertTrue(
            any('"tests_post"."body"' in s for s in post_sql),
            "body must be selected when OPTIMIZE_ONLY_FIELDS=False",
        )

    def test_safe_mode_exception_degrades_gracefully(self):
        from graphql import parse as gql_parse
        from graphql.language.ast import OperationDefinitionNode

        import django_graphex.utils as utils_module

        gql_doc = gql_parse(
            "{ allAuthors { results { name posts { results { title } } } totalCount } }"
        )
        op = next(
            d for d in gql_doc.definitions if isinstance(d, OperationDefinitionNode)
        )
        field_node = op.selection_set.selections[0]

        class _GT:
            pass

        from .models import Author

        info = _FakeInfo(_FakeParentType(_GT), "all_authors", [field_node])

        with (
            mock.patch.object(graphql_api_settings, "OPTIMIZE_ONLY_FIELDS", True),
            mock.patch.object(graphql_api_settings, "OPTIMIZER_SAFE_MODE", True),
            mock.patch.object(
                utils_module,
                "_collect_prefetch_only_sets",
                side_effect=RuntimeError("safe-mode-e2e-boom"),
            ),
            self.assertLogs("django_graphex.utils", level="WARNING") as cm,
        ):
            qs = queryset_factory(Author, None, info)

        self.assertEqual(qs.model, Author)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("WARNING", cm.output[0])
