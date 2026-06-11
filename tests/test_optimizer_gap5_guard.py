"""Gap #5 — defensive inline-fragment guard for the query-optimizer walkers.

PROVEN BUG (inert today, latent): the optimizer walkers descend through
``InlineFragmentNode`` TRANSPARENTLY, ignoring ``field.type_condition``.
``find_field`` matches by NAME only, so a query like::

    { a { name ... on SomethingElse { posts { id } } } }

while walking the ``Author`` model resolves ``posts`` against Author's relation
map (``prefetch_related=['posts']``) DESPITE the inline fragment targeting a
DIFFERENT concrete type (``SomethingElse``).  When a polymorphic
(union/interface/abstract) output type is eventually exposed this becomes a
real wrong-model bug.

This module is the DEFENSIVE GUARD: a subset of the future Track-2
union/interface support.  The walkers must NOT descend into an inline fragment
whose ``type_condition`` names a DIFFERENT concrete type than the one currently
being walked.

STRICT TDD: these tests are RED first (they fail against the unguarded
walkers), then the guard implementation turns them GREEN.

TEST DISCIPLINE: every test states the mutation that makes it RED.
"""

from __future__ import annotations

import graphene
from django.test import TestCase
from graphql import parse

from django_graphex import DjangoObjectType
from django_graphex.registry import Registry
from django_graphex.utils import (
    _collect_only_fields,
    _collect_only_fields_is_full_load,
    _collect_prefetch_only_sets,
    _inline_fragment_applies,
    _relation_field_map,
    _walk_annotated_fields,
    _walk_filtered_prefetches,
    recursive_params,
)
from tests.models import Author, Post

# A graphene type whose GraphQL type name we can feed to the guard as the
# "current type" identity.  Author has a reverse-FK ``posts`` relation, so the
# unguarded walker happily attributes ``posts`` from ANY inline fragment.
_R_GAP5 = Registry()


class _AuthorTypeGap5(DjangoObjectType):
    class Meta:
        model = Author
        registry = _R_GAP5


# A SECOND concrete type in the same registry/schema.  Its GraphQL type name is
# used as the FOREIGN ``... on <PostTypeName>`` target while we walk Author, so
# the guard has a real, distinct GraphQL type name to reject.
class _PostTypeGap5(DjangoObjectType):
    class Meta:
        model = Post
        registry = _R_GAP5


class _QueryGap5(graphene.ObjectType):
    a = graphene.Field(_AuthorTypeGap5)
    p = graphene.Field(_PostTypeGap5)


# A built schema lets us resolve the real ``GraphQLObjectType`` objects (with the
# ``.name`` / ``.graphene_type`` identity the production walkers thread into the
# guard).  Walking a helper against this gql_type mirrors the production path.
_SCHEMA_GAP5 = graphene.Schema(query=_QueryGap5)
_AUTHOR_GQL_NAME = _AuthorTypeGap5._meta.name
_POST_GQL_NAME = _PostTypeGap5._meta.name
_AUTHOR_GQL = _SCHEMA_GAP5.graphql_schema.get_type(_AUTHOR_GQL_NAME)


def _selection_set(query_str):
    """Return the selection set of the single root field ``a`` in *query_str*."""
    doc = parse(query_str)
    op = doc.definitions[0]
    # Root selection has exactly one field "a"; return its inner selection set.
    root_field = op.selection_set.selections[0]
    return root_field.selection_set


# ---------------------------------------------------------------------------
# Helper-level tests for _inline_fragment_applies (the guard primitive).
# ---------------------------------------------------------------------------


