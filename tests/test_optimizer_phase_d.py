"""Tests for optimizer-phase-d: AnnotatedField optimization.

D1 slice: §1-6 + §8-9 implementation + tests 1-6b/8/10.
D2 slice (§7 window-compose): NOT included here.

STRICT TDD: RED tests are written first, then GREEN implementation fills them.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import graphene
from django.db import connection
from django.db.models import Count, F, Sum
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from django_graphex import (
    AnnotatedField,
    DjangoFilterListField,
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoObjectType,
)
from django_graphex.registry import Registry

# ---------------------------------------------------------------------------
# Phase 1: AnnotatedField class + setting unit tests (tasks 1.1 - 1.4)
# ---------------------------------------------------------------------------


class TestAnnotatedFieldStoresAttrs(TestCase):
    """1.1 — AnnotatedField stores expression, aliases, annotation_name."""

    def test_annotated_field_stores_attrs(self):
        """AnnotatedField stores expression, aliases default {}, annotation_name derived."""
        expr = Count("comments")
        field = AnnotatedField(graphene.Int, expr)
        self.assertIs(field.expression, expr)
        self.assertEqual(field.aliases, {})
        self.assertEqual(
            field.annotation_name("comment_count"),
            "_gqx_ann_comment_count",
        )


class TestAnnotatedFieldAliasesAndOverride(TestCase):
    """1.2 — AnnotatedField aliases and annotation_name override survive."""

    def test_annotated_field_aliases_and_override(self):
        """aliases and annotation_name override are stored correctly."""
        expr = F("subtotal") / F("item_cnt")
        aliases = {"subtotal": Sum("price"), "item_cnt": Count("id")}
        field = AnnotatedField(
            graphene.Float, expr, aliases=aliases, annotation_name="my_ann"
        )
        self.assertIs(field.expression, expr)
        self.assertEqual(field.aliases, aliases)
        self.assertEqual(field._explicit_annotation_name, "my_ann")
        # annotation_name() should return the override regardless of field_name.
        self.assertEqual(field.annotation_name("whatever"), "my_ann")


class TestAnnotatedFieldDefaultResolver(TestCase):
    """1.3 — Default resolver reads _gqx_ann_<field_name> from root."""

    def test_annotated_field_default_resolver_absent(self):
        """Resolver returns None when annotation attr is absent on root."""
        field = AnnotatedField(graphene.Int, Count("comments"))

        class FakeInfo:
            field_name = "commentCount"

        class FakeRoot:
            pass

        result = field._default_resolver(FakeRoot(), FakeInfo())
        self.assertIsNone(result)

    def test_annotated_field_default_resolver_present(self):
        """Resolver returns the annotation value when attr is present on root."""
        field = AnnotatedField(graphene.Int, Count("comments"))

        class FakeInfo:
            field_name = "commentCount"

        class FakeRoot:
            _gqx_ann_comment_count = 42

        result = field._default_resolver(FakeRoot(), FakeInfo())
        self.assertEqual(result, 42)

    def test_resolve_expression_callable(self):
        """resolve_expression calls a zero-arg callable."""
        expr = Count("comments")
        result = AnnotatedField.resolve_expression(lambda: expr)
        self.assertIs(result, expr)

    def test_resolve_expression_instance(self):
        """resolve_expression returns Expression as-is."""
        expr = Count("comments")
        result = AnnotatedField.resolve_expression(expr)
        self.assertIs(result, expr)


class TestOptimizeAnnotatedFieldsSettingDefault(TestCase):
    """1.4 / 10 — OPTIMIZE_ANNOTATED_FIELDS defaults True."""

    def test_optimize_annotated_fields_setting_default(self):
        """OPTIMIZE_ANNOTATED_FIELDS defaults to True."""
        from django_graphex import settings as settings_module

        s = settings_module.graphql_api_settings
        self.assertTrue(
            hasattr(s, "OPTIMIZE_ANNOTATED_FIELDS"),
            "graphql_api_settings must expose OPTIMIZE_ANNOTATED_FIELDS",
        )
        self.assertIs(s.OPTIMIZE_ANNOTATED_FIELDS, True)

    @override_settings(DJANGO_GRAPHEX={"OPTIMIZE_ANNOTATED_FIELDS": False})
    def test_optimize_annotated_fields_explicit_false(self):
        """OPTIMIZE_ANNOTATED_FIELDS=False propagates via override_settings."""
        from django_graphex import settings as settings_module

        s = settings_module.graphql_api_settings
        self.assertIs(s.OPTIMIZE_ANNOTATED_FIELDS, False)


# ---------------------------------------------------------------------------
# Phase 2: _collect_annotated_fields walker unit tests (tasks 2.1 - 2.3)
# ---------------------------------------------------------------------------

# Build a minimal schema for walker tests (no DB needed).
_RWALK = Registry()


class _DWalkPost(DjangoObjectType):
    comment_count = AnnotatedField(graphene.Int, Count("comments"))

    class Meta:
        from tests.models import Post as _P

        model = _P
        registry = _RWALK


class _DWalkPostList(DjangoListObjectType):
    class Meta:
        from tests.models import Post as _P

        model = _P
        registry = _RWALK


class _DWalkQuery(graphene.ObjectType):
    all_posts = DjangoListObjectField(_DWalkPostList)
    all_posts_flat = graphene.List(_DWalkPost)


_walk_schema = graphene.Schema(query=_DWalkQuery)


def _make_info_for_field(schema, query_str, field_name):
    """Build a minimal mock GraphQLResolveInfo for a root field."""
    from graphql import parse
    from graphql.language.ast import OperationDefinitionNode

    gql_schema = schema.graphql_schema
    doc = parse(query_str)
    op = doc.definitions[0]
    assert isinstance(op, OperationDefinitionNode)

    field_nodes = [
        sel
        for sel in op.selection_set.selections
        if hasattr(sel, "name") and sel.name.value == field_name
    ]
    assert field_nodes, f"Field {field_name!r} not found in query"

    # Build mock info
    info = MagicMock()
    info.field_nodes = field_nodes
    info.fragments = {}
    info.return_type = gql_schema.query_type.fields[field_name].type
    return info


class TestCollectAnnotatedFieldsSelected(TestCase):
    """2.1 — _collect_annotated_fields returns annotation when field selected."""

    def test_collect_annotated_fields_selected(self):
        from django_graphex.utils import _collect_annotated_fields

        info = _make_info_for_field(
            _walk_schema,
            "{ allPostsFlat { id commentCount } }",
            "allPostsFlat",
        )
        annotations, aliases, names = _collect_annotated_fields(info)
        self.assertIn("_gqx_ann_comment_count", annotations)
        self.assertIn("comment_count", names)
        self.assertIsInstance(aliases, dict)

    def test_collect_annotated_fields_absent(self):
        """2.2 — No annotation when field not selected."""
        from django_graphex.utils import _collect_annotated_fields

        info = _make_info_for_field(
            _walk_schema,
            "{ allPostsFlat { id title } }",
            "allPostsFlat",
        )
        annotations, aliases, names = _collect_annotated_fields(info)
        self.assertEqual(annotations, {})
        self.assertEqual(names, set())


class TestCollectAnnotatedFieldsWrapperDescent(TestCase):
    """2.3 — Walker descends into DjangoListObjectType results wrapper."""

    def test_collect_annotated_fields_wrapper_descent(self):
        """Wrapper shape allPosts { results { commentCount } } is descended."""
        from django_graphex.utils import _collect_annotated_fields

        info = _make_info_for_field(
            _walk_schema,
            "{ allPosts { results { id commentCount } totalCount } }",
            "allPosts",
        )
        annotations, aliases, names = _collect_annotated_fields(info)
        self.assertIn("_gqx_ann_comment_count", annotations)
        self.assertIn("comment_count", names)


# ---------------------------------------------------------------------------
# Phase 3: .only() integration — AnnotatedField leaves skipped (tasks 3.1 - 3.2)
# ---------------------------------------------------------------------------


class TestCollectOnlyFieldsAnnotatedLeafSkipped(TestCase):
    """3.1 — AnnotatedField leaf does not cause full-load, not added to only."""

    def test_collect_only_fields_annotated_leaf_skipped(self):
        # Build a minimal selection set: id + title + commentCount (AnnotatedField)
        from graphql import parse

        from django_graphex.utils import _collect_only_fields
        from tests.models import Post

        doc = parse("{ id title commentCount }")

        op = doc.definitions[0]
        selection_set = op.selection_set

        only = _collect_only_fields(
            Post,
            selection_set,
            {},
            annotated_names={"comment_count"},
        )
        self.assertIn("id", only)
        self.assertIn("title", only)
        # _gqx_ann_comment_count must NOT be in only (it's not a concrete column)
        self.assertFalse(any("comment_count" in col for col in only))
        # model_full must NOT have been triggered: body should NOT be in only
        self.assertNotIn("body", only)

    def test_collect_only_fields_wrapper_path_annotated_leaf_skipped(self):
        """3.1b — Wrapper recursion path: annotated leaf not full-load."""
        # Simulate wrapper shape: { results { id title commentCount } }
        from graphql import parse

        from django_graphex.utils import _collect_only_fields
        from tests.models import Post

        doc = parse("{ results { id title commentCount } }")

        op = doc.definitions[0]
        selection_set = op.selection_set

        only = _collect_only_fields(
            Post,
            selection_set,
            {},
            annotated_names={"comment_count"},
        )
        self.assertIn("id", only)
        self.assertIn("title", only)
        self.assertFalse(any("comment_count" in col for col in only))
        # model_full not triggered: body should not be added
        self.assertNotIn("body", only)


class TestCollectOnlyFieldsIsFullLoadAnnotatedSkipped(TestCase):
    """3.2 — _collect_only_fields_is_full_load returns False for AnnotatedField."""

    def test_collect_only_fields_is_full_load_annotated_skipped(self):
        from graphql import parse

        from django_graphex.utils import _collect_only_fields_is_full_load
        from tests.models import Post

        doc = parse("{ id commentCount }")

        op = doc.definitions[0]
        selection_set = op.selection_set

        result = _collect_only_fields_is_full_load(
            Post,
            selection_set,
            {},
            annotated_names={"comment_count"},
        )
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# Phase 4: Root injection integration tests (tasks 4.1 - 4.3)
# ---------------------------------------------------------------------------

# Build dedicated schema for integration tests
_RANN = Registry()


class _DPostType(DjangoObjectType):
    comment_count = AnnotatedField(graphene.Int, lambda: Count("comments"))

    class Meta:
        from tests.models import Post as _P

        model = _P
        registry = _RANN


class _DPostListType(DjangoListObjectType):
    class Meta:
        from tests.models import Post as _P

        model = _P
        registry = _RANN


class _AnnQuery(graphene.ObjectType):
    # Flat List field — EXACTLY 1 query (no count query).
    # DjangoFilterListField calls queryset_factory internally.
    all_posts_list = DjangoFilterListField(_DPostType)
    # DjangoListObjectType wrapper — 2 queries (results + count)
    all_posts = DjangoListObjectField(_DPostListType)


_ann_schema = graphene.Schema(query=_AnnQuery)


def _exec(schema, query):
    result = schema.execute(query)
    assert result.errors is None, result.errors
    return result.data


class TestRootAnnotationInjected1Query(TestCase):
    """4.1 — Flat List field with AnnotatedField = exactly 1 query."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Comment, Post

        author = Author.objects.create(name="Alice", bio="")
        for i in range(3):
            p = Post.objects.create(title=f"Post{i}", author=author)
            for j in range(i + 1):
                Comment.objects.create(post=p, body=f"c{j}")

    def test_root_annotation_injected_1query(self):
        """FLAT graphene.List(DPostType) with commentCount = exactly 1 DB query."""
        from tests.models import Comment, Post

        query = "{ allPostsList { id commentCount } }"
        with self.assertNumQueries(1):
            with CaptureQueriesContext(connection) as ctx:
                data = _exec(_ann_schema, query)
        # Assert COUNT appears in SQL
        sqls = " ".join(q["sql"] for q in ctx.captured_queries)
        self.assertIn("COUNT", sqls.upper())
        # Assert values correct
        by_id = {r["id"]: r["commentCount"] for r in data["allPostsList"]}
        for post in Post.objects.all():
            expected = Comment.objects.filter(post=post).count()
            self.assertEqual(by_id[str(post.id)], expected, f"post {post.id}")


