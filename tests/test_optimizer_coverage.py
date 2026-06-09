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
    _collect_only_fields,
    _concrete_field_map,
    _merge_filtered_prefetches,
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
        field = next(
            f for f in OptNote._meta.get_fields() if isinstance(f, GenericForeignKey)
        )
        self.assertIsNone(_relation_optimization(field))

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