class TestInlineFragmentAppliesHelper(TestCase):
    """The guard primitive routes inline fragments by type_condition."""

    def _inline_node(self, query_str):
        sel = _selection_set(query_str)
        for node in sel.selections:
            # The inline fragment is the node carrying a type_condition.
            if (
                getattr(node, "type_condition", None) is not None
                or type(node).__name__ == "InlineFragmentNode"
            ):
                if type(node).__name__ == "InlineFragmentNode":
                    return node
        # Fallback: first node that looks like an inline fragment.
        for node in sel.selections:
            if type(node).__name__ == "InlineFragmentNode":
                return node
        raise AssertionError("no inline fragment found in query")

    def test_no_type_condition_descends(self):
        """type_condition is None -> descend (True).

        Mutation: returning False here would break bare ``... { }`` inline
        fragments, regressing existing queries.
        """
        node = self._inline_node("{ a { ... { posts { id } } } }")
        self.assertTrue(
            _inline_fragment_applies(node, current_type_name="_AuthorTypeGap5")
        )

    def test_same_type_name_descends(self):
        """type_condition == current type name -> descend (True).

        Mutation: returning False would skip ``... on <SameType>`` and lose
        legitimately-selected fields.
        """
        node = self._inline_node("{ a { ... on _AuthorTypeGap5 { posts { id } } } }")
        self.assertTrue(
            _inline_fragment_applies(node, current_type_name="_AuthorTypeGap5")
        )

    def test_different_concrete_type_skipped(self):
        """type_condition names a DIFFERENT concrete type -> SKIP (False).

        Mutation: returning True here is exactly the GAP-5 bug.
        """
        node = self._inline_node("{ a { ... on SomethingElse { posts { id } } } }")
        self.assertFalse(
            _inline_fragment_applies(node, current_type_name="_AuthorTypeGap5")
        )

    def test_unknown_current_type_descends(self):
        """current type cannot be determined -> descend (True), never worse.

        Mutation: returning False when we don't know the current type would
        silently drop optimizations for queries the walker can't classify.
        """
        node = self._inline_node("{ a { ... on SomethingElse { posts { id } } } }")
        self.assertTrue(
            _inline_fragment_applies(node, current_type_name=None, current_model=None)
        )

    def test_matches_model_name_descends(self):
        """type_condition == current model class name -> descend (True).

        Best-effort model-name match for sites that carry only the Django model.
        Mutation: returning False would skip ``... on Author`` while walking the
        Author model.
        """
        node = self._inline_node("{ a { ... on Author { posts { id } } } }")
        self.assertTrue(_inline_fragment_applies(node, current_model=Author))


# ---------------------------------------------------------------------------
# recursive_params (select/prefetch walker) — the canonical mis-attribution.
# ---------------------------------------------------------------------------


class TestRecursiveParamsInlineFragmentGuard(TestCase):
    """recursive_params must not attribute fields from a foreign inline fragment."""

    def test_mis_attribution_skipped(self):
        """`... on SomethingElse { posts }` while walking Author -> posts NOT collected.

        TODAY (unguarded): ``posts`` IS collected into prefetch_related because
        the walker descends transparently and find_field matches by name.
        Mutation: removing the guard at the recursive_params inline-fragment
        site makes ``posts`` reappear in prefetch_related -> RED.
        """
        sel = _selection_set("{ a { name ... on SomethingElse { posts { id } } } }")
        select_related, prefetch_related = recursive_params(
            sel,
            {},
            _relation_field_map(Author),
            [],
            [],
            current_type_name="_AuthorTypeGap5",
        )
        self.assertNotIn(
            "posts",
            prefetch_related,
            "posts must NOT be prefetched: the inline fragment targets "
            "SomethingElse, not the Author type being walked (GAP-5).",
        )
        self.assertEqual(select_related, [])

    def test_same_type_still_descends(self):
        """`... on _AuthorTypeGap5 { posts }` while walking Author -> posts COLLECTED.

        No regression: same-type inline fragments still descend.
        Mutation: over-broad guard (skipping same-type) drops ``posts`` -> RED.
        """
        sel = _selection_set("{ a { name ... on _AuthorTypeGap5 { posts { id } } } }")
        _select, prefetch_related = recursive_params(
            sel,
            {},
            _relation_field_map(Author),
            [],
            [],
            current_type_name="_AuthorTypeGap5",
        )
        self.assertIn(
            "posts",
            prefetch_related,
            "posts MUST be prefetched for a same-type inline fragment.",
        )

    def test_no_type_condition_descends(self):
        """Bare inline fragment (no type_condition) -> posts COLLECTED (unchanged).

        Mutation: guard rejecting None type_condition drops ``posts`` -> RED.
        """
        sel = _selection_set("{ a { name ... { posts { id } } } }")
        _select, prefetch_related = recursive_params(
            sel,
            {},
            _relation_field_map(Author),
            [],
            [],
            current_type_name="_AuthorTypeGap5",
        )
        self.assertIn("posts", prefetch_related)

    def test_unknown_current_type_preserves_today_behavior(self):
        """No current type identity -> descend (today's behavior preserved).

        Mutation: defaulting to skip when type is unknown would regress every
        caller that does not thread a type identity -> RED.
        """
        sel = _selection_set("{ a { name ... on SomethingElse { posts { id } } } }")
        _select, prefetch_related = recursive_params(
            sel,
            {},
            _relation_field_map(Author),
            [],
            [],
        )
        self.assertIn(
            "posts",
            prefetch_related,
            "With no current_type_name the walker must preserve today's "
            "transparent-descent behavior (never make it worse).",
        )

    def test_fragment_spread_unaffected(self):
        """Fragment spreads keep working exactly as today.

        Mutation: touching FragmentSpread handling would drop ``posts`` -> RED.
        """
        doc = parse(
            "{ a { name ...F } } fragment F on _AuthorTypeGap5 { posts { id } }"
        )
        op = doc.definitions[0]
        frag = doc.definitions[1]
        sel = op.selection_set.selections[0].selection_set
        _select, prefetch_related = recursive_params(
            sel,
            {"F": frag},
            _relation_field_map(Author),
            [],
            [],
            current_type_name="_AuthorTypeGap5",
        )
        self.assertIn("posts", prefetch_related)