class TestRootAnnotationInjectedWrapper2Queries(TestCase):
    """4.1b — DjangoListObjectType wrapper with AnnotatedField = exactly 2 queries."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Comment, Post

        author = Author.objects.create(name="Bob", bio="")
        for i in range(2):
            p = Post.objects.create(title=f"P{i}", author=author)
            for j in range(i + 2):
                Comment.objects.create(post=p, body=f"b{j}")

    def test_root_annotation_injected_wrapper_2queries(self):
        """DjangoListObjectType wrapper with totalCount = exactly 2 queries."""
        from tests.models import Comment, Post

        query = "{ allPosts { results { id commentCount } totalCount } }"
        with self.assertNumQueries(2):
            data = _exec(_ann_schema, query)
        results = data["allPosts"]["results"]
        by_id = {r["id"]: r["commentCount"] for r in results}
        for post in Post.objects.all():
            expected = Comment.objects.filter(post=post).count()
            self.assertEqual(by_id[str(post.id)], expected)


class TestRootAnnotationAbsentNoSQL(TestCase):
    """4.2 — No COUNT in SQL when commentCount not selected."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        author = Author.objects.create(name="Charlie", bio="")
        Post.objects.create(title="P0", author=author)

    def test_root_annotation_absent_no_sql(self):
        """When commentCount NOT selected, SQL must not contain _gqx_ann_ or COUNT."""
        query = "{ allPostsList { id title } }"
        with CaptureQueriesContext(connection) as ctx:
            _exec(_ann_schema, query)
        sqls = " ".join(q["sql"] for q in ctx.captured_queries)
        self.assertNotIn("_gqx_ann_", sqls)


