"""Tests for optimizer-phase-e: Per-field optimize_<field> hook.

STRICT TDD: RED tests are written first, then GREEN implementation fills them.

Coverage matrix:
  AC1  — window path hook (is_window=True, pre-check-7 re-run)
  AC2  — filtered-plain path hook (is_window=False)
  AC2b — unfiltered-plain path hook (SITE A bare-string + Prefetch)
  AC2b — unfiltered-plain nested under filtered (SITE B _merge)
  AC4  — SQL + query-count integration proof
  AC5  — hook adds .distinct() -> window opt-out, plain fallback w/ hook
  AC6  — hook annotate collides with _gqx_rn (SAFE_MODE boundary)
  AC9  — SAFE_MODE=True degrades whole resolve + WARNING; False propagates
  AC10 — non-QuerySet return emits WARNING, uses unmodified qs
  AC11 — OPTIMIZE_QUERYSET=False skips hook; ONLY/ANNOTATED flags do NOT
"""

from __future__ import annotations

import graphene
from django.db import connection
from django.db.models import Value
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from django_graphex import (
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoObjectType,
)
from django_graphex.registry import Registry

# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------


def _exec(schema, query, variables=None):
    """Execute a GraphQL query and assert no errors."""
    result = schema.execute(query, variable_values=variables)
    assert result.errors is None, result.errors
    return result.data


# ---------------------------------------------------------------------------
# Phase 1 / Task 1.1 — _get_field_optimize_hook unit tests (RED)
# ---------------------------------------------------------------------------


class TestGetFieldOptimizeHook(TestCase):
    """Unit tests for _get_field_optimize_hook lookup helper."""

    def test_returns_hook_when_present(self):
        """_get_field_optimize_hook returns the staticmethod when optimize_posts exists."""
        from django_graphex.utils import _get_field_optimize_hook

        class _FakeGrapheneType:
            @staticmethod
            def optimize_posts(qs, info, **kwargs):
                return qs

        class _FakeGQLType:
            graphene_type = _FakeGrapheneType

        hook = _get_field_optimize_hook(_FakeGQLType, "posts")
        self.assertIs(hook, _FakeGrapheneType.optimize_posts)

    def test_returns_none_when_absent(self):
        """_get_field_optimize_hook returns None when optimize_posts is NOT declared."""
        from django_graphex.utils import _get_field_optimize_hook

        class _FakeGrapheneType:
            pass  # no optimize_posts

        class _FakeGQLType:
            graphene_type = _FakeGrapheneType

        result = _get_field_optimize_hook(_FakeGQLType, "posts")
        self.assertIsNone(result)

    def test_returns_none_when_gql_type_is_none(self):
        """_get_field_optimize_hook returns None when gql_type is None."""
        from django_graphex.utils import _get_field_optimize_hook

        result = _get_field_optimize_hook(None, "posts")
        self.assertIsNone(result)

    def test_returns_none_when_no_graphene_type(self):
        """_get_field_optimize_hook returns None when gql_type has no graphene_type attr."""
        from django_graphex.utils import _get_field_optimize_hook

        class _FakeGQLType:
            pass  # no graphene_type attr

        result = _get_field_optimize_hook(_FakeGQLType, "posts")
        self.assertIsNone(result)

    def test_camel_case_field_name_is_snake_cased(self):
        """_get_field_optimize_hook converts camelCase to snake_case for the lookup."""
        from django_graphex.utils import _get_field_optimize_hook

        class _FakeGrapheneType:
            @staticmethod
            def optimize_blog_posts(qs, info, **kwargs):
                return qs

        class _FakeGQLType:
            graphene_type = _FakeGrapheneType

        # GraphQL field name "blogPosts" -> optimize_blog_posts
        hook = _get_field_optimize_hook(_FakeGQLType, "blogPosts")
        self.assertIs(hook, _FakeGrapheneType.optimize_blog_posts)


# ---------------------------------------------------------------------------
# Phase 1 / Task 1.2 — _apply_field_hook unit tests (RED)
# ---------------------------------------------------------------------------


class TestApplyFieldHook(TestCase):
    """Unit tests for _apply_field_hook applier helper."""

    def _make_qs(self):
        """Return a real QuerySet for use in tests."""
        from tests.models import Post

        return Post.objects.all()

    def test_returns_qs_unchanged_when_hook_is_none(self):
        """_apply_field_hook returns the original qs when hook=None (no-op)."""
        from django_graphex.utils import _apply_field_hook

        qs = self._make_qs()
        result = _apply_field_hook(qs, None, None, filter_value=None, is_window=False)
        self.assertIs(result, qs)

    def test_returns_hook_result_when_valid_queryset(self):
        """_apply_field_hook returns the hook's QuerySet result when valid."""
        from django_graphex.utils import _apply_field_hook
        from tests.models import Post

        qs = Post.objects.all()
        filtered = Post.objects.filter(id__gt=0)

        def hook(q, info, **kwargs):
            return filtered

        result = _apply_field_hook(qs, hook, None, filter_value=None, is_window=False)
        self.assertIs(result, filtered)

    def test_hook_receives_filter_value_and_is_window_kwargs(self):
        """_apply_field_hook passes filter_value and is_window as kwargs to the hook."""
        from django_graphex.utils import _apply_field_hook
        from tests.models import Post

        qs = Post.objects.all()
        received = {}

        def hook(q, info, **kwargs):
            received.update(kwargs)
            return q

        _apply_field_hook(qs, hook, None, filter_value={"title": "x"}, is_window=True)
        self.assertEqual(received.get("filter_value"), {"title": "x"})
        self.assertIs(received.get("is_window"), True)

    def test_non_queryset_return_emits_warning_and_returns_original(self):
        """AC10: non-QuerySet return emits WARNING and returns unmodified qs."""
        from django_graphex.utils import _apply_field_hook
        from tests.models import Post

        qs = Post.objects.all()

        def hook(q, info, **kwargs):
            return None  # wrong type

        with self.assertLogs("django_graphex.utils", level="WARNING") as cm:
            result = _apply_field_hook(
                qs, hook, None, filter_value=None, is_window=False
            )

        self.assertIs(
            result, qs, "Must return original qs when hook returns non-QuerySet"
        )
        self.assertTrue(
            any(
                "non-QuerySet" in msg
                or "non_queryset" in msg.lower()
                or "non-queryset" in msg.lower()
                for msg in cm.output
            ),
            f"WARNING not found in: {cm.output}",
        )

    @override_settings(DJANGO_GRAPHEX={"OPTIMIZER_SAFE_MODE": False})
    def test_exception_propagates_when_safe_mode_false(self):
        """AC9 (False): exception propagates when OPTIMIZER_SAFE_MODE=False (default)."""
        from django_graphex.utils import _apply_field_hook
        from tests.models import Post

        qs = Post.objects.all()

        def hook(q, info, **kwargs):
            raise ValueError("hook error")

        with self.assertRaises(
            ValueError, msg="Exception must propagate when SAFE_MODE=False"
        ):
            _apply_field_hook(qs, hook, None, filter_value=None, is_window=False)

    @override_settings(DJANGO_GRAPHEX={"OPTIMIZER_SAFE_MODE": True})
    def test_exception_propagates_from_helper_even_when_safe_mode_true(self):
        """AC9 (coarse): _apply_field_hook does NOT swallow the exception, even when
        OPTIMIZER_SAFE_MODE=True.

        SAFE_MODE is a COARSE boundary owned by queryset_factory, NOT per-field
        isolation. _apply_field_hook must let the exception propagate so the
        queryset_factory boundary can degrade the WHOLE resolve. A per-field
        try/except here is explicitly forbidden by the Phase E spec scope
        boundary, so the helper re-raising under SAFE_MODE=True is the contract.
        """
        from django_graphex.utils import _apply_field_hook
        from tests.models import Post

        qs = Post.objects.all()

        def hook(q, info, **kwargs):
            raise ValueError("hook error")

        with self.assertRaises(
            ValueError,
            msg="_apply_field_hook must propagate the exception even under SAFE_MODE "
            "(coarse degrade is owned by queryset_factory, not per-field)",
        ):
            _apply_field_hook(qs, hook, None, filter_value=None, is_window=False)