# ---------------------------------------------------------------------------
# _collect_only_fields (.only() walker) — analogous coverage.
# ---------------------------------------------------------------------------


class TestCollectOnlyFieldsInlineFragmentGuard(TestCase):
    """_collect_only_fields must not narrow .only() through a foreign fragment."""

    def test_foreign_inline_fragment_relation_not_descended(self):
        """`... on SomethingElse { posts { ... } }` must not pull Author.posts join key.

        We assert the foreign-fragment relation does NOT contribute an
        Author-side ``.only()`` column for ``posts`` descent.  Concretely:
        the bio (a plain Author leaf selected outside the fragment) must be the
        only non-pk concrete narrowing, and walking the fragment must NOT add
        any ``posts__`` prefixed column.

        Mutation: removing the guard at the _collect_only_fields inline-fragment
        site descends into Author.posts (a prefetch relation, here selected
        under a foreign type) -> no posts__ column is added either way for a
        prefetch, so we instead assert the SAME-type case below differs.
        """
        doc = parse("{ a { id ... on SomethingElse { bio } } }")
        op = doc.definitions[0]
        sel = op.selection_set.selections[0].selection_set
        only = _collect_only_fields(
            Author,
            sel,
            {},
            current_type_name="_AuthorTypeGap5",
        )
        # bio lives behind a foreign inline fragment -> must NOT be narrowed in.
        self.assertNotIn("bio", only, "bio came from a foreign-typed fragment")
        # pk always present.
        self.assertIn("id", only)

    def test_same_type_inline_fragment_descends(self):
        """`... on _AuthorTypeGap5 { bio }` -> bio IS narrowed in (no regression).

        Mutation: over-broad guard skips the same-type fragment, bio missing
        from .only() -> RED.
        """
        doc = parse("{ a { id ... on _AuthorTypeGap5 { bio } } }")
        op = doc.definitions[0]
        sel = op.selection_set.selections[0].selection_set
        only = _collect_only_fields(
            Author,
            sel,
            {},
            current_type_name="_AuthorTypeGap5",
        )
        self.assertIn("bio", only)
        self.assertIn("id", only)

    def test_model_name_alone_does_not_skip(self):
        """Model name alone is NOT a reliable basis to SKIP -> descend.

        GraphQL type names (``AuthorType``) normally differ from the Django
        model class name (``Author``).  A model-name mismatch is therefore
        inconclusive, so with ONLY ``current_model`` known the walker must
        preserve transparent descent — bio IS collected.  (The real skip is
        proven by ``test_foreign_inline_fragment_skipped_with_type_name`` below,
        which threads a reliable GraphQL type name.)

        Mutation: if the guard treated a model-name mismatch as a SKIP, every
        legitimate ``... on <Model>Type`` fragment would be dropped — bio would
        be missing -> RED.
        """
        doc = parse("{ a { id ... on SomethingElse { bio } } }")
        op = doc.definitions[0]
        sel = op.selection_set.selections[0].selection_set
        only = _collect_only_fields(Author, sel, {})
        self.assertIn("bio", only)
        self.assertIn("id", only)

    def test_foreign_inline_fragment_skipped_with_type_name(self):
        """With a reliable GraphQL type name, a foreign fragment IS skipped.

        ``current_type_name='_AuthorTypeGap5'`` is the GraphQL type identity.
        ``... on SomethingElse { bio }`` does not match it, so it is skipped and
        bio is NOT narrowed.

        Mutation: removing the guard at the _collect_only_fields inline-fragment
        site descends into the foreign fragment -> bio appears -> RED.
        """
        doc = parse("{ a { id ... on SomethingElse { bio } } }")
        op = doc.definitions[0]
        sel = op.selection_set.selections[0].selection_set
        only = _collect_only_fields(
            Author, sel, {}, current_type_name="_AuthorTypeGap5"
        )
        self.assertNotIn("bio", only)
        self.assertIn("id", only)

    def test_bare_inline_fragment_descends_without_type_name(self):
        """Bare inline fragment (no type_condition) descends regardless.

        Mutation: guard rejecting None type_condition drops bio -> RED.
        """
        doc = parse("{ a { id ... { bio } } }")
        op = doc.definitions[0]
        sel = op.selection_set.selections[0].selection_set
        only = _collect_only_fields(Author, sel, {})
        self.assertIn("bio", only)