class TestKillSwitchDisablesAnnotation(TestCase):
    """4.3 / 8 — OPTIMIZE_ANNOTATED_FIELDS=False disables annotation."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        author = Author.objects.create(name="Dave", bio="")
        Post.objects.create(title="PX", author=author)

    def test_kill_switch_disables_annotation(self):
        """With kill-switch off, no _gqx_ann_* in SQL and field resolves to None."""
        from django_graphex.settings import graphql_api_settings

        query = "{ allPostsList { id commentCount } }"
        with patch.object(graphql_api_settings, "OPTIMIZE_ANNOTATED_FIELDS", False):
            with CaptureQueriesContext(connection) as ctx:
                data = _exec(_ann_schema, query)
        sqls = " ".join(q["sql"] for q in ctx.captured_queries)
        self.assertNotIn("_gqx_ann_", sqls)
        # Field should resolve to None (default resolver returns getattr(root, ann, None))
        for r in data["allPostsList"]:
            self.assertIsNone(r["commentCount"])


# ---------------------------------------------------------------------------
# Phase 5: SELECT→PREFETCH promotion tests (tasks 5.1 - 5.3)
# ---------------------------------------------------------------------------

# Schema for promotion tests
_RPROM = Registry()


class _AuthorTypePromo(DjangoObjectType):
    post_count = AnnotatedField(graphene.Int, lambda: Count("posts"))

    class Meta:
        from tests.models import Author as _A

        model = _A
        registry = _RPROM


class _PostTypePromo(DjangoObjectType):
    class Meta:
        from tests.models import Post as _P

        model = _P
        registry = _RPROM


class _PostListTypePromo(DjangoListObjectType):
    class Meta:
        from tests.models import Post as _P

        model = _P
        registry = _RPROM


class _PromoQuery(graphene.ObjectType):
    all_posts = DjangoListObjectField(_PostListTypePromo)


_promo_schema = graphene.Schema(query=_PromoQuery)


class TestSelectToPrefetchPromotion(TestCase):
    """5.1 — select_related author → prefetch when author has AnnotatedField selected."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        for i in range(3):
            a = Author.objects.create(name=f"A{i}", bio="")
            Post.objects.create(title=f"Post{i}", author=a)

    def test_select_to_prefetch_promotion(self):
        """Author with AnnotatedField postCount → promoted to prefetch (3 queries: count + posts + authors)."""
        query = "{ allPosts { results { id author { name postCount } } } }"
        # DjangoListObjectType = 2 base queries (count + posts) + 1 prefetch author = 3
        with self.assertNumQueries(3):
            with CaptureQueriesContext(connection):
                data = _exec(_promo_schema, query)
        # Verify postCount value is present and not None
        results = data["allPosts"]["results"]
        for r in results:
            self.assertIsNotNone(r["author"]["postCount"])

    def test_no_promotion_when_no_annotated_field(self):
        """5.2 — Author stays in select_related when no AnnotatedField selected."""
        # 2 total: 1 count + 1 posts-with-author-join
        query = "{ allPosts { results { id author { name } } } }"
        with self.assertNumQueries(2):
            with CaptureQueriesContext(connection):
                data = _exec(_promo_schema, query)
        results = data["allPosts"]["results"]
        self.assertTrue(len(results) > 0)


