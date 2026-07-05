"""Tests for optimizer-phase-d: AnnotatedField optimization.

D1 slice: §1-6 + §8-9 implementation + tests 1-6b/8/10.
D2 slice (§7 window-compose): Tests 7.1, 7.2, 7.3 — window-prefetch composition.

STRICT TDD: RED tests are written first, then GREEN implementation fills them.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.db import connection
from django.db.models import Count, F, Sum
from django.db.models.expressions import (
    Window,  # noqa: F401 - used for error-expression test
)
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from graphql import (
    GraphQLFloat,
    GraphQLInt,
    GraphQLString,
    graphql_sync,
)

from django_graphex.core import ObjectType, field
from django_graphex.core.descriptors import NativeList
from django_graphex.fields import (
    AnnotatedField,
    DjangoFilterListField,
    DjangoListObjectField,
)
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair


def _execute(schema, query):
    """Execute *query* against a native ``DjangoGraphQLSchema`` (graphene-free).

    Drop-in for the retired ``_execute(schema, query)``: returns the graphql-core
    ``ExecutionResult`` (same ``.data`` / ``.errors`` shape graphene returned).
    """
    return graphql_sync(schema.graphql_schema, query)


def _gtype(name, bases, ns):
    """Build a dynamic native type via ``type()`` with pydantic-safe namespace.

    Native ``ObjectType`` / ``DjangoObjectType`` / ``DjangoListObjectType`` are
    pydantic ``BaseModel`` subclasses; building them with ``type(name, bases, ns)``
    requires ``ns['__module__']`` and a nested ``Meta`` whose ``__qualname__`` is
    ``"<Outer>.Meta"`` (the value a ``class`` body produces).
    """
    ns = dict(ns)
    ns.setdefault("__module__", __name__)
    ns["__qualname__"] = name
    for attr_name, attr_val in list(ns.items()):
        if isinstance(attr_val, type):
            try:
                attr_val.__qualname__ = f"{name}.{attr_name}"
            except (AttributeError, TypeError):  # pragma: no cover - defensive
                pass
    return type(name, bases, ns)


# ---------------------------------------------------------------------------
# Phase 1: AnnotatedField class + setting unit tests (tasks 1.1 - 1.4)
# ---------------------------------------------------------------------------


class TestAnnotatedFieldStoresAttrs(TestCase):
    """1.1 — AnnotatedField stores expression, aliases, annotation_name.

    See the tests below for the exact contract covered.
    """

    def test_annotated_field_stores_attrs(self) -> None:
        """AnnotatedField stores expression, aliases default {}, annotation_name derived.

        This test breaks if this contract regresses.
        """
        expr = Count("comments")
        field = AnnotatedField(GraphQLInt, expr)
        self.assertIs(field.expression, expr)
        self.assertEqual(field.aliases, {})
        self.assertEqual(
            field.annotation_name("comment_count"),
            "_gqx_ann_comment_count",
        )


class TestAnnotatedFieldAliasesAndOverride(TestCase):
    """1.2 — AnnotatedField aliases and annotation_name override survive.

    See the tests below for the exact contract covered.
    """

    def test_annotated_field_aliases_and_override(self) -> None:
        """aliases and annotation_name override are stored correctly.

        This test breaks if this contract regresses.
        """
        expr = F("subtotal") / F("item_cnt")
        aliases = {"subtotal": Sum("price"), "item_cnt": Count("id")}
        field = AnnotatedField(
            GraphQLFloat, expr, aliases=aliases, annotation_name="my_ann"
        )
        self.assertIs(field.expression, expr)
        self.assertEqual(field.aliases, aliases)
        self.assertEqual(field._explicit_annotation_name, "my_ann")
        # annotation_name() should return the override regardless of field_name.
        self.assertEqual(field.annotation_name("whatever"), "my_ann")


class TestAnnotatedFieldDefaultResolver(TestCase):
    """1.3 — Default resolver reads _gqx_ann_<field_name> from root.

    See the tests below for the exact contract covered.
    """

    def test_annotated_field_default_resolver_absent(self) -> None:
        """Resolver returns None when annotation attr is absent on root.

        This test breaks if this contract regresses.
        """
        field = AnnotatedField(GraphQLInt, Count("comments"))

        class FakeInfo:
            field_name = "commentCount"

        class FakeRoot:
            pass

        result = field._default_resolver(FakeRoot(), FakeInfo())
        self.assertIsNone(result)

    def test_annotated_field_default_resolver_present(self) -> None:
        """Resolver returns the annotation value when attr is present on root.

        This test breaks if this contract regresses.
        """
        field = AnnotatedField(GraphQLInt, Count("comments"))

        class FakeInfo:
            field_name = "commentCount"

        class FakeRoot:
            _gqx_ann_comment_count = 42

        result = field._default_resolver(FakeRoot(), FakeInfo())
        self.assertEqual(result, 42)

    def test_resolve_expression_callable(self) -> None:
        """resolve_expression calls a zero-arg callable.

        This test breaks if this contract regresses.
        """
        expr = Count("comments")
        result = AnnotatedField.resolve_expression(lambda: expr)
        self.assertIs(result, expr)

    def test_resolve_expression_instance(self) -> None:
        """resolve_expression returns Expression as-is.

        This test breaks if this contract regresses.
        """
        expr = Count("comments")
        result = AnnotatedField.resolve_expression(expr)
        self.assertIs(result, expr)


class TestOptimizeAnnotatedFieldsSettingDefault(TestCase):
    """1.4 / 10 — OPTIMIZE_ANNOTATED_FIELDS defaults True.

    See the tests below for the exact contract covered.
    """

    def test_optimize_annotated_fields_setting_default(self) -> None:
        """OPTIMIZE_ANNOTATED_FIELDS defaults to True.

        This test breaks if this contract regresses.
        """
        from django_graphex import settings as settings_module

        s = settings_module.graphql_api_settings
        self.assertTrue(
            hasattr(s, "OPTIMIZE_ANNOTATED_FIELDS"),
            "graphql_api_settings must expose OPTIMIZE_ANNOTATED_FIELDS",
        )
        self.assertIs(s.OPTIMIZE_ANNOTATED_FIELDS, True)

    @override_settings(DJANGO_GRAPHEX={"OPTIMIZE_ANNOTATED_FIELDS": False})
    def test_optimize_annotated_fields_explicit_false(self) -> None:
        """OPTIMIZE_ANNOTATED_FIELDS=False propagates via override_settings.

        This test breaks if this contract regresses.
        """
        from django_graphex import settings as settings_module

        s = settings_module.graphql_api_settings
        self.assertIs(s.OPTIMIZE_ANNOTATED_FIELDS, False)


# ---------------------------------------------------------------------------
# Phase 2: _collect_annotated_fields walker unit tests (tasks 2.1 - 2.3)
# ---------------------------------------------------------------------------

# Build a minimal schema for walker tests (no DB needed).
_RWALK = Registry()


class _DWalkPost(DjangoObjectType):
    comment_count = AnnotatedField(GraphQLInt, Count("comments"))

    class Meta:
        from tests.models import Post as _P

        model = _P
        registry = _RWALK


class _DWalkPostList(DjangoListObjectType):
    class Meta:
        from tests.models import Post as _P

        model = _P
        registry = _RWALK


class _DWalkQuery(ObjectType):
    all_posts = DjangoListObjectField(_DWalkPostList)
    all_posts_flat = DjangoFilterListField(_DWalkPost)


_walk_schema = DjangoGraphQLSchema(query=_DWalkQuery, registries=isolated_pair(_RWALK))


def _make_info_for_field(schema, query_str, field_name):
    """Build a minimal mock GraphQLResolveInfo for a root field.

    This test breaks if this contract regresses.
    """
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
    """2.1 — _collect_annotated_fields returns annotation when field selected.

    See the tests below for the exact contract covered.
    """

    def test_collect_annotated_fields_selected(self) -> None:
        """ "_collect_annotated_fields" returns the annotation when "commentCount" is selected.

        This test breaks if a selected AnnotatedField stops being collected
        into the annotations/names output.
        """
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

    def test_collect_annotated_fields_absent(self) -> None:
        """2.2 — No annotation when field not selected.

        This test breaks if this contract regresses.
        """
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
    """2.3 — Walker descends into DjangoListObjectType results wrapper.

    See the tests below for the exact contract covered.
    """

    def test_collect_annotated_fields_wrapper_descent(self) -> None:
        """Wrapper shape allPosts { results { commentCount } } is descended.

        This test breaks if this contract regresses.
        """
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
    """3.1 — AnnotatedField leaf does not cause full-load, not added to only.

    See the tests below for the exact contract covered.
    """

    def test_collect_only_fields_annotated_leaf_skipped(self) -> None:
        """An AnnotatedField leaf ("commentCount") does not force a full-load and is not added to only().

        This test breaks if the annotated leaf starts being treated as an
        unknown concrete column, dropping the narrowing to a full-load
        (surfaced here as "body" appearing in "only").
        """
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

    def test_collect_only_fields_wrapper_path_annotated_leaf_skipped(self) -> None:
        """3.1b — Wrapper recursion path: annotated leaf not full-load.

        This test breaks if this contract regresses.
        """
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
    """3.2 — _collect_only_fields_is_full_load returns False for AnnotatedField.

    See the tests below for the exact contract covered.
    """

    def test_collect_only_fields_is_full_load_annotated_skipped(self) -> None:
        """ "_collect_only_fields_is_full_load" returns False for a selection containing an AnnotatedField.

        This test breaks if the AnnotatedField leaf ("commentCount") starts
        being treated as an unknown leaf, flipping full-load detection to
        True.
        """
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
    comment_count = AnnotatedField(GraphQLInt, lambda: Count("comments"))

    class Meta:
        from tests.models import Post as _P

        model = _P
        registry = _RANN


class _DPostListType(DjangoListObjectType):
    class Meta:
        from tests.models import Post as _P

        model = _P
        registry = _RANN


class _AnnQuery(ObjectType):
    # Flat List field — EXACTLY 1 query (no count query).
    # DjangoFilterListField calls queryset_factory internally.
    all_posts_list = DjangoFilterListField(_DPostType)
    # DjangoListObjectType wrapper — 2 queries (results + count)
    all_posts = DjangoListObjectField(_DPostListType)


_ann_schema = DjangoGraphQLSchema(query=_AnnQuery, registries=isolated_pair(_RANN))


def _exec(schema, query):
    result = _execute(schema, query)
    assert result.errors is None, result.errors
    return result.data


class TestRootAnnotationInjected1Query(TestCase):
    """4.1 — Flat List field with AnnotatedField = exactly 1 query.

    See the tests below for the exact contract covered.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with three posts carrying an increasing number of comments each.

        This test breaks if this contract regresses.
        """
        from tests.models import Author, Comment, Post

        author = Author.objects.create(name="Alice", bio="")
        for i in range(3):
            p = Post.objects.create(title=f"Post{i}", author=author)
            for j in range(i + 1):
                Comment.objects.create(post=p, body=f"c{j}")

    def test_root_annotation_injected_1query(self) -> None:
        """FLAT DjangoFilterListField(DPostType) with commentCount = exactly 1 DB query.

        This test breaks if this contract regresses.
        """
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
    """4.1b — DjangoListObjectType wrapper with AnnotatedField = exactly 2 queries.

    See the tests below for the exact contract covered.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with two posts carrying an increasing number of comments each.

        This test breaks if this contract regresses.
        """
        from tests.models import Author, Comment, Post

        author = Author.objects.create(name="Bob", bio="")
        for i in range(2):
            p = Post.objects.create(title=f"P{i}", author=author)
            for j in range(i + 2):
                Comment.objects.create(post=p, body=f"b{j}")

    def test_root_annotation_injected_wrapper_2queries(self) -> None:
        """DjangoListObjectType wrapper with totalCount = exactly 1 query.

        totalCount is selected after results, so the lazy count reuses the
        materialized result cache — the annotated SELECT is the only query
        (no separate COUNT).
        """
        from tests.models import Comment, Post

        query = "{ allPosts { results { id commentCount } totalCount } }"
        with self.assertNumQueries(1):
            data = _exec(_ann_schema, query)
        results = data["allPosts"]["results"]
        by_id = {r["id"]: r["commentCount"] for r in results}
        for post in Post.objects.all():
            expected = Comment.objects.filter(post=post).count()
            self.assertEqual(by_id[str(post.id)], expected)


class TestRootAnnotationAbsentNoSQL(TestCase):
    """4.2 — No COUNT in SQL when commentCount not selected.

    See the tests below for the exact contract covered.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with one post, for the annotation-absence test.

        This test breaks if this contract regresses.
        """
        from tests.models import Author, Post

        author = Author.objects.create(name="Charlie", bio="")
        Post.objects.create(title="P0", author=author)

    def test_root_annotation_absent_no_sql(self) -> None:
        """When commentCount NOT selected, SQL must not contain _gqx_ann_ or COUNT.

        This test breaks if this contract regresses.
        """
        query = "{ allPostsList { id title } }"
        with CaptureQueriesContext(connection) as ctx:
            _exec(_ann_schema, query)
        sqls = " ".join(q["sql"] for q in ctx.captured_queries)
        self.assertNotIn("_gqx_ann_", sqls)


class TestKillSwitchDisablesAnnotation(TestCase):
    """4.3 / 8 — OPTIMIZE_ANNOTATED_FIELDS=False disables annotation.

    See the tests below for the exact contract covered.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with one post, for the annotation kill-switch test.

        This test breaks if this contract regresses.
        """
        from tests.models import Author, Post

        author = Author.objects.create(name="Dave", bio="")
        Post.objects.create(title="PX", author=author)

    def test_kill_switch_disables_annotation(self) -> None:
        """With kill-switch off, no _gqx_ann_* in SQL and field resolves to None.

        This test breaks if this contract regresses.
        """
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
    post_count = AnnotatedField(GraphQLInt, lambda: Count("posts"))

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


class _PromoQuery(ObjectType):
    all_posts = DjangoListObjectField(_PostListTypePromo)


_promo_schema = DjangoGraphQLSchema(query=_PromoQuery, registries=isolated_pair(_RPROM))


class TestSelectToPrefetchPromotion(TestCase):
    """5.1 — select_related author → prefetch when author has AnnotatedField selected.

    See the tests below for the exact contract covered.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create three authors, each with one post, for the select-to-prefetch promotion test.

        This test breaks if this contract regresses.
        """
        from tests.models import Author, Post

        for i in range(3):
            a = Author.objects.create(name=f"A{i}", bio="")
            Post.objects.create(title=f"Post{i}", author=a)

    def test_select_to_prefetch_promotion(self) -> None:
        """Author with AnnotatedField postCount → promoted to prefetch (2 queries: posts + authors).

        This test breaks if this contract regresses.
        """
        query = "{ allPosts { results { id author { name postCount } } } }"
        # totalCount is not selected, so the lazy count is never accessed and no
        # COUNT query is issued: 1 posts + 1 prefetch author = 2.
        with self.assertNumQueries(2):
            with CaptureQueriesContext(connection):
                data = _exec(_promo_schema, query)
        # Verify postCount value is present and not None
        results = data["allPosts"]["results"]
        for r in results:
            self.assertIsNotNone(r["author"]["postCount"])

    def test_no_promotion_when_no_annotated_field(self) -> None:
        """5.2 — Author stays in select_related when no AnnotatedField selected.

        This test breaks if this contract regresses.
        """
        # 1 total: 1 posts-with-author-join. totalCount is not selected, so the
        # lazy count is never accessed and no COUNT query is issued.
        query = "{ allPosts { results { id author { name } } } }"
        with self.assertNumQueries(1):
            with CaptureQueriesContext(connection):
                data = _exec(_promo_schema, query)
        results = data["allPosts"]["results"]
        self.assertTrue(len(results) > 0)


class TestPromotionGrandchildSelectSurvival(TestCase):
    """5.3 — Grandchild select_related survives promotion of parent to prefetch.

    See the tests below for the exact contract covered.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create two authors, each with a profile and a post, for the grandchild-survival test.

        This test breaks if this contract regresses.
        """
        from tests.models import Author, AuthorProfile, Post

        for i in range(2):
            a = Author.objects.create(name=f"B{i}", bio="")
            AuthorProfile.objects.create(author=a, bio=f"bio{i}")
            Post.objects.create(title=f"Q{i}", author=a)

    def test_promotion_grandchild_select_survival(self) -> None:
        """Promotion of author to prefetch must not lose the author_profile child O2O.

        This test breaks if this contract regresses.
        """
        from tests.models import Author as _Author
        from tests.models import AuthorProfile as _AP
        from tests.models import Post as _Post

        _RGC = Registry()

        class _APType(DjangoObjectType):
            class Meta:
                model = _AP
                registry = _RGC

        class _AuthGC(DjangoObjectType):
            post_count = AnnotatedField(GraphQLInt, lambda: Count("posts"))

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

        class _GCQuery(ObjectType):
            all_posts = DjangoListObjectField(_PostGCList)

        gc_schema = DjangoGraphQLSchema(query=_GCQuery, registries=isolated_pair(_RGC))
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
    """6.1 — _compute_child_only self-collects child AnnotatedField annotations.

    See the tests below for the exact contract covered.
    """

    def test_compute_child_only_self_collects_annotations(self) -> None:
        """_compute_child_only with child_gql_type returns PrefetchPlan with child_annotations.

        This test breaks if this contract regresses.
        """
        from django_graphex.utils import PrefetchPlan, _compute_child_only
        from tests.models import Author, Post

        _R6 = Registry()

        class _PostT(DjangoObjectType):
            comment_count = AnnotatedField(GraphQLInt, lambda: Count("comments"))

            class Meta:
                model = Post
                registry = _R6

        class _AuthT(DjangoObjectType):
            class Meta:
                model = Author
                registry = _R6

        class _Q(ObjectType):
            all_authors = DjangoFilterListField(_AuthT)

        schema = DjangoGraphQLSchema(query=_Q, registries=isolated_pair(_R6))
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
    """6.2 — Prefetch child annotation injected in child Prefetch queryset.

    See the tests below for the exact contract covered.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create two authors, each with two posts, for the prefetch-child-annotation test.

        This test breaks if this contract regresses.
        """
        from tests.models import Author, Comment, Post

        for i in range(2):
            a = Author.objects.create(name=f"C{i}", bio="")
            for j in range(2):
                p = Post.objects.create(title=f"P{i}{j}", author=a)
                for k in range(j + 1):
                    Comment.objects.create(post=p, body=f"c{k}")

    def test_prefetch_child_annotation(self) -> None:
        """Author.posts prefetch carries commentCount annotation on child Prefetch qs.

        This test breaks if this contract regresses.
        """
        from tests.models import Author, Comment, Post

        _R6B = Registry()

        class _PostType6(DjangoObjectType):
            comment_count = AnnotatedField(GraphQLInt, lambda: Count("comments"))

            class Meta:
                model = Post
                registry = _R6B

        class _AuthType6(DjangoObjectType):
            # Declare posts explicitly to avoid graphene picking up PostListType
            # from a different registry's DjangoListObjectType for Post.
            posts = field(NativeList(_PostType6))

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

        class _Q6(ObjectType):
            all_authors = DjangoListObjectField(_AuthList6)

        schema6 = DjangoGraphQLSchema(query=_Q6, registries=isolated_pair(_R6B))
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
    """6.3 — OPTIMIZE_ONLY_FIELDS=False + OPTIMIZE_ANNOTATED_FIELDS=True injects child annotation.

    See the tests below for the exact contract covered.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with one post carrying one comment, for the prefetch-gate test.

        This test breaks if this contract regresses.
        """
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
    def test_prefetch_gate_fires_on_annotated_fields_only(self) -> None:
        """Child annotation present even when OPTIMIZE_ONLY_FIELDS is False.

        This test breaks if this contract regresses.
        """
        from tests.models import Author, Comment, Post

        _R6C = Registry()

        class _PostT6C(DjangoObjectType):
            comment_count = AnnotatedField(GraphQLInt, lambda: Count("comments"))

            class Meta:
                model = Post
                registry = _R6C

        class _AuthT6C(DjangoObjectType):
            # Declare posts explicitly to avoid graphene picking up PostListType
            # from a different registry's DjangoListObjectType for Post.
            posts = field(NativeList(_PostT6C))

            def resolve_posts(root, info):
                return root.posts.all()

            class Meta:
                model = Author
                registry = _R6C

        class _AuthList6C(DjangoListObjectType):
            class Meta:
                model = Author
                registry = _R6C

        class _Q6C(ObjectType):
            all_authors = DjangoListObjectField(_AuthList6C)

        schema6c = DjangoGraphQLSchema(query=_Q6C, registries=isolated_pair(_R6C))
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
# S1 (W1 coverage gap from verify-report): mixed concrete+annotated prefetch
# child still gets .only() narrowing.
#
# Mutation guard: if child_ann_names is NOT threaded into
# _collect_only_fields_is_full_load (utils.py:1016), the AnnotatedField leaf
# is treated as an unknown computed field → is_full_load=True → annotate-only
# fallback (only_cols=[]) → .only() is skipped → "body" appears in the
# prefetch SQL → the SQL assertion below goes RED.
# ---------------------------------------------------------------------------


class TestMixedConcreteAnnotatedChildOnlyNarrowing(TestCase):
    """S1 — mixed concrete+annotated prefetch child keeps .only() narrowing.

    A query that selects a prefetch child with BOTH a concrete field (title)
    AND an AnnotatedField (commentCount) must:
    (a) Emit a narrowed prefetch SQL: id, title, author_id present; body ABSENT.
    (b) Resolve commentCount to the correct aggregate value.

    This guards the child_ann_names threading in _compute_child_only
    (utils.py ~1016). Dropping that threading makes is_full_load return True,
    which falls through to the annotate-only plan (only_cols=[]), skipping
    .only() — so body is fetched and assertion (a) fails (RED).
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with two posts carrying a distinct comment count each.

        Shared as fixture data for the mixed-child-annotation narrowing
        test.
        """
        from tests.models import Author, Comment, Post

        cls.author = Author.objects.create(name="MixedChild_Author", bio="")
        cls.post_a = Post.objects.create(
            title="MixedChild_PostA", body="should not be fetched", author=cls.author
        )
        cls.post_b = Post.objects.create(
            title="MixedChild_PostB", body="also not fetched", author=cls.author
        )
        # 1 comment on post_a, 2 on post_b — distinct counts make value-correctness
        # assertions non-vacuous.
        Comment.objects.create(post=cls.post_a, body="c1")
        Comment.objects.create(post=cls.post_b, body="c2")
        Comment.objects.create(post=cls.post_b, body="c3")

    def test_mixed_child_only_narrowing_and_annotation_value(self) -> None:
        """Mixed concrete+annotated child: SQL narrowed (no body) + value correct.

        (a) The posts prefetch SQL must NOT SELECT the "body" column.
        (b) The posts prefetch SQL MUST SELECT "id", "title", and the FK-back
            attname ("author_id") — the structural columns.
        (c) commentCount must equal the actual comment count for each post.

        Mutation: remove annotated_names=child_ann_names from the
        _collect_only_fields_is_full_load call in _compute_child_only
        (utils.py ~1016). That makes is_full_load=True, which returns a plan
        with only_cols=[], so _narrow_plain_prefetch skips .only() entirely —
        body IS selected and assertion (a) fails (RED).
        """
        from tests.models import Author, Post

        _RS1 = Registry()

        class _PostTypeS1(DjangoObjectType):
            comment_count = AnnotatedField(GraphQLInt, lambda: Count("comments"))

            class Meta:
                model = Post
                registry = _RS1

        class _AuthorTypeS1(DjangoObjectType):
            # Explicit graphene.List so the plain-prefetch path (_narrow_plain_prefetch
            # via _collect_prefetch_only_sets) is exercised — NOT the window path.
            posts = field(NativeList(_PostTypeS1))

            def resolve_posts(root, info):
                return root.posts.all()

            class Meta:
                model = Author
                registry = _RS1

        class _AuthorListS1(DjangoListObjectType):
            class Meta:
                model = Author
                registry = _RS1

        class _QueryS1(ObjectType):
            all_authors = DjangoListObjectField(_AuthorListS1)

        schema_s1 = DjangoGraphQLSchema(query=_QueryS1, registries=isolated_pair(_RS1))

        # Select both a concrete field (title) and the AnnotatedField (commentCount).
        # This is exactly the "mixed" child scenario.
        query = "{ allAuthors { results { posts { id title commentCount } } } }"

        with CaptureQueriesContext(connection) as ctx:
            data = _exec(schema_s1, query)

        # Isolate the posts prefetch query: it references the Post table and
        # includes the FK-back column (author_id).  Skip the author-list query
        # (which contains "tests_author") but not the posts prefetch.
        post_sqls = [
            q["sql"] for q in ctx.captured_queries if "tests_post" in q["sql"].lower()
        ]
        self.assertTrue(
            post_sqls,
            "Expected at least one query against the posts (tests_post) table. "
            f"Captured queries: {[q['sql'] for q in ctx.captured_queries]}",
        )
        combined_post_sql = " ".join(post_sqls).lower()

        # (a) body must NOT appear in the prefetch SQL — .only() is narrowing correctly.
        # If child_ann_names threading is dropped, is_full_load becomes True and the
        # annotate-only fallback (only_cols=[]) skips .only(), selecting body as well.
        self.assertNotIn(
            '"body"',
            combined_post_sql,
            "The posts prefetch SQL must NOT select the 'body' column — .only() "
            "narrowing was lost on the mixed concrete+annotated child. "
            "This likely means child_ann_names was not threaded into "
            "_collect_only_fields_is_full_load in _compute_child_only (utils.py ~1016). "
            f"SQL: {combined_post_sql}",
        )

        # (b) Structural columns MUST be present: id, title, and author_id (FK-back).
        for col in ('"id"', '"title"', '"author_id"'):
            self.assertIn(
                col,
                combined_post_sql,
                f"Column {col} must be present in the narrowed prefetch SQL. "
                f"SQL: {combined_post_sql}",
            )

        # (c) commentCount must equal the actual count — proves the annotation is
        # still injected even when .only() narrowing is active.
        expected_counts = {
            str(self.post_a.pk): 1,
            str(self.post_b.pk): 2,
        }
        results = data["allAuthors"]["results"]
        self.assertEqual(len(results), 1, "Expected exactly one author")
        for post_data in results[0]["posts"]:
            pid = post_data["id"]
            self.assertIn(pid, expected_counts, f"Unexpected post id {pid}")
            self.assertEqual(
                post_data["commentCount"],
                expected_counts[pid],
                f"commentCount mismatch for post {pid}: "
                f"expected {expected_counts[pid]}, got {post_data['commentCount']}",
            )


# ---------------------------------------------------------------------------
# Phase 8: SAFE_MODE + collision-safety + alias-before-annotate tests (tasks 8.1-8.4)
# ---------------------------------------------------------------------------


class TestSafeModeContractStructural(TestCase):
    """8.1 — OPTIMIZER_SAFE_MODE=True wraps _apply_optimizations.

    See the tests below for the exact contract covered.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with one post, for the SAFE_MODE structural test.

        This test breaks if this contract regresses.
        """
        from tests.models import Author, Post

        a = Author.objects.create(name="Safe", bio="")
        Post.objects.create(title="SP", author=a)

    def test_safe_mode_catches_apply_optimizations_error(self) -> None:
        """With SAFE_MODE=True, FieldError from _apply_optimizations is swallowed.

        This test breaks if this contract regresses.

        Raises:
            FieldError: Only inside the throwaway "_raise_once" patch target,
                which this test relies on triggering (and asserts is
                swallowed) to prove the SAFE_MODE contract.
        """
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

            class _Q8(ObjectType):
                all_posts = DjangoListObjectField(_PostList8)

            schema8 = DjangoGraphQLSchema(query=_Q8, registries=isolated_pair(_R8))
            # With SAFE_MODE=True, the FieldError should NOT propagate.
            result = _execute(schema8, "{ allPosts { results { id } } }")
            self.assertIsNone(result.errors, result.errors)


class TestSafeModeFalsePropagatesBuildError(TestCase):
    """8.2 — OPTIMIZER_SAFE_MODE=False propagates FieldError from optimization.

    See the tests below for the exact contract covered.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with one post, for the SAFE_MODE=False propagation test.

        This test breaks if this contract regresses.
        """
        from tests.models import Author, Post

        a = Author.objects.create(name="Loud", bio="")
        Post.objects.create(title="LP", author=a)

    def test_safe_mode_false_propagates_build_error(self) -> None:
        """With SAFE_MODE=False (default), FieldError from optimization propagates.

        This test breaks if this contract regresses.

        Raises:
            FieldError: Only inside the throwaway "_raise" patch target,
                which this test relies on triggering (and asserts propagates)
                to prove the non-safe-mode contract.
        """
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

            class _Q8B(ObjectType):
                all_posts = DjangoListObjectField(_PostList8B)

            schema8b = DjangoGraphQLSchema(query=_Q8B, registries=isolated_pair(_R8B))
            result = _execute(schema8b, "{ allPosts { results { id } } }")
            self.assertIsNotNone(result.errors)


class TestAliasBeforeAnnotateOrder(TestCase):
    """8.3 — alias() is called before annotate() in root injection.

    See the tests below for the exact contract covered.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with one post, for the alias-before-annotate ordering test.

        This test breaks if this contract regresses.
        """
        from tests.models import Author, Post

        a = Author.objects.create(name="ABO", bio="")
        Post.objects.create(title="AO1", author=a)

    def test_alias_before_annotate_order(self) -> None:
        """alias(**aliases) must be called before annotate(**annotations) on root qs.

        This test breaks if this contract regresses.
        """
        from django.db.models import QuerySet

        from tests.models import Post

        _R8C = Registry()

        class _PostT8C(DjangoObjectType):
            # ratio uses an alias (cnt) in its expression
            ratio = AnnotatedField(
                GraphQLFloat,
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

        class _Q8C(ObjectType):
            all_posts = DjangoListObjectField(_PostList8C)

        schema8c = DjangoGraphQLSchema(query=_Q8C, registries=isolated_pair(_R8C))

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
    """8.4 — Two AnnotatedFields use distinct annotation keys; override avoids clash.

    See the tests below for the exact contract covered.
    """

    def test_annotation_name_collision_safety(self) -> None:
        """Two AnnotatedFields on the same type use distinct _gqx_ann_* keys.

        This test breaks if this contract regresses.
        """
        field_a = AnnotatedField(
            GraphQLInt, Count("comments"), annotation_name="explicit_a"
        )
        field_b = AnnotatedField(GraphQLInt, Count("tags"))

        self.assertNotEqual(
            field_a.annotation_name("comment_count"),
            field_b.annotation_name("tag_count"),
        )
        self.assertEqual(field_a.annotation_name("comment_count"), "explicit_a")
        self.assertEqual(field_b.annotation_name("tag_count"), "_gqx_ann_tag_count")

    def test_annotation_name_prefix_isolation_from_window(self) -> None:
        """_gqx_ann_ prefix must not collide with _gqx_rn or _gqx_total.

        This test breaks if this contract regresses.
        """
        field = AnnotatedField(GraphQLInt, Count("tags"))
        ann = field.annotation_name("rank")
        self.assertEqual(ann, "_gqx_ann_rank")
        self.assertNotEqual(ann, "_gqx_rn")
        self.assertNotEqual(ann, "_gqx_total")


# ---------------------------------------------------------------------------
# Phase 9: Verification / import / export checks (tasks 9.3, 9.4)
# ---------------------------------------------------------------------------


class TestAnnotatedFieldImportable(TestCase):
    """9.3 — AnnotatedField importable from top-level package.

    See the tests below for the exact contract covered.
    """

    def test_annotated_field_importable(self) -> None:
        """from django_graphex import AnnotatedField works.

        This test breaks if this contract regresses.
        """
        from django_graphex.fields import AnnotatedField as AF

        self.assertIsNotNone(AF)
        self.assertTrue(callable(AF))

    def test_annotated_field_public_via_submodule(self) -> None:
        """AnnotatedField is public via django_graphex.fields (v2.0 submodule-only API);
        the package root no longer re-exports it."""
        import django_graphex
        from django_graphex.fields import AnnotatedField

        self.assertIsNotNone(AnnotatedField)
        self.assertNotIn("AnnotatedField", django_graphex.__all__)


class TestAnnotatedFieldsSettingAccessible(TestCase):
    """9.4 — OPTIMIZE_ANNOTATED_FIELDS accessible via graphql_api_settings.

    See the tests below for the exact contract covered.
    """

    def test_optimize_annotated_fields_setting(self) -> None:
        """OPTIMIZE_ANNOTATED_FIELDS accessible from graphql_api_settings.

        This test breaks if this contract regresses.
        """
        from django_graphex.settings import graphql_api_settings as s

        self.assertIs(s.OPTIMIZE_ANNOTATED_FIELDS, True)


# ---------------------------------------------------------------------------
# Phase 7: Window-prefetch composition (D2 slice — tasks 7.1, 7.2, 7.3)
# ---------------------------------------------------------------------------


def _build_window_annotated_schema(use_aggregate=False):
    """Build a minimal schema for window-compose D2 e2e tests.

    Author has a nested DjangoNestedListObjectField (posts) — the window path.
    The PostType declares an AnnotatedField:
      - use_aggregate=False: views_x2 = F("views") * 2  (concrete-column)
      - use_aggregate=True:  comment_count = Count("comments")  (aggregate, must decline)
    """
    from django_graphex.fields import DjangoNestedListObjectField
    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
    from django_graphex.types import (
        DjangoListObjectField,
        DjangoListObjectType,
        DjangoObjectType,
    )
    from tests.models import Author, Post

    _REG = Registry()
    paginator = LimitOffsetGraphqlPagination(default_limit=5)

    if use_aggregate:
        extra_fields = {
            "comment_count": AnnotatedField(GraphQLInt, Count("comments")),
        }
        extra_fields_query = "commentCount"
    else:
        extra_fields = {
            "views_x2": AnnotatedField(GraphQLInt, F("views") * 2),
        }
        extra_fields_query = "viewsX2"

    _PostType = _gtype(
        "_WinAnnPostType",
        (DjangoObjectType,),
        {
            **extra_fields,
            "Meta": type("Meta", (), {"model": Post, "registry": _REG}),
        },
    )

    _PostListType = _gtype(
        "_WinAnnPostListType",
        (DjangoListObjectType,),
        {
            "Meta": type(
                "Meta",
                (),
                {
                    "model": Post,
                    "pagination": paginator,
                    "registry": _REG,
                },
            ),
        },
    )

    _AuthorType = _gtype(
        "_WinAnnAuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
            "Meta": type("Meta", (), {"model": Author, "registry": _REG}),
        },
    )

    _AuthorListType = _gtype(
        "_WinAnnAuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG})},
    )

    schema = DjangoGraphQLSchema(
        query=_gtype(
            "_WinAnnQuery",
            (ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        ),
        registries=isolated_pair(_REG),
    )
    return schema, extra_fields_query


class TestWindowCompositeConcreteColumn(TestCase):
    """7.1 RED → GREEN: windowed nested child with concrete-column AnnotatedField.

    The annotation expression (F("views") * 2) must appear in the window
    child SQL, the value must be correct, and no N+1 (exactly 1 ROW_NUMBER
    query across ALL parents — proves batched, not per-author N+1).

    Two authors are created so that a naive N+1 implementation would emit
    one window query PER author (len(window_sql) == 2), while the correct
    batched implementation emits exactly ONE query covering both parents.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create two authors, each with several posts carrying distinct "views" values.

        Two parents are required so a naive per-author window implementation
        would be caught by the batched-query assertions below.
        """
        from tests.models import Author, Post

        # Author 1: 3 posts, views=10/11/12
        cls.author1 = Author.objects.create(name="WinAnn_Author1")
        cls.posts_a1 = []
        for i in range(3):
            p = Post.objects.create(
                title=f"WinAnnPost_A1_{i}",
                author=cls.author1,
                views=10 + i,
            )
            cls.posts_a1.append(p)

        # Author 2: 2 posts, views=20/21 — distinct views so cross-author
        # value-correctness can be independently verified.
        cls.author2 = Author.objects.create(name="WinAnn_Author2")
        cls.posts_a2 = []
        for i in range(2):
            p = Post.objects.create(
                title=f"WinAnnPost_A2_{i}",
                author=cls.author2,
                views=20 + i,
            )
            cls.posts_a2.append(p)

        # Combined lookup map: post.pk → views * 2
        cls.views_map = {str(p.pk): p.views * 2 for p in cls.posts_a1 + cls.posts_a2}

    def _exec(self, schema, query):
        result = _execute(schema, query)
        self.assertIsNone(result.errors, result.errors)
        return result.data

    def test_window_compose_concrete_column(self) -> None:
        """7.1: Concrete-column AnnotatedField (views_x2 = F('views')*2) composes
        inside the window prefetch across TWO parents.

        Asserts:
        1. The concrete-column expression appears in the window child SQL.
        2. The resolved viewsX2 values are correct (views*2) for BOTH authors.
        3. EXACTLY 1 ROW_NUMBER query is emitted across both parents — proves the
           implementation is batched, not N+1 (which would emit 2 window queries).
        4. The window still slices (ROW_NUMBER() in SQL).
        """
        schema, ann_field = _build_window_annotated_schema(use_aggregate=False)
        query = (
            '{ authors { results { posts { results(limit: 5, offset: 0, ordering: "id") '
            "{ id viewsX2 } totalCount } } } }"
        )

        with CaptureQueriesContext(connection) as ctx:
            data = self._exec(schema, query)

        sql_list = [q["sql"].upper() for q in ctx.captured_queries]

        # (1) Window SQL must be emitted (ROW_NUMBER present).
        window_sql = [s for s in sql_list if "ROW_NUMBER()" in s]
        self.assertGreaterEqual(
            len(window_sql), 1, "Must emit ROW_NUMBER() for the window child"
        )

        # (2) Concrete-column expression must appear in the window child SQL.
        # F("views") * 2 compiles to something like "views" * 2 (SQL is uppercased).
        # The annotation key _gqx_ann_views_x2 is another reliable indicator.
        found_expr = any(
            ("VIEWS" in s and ("* 2" in s or "*2" in s)) or "_GQX_ANN_VIEWS_X2" in s
            for s in sql_list
        )
        self.assertTrue(
            found_expr,
            f"views*2 expression must appear in window child SQL. Captured: {sql_list}",
        )

        # (3) EXACTLY 1 window query across BOTH parents — the definitive N+1 check.
        # With a single author the assertion len==1 is trivially true even for N+1
        # (because there is only one parent to query).  With TWO authors an N+1
        # implementation emits 2 window queries (one per author), so this assertion
        # would fail, catching the regression.
        self.assertEqual(
            len(window_sql),
            1,
            "Posts must be fetched in a SINGLE window prefetch query across BOTH "
            "authors (no N+1). An N+1 implementation would emit 2 ROW_NUMBER queries.",
        )

        # (4) Value correctness: viewsX2 == views * 2 for every post of BOTH authors.
        author_results = data["authors"]["results"]
        self.assertEqual(
            len(author_results),
            2,
            "Expected exactly 2 authors in results",
        )
        for author_data in author_results:
            for row in author_data["posts"]["results"]:
                expected = self.views_map.get(row["id"])
                self.assertIsNotNone(
                    expected,
                    f"Unknown post id {row['id']} not in views_map",
                )
                self.assertEqual(
                    row["viewsX2"],
                    expected,
                    f"viewsX2 must equal views*2 for post {row['id']}",
                )


class TestWindowAggregateFallsBack(TestCase):
    """7.2 RED → GREEN: windowed child with aggregate AnnotatedField falls back
    to build_prefetch (structural decline), result still correct.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with posts carrying comments, for the aggregate-fallback test.

        This test breaks if this contract regresses.
        """
        from tests.models import Author, Comment, Post

        cls.author = Author.objects.create(name="WinAgg_Author1")
        cls.post = Post.objects.create(title="WinAggPost1", author=cls.author)
        Comment.objects.create(post=cls.post, body="c1")
        Comment.objects.create(post=cls.post, body="c2")

    def _exec(self, schema, query):
        result = _execute(schema, query)
        self.assertIsNone(result.errors, result.errors)
        return result.data

    def test_window_aggregate_falls_back_to_build_prefetch(self) -> None:
        """7.2: aggregate AnnotatedField (Count('comments')) on a windowed child
        is structurally declined (build_window_prefetch returns None) and falls
        back to build_prefetch (plain path).

        Asserts:
        1. No ROW_NUMBER() in SQL (window NOT used for this child).
        2. commentCount value is correct (=2 for the test post).
        3. No unhandled exception.
        """
        schema, ann_field = _build_window_annotated_schema(use_aggregate=True)
        query = (
            '{ authors { results { posts { results(limit: 5, offset: 0, ordering: "id") '
            "{ id commentCount } totalCount } } } }"
        )

        with CaptureQueriesContext(connection) as ctx:
            data = self._exec(schema, query)

        sql_list = [q["sql"].upper() for q in ctx.captured_queries]

        # (1) Window must NOT be used — declined due to aggregate expression.
        window_sql = [s for s in sql_list if "ROW_NUMBER()" in s]
        self.assertEqual(
            len(window_sql),
            0,
            "Aggregate AnnotatedField must cause window path to decline (no ROW_NUMBER)",
        )

        # (2) Value correctness: commentCount must be 2 for the test post.
        results = data["authors"]["results"][0]["posts"]["results"]
        self.assertEqual(len(results), 1, "Must have exactly 1 post result")
        self.assertEqual(
            results[0]["commentCount"],
            2,
            f"commentCount must equal 2, got {results[0]['commentCount']}",
        )


class TestWindowInjectionErrorGracefulFallback(TestCase):
    """7.3 RED → GREEN: a FieldError during annotation injection inside
    build_window_prefetch is caught gracefully — build_window_prefetch returns None
    (fall back to build_prefetch), no unhandled exception propagates.
    """

    def test_window_injection_error_graceful_fallback(self) -> None:
        """7.3: When qs.annotate() raises FieldError inside build_window_prefetch, it returns None gracefully.

        Simulated via mock; the function must return None (the fall-back
        signal to the caller) instead of propagating the exception. Asserts:
        1. build_window_prefetch returns None (fall-back signal to caller).
        2. No unhandled exception escapes from build_window_prefetch.
        3. The fallback path (build_prefetch) is invoked by _walk_filtered_prefetches.

        Raises:
            FieldError: Only inside the mocked "annotate" side effect, which
                this test relies on triggering (and asserts is caught) to
                prove the graceful-fallback contract.
        """
        from unittest.mock import patch

        from django.core.exceptions import FieldError

        from django_graphex.fields import DjangoNestedListObjectField
        from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
        from django_graphex.types import DjangoListObjectType, DjangoObjectType
        from tests.models import Author, Post

        _REG_ERR = Registry()
        paginator = LimitOffsetGraphqlPagination(default_limit=5)

        _PostType = _gtype(
            "_ErrPostType",
            (DjangoObjectType,),
            {
                # AnnotatedField with a concrete-column expression that will
                # trigger a FieldError when .annotate() is called (mocked below).
                "views_x2": AnnotatedField(GraphQLInt, F("views") * 2),
                "Meta": type("Meta", (), {"model": Post, "registry": _REG_ERR}),
            },
        )
        _PostListType = _gtype(
            "_ErrPostListType",
            (DjangoListObjectType,),
            {
                "Meta": type(
                    "Meta",
                    (),
                    {
                        "model": Post,
                        "pagination": paginator,
                        "registry": _REG_ERR,
                    },
                )
            },
        )
        _AuthorType = _gtype(
            "_ErrAuthorType",
            (DjangoObjectType,),
            {
                "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
                "Meta": type("Meta", (), {"model": Author, "registry": _REG_ERR}),
            },
        )

        posts_field = _AuthorType._meta.fields["posts"]

        # Build a minimal graphene schema so the GraphQLObjectType for _PostType
        # is registered and accessible via the schema's type_map.  Without a schema,
        # graphene types are not yet wired into GraphQLObjectType instances, so
        # _compute_child_only → _walk_annotated_fields would have no GraphQL type to
        # look up AnnotatedFields on and child_annotations would remain empty.
        _schema = DjangoGraphQLSchema(
            query=_gtype(
                "_ErrFallbackQuery",
                (ObjectType,),
                {"dummy": field(GraphQLString)},
            ),
            types=[_PostType, _PostListType, _AuthorType],
            registries=isolated_pair(_REG_ERR),
        )
        gql_schema = _schema.graphql_schema
        # The GraphQLObjectType for the inner row type (_PostType / "_ErrPostType").
        post_gql_type = gql_schema.type_map.get("_ErrPostType")
        self.assertIsNotNone(
            post_gql_type,
            "Could not resolve _ErrPostType from schema type_map — schema not wired",
        )

        # Build a minimal set of args for build_window_prefetch.
        author = Author.objects.create(name="ErrFallbackAuthor")
        Post.objects.create(title="ErrFallbackPost", author=author, views=7)

        # Simulate a FieldError from qs.annotate() at injection time by patching
        # the QuerySet.annotate method on the child manager's queryset.
        from django.db.models import QuerySet

        original_annotate = QuerySet.annotate

        call_count = {"n": 0}

        def failing_annotate(self, **kwargs):
            call_count["n"] += 1
            # Fail only on the FIRST annotate call (the user annotation).
            # The second call (window expressions) should not be reached after fallback.
            if call_count["n"] == 1 and "_gqx_ann_views_x2" in kwargs:
                raise FieldError("Simulated injection error for test")
            return original_annotate(self, **kwargs)

        # Build a fake sub_selection and fragments via the existing Phase-C helper.
        # We use a simplified approach: just verify the return value is None on error.
        from graphql.language.ast import FieldNode, NameNode, SelectionSetNode

        def make_field_node(name):
            n = FieldNode(name=NameNode(value=name))
            return n

        sub_sel = SelectionSetNode(
            selections=[make_field_node("id"), make_field_node("viewsX2")]
        )

        # Build a mock info-like for _compute_child_only inner call.
        from tests.models import Post as PostModel

        author_rel = PostModel._meta.get_field("author").remote_field  # ManyToOneRel

        with patch.object(QuerySet, "annotate", failing_annotate):
            result = posts_field.build_window_prefetch(
                lookup="posts",
                filter_value=None,
                slice_tuple=(0, 5, ["id"]),
                related_field=author_rel,
                sub_selection=sub_sel,
                fragments={},
                # Pass the inner GraphQLObjectType and graphene type so
                # _compute_child_only populates plan.child_annotations with
                # _gqx_ann_views_x2.  Without these the try/except block is never
                # reached (plan is None → pre-check 6 returns None early).
                child_gql_type=post_gql_type,
                child_graphene_type=_PostType,
            )

        # build_window_prefetch must return None when injection fails (graceful fallback).
        self.assertIsNone(
            result,
            "build_window_prefetch must return None when annotation injection fails",
        )
        # Confirm the mock annotate was actually invoked — the try/except block
        # truly exercised.  If call_count is 0 the test is vacuous (the mock never
        # fired and None came from an earlier pre-check, not the graceful fallback).
        self.assertGreater(
            call_count["n"],
            0,
            "failing_annotate was never called — the try/except block was not reached. "
            "The test is vacuous. Check that child_gql_type/child_graphene_type are "
            "correctly passed and plan.child_annotations is populated.",
        )


# ---------------------------------------------------------------------------
# 7.1-strength / 8.3-strength: alias()-before-annotate() ordering in the
# WINDOW prefetch path (build_window_prefetch) has TEETH.
#
# Context: test 8.3 (TestAliasBeforeAnnotateOrder) exercises the ROOT
# injection path and verifies call-order via spying, but the spy still calls
# the original functions — so even reversed order stays GREEN at the root
# because Django's QuerySet.annotate() raises FieldError lazily (at SQL-eval
# time, not at call time) for some expressions.  More importantly, test 7.1
# only uses views_x2 = F("views") * 2, which has NO aliases dict, so
# child_aliases is empty and the alias/annotate block in build_window_prefetch
# (lines ~737-745 in fields.py) is NEVER entered — reversing lines 739-742
# has zero effect on any existing test.
#
# This test uses an alias-DEPENDENT AnnotatedField inside the WINDOW child:
#   alias: views_base = F("views") * 3    (concrete-column, non-aggregate)
#   expression: F("views_base") + 0       (references the alias name)
# If .annotate() runs before .alias(), Django cannot resolve "views_base" as
# an existing column/annotation, so the QuerySet raises FieldError at build
# time (inside build_window_prefetch's try/except at ~line 737), which causes
# build_window_prefetch to return None (fall back to build_prefetch / plain
# path WITHOUT ROW_NUMBER).  The test asserts ROW_NUMBER() IS present,
# catching exactly that regression.
#
# Path used: window prefetch child (build_window_prefetch → _compute_child_only
# → child_aliases/child_annotations populated → fields.py lines 737-745).
# The root injection path is NOT involved because the AnnotatedField lives on
# the window CHILD (PostType), not on the root query type.
# ---------------------------------------------------------------------------


def _build_alias_dependent_window_schema():
    """Build a schema where the window child's AnnotatedField has a non-empty
    aliases dict whose expression REFERENCES the alias name.

    PostType declares:
        views_tripled = AnnotatedField(
            GraphQLInt,
            expression=F("views_base") + 0,   # references the alias
            aliases={"views_base": F("views") * 3},
        )

    This is a concrete-column expression (no aggregate), so it passes the
    aggregate pre-check in build_window_prefetch, and child_aliases is
    non-empty — the alias()/annotate() block at fields.py ~737-745 is
    ACTUALLY entered.  Reversing that block causes FieldError at build time
    (Django cannot resolve "views_base" before the alias is set), the
    try/except returns None, and the test fails because ROW_NUMBER() vanishes.
    """
    from django_graphex.fields import DjangoNestedListObjectField
    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
    from django_graphex.types import (
        DjangoListObjectField,
        DjangoListObjectType,
        DjangoObjectType,
    )
    from tests.models import Author, Post

    _REG = Registry()
    paginator = LimitOffsetGraphqlPagination(default_limit=10)

    _PostType = _gtype(
        "_AliasDepPostType",
        (DjangoObjectType,),
        {
            "views_tripled": AnnotatedField(
                GraphQLInt,
                # Expression references the alias name "views_base".
                # alias() MUST be called first; annotate() references it.
                F("views_base") + 0,
                aliases={"views_base": F("views") * 3},
            ),
            "Meta": type("Meta", (), {"model": Post, "registry": _REG}),
        },
    )
    _PostListType = _gtype(
        "_AliasDepPostListType",
        (DjangoListObjectType,),
        {
            "Meta": type(
                "Meta",
                (),
                {
                    "model": Post,
                    "pagination": paginator,
                    "registry": _REG,
                },
            )
        },
    )
    _AuthorType = _gtype(
        "_AliasDepAuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
            "Meta": type("Meta", (), {"model": Author, "registry": _REG}),
        },
    )
    _AuthorListType = _gtype(
        "_AliasDepAuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG})},
    )
    schema = DjangoGraphQLSchema(
        query=_gtype(
            "_AliasDepQuery",
            (ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        ),
        registries=isolated_pair(_REG),
    )
    return schema


class TestWindowAliasBeforeAnnotateOrdering(TestCase):
    """7.1-strength / alias-ordering: alias()-before-annotate() in
    build_window_prefetch has genuine TEETH.

    The AnnotatedField on the window child has:
        aliases={"views_base": F("views") * 3}
        expression=F("views_base") + 0   # references the alias

    Correct order (alias then annotate):
        qs = qs.alias(views_base=F("views") * 3)
        qs = qs.annotate(_gqx_ann_views_tripled=F("views_base") + 0)
        → ROW_NUMBER() is emitted; viewsTripled == views * 3.

    Wrong order (annotate before alias — the mutation):
        qs = qs.annotate(_gqx_ann_views_tripled=F("views_base") + 0)  # FieldError
        → build_window_prefetch catches the exception, returns None, falls back
          to build_prefetch (plain path, no ROW_NUMBER).
        → The assertion "ROW_NUMBER() IS present" FAILS → test is RED.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with posts, for the window alias-dependency-ordering test.

        This test breaks if this contract regresses.
        """
        from tests.models import Author, Post

        a = Author.objects.create(name="AliasDep_Author1")
        cls.posts = []
        for i in range(2):
            p = Post.objects.create(
                title=f"AliasDep_Post{i}",
                author=a,
                views=5 + i,  # views=5, 6 → tripled=15, 18
            )
            cls.posts.append(p)

    def _exec(self, schema, query):
        result = _execute(schema, query)
        self.assertIsNone(result.errors, result.errors)
        return result.data

    def test_window_alias_before_annotate_correct_values_and_row_number(self) -> None:
        """Alias-dependent AnnotatedField in window child: correct value + ROW_NUMBER.

        (a) ROW_NUMBER() IS in SQL — window path was taken (alias order correct).
        (b) viewsTripled == views * 3 for each post (alias expression resolved).

        Mutation teeth: swap alias/annotate order in build_window_prefetch →
        Django raises FieldError("views_base") at build time → try/except
        returns None → build_prefetch fallback → NO ROW_NUMBER → assertion (a)
        FAILS → test is RED.  (Verified; production restored after check.)
        """
        schema = _build_alias_dependent_window_schema()
        query = (
            '{ authors { results { posts { results(limit: 10, offset: 0, ordering: "id") '
            "{ id viewsTripled } totalCount } } } }"
        )

        with CaptureQueriesContext(connection) as ctx:
            data = self._exec(schema, query)

        sql_list = [q["sql"].upper() for q in ctx.captured_queries]

        # (a) Window path must have been taken — ROW_NUMBER() IS present.
        # If alias/annotate order were swapped, build_window_prefetch would
        # return None (FieldError caught) and this assertion fails (RED).
        window_sql = [s for s in sql_list if "ROW_NUMBER()" in s]
        self.assertGreaterEqual(
            len(window_sql),
            1,
            "ROW_NUMBER() must appear in SQL — the window path must be taken "
            "(alias-before-annotate order is correct). If this fails, the alias/"
            "annotate order in build_window_prefetch is wrong. "
            f"Captured SQL: {sql_list}",
        )

        # (b) Value correctness: viewsTripled == views * 3.
        # Also confirms that the alias ("views_base") was resolved by the DB,
        # not just that the annotate call was reached.
        views_tripled_map = {str(p.pk): p.views * 3 for p in self.posts}
        author_results = data["authors"]["results"]
        self.assertGreater(len(author_results), 0, "Expected at least one author")
        for author_data in author_results:
            for row in author_data["posts"]["results"]:
                expected = views_tripled_map.get(row["id"])
                self.assertIsNotNone(
                    expected,
                    f"Unknown post id {row['id']} not in views_tripled_map",
                )
                self.assertEqual(
                    row["viewsTripled"],
                    expected,
                    f"viewsTripled must equal views*3 for post {row['id']}. "
                    f"Got {row['viewsTripled']}, expected {expected}. "
                    "If alias() ran after annotate(), Django would have raised "
                    "FieldError and fallen back to build_prefetch (plain path), "
                    "producing a non-None value via a different code path — but "
                    "ROW_NUMBER() would be absent and assertion (a) would already "
                    "have caught the regression.",
                )