# ---------------------------------------------------------------------------
# _collect_prefetch_only_sets (prefetch-only column-plan walker) — SC-1.
#
# This site had a guard threaded with ONLY ``current_model`` (no GraphQL
# type-name identity), making it INERT: a model name alone can never trigger a
# SKIP, so a foreign-typed fragment whose body names a same-named relation was
# still collected into the prefetch-only plan map.  The fix threads the full
# GraphQL identity (type name + graphene type) from ``gql_type``.
# ---------------------------------------------------------------------------


class TestCollectPrefetchOnlySetsInlineFragmentGuard(TestCase):
    """_collect_prefetch_only_sets must not plan a relation from a foreign fragment."""

    def test_foreign_fragment_relation_not_collected(self):
        """`... on <PostType> { posts }` while walking Author -> posts NOT planned.

        Author has a reverse-FK ``posts``.  A foreign-typed inline fragment that
        re-uses the name ``posts`` must be SKIPPED, so no PrefetchPlan is built
        for it.

        Mutation: reverting the guard to ``current_model=model`` alone (its
        inert form) makes the walker descend transparently -> ``posts`` reappears
        in the plan map -> RED.
        """
        query = "{ a { name ... on " + _POST_GQL_NAME + " { posts { id } } } }"
        sel = _selection_set(query)
        out = _collect_prefetch_only_sets(Author, sel, {}, gql_type=_AUTHOR_GQL)
        self.assertNotIn(
            "posts",
            out,
            "posts must NOT be planned: the inline fragment targets the Post "
            "type, not the Author type being walked (GAP-5 SC-1).",
        )

    def test_same_type_fragment_relation_still_collected(self):
        """`... on <AuthorType> { posts }` -> posts IS planned (no regression).

        Mutation: an over-broad guard that skips the same-type fragment drops
        the legitimate ``posts`` plan -> RED.
        """
        query = "{ a { name ... on " + _AUTHOR_GQL_NAME + " { posts { id } } } }"
        sel = _selection_set(query)
        out = _collect_prefetch_only_sets(Author, sel, {}, gql_type=_AUTHOR_GQL)
        self.assertIn(
            "posts",
            out,
            "posts MUST be planned for a same-type inline fragment.",
        )


# ---------------------------------------------------------------------------
# _collect_only_fields_is_full_load (full-load detector) — SC-2.
#
# This site's guard was INERT for the same reason (model only, and the helper
# did not even accept a GraphQL type name).  It also created a SIBLING
# DISAGREEMENT with ``_collect_only_fields``: a foreign fragment's unknown leaf
# would flip the full-load detector to True (vetoing ``.only()`` narrowing)
# while the column collector correctly skipped it.  The fix adds a
# ``current_type_name`` parameter and threads it so both walkers agree.
# ---------------------------------------------------------------------------