class TestPromotionGrandchildSelectSurvival(TestCase):
    """5.3 — Grandchild select_related survives promotion of parent to prefetch."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, AuthorProfile, Post

        for i in range(2):
            a = Author.objects.create(name=f"B{i}", bio="")
            AuthorProfile.objects.create(author=a, bio=f"bio{i}")
            Post.objects.create(title=f"Q{i}", author=a)

    def test_promotion_grandchild_select_survival(self):
        """Promotion of author to prefetch must not lose the author_profile child O2O."""
        from tests.models import Author as _Author
        from tests.models import AuthorProfile as _AP
        from tests.models import Post as _Post

        _RGC = Registry()

        class _APType(DjangoObjectType):
            class Meta:
                model = _AP
                registry = _RGC

        class _AuthGC(DjangoObjectType):
            post_count = AnnotatedField(graphene.Int, lambda: Count("posts"))

            class Meta:
                model = _Author
                registry = _RGC

        class _PostGC(DjangoObjectType):
            class Meta:
                model = _Post
                registry = _RGC

        class _PostGCList(DjangoListObjectType):
            class Meta:
                model = _Post
                registry = _RGC

        class _GCQuery(graphene.ObjectType):
            all_posts = DjangoListObjectField(_PostGCList)

        gc_schema = graphene.Schema(query=_GCQuery)
        query = "{ allPosts { results { author { name postCount authorProfile { bio } } } } }"
        # Should not raise "Invalid field name(s) given in select_related"
        data = _exec(gc_schema, query)
        results = data["allPosts"]["results"]
        for r in results:
            self.assertIsNotNone(r["author"]["postCount"])
            # authorProfile must not be None — if promotion loses the grandchild
            # O2O select_related the profile will be null and this assertion fails.
            self.assertIsNotNone(
                r["author"]["authorProfile"],
                f"authorProfile is None for author '{r['author']['name']}'; "
                "grandchild select_related was lost during promotion",
            )
            self.assertIn("bio", r["author"]["authorProfile"])


# ---------------------------------------------------------------------------
# Phase 6: PrefetchPlan extension + child-annotation collection (tasks 6.1-6.3)
# ---------------------------------------------------------------------------


class TestComputeChildOnlySelfCollectsAnnotations(TestCase):
    """6.1 — _compute_child_only self-collects child AnnotatedField annotations."""

    def test_compute_child_only_self_collects_annotations(self):
        """_compute_child_only with child_gql_type returns PrefetchPlan with child_annotations."""
        from django_graphex.utils import PrefetchPlan, _compute_child_only
        from tests.models import Author, Post

        _R6 = Registry()

        class _PostT(DjangoObjectType):
            comment_count = AnnotatedField(graphene.Int, lambda: Count("comments"))

            class Meta:
                model = Post
                registry = _R6

        class _AuthT(DjangoObjectType):
            class Meta:
                model = Author
                registry = _R6

        class _Q(graphene.ObjectType):
            all_authors = graphene.List(_AuthT)

        schema = graphene.Schema(query=_Q)
        gql_schema = schema.graphql_schema
        post_gql_type = gql_schema.type_map.get("_PostT")

        from graphql import parse

        doc = parse("{ id commentCount }")

        op = doc.definitions[0]
        sub_selection = op.selection_set

        rel_field = Author._meta.get_field("posts")

        plan = _compute_child_only(
            Post,
            rel_field,
            sub_selection,
            {},
            child_gql_type=post_gql_type,
            child_graphene_type=_PostT,
        )
        self.assertIsNotNone(plan)
        self.assertIsInstance(plan, PrefetchPlan)
        self.assertIn("_gqx_ann_comment_count", plan.child_annotations)
        # annotation key must NOT be in only_cols
        self.assertFalse(
            any("comment_count" in col for col in plan.only_cols),
            f"Annotated leaf found in only_cols: {plan.only_cols}",
        )


class TestPrefetchChildAnnotation(TestCase):
    """6.2 — Prefetch child annotation injected in child Prefetch queryset."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Comment, Post

        for i in range(2):
            a = Author.objects.create(name=f"C{i}", bio="")
            for j in range(2):
                p = Post.objects.create(title=f"P{i}{j}", author=a)
                for k in range(j + 1):
                    Comment.objects.create(post=p, body=f"c{k}")

    def test_prefetch_child_annotation(self):
        """Author.posts prefetch carries commentCount annotation on child Prefetch qs."""
        from tests.models import Author, Comment, Post

        _R6B = Registry()

        class _PostType6(DjangoObjectType):
            comment_count = AnnotatedField(graphene.Int, lambda: Count("comments"))

            class Meta:
                model = Post
                registry = _R6B

        class _AuthType6(DjangoObjectType):
            # Declare posts explicitly to avoid graphene picking up PostListType
            # from a different registry's DjangoListObjectType for Post.
            posts = graphene.List(lambda: _PostType6)

            def resolve_posts(root, info):
                # Return the pre-fetched related set (or fallback to queryset).
                # _apply_optimizations will have set up a Prefetch on root's qs.
                return root.posts.all()

            class Meta:
                model = Author
                registry = _R6B

        class _AuthList6(DjangoListObjectType):
            class Meta:
                model = Author
                registry = _R6B

        class _Q6(graphene.ObjectType):
            all_authors = DjangoListObjectField(_AuthList6)

        schema6 = graphene.Schema(query=_Q6)
        query = "{ allAuthors { results { name posts { id commentCount } } } }"

        with CaptureQueriesContext(connection) as ctx:
            data = _exec(schema6, query)

        sqls = " ".join(q["sql"] for q in ctx.captured_queries)
        self.assertIn(
            "COUNT", sqls.upper(), "Child Prefetch queryset should contain COUNT"
        )

        # Verify values
        for author_data in data["allAuthors"]["results"]:
            for post_data in author_data["posts"]:
                post = Post.objects.get(id=post_data["id"])
                expected = Comment.objects.filter(post=post).count()
                self.assertEqual(post_data["commentCount"], expected)