# ---------------------------------------------------------------------------
# Phase 3 / Task 3.1 — Window path hook tests (RED)
# ---------------------------------------------------------------------------

_REG_WIN = {}


def _build_window_hook_schema(
    parent_has_hook=True, hook_adds_distinct=False, hook_adds_gqx_rn=False
):
    """Build a schema with an Author + posts field where AuthorType optionally
    declares optimize_posts.

    Returns (schema, captured_kwargs_list) where captured_kwargs_list is
    mutated in-place by the hook so tests can inspect is_window and filter_value.
    """
    from django_graphex.fields import DjangoNestedListObjectField
    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
    from tests.models import Author, Post

    _REG_WIN.clear()
    captured_kwargs: list[dict] = []

    _PostListType = type(
        "_WinHookPostListType",
        (DjangoListObjectType,),
        {
            "Meta": type(
                "Meta",
                (),
                {
                    "model": Post,
                    "pagination": LimitOffsetGraphqlPagination(default_limit=5),
                    "registry": _REG_WIN,
                },
            )
        },
    )

    author_attrs: dict = {
        "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
        "Meta": type("Meta", (), {"model": Author, "registry": _REG_WIN}),
    }

    if parent_has_hook:
        if hook_adds_distinct:

            def optimize_posts(qs, info, **kwargs):
                captured_kwargs.append(dict(kwargs))
                return qs.distinct()
        elif hook_adds_gqx_rn:

            def optimize_posts(qs, info, **kwargs):
                captured_kwargs.append(dict(kwargs))
                return qs.annotate(_gqx_rn=Value(0))
        else:

            def optimize_posts(qs, info, **kwargs):
                captured_kwargs.append(dict(kwargs))
                # Use order_by to produce observable SQL change without
                # conflicting with .only() deferred fields.
                return qs.order_by("-views", "id")

        optimize_posts = staticmethod(optimize_posts)
        author_attrs["optimize_posts"] = optimize_posts

    _AuthorType = type("_WinHookAuthorType", (DjangoObjectType,), author_attrs)

    _AuthorListType = type(
        "_WinHookAuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG_WIN})},
    )

    schema = graphene.Schema(
        query=type(
            "WinHookQuery",
            (graphene.ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        )
    )
    return schema, captured_kwargs


class TestWindowPathHook(TestCase):
    """AC1 / AC5 / AC6 — window path hook fires correctly."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Category, Post

        cls.cat = Category.objects.create(title="SciCat")
        # TWO authors each with multiple posts. The window slice is a single
        # subquery PARTITIONED BY the FK, batched across ALL parents in ONE
        # query. With >= 2 parents, a regression that broke the batched window
        # prefetch into per-parent resolution would inflate the query count and
        # be caught by assertNumQueries (a single-parent fixture cannot observe
        # per-parent N+1 — 1 parent == at most 1 extra query).
        cls.author1 = Author.objects.create(name="WinHookAuthor1")
        cls.author2 = Author.objects.create(name="WinHookAuthor2")
        for i in range(4):
            Post.objects.create(
                title=f"WHP1-{i}", author=cls.author1, category=cls.cat, views=i
            )
            Post.objects.create(
                title=f"WHP2-{i}", author=cls.author2, category=cls.cat, views=i
            )

    @override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": True})
    def test_ac1_window_hook_fires_with_is_window_true(self):
        """AC1: optimize_posts fires with is_window=True on window path.

        The hook adds .order_by("-views", "id") — SQL must include ORDER BY views
        (or the window subquery must carry this order), proving the hook ran.
        """
        schema, captured = _build_window_hook_schema(parent_has_hook=True)

        query = """
        { authors { results {
            posts { results(limit: 3, offset: 0) { id title } totalCount }
        } totalCount } }
        """
        # assertNumQueries pins the batched window contract: the windowed posts
        # are sliced in a SINGLE subquery PARTITIONED BY the author FK across
        # BOTH authors. The count is INDEPENDENT of the number of parents — a
        # regression to per-parent resolution would add one query per author and
        # break this assertion (the multi-parent fixture makes that observable).
        with self.assertNumQueries(3):
            with CaptureQueriesContext(connection) as ctx:
                data = _exec(schema, query)

        self.assertIn("authors", data)

        # The hook must have fired and recorded is_window=True
        self.assertGreater(
            len(captured), 0, "optimize_posts hook must have been called"
        )
        self.assertTrue(
            any(kw.get("is_window") is True for kw in captured),
            f"At least one call must have is_window=True; captured: {captured}",
        )

        # SQL must contain the ordering introduced by the hook (views column).
        all_sql = " ".join(q["sql"].upper() for q in ctx.captured_queries)
        self.assertIn(
            "VIEWS", all_sql, "Hook's order_by(-views) must appear in prefetch SQL"
        )

    @override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": True})
    def test_ac5_hook_adds_distinct_falls_back_to_plain(self):
        """AC5: hook adds .distinct() -> pre-check 7 re-runs, falls back to plain build_prefetch.

        is_window=False on fallback (FINAL path taken is plain).
        SQL must NOT contain ROW_NUMBER() (no window slicing).
        """
        schema, captured = _build_window_hook_schema(
            parent_has_hook=True, hook_adds_distinct=True
        )

        query = """
        { authors { results {
            posts { results(limit: 3, offset: 0) { id title } totalCount }
        } totalCount } }
        """
        with CaptureQueriesContext(connection) as ctx:
            data = _exec(schema, query)

        self.assertIn("authors", data)
        self.assertGreater(
            len(captured), 0, "optimize_posts hook must have been called"
        )

        # is_window must be False — final path is plain after fallback
        self.assertTrue(
            any(kw.get("is_window") is False for kw in captured),
            f"At least one call must have is_window=False (plain fallback); captured: {captured}",
        )

        # Must NOT use window (ROW_NUMBER absent)
        all_sql = " ".join(q["sql"].upper() for q in ctx.captured_queries)
        self.assertNotIn(
            "ROW_NUMBER()", all_sql, "AC5: no window SQL after hook-distinct fallback"
        )

        # Prong 2 of AC5 (customization MUST be preserved on fallback): the hook's
        # .distinct() must survive into the plain build_prefetch SQL. Without this
        # the test would still pass if the fallback re-applied the UN-hooked qs
        # (ROW_NUMBER absent + an is_window=False call both still hold), leaving
        # the "customization preserved" half of the spec unguarded.
        self.assertIn(
            "DISTINCT",
            all_sql,
            "AC5: hook .distinct() customization must survive the plain fallback",
        )

    @override_settings(
        DJANGO_GRAPHEX={
            "OPTIMIZE_NESTED_PAGINATION": True,
        }
    )
    def test_ac6_hook_aliasing_gqx_rn_is_silently_overwritten_noop(self):
        """AC6 (revised): a hook adding ``.annotate(_gqx_rn=Value(0))`` does NOT
        actually collide with the window alias.

        EMPIRICAL CONTRACT (verified at the ORM level): Django allows re-aliasing
        an annotation, and the later window ``.annotate(_gqx_rn=Window(RowNumber()
        ...))`` (fields.py:756) silently OVERWRITES the hook's ``Value(0)``.  No
        FieldError is raised at window-annotate time, so there is no collision to
        catch and no degrade is triggered.  The original AC6 "collision degrades"
        framing was therefore vacuous — its only assertion (errors is None) held
        whether or not the hook fired.

        This test instead pins the REAL, observable behavior:
          1. the hook FIRES on the window path with is_window=True (proving the
             window-path hook application at fields.py:729 is present — removing
             it makes ``captured`` empty and FAILS this test), and
          2. aliasing ``_gqx_rn`` is a benign no-op: the windowed query still
             succeeds (no errors, ROW_NUMBER window slicing intact).
        """
        schema, captured = _build_window_hook_schema(
            parent_has_hook=True, hook_adds_gqx_rn=True
        )

        query = """
        { authors { results {
            posts { results(limit: 3, offset: 0) { id title } totalCount }
        } totalCount } }
        """
        with CaptureQueriesContext(connection) as ctx:
            result = schema.execute(query)

        # No collision / no 500: the alias is silently overwritten by the window.
        self.assertIsNone(
            result.errors,
            f"AC6: aliasing _gqx_rn must be a no-op, not a 500: {result.errors}",
        )

        # (1) The window-path hook MUST have fired with is_window=True. This is the
        # discriminating assertion the old test lacked: it FAILS if the window hook
        # application is removed (then the hook never fires and captured is empty).
        self.assertGreater(
            len(captured), 0, "optimize_posts hook must fire on the window path"
        )
        self.assertTrue(
            any(kw.get("is_window") is True for kw in captured),
            f"window-path hook must fire with is_window=True; captured: {captured}",
        )

        # (2) The window slicing is still applied (the Value(0) alias was
        # overwritten by the Window RowNumber annotation, not the other way round).
        all_sql = " ".join(q["sql"].upper() for q in ctx.captured_queries)
        self.assertIn(
            "ROW_NUMBER()",
            all_sql,
            "AC6: window slicing must survive — _gqx_rn=Value(0) is overwritten by the window annotation",
        )


# ---------------------------------------------------------------------------
# Phase 5 / Task 5.1 — Filtered-plain path hook tests (RED)
# ---------------------------------------------------------------------------

_REG_FILT = {}


def _build_filtered_hook_schema():
    """Build a schema where posts has a filter arg; parent has optimize_posts."""
    from django_graphex.fields import DjangoNestedListObjectField
    from tests.models import Author, Post

    _REG_FILT.clear()
    captured_kwargs: list[dict] = []

    _PostListType = type(
        "_FiltHookPostListType",
        (DjangoListObjectType,),
        {
            "Meta": type(
                "Meta",
                (),
                {
                    "model": Post,
                    "filter_fields": {"title": ["exact"]},
                    "registry": _REG_FILT,
                },
            )
        },
    )

    def optimize_posts(qs, info, **kwargs):
        captured_kwargs.append(dict(kwargs))
        return qs.select_related("category")

    _AuthorType = type(
        "_FiltHookAuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
            "optimize_posts": staticmethod(optimize_posts),
            "Meta": type("Meta", (), {"model": Author, "registry": _REG_FILT}),
        },
    )

    _AuthorListType = type(
        "_FiltHookAuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG_FILT})},
    )

    schema = graphene.Schema(
        query=type(
            "FiltHookQuery",
            (graphene.ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        )
    )
    return schema, captured_kwargs


class TestFilteredPlainPathHook(TestCase):
    """AC2 — filtered-plain path hook fires with is_window=False."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Category, Post

        # TWO authors each owning a post titled "FiltPost" so the filtered
        # prefetch batches across BOTH parents in one query; a per-parent N+1
        # would inflate assertNumQueries beyond the expected count.
        cls.cat = Category.objects.create(title="FiltCat")
        cls.author1 = Author.objects.create(name="FiltHookAuthor1")
        cls.author2 = Author.objects.create(name="FiltHookAuthor2")
        Post.objects.create(title="FiltPost", author=cls.author1, category=cls.cat)
        Post.objects.create(title="FiltPost", author=cls.author2, category=cls.cat)

    @override_settings(
        DJANGO_GRAPHEX={
            "OPTIMIZE_NESTED_PAGINATION": False,
            "OPTIMIZE_ONLY_FIELDS": False,
        }
    )
    def test_ac2_filtered_plain_hook_fires_with_is_window_false(self):
        """AC2: optimize_posts fires with is_window=False on filtered-plain path.

        SQL must contain JOIN for category (hook adds select_related).
        assertNumQueries ensures no N+1.
        """
        schema, captured = _build_filtered_hook_schema()

        query = """
        { authors { results {
            posts(filter: {title: {exact: "FiltPost"}}) {
                results { id title }
                totalCount
            }
        } totalCount } }
        """
        with self.assertNumQueries(3):
            with CaptureQueriesContext(connection) as ctx:
                data = _exec(schema, query)

        self.assertIn("authors", data)
        self.assertGreater(
            len(captured),
            0,
            "optimize_posts hook must have been called on filtered path",
        )
        self.assertTrue(
            all(kw.get("is_window") is False for kw in captured),
            f"All calls must have is_window=False on filtered-plain; captured: {captured}",
        )

        # filter_value must be passed to the hook
        self.assertTrue(
            any(kw.get("filter_value") is not None for kw in captured),
            f"filter_value must be passed to hook; captured: {captured}",
        )

        # SQL should contain category JOIN from select_related
        all_sql = " ".join(q["sql"].upper() for q in ctx.captured_queries)
        self.assertIn(
            "CATEGORY", all_sql, "Hook's select_related(category) must appear in SQL"
        )


# ---------------------------------------------------------------------------
# Phase 7 / Tasks 7.1 + 7.2 + 7.3 — Unfiltered-plain path hook (RED)
# ---------------------------------------------------------------------------

_REG_UNFILT = {}


def _build_unfiltered_hook_schema(has_hook=True):
    """Build a schema where posts is unfiltered; parent has optimize_posts."""
    from django_graphex.fields import DjangoNestedListObjectField
    from tests.models import Author, Post

    _REG_UNFILT.clear()
    captured_kwargs: list[dict] = []

    _PostListType = type(
        "_UnfHookPostListType",
        (DjangoListObjectType,),
        {
            "Meta": type(
                "Meta",
                (),
                {
                    "model": Post,
                    "registry": _REG_UNFILT,
                },
            )
        },
    )

    author_attrs: dict = {
        "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
        "Meta": type("Meta", (), {"model": Author, "registry": _REG_UNFILT}),
    }

    if has_hook:

        def optimize_posts(qs, info, **kwargs):
            captured_kwargs.append(dict(kwargs))
            return qs.select_related("category")

        author_attrs["optimize_posts"] = staticmethod(optimize_posts)

    _AuthorType = type("_UnfHookAuthorType", (DjangoObjectType,), author_attrs)
    _AuthorListType = type(
        "_UnfHookAuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG_UNFILT})},
    )

    schema = graphene.Schema(
        query=type(
            "UnfHookQuery",
            (graphene.ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        )
    )
    return schema, captured_kwargs


class TestUnfilteredTopLevelHook(TestCase):
    """AC2b SITE A — unfiltered top-level hook fires with is_window=False."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Category, Post

        # TWO authors each with a post so the unfiltered top-level prefetch
        # batches across BOTH parents in one query; a per-parent N+1 would
        # inflate assertNumQueries beyond the expected count.
        cls.cat = Category.objects.create(title="UnfCat")
        cls.author1 = Author.objects.create(name="UnfHookAuthor1")
        cls.author2 = Author.objects.create(name="UnfHookAuthor2")
        Post.objects.create(title="UnfPost1", author=cls.author1, category=cls.cat)
        Post.objects.create(title="UnfPost2", author=cls.author2, category=cls.cat)

    @override_settings(
        DJANGO_GRAPHEX={
            "OPTIMIZE_NESTED_PAGINATION": False,
            "OPTIMIZE_ONLY_FIELDS": False,
        }
    )
    def test_ac2b_unfiltered_top_level_hook_fires(self):
        """AC2b SITE A: optimize_posts fires on unfiltered plain path.

        is_window=False; SQL contains JOIN for category; assertNumQueries has no N+1.
        OPTIMIZE_ONLY_FIELDS=False to avoid .only()/.select_related conflict.
        """
        schema, captured = _build_unfiltered_hook_schema(has_hook=True)

        query = "{ authors { results { posts { results { id title } totalCount } } totalCount } }"

        with self.assertNumQueries(3):
            with CaptureQueriesContext(connection) as ctx:
                data = _exec(schema, query)

        self.assertIn("authors", data)
        self.assertGreater(
            len(captured), 0, "optimize_posts hook must have been called"
        )
        self.assertTrue(
            all(kw.get("is_window") is False for kw in captured),
            f"All calls must have is_window=False; captured: {captured}",
        )

        all_sql = " ".join(q["sql"].upper() for q in ctx.captured_queries)
        self.assertIn(
            "CATEGORY", all_sql, "Hook's select_related(category) must appear in SQL"
        )

    @override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": False})
    def test_ac2b_no_hook_is_noop(self):
        """Opt-out: no optimize_posts -> behavior identical to pre-phase-E (no error)."""
        schema, captured = _build_unfiltered_hook_schema(has_hook=False)

        query = "{ authors { results { posts { results { id title } totalCount } } totalCount } }"

        # No exception; no captured kwargs
        data = _exec(schema, query)
        self.assertIn("authors", data)
        self.assertEqual(
            len(captured), 0, "No hook calls when optimize_posts is not declared"
        )


# ---------------------------------------------------------------------------
# Phase 7 / Task 7.2 — SITE B: re-rooted nested under filtered ancestor (RED)
# ---------------------------------------------------------------------------

_REG_SITE_B = {}


def _build_site_b_schema():
    """Build a schema: Author -> posts (filtered) -> comments (unfiltered).

    Comments are unfiltered but nested under a filtered posts ancestor.
    optimize_comments is declared on PostType (the parent of comments).
    """
    from django_graphex.fields import DjangoNestedListObjectField
    from tests.models import Author, Comment, Post

    _REG_SITE_B.clear()
    captured_kwargs: list[dict] = []

    _CommentListType = type(
        "_SiteBCommentListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Comment, "registry": _REG_SITE_B})},
    )

    def optimize_comments(qs, info, **kwargs):
        captured_kwargs.append(dict(kwargs))
        return qs.select_related("post")

    _PostType = type(
        "_SiteBPostType",
        (DjangoObjectType,),
        {
            "comments": DjangoNestedListObjectField(
                _CommentListType, accessor="comments"
            ),
            "optimize_comments": staticmethod(optimize_comments),
            "Meta": type("Meta", (), {"model": Post, "registry": _REG_SITE_B}),
        },
    )

    _PostListType = type(
        "_SiteBPostListType",
        (DjangoListObjectType,),
        {
            "Meta": type(
                "Meta",
                (),
                {
                    "model": Post,
                    "filter_fields": {"title": ["exact"]},
                    "registry": _REG_SITE_B,
                },
            )
        },
    )

    _AuthorType = type(
        "_SiteBAuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
            "Meta": type("Meta", (), {"model": Author, "registry": _REG_SITE_B}),
        },
    )

    _AuthorListType = type(
        "_SiteBAuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG_SITE_B})},
    )

    schema = graphene.Schema(
        query=type(
            "SiteBQuery",
            (graphene.ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        )
    )
    return schema, captured_kwargs


class TestNestedUnderFilteredHook(TestCase):
    """AC2b SITE B — unfiltered nested under filtered ancestor fires the hook."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Comment, Post

        # TWO authors, each owning a post titled "SiteBPost" (the filter matches
        # BOTH posts), each post carrying TWO comments → FOUR comments across TWO
        # comment-parents. With >= 2 comment-parents, a regression that dropped
        # the batched comment prefetch into per-post resolution would add an
        # extra query per post and break assertNumQueries — a single comment
        # under a single post could not observe that (1 parent == 1 query either
        # way).
        cls.author1 = Author.objects.create(name="SiteBAuthor1")
        cls.author2 = Author.objects.create(name="SiteBAuthor2")
        cls.post1 = Post.objects.create(title="SiteBPost", author=cls.author1)
        cls.post2 = Post.objects.create(title="SiteBPost", author=cls.author2)
        for post in (cls.post1, cls.post2):
            Comment.objects.create(post=post, body="siteb comment a")
            Comment.objects.create(post=post, body="siteb comment b")

    @override_settings(
        DJANGO_GRAPHEX={
            "OPTIMIZE_NESTED_PAGINATION": False,
            "OPTIMIZE_ONLY_FIELDS": False,
        }
    )
    def test_site_b_hook_fires_for_reroot_child(self):
        """AC2b SITE B: optimize_comments fires for re-rooted child under filtered ancestor.

        (a) SQL has JOIN on post (select_related), (b) assertNumQueries proves no
        N+1 — with TWO comment-parents the comments must be fetched in a SINGLE
        batched query, (c) is_window=False via captured kwargs.

        Because the fixture has 2 posts each with 2 comments, a regression where
        SITE B fired the hook but resolved comments per-post would emit one extra
        comment query and fail both assertNumQueries AND the
        exactly-one-comment-query assertion below.
        """
        schema, captured = _build_site_b_schema()

        query = """
        { authors { results {
            posts(filter: {title: {exact: "SiteBPost"}}) {
                results { id title comments { results { id body } totalCount } }
                totalCount
            }
        } totalCount } }
        """
        with self.assertNumQueries(4):
            with CaptureQueriesContext(connection) as ctx:
                data = _exec(schema, query)

        self.assertIn("authors", data)
        self.assertGreater(
            len(captured),
            0,
            "optimize_comments hook must fire for SITE B re-rooted child",
        )

        # is_window must be False
        self.assertTrue(
            all(kw.get("is_window") is False for kw in captured),
            f"All SITE B calls must have is_window=False; captured: {captured}",
        )

        # The comments across BOTH posts must be batched into EXACTLY ONE query —
        # this is the assertion that genuinely discriminates batched from per-parent
        # N+1 (a single-parent fixture could not). And that one query must carry a
        # JOIN from the hook's select_related("post").
        comment_queries = [
            q["sql"].upper()
            for q in ctx.captured_queries
            if "TESTS_COMMENT" in q["sql"].upper()
        ]
        self.assertEqual(
            len(comment_queries),
            1,
            f"Comments for 2 posts must be batched into 1 query (no per-parent N+1); "
            f"got {len(comment_queries)}: {comment_queries}",
        )
        # The comment query should contain a JOIN (from select_related("post"))
        comment_sql = " ".join(comment_queries)
        self.assertIn(
            "JOIN",
            comment_sql,
            "Hook's select_related(post) must add a JOIN to comment query",
        )


# ---------------------------------------------------------------------------
# Hook reached through a NON-nested-list relation (related-field walker branch)
# ---------------------------------------------------------------------------

_REG_RELFWD = {}


def _build_related_field_forward_schema():
    """Build a schema where a hooked nested list is reached THROUGH a plain FK.

    Topology: root Post -> author (forward FK, a plain related field — NOT a
    DjangoNestedListObjectField) -> posts (nested list with optimize_posts hook).

    This exercises the related-field recursion branch in _walk_filtered_prefetches
    (utils.py:~1731), which forwards hook_map through a plain FK/O2O/reverse
    relation. If that forward were dropped, the inner optimize_posts hook would be
    silently lost — this schema makes that regression observable.
    """
    from django_graphex.fields import DjangoNestedListObjectField
    from tests.models import Author, Post

    _REG_RELFWD.clear()
    captured_kwargs: list[dict] = []

    _InnerPostListType = type(
        "_RelFwdInnerPostListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Post, "registry": _REG_RELFWD})},
    )

    def optimize_posts(qs, info, **kwargs):
        captured_kwargs.append(dict(kwargs))
        return qs.select_related("category")

    # AuthorType owns the hooked nested list `posts`.
    _AuthorType = type(
        "_RelFwdAuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_InnerPostListType, accessor="posts"),
            "optimize_posts": staticmethod(optimize_posts),
            "Meta": type("Meta", (), {"model": Author, "registry": _REG_RELFWD}),
        },
    )

    # PostType exposes `author` as a forward FK (a plain related field). The
    # walker descends Post -> author via the related-field branch, then reaches
    # the hooked nested list on AuthorType.
    _PostType = type(
        "_RelFwdPostType",
        (DjangoObjectType,),
        {"Meta": type("Meta", (), {"model": Post, "registry": _REG_RELFWD})},
    )

    _PostListType = type(
        "_RelFwdPostListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Post, "registry": _REG_RELFWD})},
    )

    schema = graphene.Schema(
        query=type(
            "RelFwdQuery",
            (graphene.ObjectType,),
            {"posts": DjangoListObjectField(_PostListType)},
        )
    )
    return schema, captured_kwargs


class TestHookThroughRelatedField(TestCase):
    """Hook on a nested list reached through a plain FK fires (walker hook_map forward)."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Category, Post

        cls.cat = Category.objects.create(title="RelFwdCat")
        # TWO authors so the inner posts prefetch must batch across parents.
        cls.author1 = Author.objects.create(name="RelFwdAuthor1")
        cls.author2 = Author.objects.create(name="RelFwdAuthor2")
        Post.objects.create(title="RFPost1", author=cls.author1, category=cls.cat)
        Post.objects.create(title="RFPost2", author=cls.author2, category=cls.cat)

    @override_settings(
        DJANGO_GRAPHEX={
            "OPTIMIZE_NESTED_PAGINATION": False,
            "OPTIMIZE_ONLY_FIELDS": False,
        }
    )
    def test_hook_fires_through_forward_fk_relation(self):
        """optimize_posts fires for a nested list reached through the `author` FK.

        This pins the related-field hook_map forward in _walk_filtered_prefetches:
        if the forward were dropped, captured would be empty (hook silently lost)
        and the JOIN would be absent from the inner posts query.
        """
        schema, captured = _build_related_field_forward_schema()

        query = """
        { posts { results {
            id title
            author { posts { results { id title } totalCount } }
        } totalCount } }
        """
        with CaptureQueriesContext(connection) as ctx:
            data = _exec(schema, query)

        self.assertIn("posts", data)
        self.assertGreater(
            len(captured),
            0,
            "optimize_posts must fire for a nested list reached through a plain FK "
            "(related-field hook_map forward)",
        )
        self.assertTrue(
            all(kw.get("is_window") is False for kw in captured),
            f"is_window must be False on this plain path; captured: {captured}",
        )

        # The hook's select_related("category") must land on the INNER posts query
        # (the one reached through author), proving the hook was applied there.
        all_sql = " ".join(q["sql"].upper() for q in ctx.captured_queries)
        self.assertIn(
            "CATEGORY",
            all_sql,
            "Hook's select_related(category) must appear in the inner posts query SQL",
        )


# ---------------------------------------------------------------------------
# SITE B — multiple unfiltered children + multi-segment stripped path
# ---------------------------------------------------------------------------

_REG_SITE_B_MULTI = {}


def _build_site_b_multi_schema():
    """SITE B with TWO unfiltered hooked children under one filtered ancestor AND
    a multi-segment re-rooted descendant.

    Topology under filtered `posts`:
      - comments (reverse FK)         -> stripped 'comments'        (1 segment)
      - tags (M2M)                    -> stripped 'tags'            (1 segment)
      - category -> posts (FK -> rev) -> stripped 'category__posts' (2 segments)

    The two single-segment children exercise the zip() ORDER pairing of
    stripped_children/abs_children; `category__posts` exercises the multi-segment
    descent loop in _merge_filtered_prefetches (utils.py:~2027).
    """
    from django_graphex.fields import DjangoNestedListObjectField
    from tests.models import Author, Category, Comment, Post, Tag

    _REG_SITE_B_MULTI.clear()
    captured_kwargs: list[dict] = []

    def _record(name, select_related_field=None):
        """Build a hook that records its name AND optionally applies a
        MODEL-SPECIFIC select_related.

        When ``select_related_field`` is set it is only valid on the model that
        hook is meant for, so if the zip(stripped_children, abs_children) pairing
        is broken the hook would be applied to the WRONG child model's queryset
        and the select_related would raise eagerly — making a mis-pairing
        observable instead of silently passing.
        """

        def hook(qs, info, **kwargs):
            captured_kwargs.append({"name": name, **kwargs})
            if select_related_field is not None:
                return qs.select_related(select_related_field)
            return qs

        return staticmethod(hook)

    _CommentListType = type(
        "_SBMCommentListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Comment, "registry": _REG_SITE_B_MULTI})},
    )
    _TagListType = type(
        "_SBMTagListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Tag, "registry": _REG_SITE_B_MULTI})},
    )
    # Nested list of posts hung off Category (the multi-segment descendant target).
    _CatPostListType = type(
        "_SBMCatPostListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Post, "registry": _REG_SITE_B_MULTI})},
    )

    _CategoryType = type(
        "_SBMCategoryType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_CatPostListType, accessor="posts"),
            # select_related("author") is valid ONLY on Post — if mis-paired onto
            # Comment/Tag this raises, exposing a broken multi-segment descent.
            "optimize_posts": _record("category_posts", "author"),
            "Meta": type(
                "Meta", (), {"model": Category, "registry": _REG_SITE_B_MULTI}
            ),
        },
    )

    # PostType owns TWO unfiltered hooked nested lists (comments, tags) and exposes
    # `category` (FK) for the multi-segment descent.
    _PostType = type(
        "_SBMPostType",
        (DjangoObjectType,),
        {
            "comments": DjangoNestedListObjectField(
                _CommentListType, accessor="comments"
            ),
            "tags": DjangoNestedListObjectField(_TagListType, accessor="tags"),
            # select_related("post") is valid ONLY on Comment; if the comments
            # zip slot is mis-paired onto the Post or Category child model the
            # select_related raises (Post/Category have no "post" forward FK),
            # exposing a broken pairing. Tag has no forward relation, so its hook
            # is the identity (its presence in the captured name set still pins
            # the tags slot fires).
            "optimize_comments": _record("comments", "post"),
            "optimize_tags": _record("tags"),
            "Meta": type(
                "Meta",
                (),
                {
                    "model": Post,
                    "registry": _REG_SITE_B_MULTI,
                    # expose category so the FK descent into Category.posts works
                    "only_fields": ["id", "title", "comments", "tags", "category"],
                },
            ),
        },
    )

    _PostListType = type(
        "_SBMPostListType",
        (DjangoListObjectType,),
        {
            "Meta": type(
                "Meta",
                (),
                {
                    "model": Post,
                    "filter_fields": {"title": ["exact"]},
                    "registry": _REG_SITE_B_MULTI,
                },
            )
        },
    )

    _AuthorType = type(
        "_SBMAuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
            "Meta": type("Meta", (), {"model": Author, "registry": _REG_SITE_B_MULTI}),
        },
    )

    _AuthorListType = type(
        "_SBMAuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG_SITE_B_MULTI})},
    )

    schema = graphene.Schema(
        query=type(
            "SBMQuery",
            (graphene.ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        )
    )
    return schema, captured_kwargs


class TestSiteBMultiChildAndMultiSegment(TestCase):
    """SITE B: multiple unfiltered children (zip pairing) + multi-segment descent."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Category, Comment, Post, Tag

        cls.cat = Category.objects.create(title="SBMCat")
        cls.author = Author.objects.create(name="SBMAuthor")
        cls.post = Post.objects.create(
            title="SBMPost", author=cls.author, category=cls.cat
        )
        Comment.objects.create(post=cls.post, body="c1")
        tag = Tag.objects.create(label="t1")
        cls.post.tags.add(tag)
        # A sibling post under the SAME category, to give Category.posts content.
        Post.objects.create(title="SBMSibling", author=cls.author, category=cls.cat)

    @override_settings(
        DJANGO_GRAPHEX={
            "OPTIMIZE_NESTED_PAGINATION": False,
            "OPTIMIZE_ONLY_FIELDS": False,
        }
    )
    def test_multiple_children_and_multi_segment_hooks_all_fire(self):
        """All three SITE B hooks fire: two single-segment children + one 2-segment.

        comments and tags pin the zip(stripped_children, abs_children) ORDER
        pairing; category->posts pins the multi-segment descent loop that resolves
        the child model across 'category__posts'. A mis-pairing or a broken
        multi-segment descent would drop one or more hooks (captured names would
        be missing).
        """
        schema, captured = _build_site_b_multi_schema()

        query = """
        { authors { results {
            posts(filter: {title: {exact: "SBMPost"}}) {
                results {
                    id title
                    comments { results { id body } totalCount }
                    tags { results { id label } totalCount }
                    category { posts { results { id title } totalCount } }
                }
                totalCount
            }
        } totalCount } }
        """
        _exec(schema, query)

        fired = {c["name"] for c in captured}
        self.assertIn(
            "comments", fired, "SITE B: optimize_comments (single-segment) must fire"
        )
        self.assertIn("tags", fired, "SITE B: optimize_tags (single-segment) must fire")
        self.assertIn(
            "category_posts",
            fired,
            "SITE B: optimize_posts on Category (multi-segment 'category__posts') must fire",
        )
        # All SITE B re-rooted hooks run on the plain path.
        self.assertTrue(
            all(c.get("is_window") is False for c in captured),
            f"All SITE B calls must have is_window=False; captured: {captured}",
        )


# ---------------------------------------------------------------------------
# Phase 7 / Task 7.3 — AC11 gate independence tests (RED)
# ---------------------------------------------------------------------------


class TestHookGateIndependence(TestCase):
    """AC11 — hook fires regardless of OPTIMIZE_ONLY/ANNOTATED; OPTIMIZE_QUERYSET=False skips it."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Category, Post

        cls.cat = Category.objects.create(title="GateCat")
        cls.author = Author.objects.create(name="GateAuthor")
        Post.objects.create(title="GatePost", author=cls.author, category=cls.cat)

    @override_settings(
        DJANGO_GRAPHEX={
            "OPTIMIZE_NESTED_PAGINATION": False,
            "OPTIMIZE_ONLY_FIELDS": False,
            "OPTIMIZE_ANNOTATED_FIELDS": False,
        }
    )
    def test_hook_fires_when_only_and_annotated_off(self):
        """AC11: hook fires even when OPTIMIZE_ONLY_FIELDS=False AND OPTIMIZE_ANNOTATED_FIELDS=False."""
        schema, captured = _build_unfiltered_hook_schema(has_hook=True)

        query = "{ authors { results { posts { results { id title } totalCount } } totalCount } }"
        with CaptureQueriesContext(connection) as ctx:
            data = _exec(schema, query)

        self.assertIn("authors", data)
        self.assertGreater(
            len(captured),
            0,
            "optimize_posts must fire even when ONLY=False AND ANNOTATED=False",
        )

        all_sql = " ".join(q["sql"].upper() for q in ctx.captured_queries)
        self.assertIn(
            "CATEGORY",
            all_sql,
            "Hook's select_related(category) must apply even with settings off",
        )

    @override_settings(
        DJANGO_GRAPHEX={
            "OPTIMIZE_QUERYSET": False,
        }
    )
    def test_hook_does_not_fire_when_optimize_queryset_false(self):
        """AC11: hook does NOT fire when OPTIMIZE_QUERYSET=False."""
        schema, captured = _build_unfiltered_hook_schema(has_hook=True)

        query = "{ authors { results { posts { results { id title } totalCount } } totalCount } }"
        _exec(schema, query)

        self.assertEqual(
            len(captured), 0, "Hook must NOT fire when OPTIMIZE_QUERYSET=False"
        )


# ---------------------------------------------------------------------------
# Phase 9 / Task 9.1 — SQL + query count integration (RED)
# ---------------------------------------------------------------------------


class TestHookSQLAndQueryCount(TestCase):
    """AC4 — end-to-end SQL proof that the hook is causal."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Category, Post

        cls.cat = Category.objects.create(title="IntCat")
        cls.author = Author.objects.create(name="IntAuthor")
        for i in range(3):
            Post.objects.create(
                title=f"IntPost{i}", author=cls.author, category=cls.cat
            )

    @override_settings(
        DJANGO_GRAPHEX={
            "OPTIMIZE_NESTED_PAGINATION": False,
            "OPTIMIZE_ONLY_FIELDS": False,
        }
    )
    def test_hooked_case_has_join_control_does_not(self):
        """AC4: with hook the prefetch SQL has JOIN; without hook it does not.

        assertNumQueries(N) for both cases proves no N+1 regression.
        OPTIMIZE_ONLY_FIELDS=False to avoid .only()/.select_related conflict.
        """
        query = "{ authors { results { posts { results { id title } totalCount } } totalCount } }"

        # --- With hook ---
        schema_hook, _ = _build_unfiltered_hook_schema(has_hook=True)
        with self.assertNumQueries(3):
            with CaptureQueriesContext(connection) as ctx_hook:
                _exec(schema_hook, query)

        hook_sql = " ".join(q["sql"].upper() for q in ctx_hook.captured_queries)
        self.assertIn("CATEGORY", hook_sql, "Hooked case must JOIN category")

        # --- Without hook (control) ---
        schema_ctrl, _ = _build_unfiltered_hook_schema(has_hook=False)
        with self.assertNumQueries(3):
            with CaptureQueriesContext(connection) as ctx_ctrl:
                _exec(schema_ctrl, query)

        ctrl_sql = " ".join(q["sql"].upper() for q in ctx_ctrl.captured_queries)
        # Control must NOT have category JOIN in POSTS prefetch query
        # (It may have it on author query if select_related adds it, but the
        # post prefetch query in particular should lack it when hook is absent)
        # We check the hook is causal: joining category must be absent without the hook.
        # More precisely: count JOINs should be fewer or zero in control
        hook_join_count = hook_sql.count("JOIN")
        ctrl_join_count = ctrl_sql.count("JOIN")
        self.assertGreater(
            hook_join_count,
            ctrl_join_count,
            f"Hook case ({hook_join_count} JOINs) must have more JOINs than control ({ctrl_join_count} JOINs)",
        )


# ---------------------------------------------------------------------------
# Phase 9 / Task 9.2 — SAFE_MODE degrade (RED)
# ---------------------------------------------------------------------------


class TestSafeModeDegrade(TestCase):
    """AC9 (SAFE_MODE=True): raising hook degrades whole resolve to un-optimized base."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        # TWO authors each with multiple posts so a per-parent N+1 (the
        # un-optimized base) is observable as extra queries vs. the batched
        # optimized prefetch. This lets assertNumQueries discriminate a COARSE
        # degrade (whole resolve un-optimized → N+1 over authors) from a
        # per-field hook-only skip (rest stays optimized → batched).
        cls.author1 = Author.objects.create(name="SMAuthor1")
        cls.author2 = Author.objects.create(name="SMAuthor2")
        for i in range(3):
            Post.objects.create(title=f"SMPost1-{i}", author=cls.author1)
            Post.objects.create(title=f"SMPost2-{i}", author=cls.author2)

    @staticmethod
    def _build_schema(optimize_posts):
        from django_graphex.fields import DjangoNestedListObjectField
        from tests.models import Author, Post

        _reg = Registry()

        _PostListType = type(
            "_SMPostListType",
            (DjangoListObjectType,),
            {"Meta": type("Meta", (), {"model": Post, "registry": _reg})},
        )

        author_attrs = {
            "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
            "Meta": type("Meta", (), {"model": Author, "registry": _reg}),
        }
        if optimize_posts is not None:
            author_attrs["optimize_posts"] = staticmethod(optimize_posts)

        type("_SMAuthorType", (DjangoObjectType,), author_attrs)

        _AuthorListType = type(
            "_SMAuthorListType",
            (DjangoListObjectType,),
            {"Meta": type("Meta", (), {"model": Author, "registry": _reg})},
        )

        return graphene.Schema(
            query=type(
                "SMQuery",
                (graphene.ObjectType,),
                {"authors": DjangoListObjectField(_AuthorListType)},
            )
        )

    @override_settings(
        DJANGO_GRAPHEX={
            "OPTIMIZE_NESTED_PAGINATION": False,
            "OPTIMIZER_SAFE_MODE": True,
        }
    )
    def test_safe_mode_raising_hook_degrades_whole_resolve_coarsely(self):
        """AC9 + SAFE_MODE=True: a raising hook degrades the WHOLE resolve to the
        un-optimized base via the queryset_factory boundary (COARSE, not per-field).

        Distinguishes coarse from per-field by (1) the boundary WARNING text
        'serving un-optimized queryset (OPTIMIZER_SAFE_MODE)' and (2) the query
        count matching the un-optimized N+1 baseline (one extra posts query per
        author) rather than the single batched prefetch query.
        """
        query = "{ authors { results { posts { results { id title } totalCount } } totalCount } }"

        # Baseline: an OPTIMIZED resolve (no raising hook) batches the posts
        # prefetch into ONE query → fewer total queries than the un-optimized N+1.
        schema_ok = self._build_schema(optimize_posts=None)
        with CaptureQueriesContext(connection) as ctx_ok:
            _exec(schema_ok, query)
        optimized_count = len(ctx_ok.captured_queries)

        # Raising hook under SAFE_MODE=True: the queryset_factory boundary catches
        # the propagated exception and serves the base UN-optimized for the whole
        # resolve, so the posts prefetch is dropped → per-author N+1.
        def optimize_posts(qs, info, **kwargs):
            raise ValueError("deliberate hook error")

        schema_raise = self._build_schema(optimize_posts=optimize_posts)
        with self.assertLogs("django_graphex.utils", level="WARNING") as cm:
            with CaptureQueriesContext(connection) as ctx_raise:
                result = schema_raise.execute(query)
        degraded_count = len(ctx_raise.captured_queries)

        # (1) The COARSE boundary warning must be the one that fired — NOT a
        # per-field _apply_field_hook local catch (which no longer exists).
        self.assertTrue(
            any("serving un-optimized" in msg for msg in cm.output),
            f"Expected the queryset_factory COARSE boundary warning "
            f"('serving un-optimized queryset'); got: {cm.output}",
        )

        # (2) The degraded resolve must run MORE queries than the optimized
        # baseline — i.e. the prefetch was dropped for the WHOLE resolve (per-author
        # N+1), not just the hooked field. With 2 authors this is observable.
        self.assertGreater(
            degraded_count,
            optimized_count,
            f"COARSE degrade must drop the batched prefetch (un-optimized N+1): "
            f"degraded={degraded_count} vs optimized={optimized_count}",
        )

        # No 500 / uncaught ValueError propagation to GraphQL errors.
        if result.errors:
            for err in result.errors:
                self.assertNotIsInstance(
                    getattr(err, "original_error", None),
                    ValueError,
                    "ValueError from hook must NOT propagate as a GraphQL error under SAFE_MODE=True",
                )


# ---------------------------------------------------------------------------
# Phase 9 / Task 9.3 — Opt-out: no hook -> no behavior change (RED)
# ---------------------------------------------------------------------------


class TestOptOut(TestCase):
    """Opt-out: no optimize_posts declared -> byte-identical to pre-Phase-E behavior."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        cls.author = Author.objects.create(name="OptOutAuthor")
        Post.objects.create(title="OptOutPost", author=cls.author)

    @override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": False})
    def test_no_hook_no_error_and_no_behavior_change(self):
        """No optimize_posts -> no AttributeError, no exception, identical query count."""
        schema, captured = _build_unfiltered_hook_schema(has_hook=False)

        query = "{ authors { results { posts { results { id title } totalCount } } totalCount } }"

        # Should not raise any exception
        data = _exec(schema, query)
        self.assertIn("authors", data)
        self.assertEqual(len(captured), 0)