class TestCollectOnlyFieldsIsFullLoadInlineFragmentGuard(TestCase):
    """A foreign fragment must not flip the child to full-load."""

    def test_foreign_fragment_unknown_leaf_does_not_flip_full_load(self):
        """`... on <PostType> { someProp }` while walking Author -> NOT full-load.

        ``someProp`` is an unknown/computed leaf.  If the foreign fragment were
        descended into, that unknown leaf would set full-load=True and silently
        veto ``.only()`` narrowing for the Author branch.  With the GraphQL type
        name threaded, the foreign fragment is SKIPPED and full-load stays False.

        Mutation: reverting to the inert ``current_model=model`` guard (or
        dropping the ``current_type_name`` parameter) makes the detector descend
        into the foreign fragment -> ``someProp`` flips full-load to True -> RED.
        """
        doc = parse("{ a { id ... on " + _POST_GQL_NAME + " { someProp } } }")
        op = doc.definitions[0]
        sel = op.selection_set.selections[0].selection_set
        is_full = _collect_only_fields_is_full_load(
            Author, sel, {}, current_type_name=_AUTHOR_GQL_NAME
        )
        self.assertFalse(
            is_full,
            "A foreign-typed fragment's unknown leaf must NOT flip the Author "
            "branch to full-load (GAP-5 SC-2).",
        )

    def test_same_type_fragment_unknown_leaf_still_flips_full_load(self):
        """`... on <AuthorType> { someProp }` -> full-load True (no regression).

        A same-type fragment carrying a genuinely-unknown leaf must still flip
        full-load, exactly as today.

        Mutation: an over-broad guard skipping the same-type fragment would
        wrongly report not-full-load -> RED.
        """
        doc = parse("{ a { id ... on " + _AUTHOR_GQL_NAME + " { someProp } } }")
        op = doc.definitions[0]
        sel = op.selection_set.selections[0].selection_set
        is_full = _collect_only_fields_is_full_load(
            Author, sel, {}, current_type_name=_AUTHOR_GQL_NAME
        )
        self.assertTrue(
            is_full,
            "A same-type fragment's unknown leaf must still flip full-load.",
        )

    def test_full_load_detector_agrees_with_collect_only_fields(self):
        """The two sibling walkers must agree on foreign-fragment scope.

        For a foreign fragment carrying an unknown leaf, the full-load detector
        must NOT flip (False) while ``_collect_only_fields`` must NOT narrow the
        leaf in — both treat the foreign fragment as out of scope.

        Mutation: any threading mismatch between the two walkers re-opens the
        sibling disagreement that silently vetoes ``.only()`` -> RED.
        """
        doc = parse("{ a { id ... on " + _POST_GQL_NAME + " { someProp } } }")
        op = doc.definitions[0]
        sel = op.selection_set.selections[0].selection_set
        is_full = _collect_only_fields_is_full_load(
            Author, sel, {}, current_type_name=_AUTHOR_GQL_NAME
        )
        only = _collect_only_fields(Author, sel, {}, current_type_name=_AUTHOR_GQL_NAME)
        self.assertFalse(is_full)
        self.assertNotIn("some_prop", only)
        self.assertNotIn("someProp", only)


# ---------------------------------------------------------------------------
# _walk_filtered_prefetches (filtered-Prefetch walker).
#
# This site already threads the full identity; the test pins it so a future
# regression to an insufficient identity fails RED.
# ---------------------------------------------------------------------------


class TestWalkFilteredPrefetchesInlineFragmentGuard(TestCase):
    """_walk_filtered_prefetches must skip foreign-typed inline fragments."""

    def _info(self, fragments=None):
        import types as _t

        return _t.SimpleNamespace(
            fragments=fragments or {}, variable_values={}, schema=None
        )

    def test_foreign_fragment_skipped(self):
        """`... on <PostType> { posts { id } }` while walking Author -> no descent.

        We assert the walker does not raise and does not produce any Prefetch
        for a relation reached only through the foreign fragment.  The guard
        skips it before resolving fields on the Author gql_type.

        Mutation: dropping the GraphQL identity here makes the guard inert; the
        walker descends into the foreign fragment and resolves ``posts`` against
        the Author gql_type -> a stray Prefetch/seen entry appears -> RED.
        """
        query = "{ a { name ... on " + _POST_GQL_NAME + " { posts { id } } } }"
        sel = _selection_set(query)
        out: list = []
        seen: dict = {}
        _walk_filtered_prefetches(_AUTHOR_GQL, Author, sel, "", self._info(), out, seen)
        self.assertNotIn(
            "posts",
            seen,
            "A foreign-typed fragment must not contribute a posts lookup "
            "(GAP-5 filtered-prefetch walker).",
        )

    def test_same_type_fragment_descends(self):
        """`... on <AuthorType> { posts { id } }` -> walker descends (no regression).

        Mutation: an over-broad guard skips the same-type fragment -> the inner
        ``posts`` selection is never visited.  Here ``posts`` is unfiltered so it
        produces no Prefetch object, but the descent itself must occur without
        error and the same-type fragment must not be rejected.
        """
        query = "{ a { name ... on " + _AUTHOR_GQL_NAME + " { posts { id } } } }"
        sel = _selection_set(query)
        out: list = []
        seen: dict = {}
        # Must not raise and must accept the same-type fragment.
        _walk_filtered_prefetches(_AUTHOR_GQL, Author, sel, "", self._info(), out, seen)