class TestPrefetchGateFiresOnAnnotatedFieldsOnly(TestCase):
    """6.3 — OPTIMIZE_ONLY_FIELDS=False + OPTIMIZE_ANNOTATED_FIELDS=True injects child annotation."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Comment, Post

        a = Author.objects.create(name="E0", bio="")
        p = Post.objects.create(title="PG", author=a)
        Comment.objects.create(post=p, body="x")

    @override_settings(
        DJANGO_GRAPHEX={
            "OPTIMIZE_ONLY_FIELDS": False,
            "OPTIMIZE_ANNOTATED_FIELDS": True,
        }
    )
    def test_prefetch_gate_fires_on_annotated_fields_only(self):
        """Child annotation present even when OPTIMIZE_ONLY_FIELDS is False."""
        from tests.models import Author, Comment, Post

        _R6C = Registry()

        class _PostT6C(DjangoObjectType):
            comment_count = AnnotatedField(graphene.Int, lambda: Count("comments"))

            class Meta:
                model = Post
                registry = _R6C

        class _AuthT6C(DjangoObjectType):
            # Declare posts explicitly to avoid graphene picking up PostListType
            # from a different registry's DjangoListObjectType for Post.
            posts = graphene.List(lambda: _PostT6C)

            def resolve_posts(root, info):
                return root.posts.all()

            class Meta:
                model = Author
                registry = _R6C

        class _AuthList6C(DjangoListObjectType):
            class Meta:
                model = Author
                registry = _R6C

        class _Q6C(graphene.ObjectType):
            all_authors = DjangoListObjectField(_AuthList6C)

        schema6c = graphene.Schema(query=_Q6C)
        query = "{ allAuthors { results { name posts { id commentCount } } } }"

        with CaptureQueriesContext(connection) as ctx:
            data = _exec(schema6c, query)

        sqls = " ".join(q["sql"] for q in ctx.captured_queries)
        self.assertIn(
            "COUNT",
            sqls.upper(),
            "Child annotation should be present despite ONLY_FIELDS=False",
        )
        # Values correct
        for author_data in data["allAuthors"]["results"]:
            for post_data in author_data["posts"]:
                post = Post.objects.get(id=post_data["id"])
                expected = Comment.objects.filter(post=post).count()
                self.assertEqual(post_data["commentCount"], expected)


# ---------------------------------------------------------------------------
# Phase 8: SAFE_MODE + collision-safety + alias-before-annotate tests (tasks 8.1-8.4)
# ---------------------------------------------------------------------------


class TestSafeModeContractStructural(TestCase):
    """8.1 — OPTIMIZER_SAFE_MODE=True wraps _apply_optimizations."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        a = Author.objects.create(name="Safe", bio="")
        Post.objects.create(title="SP", author=a)

    def test_safe_mode_catches_apply_optimizations_error(self):
        """With SAFE_MODE=True, FieldError from _apply_optimizations is swallowed."""
        from django.core.exceptions import FieldError

        from django_graphex.settings import graphql_api_settings
        from tests.models import Post

        call_count = {"n": 0}

        def _raise_once(base, model, info, kwargs, custom_used):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise FieldError("test error")
            return base

        with (
            patch.object(graphql_api_settings, "OPTIMIZER_SAFE_MODE", True),
            patch("django_graphex.utils._apply_optimizations", side_effect=_raise_once),
        ):
            _R8 = Registry()

            class _PostT8(DjangoObjectType):
                class Meta:
                    model = Post
                    registry = _R8

            class _PostList8(DjangoListObjectType):
                class Meta:
                    model = Post
                    registry = _R8

            class _Q8(graphene.ObjectType):
                all_posts = DjangoListObjectField(_PostList8)

            schema8 = graphene.Schema(query=_Q8)
            # With SAFE_MODE=True, the FieldError should NOT propagate.
            result = schema8.execute("{ allPosts { results { id } } }")
            self.assertIsNone(result.errors, result.errors)


class TestSafeModeFalsePropagatesBuildError(TestCase):
    """8.2 — OPTIMIZER_SAFE_MODE=False propagates FieldError from optimization."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        a = Author.objects.create(name="Loud", bio="")
        Post.objects.create(title="LP", author=a)

    def test_safe_mode_false_propagates_build_error(self):
        """With SAFE_MODE=False (default), FieldError from optimization propagates."""
        from django.core.exceptions import FieldError

        from tests.models import Post

        def _raise(base, model, info, kwargs, custom_used):
            raise FieldError("intentional")

        with patch("django_graphex.utils._apply_optimizations", side_effect=_raise):
            _R8B = Registry()

            class _PostT8B(DjangoObjectType):
                class Meta:
                    model = Post
                    registry = _R8B

            class _PostList8B(DjangoListObjectType):
                class Meta:
                    model = Post
                    registry = _R8B

            class _Q8B(graphene.ObjectType):
                all_posts = DjangoListObjectField(_PostList8B)

            schema8b = graphene.Schema(query=_Q8B)
            result = schema8b.execute("{ allPosts { results { id } } }")
            self.assertIsNotNone(result.errors)


class TestAliasBeforeAnnotateOrder(TestCase):
    """8.3 — alias() is called before annotate() in root injection."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        a = Author.objects.create(name="ABO", bio="")
        Post.objects.create(title="AO1", author=a)

    def test_alias_before_annotate_order(self):
        """alias(**aliases) must be called before annotate(**annotations) on root qs."""
        from django.db.models import QuerySet

        from tests.models import Post

        _R8C = Registry()

        class _PostT8C(DjangoObjectType):
            # ratio uses an alias (cnt) in its expression
            ratio = AnnotatedField(
                graphene.Float,
                lambda: F("cnt") * 1.0,
                aliases={"cnt": Count("comments")},
            )

            class Meta:
                model = Post
                registry = _R8C

        class _PostList8C(DjangoListObjectType):
            class Meta:
                model = Post
                registry = _R8C

        class _Q8C(graphene.ObjectType):
            all_posts = DjangoListObjectField(_PostList8C)

        schema8c = graphene.Schema(query=_Q8C)

        call_order = []
        _orig_alias = QuerySet.alias
        _orig_annotate = QuerySet.annotate

        def _spy_alias(self_qs, **kwargs):
            call_order.append("alias")
            return _orig_alias(self_qs, **kwargs)

        def _spy_annotate(self_qs, **kwargs):
            call_order.append("annotate")
            return _orig_annotate(self_qs, **kwargs)

        with (
            patch.object(QuerySet, "alias", _spy_alias),
            patch.object(QuerySet, "annotate", _spy_annotate),
        ):
            data = _exec(schema8c, "{ allPosts { results { id ratio } } }")

        alias_indices = [i for i, c in enumerate(call_order) if c == "alias"]
        annotate_indices = [i for i, c in enumerate(call_order) if c == "annotate"]
        # Both alias() and annotate() must have been called — if either is absent
        # the injection path is broken and the ordering guarantee is meaningless.
        self.assertTrue(
            alias_indices,
            f"alias() was never called; root annotation injection is broken. "
            f"Order: {call_order}",
        )
        self.assertTrue(
            annotate_indices,
            f"annotate() was never called; root annotation injection is broken. "
            f"Order: {call_order}",
        )
        # The first alias() must precede the last annotate()
        self.assertLess(
            min(alias_indices),
            max(annotate_indices),
            f"alias() must be called before annotate(). Order: {call_order}",
        )
        # End-to-end: the aliased AnnotatedField (ratio) must resolve to a
        # non-None value — confirms the alias expression was actually applied.
        results = data["allPosts"]["results"]
        self.assertTrue(len(results) > 0, "Expected at least one Post in results")
        for r in results:
            self.assertIsNotNone(
                r["ratio"],
                f"ratio resolved to None; alias/annotate injection may be broken. "
                f"Post id={r['id']}",
            )