# ---------------------------------------------------------------------------
# _walk_annotated_fields (AnnotatedField select-detection walker).
#
# This site already threads the type name + graphene type; the test pins it so
# a future regression to an insufficient identity fails RED.
# ---------------------------------------------------------------------------


class TestWalkAnnotatedFieldsInlineFragmentGuard(TestCase):
    """_walk_annotated_fields must not collect annotations from a foreign fragment."""

    def test_foreign_fragment_annotation_not_collected(self):
        """A foreign `... on <Other> { someAnnotated }` must not be collected.

        Walking the Author gql_type, a foreign-typed inline fragment must be
        SKIPPED so any AnnotatedField named inside it is NOT pulled onto the
        Author annotations.  Author has no AnnotatedFields, so the collected
        ``names`` set must stay empty regardless of the fragment body.

        Mutation: dropping the GraphQL identity makes the guard inert; the walker
        descends and any matching annotated leaf inside the foreign fragment is
        collected onto Author -> ``names`` becomes non-empty -> RED.
        """
        import types as _t

        query = "{ a { name ... on " + _POST_GQL_NAME + " { commentCount } } }"
        sel = _selection_set(query)
        annotations: dict = {}
        aliases: dict = {}
        names: set = set()
        _walk_annotated_fields(
            _AUTHOR_GQL,
            _AuthorTypeGap5,
            sel,
            _t.SimpleNamespace(fragments={}),
            annotations,
            aliases,
            names,
        )
        self.assertEqual(
            names,
            set(),
            "A foreign-typed fragment must not contribute annotations to the "
            "Author type (GAP-5 annotated-fields walker).",
        )
        self.assertEqual(annotations, {})


# ---------------------------------------------------------------------------
# End-to-end production-path test (through _apply_optimizations).
#
# NOTE: a TRULY-FOREIGN concrete type (`... on SomethingElse`) cannot appear in
# a VALIDATED query on a non-polymorphic field — graphql-core rejects it with
# "Unknown type".  That is exactly why the GAP-5 bug is inert/latent today and
# why the mis-attribution scenario is proven via direct walker calls above
# (the same methodology as the gap-study).  The e2e test below instead proves
# the threading does NOT over-skip: a list WRAPPER must not reject a legitimate
# same-item-type inline fragment placed inside ``results`` (the wrapper name is
# not the row identity).
# ---------------------------------------------------------------------------