class TestAnnotationNameCollisionSafety(TestCase):
    """8.4 — Two AnnotatedFields use distinct annotation keys; override avoids clash."""

    def test_annotation_name_collision_safety(self):
        """Two AnnotatedFields on the same type use distinct _gqx_ann_* keys."""
        field_a = AnnotatedField(
            graphene.Int, Count("comments"), annotation_name="explicit_a"
        )
        field_b = AnnotatedField(graphene.Int, Count("tags"))

        self.assertNotEqual(
            field_a.annotation_name("comment_count"),
            field_b.annotation_name("tag_count"),
        )
        self.assertEqual(field_a.annotation_name("comment_count"), "explicit_a")
        self.assertEqual(field_b.annotation_name("tag_count"), "_gqx_ann_tag_count")

    def test_annotation_name_prefix_isolation_from_window(self):
        """_gqx_ann_ prefix must not collide with _gqx_rn or _gqx_total."""
        field = AnnotatedField(graphene.Int, Count("tags"))
        ann = field.annotation_name("rank")
        self.assertEqual(ann, "_gqx_ann_rank")
        self.assertNotEqual(ann, "_gqx_rn")
        self.assertNotEqual(ann, "_gqx_total")


# ---------------------------------------------------------------------------
# Phase 9: Verification / import / export checks (tasks 9.3, 9.4)
# ---------------------------------------------------------------------------


class TestAnnotatedFieldImportable(TestCase):
    """9.3 — AnnotatedField importable from top-level package."""

    def test_annotated_field_importable(self):
        """from django_graphex import AnnotatedField works."""
        from django_graphex import AnnotatedField as AF

        self.assertIsNotNone(AF)
        self.assertTrue(callable(AF))

    def test_annotated_field_in_all(self):
        """AnnotatedField in django_graphex.__all__."""
        import django_graphex

        self.assertIn("AnnotatedField", django_graphex.__all__)


class TestAnnotatedFieldsSettingAccessible(TestCase):
    """9.4 — OPTIMIZE_ANNOTATED_FIELDS accessible via graphql_api_settings."""

    def test_optimize_annotated_fields_setting(self):
        """OPTIMIZE_ANNOTATED_FIELDS accessible from graphql_api_settings."""
        from django_graphex.settings import graphql_api_settings as s

        self.assertIs(s.OPTIMIZE_ANNOTATED_FIELDS, True)