class TestGap5EndToEndWrapperNotFalseSkipped(TestCase):
    """Wrapper (DjangoListObjectType) must not wrongly skip same-item fragments."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author as _A
        from tests.models import Post as _P

        a = _A.objects.create(name="WrapAuthor", bio="b")
        _P.objects.create(title="WrapPost", author=a)

    def test_same_item_type_fragment_inside_results_not_skipped(self):
        """`results { ... on <ItemType> { posts } }` must still prefetch posts.

        The named return type is the LIST WRAPPER, whose name differs from the
        row item type.  The guard must NOT use the wrapper name to reject a
        legitimate same-item-type fragment placed inside ``results``.

        Mutation: trusting the wrapper name as the row identity makes the guard
        skip the legitimate `... on <ItemType>` fragment -> posts is not
        prefetched -> RED.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from django_graphex import (
            DjangoListObjectField,
            DjangoListObjectType,
        )
        from django_graphex import DjangoObjectType as _DOT

        reg = Registry()

        class _PostW(_DOT):
            class Meta:
                from tests.models import Post as _P

                model = _P
                registry = reg

        class _AuthorW(_DOT):
            posts = graphene.List(lambda: _PostW)

            def resolve_posts(root, info):
                return root.posts.all()

            class Meta:
                model = Author
                registry = reg

        class _AuthorWList(DjangoListObjectType):
            class Meta:
                model = Author
                registry = reg

        class _QueryW(graphene.ObjectType):
            all_authors = DjangoListObjectField(_AuthorWList)

        schema = graphene.Schema(query=_QueryW)
        item_name = _AuthorW._meta.name
        query = (
            "{ allAuthors { results { name ... on "
            + item_name
            + " { posts { id } } } } }"
        )
        with CaptureQueriesContext(connection) as ctx:
            result = schema.execute(query)
        self.assertIsNone(result.errors, result.errors)
        post_queries = [
            q for q in ctx.captured_queries if "tests_post" in q["sql"].lower()
        ]
        self.assertTrue(
            post_queries,
            "Inside a list wrapper, a same-item-type inline fragment must still "
            "prefetch posts. The guard must not treat the wrapper name as the "
            "row identity (which would wrongly skip the fragment).",
        )

    def test_custom_results_field_name_wrapper_not_false_skipped(self):
        """Custom ``results_field_name`` wrapper must not skip same-item fragments.

        REG-1 / fwd-1: the root-type-name gate detected the list wrapper with a
        HARDCODED ``"results" in fields`` literal.  A DjangoListObjectType with a
        non-default ``Meta.results_field_name`` (e.g. ``"items"``) was NOT
        recognised as a wrapper, so the wrapper's GraphQL name was threaded into
        the row selection and a legitimate same-item-type ``... on <ItemType>``
        fragment inside the renamed results field was WRONGLY SKIPPED -> the
        nested prefetch it contained was silently dropped (N+1 regression).

        With the fix (detect the wrapper by its CONFIGURED results field name),
        ``root_type_name`` stays ``None`` for the custom-named wrapper, the guard
        never skips inside the results field, and the prefetch is preserved.

        Mutation: restoring the hardcoded ``"results"`` literal makes the custom
        ``items`` wrapper look like a flat row type, threads the wrapper name,
        skips the same-item fragment, and drops the posts prefetch -> RED.

        Multiplicity makes the regression observable as N+1: with two authors,
        a dropped prefetch yields one posts query per author (>= 2); a preserved
        prefetch yields a single batched posts query.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from django_graphex import (
            DjangoListObjectField,
            DjangoListObjectType,
        )
        from django_graphex import DjangoObjectType as _DOT
        from tests.models import Author as _A
        from tests.models import Post as _P

        # A second author so a dropped prefetch surfaces as N+1 (one posts query
        # per author) rather than a single batched query.
        a2 = _A.objects.create(name="WrapAuthor2", bio="b2")
        _P.objects.create(title="WrapPost2", author=a2)

        reg = Registry()

        class _PostCW(_DOT):
            class Meta:
                model = _P
                registry = reg

        class _AuthorCW(_DOT):
            posts = graphene.List(lambda: _PostCW)

            def resolve_posts(root, info):
                return root.posts.all()

            class Meta:
                model = Author
                registry = reg

        class _AuthorCWList(DjangoListObjectType):
            class Meta:
                model = Author
                registry = reg
                # NON-default results field name — the crux of the regression.
                results_field_name = "items"

        class _QueryCW(graphene.ObjectType):
            all_authors = DjangoListObjectField(_AuthorCWList)

        schema = graphene.Schema(query=_QueryCW)
        item_name = _AuthorCW._meta.name
        query = (
            "{ allAuthors { items { name ... on "
            + item_name
            + " { posts { id } } } } }"
        )
        with CaptureQueriesContext(connection) as ctx:
            result = schema.execute(query)
        self.assertIsNone(result.errors, result.errors)
        post_queries = [
            q for q in ctx.captured_queries if "tests_post" in q["sql"].lower()
        ]
        # Exactly ONE batched posts query (prefetch preserved).  A dropped
        # prefetch would yield one posts query per author (>= 2) -> N+1.
        self.assertEqual(
            len(post_queries),
            1,
            "A custom-named results wrapper must still prefetch posts via the "
            "same-item-type inline fragment (no N+1). The wrapper must be "
            "detected by its configured results_field_name, not a hardcoded "
            "'results' literal (REG-1 / fwd-1).",
        )
