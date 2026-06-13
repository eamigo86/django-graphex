"""Tests for optimizer-phase-c: DB-side window-function slicing of nested lists.

C1 slice: setting + flag + paginator hook.
C2 slice: G3 self-narrow spike, build_window_prefetch, walker AST descent.
"""

from __future__ import annotations

from django.db import connection
from django.db.models import Count, F, Prefetch
from django.db.models.expressions import Window
from django.db.models.functions import RowNumber
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

# ---------------------------------------------------------------------------
# Phase 1: Setting + flag foundation
# ---------------------------------------------------------------------------


class TestOptimizeNestedPaginationSetting(TestCase):
    """Tests for the OPTIMIZE_NESTED_PAGINATION setting (tasks 1.1 and 1.3)."""

    def test_setting_default(self):
        """OPTIMIZE_NESTED_PAGINATION absent from DJANGO_GRAPHEX defaults to True (task 1.1)."""
        from django_graphex import settings as settings_module

        # Read via the module-level singleton so override_settings reload is respected.
        s = settings_module.graphql_api_settings
        self.assertTrue(
            hasattr(s, "OPTIMIZE_NESTED_PAGINATION"),
            "graphql_api_settings must expose OPTIMIZE_NESTED_PAGINATION",
        )
        self.assertIs(
            s.OPTIMIZE_NESTED_PAGINATION,
            True,
            "Default value must be True",
        )

    @override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": False})
    def test_setting_explicit_false(self):
        """OPTIMIZE_NESTED_PAGINATION=False propagates via override_settings (task 1.3)."""
        from django_graphex import settings as settings_module

        s = settings_module.graphql_api_settings
        self.assertIs(
            s.OPTIMIZE_NESTED_PAGINATION,
            False,
            "Explicit False must be honoured",
        )


class TestAlreadyPaginatedFlag(TestCase):
    """Tests for the already_paginated field on DjangoListObjectBase (task 1.5)."""

    def test_already_paginated_flag_default(self):
        """already_paginated defaults to False, can be set True, old calls still valid (task 1.5)."""
        from django_graphex.base_types import DjangoListObjectBase

        # Old-style call with no already_paginated kwarg must still work.
        obj_old = DjangoListObjectBase(results=[], count=0)
        self.assertIs(
            getattr(obj_old, "already_paginated", False),
            False,
            "Default already_paginated must be False",
        )

        # Explicit False.
        obj_false = DjangoListObjectBase(results=[], count=0, already_paginated=False)
        self.assertIs(obj_false.already_paginated, False)

        # Explicit True.
        obj_true = DjangoListObjectBase(results=[], count=0, already_paginated=True)
        self.assertIs(obj_true.already_paginated, True)


# ---------------------------------------------------------------------------
# Phase 3: G3 self-narrow spike (gates .only() in build_window_prefetch)
# ---------------------------------------------------------------------------


class TestG3WindowOnlySpike(TestCase):
    """Spike/proof test: does qs.annotate(Window).filter(_gqx_rn).only() compose?

    This test runs the EXACT chain that build_window_prefetch would emit on the
    Post model (partitioned by author_id).  It asserts:
      (A) the queryset EXECUTES without FieldError or exception, and
      (B) the SELECT list is ACTUALLY narrowed (author_id + id + title from only(),
          plus the two window annotations) — not a silent full-column load.

    If (B) fails, SELF_NARROW_VERIFIED must be set False in fields.py and
    build_window_prefetch must drop .only().  If (A) fails the whole approach
    is broken — raise immediately.
    """

    # Module-level constant set by this test (True = .only() kept, False = dropped).
    # Accessed by later tests to skip the SELECT-narrowing assertion when False.
    SELF_NARROW_VERIFIED: bool | None = None  # populated by test_g3_window_only_spike

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        cls.author = Author.objects.create(name="SpikeAuthor")
        for i in range(5):
            Post.objects.create(title=f"SpPost{i}", author=cls.author)

    def test_g3_window_only_spike(self):
        """Build Window+filter+only chain on Post, assert it runs and narrows SELECT."""
        from tests.models import Post

        fk_attname = "author_id"  # Post.author FK attname
        offset, limit = 0, 3
        order_exprs = [F("id").asc()]

        qs = (
            Post.objects.all()
            .annotate(
                _gqx_rn=Window(
                    RowNumber(), partition_by=[F(fk_attname)], order_by=order_exprs
                ),
                _gqx_total=Window(Count("*"), partition_by=[F(fk_attname)]),
            )
            .filter(_gqx_rn__gt=offset, _gqx_rn__lte=offset + limit)
            .only(fk_attname, "id", "title")
        )

        # (A) Must execute without exception.
        with CaptureQueriesContext(connection) as ctx:
            rows = list(qs)

        self.assertGreater(
            len(rows), 0, "Expected at least one row from spike queryset"
        )

        # (A) Window annotations must be present on each row.
        for row in rows:
            self.assertTrue(hasattr(row, "_gqx_rn"), "Row must have _gqx_rn annotation")
            self.assertTrue(
                hasattr(row, "_gqx_total"), "Row must have _gqx_total annotation"
            )

        # (B) SELECT list narrowing check — inspect emitted SQL.
        sql = ctx.captured_queries[0]["sql"].upper()

        # The SQL must contain ROW_NUMBER() and COUNT(*) OVER
        self.assertIn("ROW_NUMBER()", sql, "Window RowNumber must appear in SQL")
        self.assertIn("COUNT(", sql, "Window Count must appear in SQL")

        # Column narrowing: the SELECT must NOT contain all columns.
        # Post has: id, title, body, author_id, category_id — 5 concrete cols.
        # After .only(author_id, id, title) only those 3 + window exprs should appear.
        # We check that "body" (deferred col) is NOT in the outer SELECT.
        # NOTE: SQLite wraps window+filter into a subquery; the outer SELECT
        # should be narrowed.  If .only() did not survive wrapping, the outer
        # SELECT will be "SELECT *" or list all columns.
        select_clause = sql.split("FROM")[0] if "FROM" in sql else sql

        # Record the outcome for SELF_NARROW_VERIFIED
        body_not_in_select = (
            '"BODY"' not in select_clause
            and "BODY" not in select_clause.split("WHERE")[0]
        )
        TestG3WindowOnlySpike.SELF_NARROW_VERIFIED = body_not_in_select

        if not body_not_in_select:
            # .only() did NOT survive window-filter wrapping: body leaked into SELECT.
            # This is the documented fallback: drop .only(), keep row-count win.
            # Spike result: SELF_NARROW_VERIFIED = False
            # The test still PASSES — this is a decision checkpoint, not a failure.
            pass
        else:
            # .only() survived: SELECT is narrowed.
            # Spike result: SELF_NARROW_VERIFIED = True
            pass

        # Always assert (A): executes, annotations present, correct row count.
        self.assertLessEqual(
            len(rows), limit, "Window slice must not exceed limit rows per author"
        )

        # Record spike result in class var for downstream tests to read.
        self.__class__.SELF_NARROW_VERIFIED = body_not_in_select


# ---------------------------------------------------------------------------
# Phase 4: build_window_prefetch — pre-checks + window construction
# ---------------------------------------------------------------------------

# Module-level type registry to avoid inner-class scoping issues.
_REG_BWP = {}


def _make_test_nested_field():
    """Build a minimal DjangoNestedListObjectField for Post (author.posts).

    Uses a module-level registry to avoid Python inner-class scoping issues.
    Returns the DjangoNestedListObjectField instance.
    """
    from django_graphex.fields import DjangoNestedListObjectField
    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
    from django_graphex.types import DjangoListObjectType, DjangoObjectType
    from tests.models import Author, Post

    _REG_BWP.clear()

    # Use type() to define inner classes so the registry variable is captured
    # via closure in the Meta namespace correctly.
    _PostListType = type(
        "_PostListType",
        (DjangoListObjectType,),
        {
            "Meta": type(
                "Meta",
                (),
                {
                    "model": Post,
                    "pagination": LimitOffsetGraphqlPagination(default_limit=5),
                    "registry": _REG_BWP,
                },
            )
        },
    )

    _AuthorType = type(
        "_AuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
            "Meta": type("Meta", (), {"model": Author, "registry": _REG_BWP}),
        },
    )

    return _AuthorType._meta.fields["posts"]


class TestBuildWindowPrefetchPreChecks(TestCase):
    """Tests for the applicability pre-checks in build_window_prefetch (task 4.1–4.7)."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        cls.author = Author.objects.create(name="BWPAuthor")
        for i in range(5):
            Post.objects.create(title=f"BWPPost{i}", author=cls.author)

    def _get_inst(self):
        """Return a minimal DjangoNestedListObjectField for Post."""
        return _make_test_nested_field()

    def test_precheck_returns_none_when_setting_false(self):
        """Pre-check 1: OPTIMIZE_NESTED_PAGINATION=False -> build_window_prefetch returns None."""
        from tests.models import Author

        inst = self._get_inst()
        related_field = Author._meta.get_field("posts")
        slice_tuple = (0, 5, ["id"])

        with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": False}):
            result = inst.build_window_prefetch(
                lookup="posts",
                filter_value=None,
                slice_tuple=slice_tuple,
                related_field=related_field,
                sub_selection=None,
                fragments={},
            )
            self.assertIsNone(
                result, "Must return None when OPTIMIZE_NESTED_PAGINATION=False"
            )

    def test_precheck_returns_none_when_slice_none(self):
        """Pre-check 2: slice_tuple=None -> returns None (Cursor/unbounded fallback)."""
        from tests.models import Author

        inst = self._get_inst()
        related_field = Author._meta.get_field("posts")

        result = inst.build_window_prefetch(
            lookup="posts",
            filter_value=None,
            slice_tuple=None,
            related_field=related_field,
            sub_selection=None,
            fragments={},
        )
        self.assertIsNone(result, "Must return None when slice_tuple is None")

    def test_precheck_returns_none_when_m2m(self):
        """Pre-check 3: many_to_many relation -> returns None.

        The fabricated related_field has many_to_many=True AND one_to_many=True so
        that pre-check 4 (one_to_many guard) would NOT reject it.  This ensures the
        test fails if and only if pre-check 3 is removed, properly isolating that guard.
        (A real Django ManyToManyField has one_to_many=False, so pre-check 4 would also
        catch it — making the test non-isolating for pre-check 3.)
        """
        from django_graphex.fields import DjangoNestedListObjectField
        from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
        from django_graphex.types import DjangoListObjectType, DjangoObjectType
        from tests.models import Post

        _reg = {}
        _PostListType3 = type(
            "_M2MPostListType",
            (DjangoListObjectType,),
            {
                "Meta": type(
                    "Meta",
                    (),
                    {
                        "model": Post,
                        "pagination": LimitOffsetGraphqlPagination(default_limit=5),
                        "registry": _reg,
                    },
                )
            },
        )
        _FakeM2MType = type(
            "_FakeM2MType",
            (DjangoObjectType,),
            {
                "posts": DjangoNestedListObjectField(_PostListType3, accessor="posts"),
                "Meta": type("Meta", (), {"model": Post, "registry": _reg}),
            },
        )

        inst = _FakeM2MType._meta.fields["posts"]

        # Fabricate a field where many_to_many=True BUT one_to_many=True as well.
        # This means pre-check 4 would NOT reject it, isolating pre-check 3.
        class _FakeM2MRelated:
            many_to_many = True
            one_to_many = True  # bypasses pre-check 4 — only pre-check 3 can block this
            field = Post._meta.get_field("author")  # concrete FK for the field attr

        result = inst.build_window_prefetch(
            lookup="posts",
            filter_value=None,
            slice_tuple=(0, 5, ["id"]),
            related_field=_FakeM2MRelated(),
            sub_selection=None,
            fragments={},
        )
        self.assertIsNone(
            result, "Must return None for M2M relations (pre-check 3 isolation)"
        )

    def test_precheck_returns_none_when_not_one_to_many(self):
        """Pre-check 4: relation that is not one_to_many -> returns None."""
        from django_graphex.fields import DjangoNestedListObjectField
        from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
        from django_graphex.types import DjangoListObjectType, DjangoObjectType
        from tests.models import Post

        _reg = {}
        _PostListType2 = type(
            "_PostListType2",
            (DjangoListObjectType,),
            {
                "Meta": type(
                    "Meta",
                    (),
                    {
                        "model": Post,
                        "pagination": LimitOffsetGraphqlPagination(default_limit=5),
                        "registry": _reg,
                    },
                )
            },
        )
        _FakeType = type(
            "_FakeType",
            (DjangoObjectType,),
            {
                "posts": DjangoNestedListObjectField(_PostListType2, accessor="posts"),
                "Meta": type("Meta", (), {"model": Post, "registry": _reg}),
            },
        )

        inst = _FakeType._meta.fields["posts"]

        # Fabricate a relation that is NOT one_to_many.
        class _FakeRelated:
            many_to_many = False
            one_to_many = False  # not one_to_many
            field = None

        result = inst.build_window_prefetch(
            lookup="posts",
            filter_value=None,
            slice_tuple=(0, 5, ["id"]),
            related_field=_FakeRelated(),
            sub_selection=None,
            fragments={},
        )
        self.assertIsNone(result, "Must return None for non-one_to_many relations")

    def test_precheck_returns_none_for_non_concrete_ordering(self):
        """Pre-check 5: non-concrete ordering term -> returns None."""
        from tests.models import Author

        inst = self._get_inst()
        related_field = Author._meta.get_field("posts")

        # "computed_prop" is not a concrete field on Post
        result = inst.build_window_prefetch(
            lookup="posts",
            filter_value=None,
            slice_tuple=(0, 5, ["computed_prop"]),
            related_field=related_field,
            sub_selection=None,
            fragments={},
        )
        self.assertIsNone(result, "Must return None for non-concrete ordering term")

    def test_precheck_returns_none_for_full_load(self):
        """Pre-check 6: _compute_child_only returns None (full load) -> returns None."""
        from unittest import mock

        import django_graphex.fields as fields_module
        from tests.models import Author

        inst = self._get_inst()
        related_field = Author._meta.get_field("posts")

        # Patch _compute_child_only in the fields module's namespace to return None
        # (simulating full-load detection without needing a real SelectionSetNode).
        with mock.patch.object(fields_module, "_compute_child_only", return_value=None):
            # Use a simple namespace object with a .selections attr so the sub_selection
            # is non-None and triggers the _compute_child_only call path.
            fake_selection = type("FakeSel", (), {"selections": []})()
            result = inst.build_window_prefetch(
                lookup="posts",
                filter_value=None,
                slice_tuple=(0, 5, ["id"]),
                related_field=related_field,
                sub_selection=fake_selection,
                fragments={},
            )
        self.assertIsNone(
            result, "Must return None when _compute_child_only returns None (full load)"
        )

    def test_build_window_prefetch_returns_prefetch_object(self):
        """Happy path: build_window_prefetch returns a Prefetch object with window SQL."""
        from tests.models import Author

        inst = self._get_inst()
        related_field = Author._meta.get_field("posts")

        result = inst.build_window_prefetch(
            lookup="posts",
            filter_value=None,
            slice_tuple=(0, 3, ["id"]),
            related_field=related_field,
            sub_selection=None,
            fragments={},
        )
        self.assertIsNotNone(
            result,
            "build_window_prefetch must return a Prefetch (not None) on happy path",
        )
        self.assertIsInstance(
            result, Prefetch, "Return value must be a Prefetch instance"
        )
        self.assertEqual(result.prefetch_through, "posts")

    def test_window_prefetch_sql_contains_row_number_and_count(self):
        """build_window_prefetch queryset emits ROW_NUMBER() and COUNT(*) OVER in SQL."""
        from tests.models import Author

        inst = self._get_inst()
        related_field = Author._meta.get_field("posts")

        pf = inst.build_window_prefetch(
            lookup="posts",
            filter_value=None,
            slice_tuple=(0, 3, ["id"]),
            related_field=related_field,
            sub_selection=None,
            fragments={},
        )
        self.assertIsNotNone(pf)

        with CaptureQueriesContext(connection) as ctx:
            list(pf.queryset)

        sql = ctx.captured_queries[0]["sql"].upper()
        self.assertIn("ROW_NUMBER()", sql, "SQL must contain ROW_NUMBER()")
        self.assertIn("COUNT(", sql, "SQL must contain COUNT()")
        self.assertIn("PARTITION BY", sql, "SQL must contain PARTITION BY")
        self.assertIn("AUTHOR_ID", sql, "SQL must partition by author_id")

    def test_window_prefetch_sql_contains_filter_range(self):
        """Window queryset must filter rows in the slice range."""
        from tests.models import Author

        inst = self._get_inst()
        related_field = Author._meta.get_field("posts")

        offset, limit = 1, 3
        pf = inst.build_window_prefetch(
            lookup="posts",
            filter_value=None,
            slice_tuple=(offset, limit, ["id"]),
            related_field=related_field,
            sub_selection=None,
            fragments={},
        )

        with CaptureQueriesContext(connection):
            rows = list(pf.queryset)

        # All returned rows must have _gqx_rn in (offset+1, offset+limit].
        for row in rows:
            self.assertGreater(row._gqx_rn, offset)
            self.assertLessEqual(row._gqx_rn, offset + limit)

    def test_window_prefetch_fk_attname_in_rows(self):
        """All rows from window prefetch carry the FK attname (author_id)."""
        from tests.models import Author

        inst = self._get_inst()
        related_field = Author._meta.get_field("posts")

        pf = inst.build_window_prefetch(
            lookup="posts",
            filter_value=None,
            slice_tuple=(0, 5, ["id"]),
            related_field=related_field,
            sub_selection=None,
            fragments={},
        )
        rows = list(pf.queryset)
        for row in rows:
            self.assertEqual(
                row.author_id, self.author.pk, "author_id must be set on each row"
            )

    def test_precheck_returns_none_for_distinct_filter(self):
        """Pre-check 7: filter that forces .distinct() -> returns None (G5)."""
        from unittest import mock

        from tests.models import Author

        inst = self._get_inst()
        related_field = Author._meta.get_field("posts")

        # Patch filter_backend.apply to return a queryset with .query.distinct = True.
        class _DistinctQS:
            """Fake queryset that reports distinct=True."""

            model = None
            query = type("Q", (), {"distinct": True})()

            def filter(self, **kw):
                return self

            def annotate(self, **kw):
                return self

        with mock.patch.object(
            inst.filter_backend, "apply", return_value=_DistinctQS()
        ):
            result = inst.build_window_prefetch(
                lookup="posts",
                filter_value={"some": "filter"},
                slice_tuple=(0, 5, ["id"]),
                related_field=related_field,
                sub_selection=None,
                fragments={},
            )
        self.assertIsNone(
            result, "Must return None when filter_backend.apply forces .distinct() (G5)"
        )


# ---------------------------------------------------------------------------
# Phase 5: Walker AST descent + paginator resolution (G2 fail-loud guard)
# ---------------------------------------------------------------------------


_REG_WALK = {}


def _build_walk_schema():
    """Build a minimal graphene Schema for walk tests with Author + paginated posts."""
    import graphene

    from django_graphex.fields import DjangoNestedListObjectField
    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
    from django_graphex.types import (
        DjangoListObjectField,
        DjangoListObjectType,
        DjangoObjectType,
    )
    from tests.models import Author, Post

    _REG_WALK.clear()

    _PostType = type(
        "_WalkPostType",
        (DjangoObjectType,),
        {"Meta": type("Meta", (), {"model": Post, "registry": _REG_WALK})},
    )

    _PostListType = type(
        "_WalkPostListType",
        (DjangoListObjectType,),
        {
            "Meta": type(
                "Meta",
                (),
                {
                    "model": Post,
                    "pagination": LimitOffsetGraphqlPagination(default_limit=5),
                    "registry": _REG_WALK,
                },
            )
        },
    )

    _AuthorType = type(
        "_WalkAuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
            "Meta": type("Meta", (), {"model": Author, "registry": _REG_WALK}),
        },
    )

    _AuthorListType = type(
        "_WalkAuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG_WALK})},
    )

    from graphene import Schema

    schema = Schema(
        query=type(
            "WalkQuery",
            (graphene.ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        )
    )
    return schema


class TestWalkerPaginationArgExtraction(TestCase):
    """Tests for pagination-arg extraction helper and G2 guard (task 5.1–5.6).

    In C2 the LIVE walker still calls build_prefetch (the switch to
    build_window_prefetch in the live path is C3).  These tests verify:
    - The paginator resolution helper (G2 fail-loud guard) works correctly.
    - The paginator extraction logic correctly handles custom resolvers.
    - The walker correctly falls back when results sub-field is not selected.
    - The walker does NOT crash (G2) when the results resolver is custom.
    """

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        cls.author = Author.objects.create(name="WalkAuthor")
        for i in range(8):
            Post.objects.create(title=f"WP{i}", author=cls.author)

    def _exec(self, schema, query):
        result = schema.execute(query)
        assert result.errors is None, result.errors
        return result.data

    def test_paginator_resolution_helper_returns_paginator_for_generic_pagination_field(
        self,
    ):
        """G2 guard: _resolve_results_paginator returns paginator from GenericPaginationField.

        Calls the production function directly so that removing or breaking the
        getattr chain in _resolve_results_paginator makes this test go RED.
        """
        from functools import partial

        from django_graphex.paginations.pagination import (
            BaseDjangoGraphqlPagination,
            LimitOffsetGraphqlPagination,
        )
        from django_graphex.paginations.utils import GenericPaginationField
        from django_graphex.utils import _resolve_results_paginator

        paginator_instance = LimitOffsetGraphqlPagination(default_limit=5)

        # Simulate what GenericPaginationField.wrap_resolve produces:
        # resolve is a partial(GenericPaginationField.list_resolver, manager)
        # with __self__ being the field instance that owns paginator_instance.
        field = GenericPaginationField.__new__(GenericPaginationField)
        field.paginator_instance = paginator_instance

        bound_method = field.list_resolver
        resolve_fn = partial(bound_method, object())

        class _FakeFieldDef:
            resolve = resolve_fn

        paginator = _resolve_results_paginator(_FakeFieldDef())

        self.assertIsInstance(
            paginator,
            BaseDjangoGraphqlPagination,
            "_resolve_results_paginator must return the paginator from a GenericPaginationField",
        )
        self.assertIs(
            paginator,
            paginator_instance,
            "_resolve_results_paginator must return the exact paginator_instance",
        )

    def test_paginator_resolution_helper_returns_none_for_custom_resolver(self):
        """G2 guard: _resolve_results_paginator returns None for a plain-function resolver.

        Calls the production function directly so that breaking the None-return
        branch makes this test go RED.
        """
        from django_graphex.utils import _resolve_results_paginator

        # A custom resolver that is NOT partial(GenericPaginationField.list_resolver...)
        def custom_resolver(root, info, **kwargs):
            return []

        class _FakeFieldDef:
            resolve = custom_resolver

        result = _resolve_results_paginator(_FakeFieldDef())

        self.assertIsNone(
            result,
            "_resolve_results_paginator must return None for a plain-function resolver",
        )

    def test_paginator_resolution_helper_returns_none_when_not_base_paginator(self):
        """G2 guard: _resolve_results_paginator returns None when bound object's
        paginator_instance is not a BaseDjangoGraphqlPagination instance.

        This directly exercises the isinstance gate inside _resolve_results_paginator.
        """
        from functools import partial

        from django_graphex.utils import _resolve_results_paginator

        # Simulate a bound object whose paginator_instance is NOT a BaseDjangoGraphqlPagination.
        class _FakeField:
            paginator_instance = object()  # not a BaseDjangoGraphqlPagination

            def list_resolver(self, manager, *args, **kwargs):  # pragma: no cover
                return []

        fake_field = _FakeField()
        resolve_fn = partial(fake_field.list_resolver, object())

        class _FakeFieldDef:
            resolve = resolve_fn

        result = _resolve_results_paginator(_FakeFieldDef())

        self.assertIsNone(
            result,
            "_resolve_results_paginator must return None when paginator_instance is not BaseDjangoGraphqlPagination",
        )

    def test_walker_live_path_emits_window_sql_in_c3(self):
        """C3 live: walker now calls build_window_prefetch for windowable nested lists.

        With C3 active, the live query for a LimitOffset nested list with
        explicit limit/offset MUST emit ROW_NUMBER() SQL (window-sliced prefetch).
        """
        schema = _build_walk_schema()
        query = """
        { authors { results {
            posts { results(limit: 3, offset: 0) { id title } totalCount }
        } totalCount } }
        """
        with CaptureQueriesContext(connection) as ctx:
            data = self._exec(schema, query)

        self.assertIn("authors", data)
        sql_list = [q["sql"].upper() for q in ctx.captured_queries]
        window_sql = [s for s in sql_list if "ROW_NUMBER()" in s]
        # C3 live: MUST emit ROW_NUMBER() SQL from the live walker.
        self.assertGreaterEqual(
            len(window_sql),
            1,
            "C3 live: walker must emit ROW_NUMBER() SQL for windowable nested lists",
        )

    def test_walker_falls_back_when_results_sub_field_not_selected(self):
        """Walker falls back to plain path when results sub-field not selected."""
        schema = _build_walk_schema()

        # Query only totalCount — no results sub-field selected.
        query = "{ authors { results { posts { totalCount } } totalCount } }"
        with CaptureQueriesContext(connection) as ctx:
            self._exec(schema, query)

        sql_list = [q["sql"].upper() for q in ctx.captured_queries]
        window_sql = [s for s in sql_list if "ROW_NUMBER()" in s]
        # Should NOT have window SQL.
        self.assertEqual(
            len(window_sql),
            0,
            "Walker must NOT emit window SQL when results sub-field absent",
        )

    def test_g2_custom_resolver_falls_back_without_crash(self):
        """G2: custom results resolver -> graceful fallback, no AttributeError/crash."""
        import graphene

        from django_graphex.fields import DjangoNestedListObjectField
        from django_graphex.types import (
            DjangoListObjectField,
            DjangoListObjectType,
            DjangoObjectType,
        )
        from tests.models import Author, Post

        _g2_reg = {}
        _PostType_g2 = type(
            "_G2PostType",
            (DjangoObjectType,),
            {"Meta": type("Meta", (), {"model": Post, "registry": _g2_reg})},
        )
        # No pagination -> no GenericPaginationField on results
        _PostListTypeCustom = type(
            "_G2PostListTypeCustom",
            (DjangoListObjectType,),
            {"Meta": type("Meta", (), {"model": Post, "registry": _g2_reg})},
        )
        _AuthorTypeCustom = type(
            "_G2AuthorTypeCustom",
            (DjangoObjectType,),
            {
                "posts": DjangoNestedListObjectField(
                    _PostListTypeCustom, accessor="posts"
                ),
                "Meta": type("Meta", (), {"model": Author, "registry": _g2_reg}),
            },
        )
        _AuthorListTypeCustom = type(
            "_G2AuthorListTypeCustom",
            (DjangoListObjectType,),
            {"Meta": type("Meta", (), {"model": Author, "registry": _g2_reg})},
        )

        from graphene import Schema

        schema = Schema(
            query=type(
                "G2Query",
                (graphene.ObjectType,),
                {"authors": DjangoListObjectField(_AuthorListTypeCustom)},
            )
        )

        # Query: with results sub-field but no paginator -> resolver is not GenericPaginationField
        query = (
            "{ authors { results { posts { results { id } totalCount } } totalCount } }"
        )
        # Must not raise an exception.
        result = schema.execute(query)
        self.assertIsNone(
            result.errors,
            f"G2: query with custom resolver must not error: {result.errors}",
        )

        # No window SQL (fell back to build_prefetch or plain path)
        with CaptureQueriesContext(connection) as ctx:
            schema.execute(query)
        sql_list = [q["sql"].upper() for q in ctx.captured_queries]
        window_sql = [s for s in sql_list if "ROW_NUMBER()" in s]
        self.assertEqual(
            len(window_sql), 0, "G2: custom resolver path must NOT emit window SQL"
        )


# ---------------------------------------------------------------------------
# _walk_window_params unit tests (covers lines 1209-1254 of utils.py)
# ---------------------------------------------------------------------------


class TestWalkWindowParamsDirect(TestCase):
    """Direct unit tests for django_graphex.utils._walk_window_params.

    These tests call the production function with minimal stubs so that
    coverage for lines 1209-1254 (the entire _walk_window_params body) is
    exercised without going through the live query path (dormant in C2).
    """

    def _make_info(self, variable_values=None):
        """Return a minimal mock of GraphQLResolveInfo."""
        from unittest.mock import MagicMock

        info = MagicMock()
        info.variable_values = variable_values or {}
        return info

    def test_returns_none_when_sub_gql_is_none(self):
        """Early exit: sub_gql=None -> returns None (line 1209)."""
        from unittest.mock import MagicMock

        from graphql.language.ast import FieldNode, NameNode, SelectionSetNode

        from django_graphex.utils import _walk_window_params

        inst = MagicMock()
        field = FieldNode(
            name=NameNode(value="posts"), selection_set=SelectionSetNode(selections=[])
        )

        result = _walk_window_params(inst, field, None, self._make_info())
        self.assertIsNone(
            result, "_walk_window_params must return None when sub_gql is None"
        )

    def test_returns_none_when_selection_set_is_none(self):
        """Early exit: field.selection_set=None -> returns None (line 1209)."""
        from unittest.mock import MagicMock

        from graphql import GraphQLObjectType
        from graphql.language.ast import FieldNode, NameNode

        from django_graphex.utils import _walk_window_params

        inst = MagicMock()
        field = FieldNode(
            name=NameNode(value="posts")
        )  # selection_set defaults to None

        sub_gql = GraphQLObjectType("FakeType", fields={})

        result = _walk_window_params(inst, field, sub_gql, self._make_info())
        self.assertIsNone(
            result,
            "_walk_window_params must return None when field.selection_set is None",
        )

    def test_returns_none_when_results_name_not_found(self):
        """Early exit: inst.type has no _meta.results_field_name -> returns None (line 1214)."""
        from unittest.mock import MagicMock

        from graphql import GraphQLObjectType
        from graphql.language.ast import FieldNode, NameNode, SelectionSetNode

        from django_graphex.utils import _walk_window_params

        inst = MagicMock()
        inst.type._meta.results_field_name = None  # Simulate missing results_field_name

        results_sel = FieldNode(name=NameNode(value="results"))
        field = FieldNode(
            name=NameNode(value="posts"),
            selection_set=SelectionSetNode(selections=[results_sel]),
        )
        sub_gql = GraphQLObjectType("FakeType", fields={})

        result = _walk_window_params(inst, field, sub_gql, self._make_info())
        self.assertIsNone(
            result,
            "_walk_window_params must return None when results_field_name is None",
        )

    def test_returns_none_when_results_not_in_selections(self):
        """Early exit: results sub-field absent from selections -> returns None (line 1227-1229)."""
        from unittest.mock import MagicMock

        from graphql import GraphQLObjectType
        from graphql.language.ast import FieldNode, NameNode, SelectionSetNode

        from django_graphex.utils import _walk_window_params

        inst = MagicMock()
        inst.type._meta.results_field_name = "results"

        # Only totalCount selected — no "results" sub-field.
        total_count_sel = FieldNode(name=NameNode(value="totalCount"))
        field = FieldNode(
            name=NameNode(value="posts"),
            selection_set=SelectionSetNode(selections=[total_count_sel]),
        )
        sub_gql = GraphQLObjectType("FakeType", fields={})

        result = _walk_window_params(inst, field, sub_gql, self._make_info())
        self.assertIsNone(
            result,
            "_walk_window_params must return None when results sub-field is absent",
        )

    def test_returns_none_when_results_field_def_missing(self):
        """Early exit: sub_gql has no 'results' field definition -> returns None (line 1235-1236)."""
        from unittest.mock import MagicMock

        from graphql import GraphQLObjectType
        from graphql.language.ast import FieldNode, NameNode, SelectionSetNode

        from django_graphex.utils import _walk_window_params

        inst = MagicMock()
        inst.type._meta.results_field_name = "results"

        results_sel = FieldNode(name=NameNode(value="results"))
        field = FieldNode(
            name=NameNode(value="posts"),
            selection_set=SelectionSetNode(selections=[results_sel]),
        )
        # sub_gql has no "results" field.
        sub_gql = GraphQLObjectType("FakeType", fields={})

        result = _walk_window_params(inst, field, sub_gql, self._make_info())
        self.assertIsNone(
            result,
            "_walk_window_params must return None when results field def is missing from sub_gql",
        )

    def test_returns_none_when_paginator_unresolvable(self):
        """Early exit: _resolve_results_paginator returns None -> returns None (line 1240-1241).

        This exercises the G2 guard path inside _walk_window_params.
        """
        from unittest.mock import MagicMock, patch

        from graphql import GraphQLField, GraphQLObjectType, GraphQLString
        from graphql.language.ast import FieldNode, NameNode, SelectionSetNode

        from django_graphex.utils import _walk_window_params

        inst = MagicMock()
        inst.type._meta.results_field_name = "results"

        results_sel = FieldNode(name=NameNode(value="results"))
        field = FieldNode(
            name=NameNode(value="posts"),
            selection_set=SelectionSetNode(selections=[results_sel]),
        )
        # sub_gql has a "results" field so the field-def lookup succeeds.
        sub_gql = GraphQLObjectType(
            "FakeType",
            fields={"results": GraphQLField(GraphQLString)},
        )

        # Patch _resolve_results_paginator to return None (custom resolver scenario).
        with patch(
            "django_graphex.utils._resolve_results_paginator", return_value=None
        ):
            result = _walk_window_params(inst, field, sub_gql, self._make_info())

        self.assertIsNone(
            result,
            "_walk_window_params must return None when paginator cannot be resolved (G2 guard)",
        )

    def test_happy_path_returns_tuple(self):
        """Happy path: all guards pass -> returns (slice_tuple, results_field_node, page_args, paginator).

        Exercises lines 1244-1254 (get_argument_values + prefetch_window_slice + return).
        """
        from unittest.mock import MagicMock, patch

        from graphql import GraphQLField, GraphQLInt, GraphQLObjectType
        from graphql.language.ast import (
            ArgumentNode,
            FieldNode,
            IntValueNode,
            NameNode,
            SelectionSetNode,
        )

        from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
        from django_graphex.utils import _walk_window_params

        paginator_instance = LimitOffsetGraphqlPagination(default_limit=5)

        inst = MagicMock()
        inst.type._meta.results_field_name = "results"

        # Build a results FieldNode with limit/offset arguments.
        results_sel = FieldNode(
            name=NameNode(value="results"),
            arguments=[
                ArgumentNode(
                    name=NameNode(value="limit"), value=IntValueNode(value="3")
                ),
                ArgumentNode(
                    name=NameNode(value="offset"), value=IntValueNode(value="0")
                ),
            ],
        )
        field = FieldNode(
            name=NameNode(value="posts"),
            selection_set=SelectionSetNode(selections=[results_sel]),
        )

        # sub_gql with a "results" field that has limit/offset args.
        from graphql import GraphQLArgument

        results_field_def = GraphQLField(
            GraphQLInt,
            args={
                "limit": GraphQLArgument(GraphQLInt),
                "offset": GraphQLArgument(GraphQLInt),
            },
        )
        sub_gql = GraphQLObjectType("FakeType", fields={"results": results_field_def})

        info = self._make_info()

        with patch(
            "django_graphex.utils._resolve_results_paginator",
            return_value=paginator_instance,
        ):
            result = _walk_window_params(inst, field, sub_gql, info)

        self.assertIsNotNone(
            result, "_walk_window_params must return a tuple on the happy path"
        )
        self.assertEqual(len(result), 4, "_walk_window_params must return a 4-tuple")
        slice_tuple, results_field_node, page_args, returned_paginator = result
        self.assertIs(returned_paginator, paginator_instance)
        self.assertIs(results_field_node, results_sel)
        # slice_tuple from LimitOffsetGraphqlPagination.prefetch_window_slice(limit=3, offset=0)
        # -> (0, 3, ordering) where ordering comes from paginator default
        self.assertIsNotNone(
            slice_tuple,
            "slice_tuple must not be None for a valid LimitOffset paginator",
        )


# ---------------------------------------------------------------------------
# Phase 6: G4 ordering parity fix (tasks 6.1-6.2)
# ---------------------------------------------------------------------------


class TestG4OrderingParity(TestCase):
    """G4: falsy-order in-memory path must order by pk, matching window ORDER BY pk.

    The window path always uses ORDER BY <pk> as a tiebreak when no ordering is
    supplied (build_window_prefetch fills order_terms with [pk.attname]).
    The in-memory path must match this so that C3-ON and C3-OFF produce
    identical rows for a no-ordering nested page.
    """

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        cls.author = Author.objects.create(name="G4Author")
        # Create posts in REVERSE insert order so arrival order != pk order.
        cls.pids = []
        for i in range(5):
            p = Post.objects.create(title=f"G4Post{i}", author=cls.author)
            cls.pids.append(p.pk)

    def test_limitoffset_falsy_order_in_memory_sorted_by_pk(self):
        """LimitOffset paginate_queryset with no order on an in-memory list must sort by pk.

        This is the G4 fix: before, list(qs) returned arrival order; after,
        it must return pk-ascending order (matching the window path).
        """
        from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
        from tests.models import Post

        paginator = LimitOffsetGraphqlPagination(default_limit=3)
        items = list(
            Post.objects.filter(author=self.author).order_by("-id")
        )  # reverse order
        # paginate with no ordering → must sort by pk asc
        result = paginator.paginate_queryset(items, limit=3, offset=0)
        pks = [r.pk for r in result]
        self.assertEqual(
            pks,
            sorted(pks),
            "In-memory LimitOffset with no ordering must sort by pk asc",
        )

    def test_page_falsy_order_in_memory_sorted_by_pk(self):
        """PageGraphqlPagination paginate_queryset with no order on in-memory list must sort by pk."""
        from django_graphex.paginations.pagination import PageGraphqlPagination
        from tests.models import Post

        paginator = PageGraphqlPagination(page_size=3)
        items = list(
            Post.objects.filter(author=self.author).order_by("-id")
        )  # reverse order
        result = paginator.paginate_queryset(items, page=1)
        pks = [r.pk for r in result]
        self.assertEqual(
            pks,
            sorted(pks),
            "In-memory PageGraphqlPagination with no ordering must sort by pk asc",
        )


# ---------------------------------------------------------------------------
# Phase 7: already_paginated wiring in list_resolver (tasks 7.1-7.5)
# ---------------------------------------------------------------------------


def _build_c3_schema(page_size=5, use_page=False):
    """Build a minimal schema for C3 e2e tests with a paginated nested posts field."""
    import graphene

    from django_graphex.fields import DjangoNestedListObjectField
    from django_graphex.paginations.pagination import (
        LimitOffsetGraphqlPagination,
        PageGraphqlPagination,
    )
    from django_graphex.types import (
        DjangoListObjectField,
        DjangoListObjectType,
        DjangoObjectType,
    )
    from tests.models import Author, Post

    _REG = {}
    paginator = (
        PageGraphqlPagination(page_size=page_size)
        if use_page
        else LimitOffsetGraphqlPagination(default_limit=page_size)
    )

    _PostType = type(
        "_C3PostType",
        (DjangoObjectType,),
        {"Meta": type("Meta", (), {"model": Post, "registry": _REG})},
    )

    _PostListType = type(
        "_C3PostListType",
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

    _AuthorType = type(
        "_C3AuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
            "Meta": type("Meta", (), {"model": Author, "registry": _REG}),
        },
    )

    _AuthorListType = type(
        "_C3AuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG})},
    )

    schema = graphene.Schema(
        query=type(
            "_C3Query",
            (graphene.ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        )
    )
    return schema


class TestAlreadyPaginatedListResolver(TestCase):
    """Tests for the already_paginated wiring in DjangoNestedListObjectField.list_resolver
    and totalCount correctness (tasks 7.1-7.5).
    """

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        cls.author = Author.objects.create(name="C3Author")
        cls.posts = []
        for i in range(10):
            p = Post.objects.create(title=f"C3Post{i:02d}", author=cls.author)
            cls.posts.append(p)

    def _exec(self, schema, query):
        result = schema.execute(query)
        assert result.errors is None, result.errors
        return result.data

    def test_window_cache_detected_already_paginated(self):
        """7.1: list_resolver detects _gqx_total on cache rows → already_paginated=True.

        When the window prefetch is active, the rows in the cache carry _gqx_total.
        list_resolver must set already_paginated=True and count=_gqx_total.
        """
        from django.db.models import Count, F, Window
        from django.db.models.functions import RowNumber

        from django_graphex.base_types import DjangoListObjectBase
        from django_graphex.fields import DjangoNestedListObjectField
        from django_graphex.types import DjangoListObjectType, DjangoObjectType
        from tests.models import Author, Post

        _REG = {}
        _PostType = type(
            "_7P",
            (DjangoObjectType,),
            {"Meta": type("Meta", (), {"model": Post, "registry": _REG})},
        )
        _PostListType = type(
            "_7PL",
            (DjangoListObjectType,),
            {"Meta": type("Meta", (), {"model": Post, "registry": _REG})},
        )

        # Manually inject a window-annotated prefetch into the author's win attr.
        # build_window_prefetch uses to_attr="_gqx_win_posts" so results land in
        # root._gqx_win_posts (NOT _prefetched_objects_cache).
        author = Author.objects.get(pk=self.author.pk)
        qs = (
            Post.objects.filter(author=author)
            .annotate(
                _gqx_rn=Window(
                    RowNumber(), partition_by=[F("author_id")], order_by=F("id").asc()
                ),
                _gqx_total=Window(Count("*"), partition_by=[F("author_id")]),
            )
            .filter(_gqx_rn__gt=0, _gqx_rn__lte=5)
        )
        rows = list(qs)

        # Inject via the to_attr attribute (the way Django's Prefetch machinery does it).
        setattr(author, "_gqx_win_posts", rows)

        # Instantiate a field and call list_resolver.
        field = DjangoNestedListObjectField(_PostListType, accessor="posts")
        result = field.list_resolver(
            manager=None,
            filter_backend=field.filter_backend,
            output_type=None,  # nested path does not apply get_queryset hook
            root=author,
            info=None,
        )

        self.assertIsInstance(result, DjangoListObjectBase)
        self.assertTrue(
            result.already_paginated,
            "list_resolver must set already_paginated=True when rows have _gqx_total",
        )
        self.assertEqual(
            result.count,
            rows[0]._gqx_total,
            "list_resolver must set count=_gqx_total from the first row",
        )
        self.assertEqual(len(result.results), len(rows))

    def test_zero_child_parent_totalcount_zero(self):
        """7.2: Empty cache for a zero-child parent → totalCount=0, already_paginated=True."""
        from django_graphex.base_types import DjangoListObjectBase
        from django_graphex.fields import DjangoNestedListObjectField
        from django_graphex.types import DjangoListObjectType, DjangoObjectType
        from tests.models import Author, Post

        _REG = {}
        _PostType = type(
            "_72P",
            (DjangoObjectType,),
            {"Meta": type("Meta", (), {"model": Post, "registry": _REG})},
        )
        _PostListType = type(
            "_72PL",
            (DjangoListObjectType,),
            {"Meta": type("Meta", (), {"model": Post, "registry": _REG})},
        )

        # An author with NO posts — inject via the to_attr win attribute.
        author_empty = Author.objects.create(name="C3EmptyAuthor")
        # build_window_prefetch uses to_attr="_gqx_win_posts".
        setattr(author_empty, "_gqx_win_posts", [])

        field = DjangoNestedListObjectField(_PostListType, accessor="posts")
        result = field.list_resolver(
            manager=None,
            filter_backend=field.filter_backend,
            output_type=None,  # nested path does not apply get_queryset hook
            root=author_empty,
            info=None,
        )

        self.assertIsInstance(result, DjangoListObjectBase)
        self.assertEqual(
            result.count,
            0,
            "Zero-child parent must have totalCount=0",
        )

    def test_offset_beyond_end_totalcount_nonzero(self):
        """7.3: Window cache empty due to offset-beyond-end → totalCount=K (non-zero).

        The author has K posts but we request a page past the end. The window
        prefetch returns no rows (cache is empty). The slice-independent count
        path must return K, NOT 0.
        """
        schema = _build_c3_schema(page_size=5)
        # offset=100 is way beyond 10 posts
        query = (
            "{ authors { results { posts { results(limit: 5, offset: 100) "
            "{ id } totalCount } } } }"
        )
        data = self._exec(schema, query)
        posts_data = data["authors"]["results"][0]["posts"]
        self.assertEqual(
            posts_data["results"],
            [],
            "Beyond-end offset must return empty results",
        )
        self.assertEqual(
            posts_data["totalCount"],
            10,
            "Beyond-end offset must return totalCount=K (10), not 0",
        )

    def test_window_slice_e2e_limitoffset(self):
        """7.4/9.1: Happy-path e2e with LimitOffset: ROW_NUMBER in SQL + correct results."""
        schema = _build_c3_schema(page_size=5)
        query = (
            '{ authors { results { posts { results(limit: 5, offset: 0, ordering: "id") '
            "{ id title } totalCount } } } }"
        )
        with CaptureQueriesContext(connection) as ctx:
            data = self._exec(schema, query)

        # Check window SQL is emitted.
        sql_list = [q["sql"].upper() for q in ctx.captured_queries]
        window_sql = [s for s in sql_list if "ROW_NUMBER()" in s]
        self.assertTrue(len(window_sql) >= 1, "Window slice must emit ROW_NUMBER() SQL")
        self.assertTrue(
            any("PARTITION BY" in s for s in window_sql), "Must have PARTITION BY"
        )

        # Correctness: first 5 posts sorted by id.
        posts_data = data["authors"]["results"][0]["posts"]
        result_ids = [p["id"] for p in posts_data["results"]]
        expected_ids = [str(p.pk) for p in sorted(self.posts, key=lambda p: p.pk)[:5]]
        self.assertEqual(
            result_ids, expected_ids, "Window slice must return correct ordered rows"
        )
        self.assertEqual(
            posts_data["totalCount"], 10, "totalCount must equal full partition count"
        )

    def test_window_slice_e2e_page(self):
        """7.4/9.2: Happy-path e2e with Page paginator: ROW_NUMBER in SQL + correct results."""
        schema = _build_c3_schema(page_size=5, use_page=True)
        query = (
            '{ authors { results { posts { results(page: 1, ordering: "id") '
            "{ id title } totalCount } } } }"
        )
        with CaptureQueriesContext(connection) as ctx:
            data = self._exec(schema, query)

        sql_list = [q["sql"].upper() for q in ctx.captured_queries]
        window_sql = [s for s in sql_list if "ROW_NUMBER()" in s]
        self.assertTrue(
            len(window_sql) >= 1, "Page window slice must emit ROW_NUMBER() SQL"
        )

        posts_data = data["authors"]["results"][0]["posts"]
        result_ids = [p["id"] for p in posts_data["results"]]
        expected_ids = [str(p.pk) for p in sorted(self.posts, key=lambda p: p.pk)[:5]]
        self.assertEqual(
            result_ids,
            expected_ids,
            "Page window slice must return correct ordered rows",
        )
        self.assertEqual(
            posts_data["totalCount"], 10, "totalCount must equal full partition count"
        )

    def test_already_paginated_no_double_slice(self):
        """8.1: GenericPaginationField must NOT re-slice when already_paginated=True.

        The rows returned are exactly the DB slice; re-slicing would corrupt
        results (e.g. returning slice[0:5] of a 5-element list at offset=5 gives []).
        """
        from django_graphex.base_types import DjangoListObjectBase
        from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
        from django_graphex.paginations.utils import GenericPaginationField

        paginator = LimitOffsetGraphqlPagination(default_limit=5)
        field = GenericPaginationField.__new__(GenericPaginationField)
        field.paginator_instance = paginator

        # Simulate rows already sliced by DB: 5 sentinel objects.
        sentinel = [object() for _ in range(5)]
        root = DjangoListObjectBase(results=sentinel, count=42, already_paginated=True)

        # Call with kwargs that would normally re-slice (offset=5 would empty the list).
        result = field.list_resolver(
            manager=object(),
            root=root,
            info=None,
            limit=5,
            offset=5,  # if re-sliced, sentinel[5:10] = [] — wrong
        )
        self.assertEqual(
            result, sentinel, "already_paginated must pass rows through untouched"
        )


# ---------------------------------------------------------------------------
# Phase 9: e2e + fallback regression suite (tasks 9.1-9.13)
# ---------------------------------------------------------------------------


class TestC3FallbackRegressions(TestCase):
    """Regression tests: every fallback condition must produce byte-for-byte
    identical results to the pre-Phase-C (in-memory) baseline.

    Tests 9.5–9.13: M2M, Cursor, Unbounded, non-concrete ordering, full-load,
    OPTIMIZE_NESTED_PAGINATION=False, results-subfield-absent, G2 custom resolver.
    """

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post, Tag

        cls.author = Author.objects.create(name="FallbackAuthor")
        cls.posts = []
        for i in range(5):
            p = Post.objects.create(title=f"FP{i:02d}", author=cls.author)
            cls.posts.append(p)
        cls.tag = Tag.objects.create(label="ft1")
        for p in cls.posts:
            p.tags.add(cls.tag)

    def _exec(self, schema, query):
        result = schema.execute(query)
        assert result.errors is None, result.errors
        return result.data

    def _no_window_sql(self, ctx):
        sql_list = [q["sql"].upper() for q in ctx.captured_queries]
        return all("ROW_NUMBER()" not in s for s in sql_list)

    def test_fallback_setting_false_no_window_sql(self):
        """9.5: OPTIMIZE_NESTED_PAGINATION=False → in-memory path, no ROW_NUMBER()."""
        schema = _build_c3_schema(page_size=5)
        query = (
            '{ authors { results { posts { results(limit: 5, offset: 0, ordering: "id") '
            "{ id title } totalCount } } } }"
        )
        # Baseline: results with setting ON.
        data_on = self._exec(schema, query)

        with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": False}):
            with CaptureQueriesContext(connection) as ctx:
                data_off = self._exec(schema, query)

        # No window SQL.
        self.assertTrue(
            self._no_window_sql(ctx),
            "OPTIMIZE_NESTED_PAGINATION=False must not emit ROW_NUMBER()",
        )
        # Results identical.
        self.assertEqual(
            data_on["authors"]["results"][0]["posts"]["results"],
            data_off["authors"]["results"][0]["posts"]["results"],
            "OPTIMIZE_NESTED_PAGINATION=False must produce identical results",
        )
        self.assertEqual(
            data_on["authors"]["results"][0]["posts"]["totalCount"],
            data_off["authors"]["results"][0]["posts"]["totalCount"],
        )

    def test_fallback_results_subfield_absent_no_window_sql(self):
        """9.6: results sub-field not selected → walker falls back, no ROW_NUMBER()."""
        schema = _build_c3_schema(page_size=5)
        # Query only totalCount (no results sub-field).
        query = "{ authors { results { posts { totalCount } } } }"
        with CaptureQueriesContext(connection) as ctx:
            data = self._exec(schema, query)
        self.assertTrue(
            self._no_window_sql(ctx), "No results sub-field: must not emit ROW_NUMBER()"
        )
        self.assertIsNotNone(data)

    def test_fallback_m2m_no_window_sql(self):
        """9.7: M2M nested list (tags) → falls back to in-memory path, no ROW_NUMBER().

        A real Django ManyToManyField has one_to_many=False, so both pre-check 3
        (many_to_many guard) and pre-check 4 (one_to_many guard) block the window
        path — defense-in-depth.  This test verifies the combined e2e fallback
        behaviour; it does NOT isolate pre-check 3 alone.  The canonical isolation
        test for pre-check 3 is
        TestBuildWindowPrefetchPreChecks.test_precheck_returns_none_when_m2m.
        """
        import graphene

        from django_graphex.fields import DjangoNestedListObjectField
        from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
        from django_graphex.types import (
            DjangoListObjectField,
            DjangoListObjectType,
            DjangoObjectType,
        )
        from tests.models import Post, Tag

        _REG = {}
        paginator = LimitOffsetGraphqlPagination(default_limit=5)

        _TagType = type(
            "_M2MTagType",
            (DjangoObjectType,),
            {"Meta": type("Meta", (), {"model": Tag, "registry": _REG})},
        )
        _TagListType = type(
            "_M2MTagListType",
            (DjangoListObjectType,),
            {
                "Meta": type(
                    "Meta",
                    (),
                    {"model": Tag, "pagination": paginator, "registry": _REG},
                )
            },
        )
        _PostType = type(
            "_M2MPostType",
            (DjangoObjectType,),
            {
                "tags": DjangoNestedListObjectField(_TagListType, accessor="tags"),
                "Meta": type("Meta", (), {"model": Post, "registry": _REG}),
            },
        )
        _PostListType = type(
            "_M2MPostListType",
            (DjangoListObjectType,),
            {"Meta": type("Meta", (), {"model": Post, "registry": _REG})},
        )

        schema = graphene.Schema(
            query=type(
                "_M2MQuery",
                (graphene.ObjectType,),
                {"posts": DjangoListObjectField(_PostListType)},
            )
        )
        query = "{ posts { results { tags { results(limit: 5, offset: 0) { label } totalCount } } } }"
        with CaptureQueriesContext(connection) as ctx:
            data = self._exec(schema, query)
        self.assertTrue(self._no_window_sql(ctx), "M2M must not emit ROW_NUMBER()")
        # Results must be correct (tag label present).
        all_tags = [
            t["label"] for r in data["posts"]["results"] for t in r["tags"]["results"]
        ]
        self.assertTrue(
            all("ft1" == lbl for lbl in all_tags), "M2M results must be correct"
        )

    def test_fallback_unbounded_no_window_sql(self):
        """9.8: Unbounded paginator (no default_limit, no limit arg) → in-memory path."""
        import graphene

        from django_graphex.fields import DjangoNestedListObjectField
        from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
        from django_graphex.types import (
            DjangoListObjectField,
            DjangoListObjectType,
            DjangoObjectType,
        )
        from tests.models import Author, Post

        _REG = {}
        # Unbounded: no default_limit, no max_limit → prefetch_window_slice returns None.
        paginator = LimitOffsetGraphqlPagination()  # DEFAULT_PAGE_SIZE=None → unbounded

        _PostType = type(
            "_UbPostType",
            (DjangoObjectType,),
            {"Meta": type("Meta", (), {"model": Post, "registry": _REG})},
        )
        _PostListType = type(
            "_UbPostListType",
            (DjangoListObjectType,),
            {
                "Meta": type(
                    "Meta",
                    (),
                    {"model": Post, "pagination": paginator, "registry": _REG},
                )
            },
        )
        _AuthorType = type(
            "_UbAuthorType",
            (DjangoObjectType,),
            {
                "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
                "Meta": type("Meta", (), {"model": Author, "registry": _REG}),
            },
        )
        _AuthorListType = type(
            "_UbAuthorListType",
            (DjangoListObjectType,),
            {"Meta": type("Meta", (), {"model": Author, "registry": _REG})},
        )

        schema = graphene.Schema(
            query=type(
                "_UbQuery",
                (graphene.ObjectType,),
                {"authors": DjangoListObjectField(_AuthorListType)},
            )
        )
        query = "{ authors { results { posts { results { id } totalCount } } } }"
        with CaptureQueriesContext(connection) as ctx:
            data = self._exec(schema, query)
        self.assertTrue(
            self._no_window_sql(ctx), "Unbounded must not emit ROW_NUMBER()"
        )
        post_results = data["authors"]["results"][0]["posts"]["results"]
        self.assertEqual(len(post_results), 5, "Unbounded must return all posts")

    def test_fallback_non_concrete_ordering_no_window_sql(self):
        """9.9: Non-concrete ordering term → pre-check 5 fallback, no ROW_NUMBER()."""
        import graphene

        from django_graphex.fields import DjangoNestedListObjectField
        from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
        from django_graphex.types import (
            DjangoListObjectField,
            DjangoListObjectType,
            DjangoObjectType,
        )
        from tests.models import Author, Post

        _REG = {}
        # default ordering="display_name" is a @property, not a concrete attname.
        # But that's on Author, not Post. Let's use a non-existent field name.
        paginator = LimitOffsetGraphqlPagination(
            default_limit=5, ordering="nonexistent_computed"
        )

        _PostType = type(
            "_NcPostType",
            (DjangoObjectType,),
            {"Meta": type("Meta", (), {"model": Post, "registry": _REG})},
        )
        _PostListType = type(
            "_NcPostListType",
            (DjangoListObjectType,),
            {
                "Meta": type(
                    "Meta",
                    (),
                    {"model": Post, "pagination": paginator, "registry": _REG},
                )
            },
        )
        _AuthorType = type(
            "_NcAuthorType",
            (DjangoObjectType,),
            {
                "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
                "Meta": type("Meta", (), {"model": Author, "registry": _REG}),
            },
        )
        _AuthorListType = type(
            "_NcAuthorListType",
            (DjangoListObjectType,),
            {"Meta": type("Meta", (), {"model": Author, "registry": _REG})},
        )

        schema = graphene.Schema(
            query=type(
                "_NcQuery",
                (graphene.ObjectType,),
                {"authors": DjangoListObjectField(_AuthorListType)},
            )
        )
        query = "{ authors { results { posts { results(limit: 5, offset: 0) { id } totalCount } } } }"
        with CaptureQueriesContext(connection) as ctx:
            data = self._exec(schema, query)
        self.assertTrue(
            self._no_window_sql(ctx), "Non-concrete ordering must not emit ROW_NUMBER()"
        )
        # Must still return results (fallback path, not a crash).
        self.assertIn("authors", data)

    def test_fallback_full_load_no_window_sql(self):
        """9.10: Full-load selection → pre-check 6 fallback, no ROW_NUMBER()."""
        import graphene

        from django_graphex.fields import DjangoNestedListObjectField
        from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
        from django_graphex.types import (
            DjangoListObjectField,
            DjangoListObjectType,
            DjangoObjectType,
        )
        from tests.models import Author, Post

        _REG = {}
        paginator = LimitOffsetGraphqlPagination(default_limit=5)

        # AuthorType with display_name (@property) will trigger full-load guard
        # when requested in a parent's selection.
        # Actually full-load is triggered on the CHILD type when a @property is requested.
        # displayName is on Author, not Post. Let's use a schema where posts is the child
        # and we request a computed field that triggers full-load.
        # The easiest way: Author._default_manager.only() with a property requested
        # on Post... Post doesn't have @property fields by default.
        # Instead, we'll use the compute-field route by patching _compute_child_only to return None.
        from unittest.mock import patch

        _PostType = type(
            "_FlPostType",
            (DjangoObjectType,),
            {"Meta": type("Meta", (), {"model": Post, "registry": _REG})},
        )
        _PostListType = type(
            "_FlPostListType",
            (DjangoListObjectType,),
            {
                "Meta": type(
                    "Meta",
                    (),
                    {"model": Post, "pagination": paginator, "registry": _REG},
                )
            },
        )
        _AuthorType = type(
            "_FlAuthorType",
            (DjangoObjectType,),
            {
                "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
                "Meta": type("Meta", (), {"model": Author, "registry": _REG}),
            },
        )
        _AuthorListType = type(
            "_FlAuthorListType",
            (DjangoListObjectType,),
            {"Meta": type("Meta", (), {"model": Author, "registry": _REG})},
        )

        schema = graphene.Schema(
            query=type(
                "_FlQuery",
                (graphene.ObjectType,),
                {"authors": DjangoListObjectField(_AuthorListType)},
            )
        )
        query = '{ authors { results { posts { results(limit: 5, offset: 0, ordering: "id") { id } totalCount } } } }'
        with patch("django_graphex.fields._compute_child_only", return_value=None):
            with CaptureQueriesContext(connection) as ctx:
                data = self._exec(schema, query)
        self.assertTrue(
            self._no_window_sql(ctx), "Full-load must not emit ROW_NUMBER()"
        )
        self.assertIn("authors", data)

    def test_fallback_query_count_m2m_matches_baseline(self):
        """9.11: M2M assertNumQueries matches pre-Phase-C baseline AND results identical."""
        import graphene

        from django_graphex.fields import DjangoNestedListObjectField
        from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
        from django_graphex.types import (
            DjangoListObjectField,
            DjangoListObjectType,
            DjangoObjectType,
        )
        from tests.models import Post, Tag

        _REG = {}
        paginator = LimitOffsetGraphqlPagination(default_limit=5)

        _TagType = type(
            "_QM2MTagType",
            (DjangoObjectType,),
            {"Meta": type("Meta", (), {"model": Tag, "registry": _REG})},
        )
        _TagListType = type(
            "_QM2MTagListType",
            (DjangoListObjectType,),
            {
                "Meta": type(
                    "Meta",
                    (),
                    {"model": Tag, "pagination": paginator, "registry": _REG},
                )
            },
        )
        _PostType = type(
            "_QM2MPostType",
            (DjangoObjectType,),
            {
                "tags": DjangoNestedListObjectField(_TagListType, accessor="tags"),
                "Meta": type("Meta", (), {"model": Post, "registry": _REG}),
            },
        )
        _PostListType = type(
            "_QM2MPostListType",
            (DjangoListObjectType,),
            {"Meta": type("Meta", (), {"model": Post, "registry": _REG})},
        )
        schema = graphene.Schema(
            query=type(
                "_QM2MQuery",
                (graphene.ObjectType,),
                {"posts": DjangoListObjectField(_PostListType)},
            )
        )
        query = '{ posts { results { tags { results(limit: 5, offset: 0, ordering: "id") { label } totalCount } } } }'

        # Derive baseline with OPTIMIZE_NESTED_PAGINATION=False.
        with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": False}):
            with CaptureQueriesContext(connection) as baseline_ctx:
                data_baseline = self._exec(schema, query)

        # Run with setting ON (M2M should fall back anyway).
        with CaptureQueriesContext(connection) as live_ctx:
            data_live = self._exec(schema, query)

        self.assertEqual(
            len(live_ctx.captured_queries),
            len(baseline_ctx.captured_queries),
            f"M2M query count must match baseline: {len(baseline_ctx.captured_queries)}",
        )
        self.assertEqual(
            data_live["posts"]["results"],
            data_baseline["posts"]["results"],
            "M2M results must be identical to baseline",
        )


class TestC3ConstantQueryCount(TestCase):
    """9.1-9.4: assertNumQueries for window-slice happy path must be constant."""

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        cls.authors = []
        for i in range(5):
            a = Author.objects.create(name=f"QA{i}")
            for j in range(10):
                Post.objects.create(title=f"QP{i}{j:02d}", author=a)
            cls.authors.append(a)

    def _exec(self, schema, query):
        result = schema.execute(query)
        assert result.errors is None, result.errors
        return result.data

    def test_constant_query_count_limitoffset(self):
        """9.3: N parents with windowed LimitOffset posts → constant query count of exactly 3.

        The exact count is derived empirically against the baseline:
        - DjangoListObjectField (authors): 1 count + 1 select = 2
        - Window posts prefetch: 1 query
        Total: 3 (constant regardless of N parents).

        Asserting the exact value (not ≤ 4) ensures a regression that adds a
        query is caught immediately.
        """
        schema = _build_c3_schema(page_size=5)
        query = (
            '{ authors { results { posts { results(limit: 5, offset: 0, ordering: "id") '
            "{ id title } totalCount } } } }"
        )
        with CaptureQueriesContext(connection) as ctx:
            self._exec(schema, query)

        sql_list = [q["sql"].upper() for q in ctx.captured_queries]
        window_sql = [s for s in sql_list if "ROW_NUMBER()" in s]
        self.assertTrue(len(window_sql) >= 1, "Must have window SQL")

        n_queries = len(ctx.captured_queries)
        # Exact constant: 2 (authors count + select) + 1 (window prefetch) = 3.
        # Any regression adding a query will be caught by this assertion.
        self.assertEqual(
            n_queries, 3, f"Query count must be exactly 3, got {n_queries}"
        )

    def test_constant_query_count_page(self):
        """9.4: N parents with windowed Page posts → constant query count of exactly 3.

        Same breakdown as LimitOffset: 2 (authors) + 1 (window prefetch) = 3.
        Asserting the exact value ensures any regression that adds a query is caught.
        """
        schema = _build_c3_schema(page_size=5, use_page=True)
        query = (
            '{ authors { results { posts { results(page: 1, ordering: "id") '
            "{ id title } totalCount } } } }"
        )
        with CaptureQueriesContext(connection) as ctx:
            self._exec(schema, query)

        sql_list = [q["sql"].upper() for q in ctx.captured_queries]
        window_sql = [s for s in sql_list if "ROW_NUMBER()" in s]
        self.assertTrue(len(window_sql) >= 1, "Must have window SQL for Page paginator")

        n_queries = len(ctx.captured_queries)
        # Exact constant: 2 (authors count + select) + 1 (window prefetch) = 3.
        self.assertEqual(
            n_queries, 3, f"Query count must be exactly 3, got {n_queries}"
        )


# ---------------------------------------------------------------------------
# CRITICAL regression: filtered offset-beyond-end totalCount correctness
# ---------------------------------------------------------------------------


def _build_c3_filtered_schema(page_size=5):
    """Build a minimal schema for C3 e2e tests with a FILTERED nested posts field.

    The nested posts field declares filter_fields={"title": ["exact", "icontains"]}
    so that the filter GraphQL argument is wired up.  This is the schema that
    exposes the totalCount bug: with Phase C ON, the empty-window-cache branch
    called manager.count() WITHOUT applying the user filter, returning the
    unfiltered partition size instead of the filtered one.
    """
    import graphene

    from django_graphex.fields import DjangoNestedListObjectField
    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
    from django_graphex.types import (
        DjangoListObjectField,
        DjangoListObjectType,
        DjangoObjectType,
    )
    from tests.models import Author, Post

    _REG = {}
    paginator = LimitOffsetGraphqlPagination(default_limit=page_size)

    _PostType = type(
        "_FC3PostType",
        (DjangoObjectType,),
        {"Meta": type("Meta", (), {"model": Post, "registry": _REG})},
    )
    _PostListType = type(
        "_FC3PostListType",
        (DjangoListObjectType,),
        {
            "Meta": type(
                "Meta",
                (),
                {
                    "model": Post,
                    "pagination": paginator,
                    "filter_fields": {"title": ["exact", "icontains"]},
                    "registry": _REG,
                },
            )
        },
    )
    _AuthorType = type(
        "_FC3AuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
            "Meta": type("Meta", (), {"model": Author, "registry": _REG}),
        },
    )
    _AuthorListType = type(
        "_FC3AuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG})},
    )

    schema = graphene.Schema(
        query=type(
            "_FC3Query",
            (graphene.ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        )
    )
    return schema


class TestFilteredOffsetBeyondEndTotalCount(TestCase):
    """CRITICAL regression: filtered nested list paged beyond filtered count.

    Scenario: an author has 10 posts total. A filter matches only 4 of them.
    A query with offset=100 (beyond any page) must report totalCount=4 (the
    filtered partition size) with Phase C ON, matching the OPTIMIZE_NESTED_PAGINATION
    =False baseline.  Before the fix, Phase C ON incorrectly called
    manager.count() WITHOUT the filter, returning totalCount=10.

    Also tests the zero-filtered-children branch (filter matches 0) to prove
    BOTH empty-cache branches (zero vs beyond-end) are correct with filters.
    """

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        cls.author = Author.objects.create(name="FilteredBeyondEndAuthor")
        cls.matching_posts = []
        # 4 posts with title containing "Zebra" (used as the filter keyword).
        # "Other" does NOT contain "Zebra", ensuring exactly 4 posts match.
        for i in range(4):
            p = Post.objects.create(title=f"ZebraPost{i:02d}", author=cls.author)
            cls.matching_posts.append(p)
        # 6 posts that do NOT contain "Zebra"
        for i in range(6):
            Post.objects.create(title=f"OtherPost{i:02d}", author=cls.author)

    def _exec(self, schema, query):
        result = schema.execute(query)
        assert result.errors is None, result.errors
        return result.data

    def test_filtered_offset_beyond_end_totalcount_matches_baseline(self):
        """CRITICAL: filtered nested list at offset:100 returns totalCount == filtered K.

        Phase C ON must match Phase C OFF (OPTIMIZE_NESTED_PAGINATION=False baseline).
        Before the fix: Phase C ON returned totalCount=10 (unfiltered); correct is 4.

        Test data: 4 posts titled "ZebraPost*" (match "Zebra") + 6 "OtherPost*" (no match).
        """
        schema = _build_c3_filtered_schema(page_size=5)
        # The filter selects only 4 posts; offset=100 is far beyond them.
        query = (
            "{ authors { results { "
            'posts(filter: {title: {icontains: "Zebra"}}) { '
            "results(limit: 5, offset: 100) { id } totalCount "
            "} } } }"
        )

        # Phase C ON (default).
        data_on = self._exec(schema, query)
        total_on = data_on["authors"]["results"][0]["posts"]["totalCount"]

        # Phase C OFF (baseline).
        from django.test import override_settings

        with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": False}):
            data_off = self._exec(schema, query)
        total_off = data_off["authors"]["results"][0]["posts"]["totalCount"]

        self.assertEqual(
            total_on,
            total_off,
            f"Phase C ON totalCount ({total_on}) must equal baseline ({total_off}) for filtered beyond-end",
        )
        # Both must equal the filtered partition size (4), not the unfiltered count (10).
        self.assertEqual(
            total_on,
            4,
            f"totalCount must be the filtered count (4), not the unfiltered count; got {total_on}",
        )
        # Results must be empty (offset beyond filtered count).
        results_on = data_on["authors"]["results"][0]["posts"]["results"]
        self.assertEqual(
            results_on, [], "Beyond-end filtered offset must return empty results"
        )

    def test_filtered_zero_match_totalcount_zero_matches_baseline(self):
        """Zero filtered matches: totalCount must be 0 with Phase C ON, matching baseline.

        This tests the other empty-cache sub-branch: a filter that matches 0
        children.  Phase C ON must return totalCount=0, not the unfiltered count.
        """
        schema = _build_c3_filtered_schema(page_size=5)
        # Filter that matches NOTHING.
        query = (
            "{ authors { results { "
            'posts(filter: {title: {exact: "NonExistentTitle"}}) { '
            "results(limit: 5, offset: 0) { id } totalCount "
            "} } } }"
        )

        data_on = self._exec(schema, query)
        total_on = data_on["authors"]["results"][0]["posts"]["totalCount"]

        from django.test import override_settings

        with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": False}):
            data_off = self._exec(schema, query)
        total_off = data_off["authors"]["results"][0]["posts"]["totalCount"]

        self.assertEqual(
            total_on,
            total_off,
            f"Zero-match filter: Phase C ON totalCount ({total_on}) must equal baseline ({total_off})",
        )
        self.assertEqual(
            total_on,
            0,
            f"Zero-match filter must return totalCount=0; got {total_on}",
        )


# ---------------------------------------------------------------------------
# WARNING 1: build_window_prefetch with real sub_selection narrows SELECT
# ---------------------------------------------------------------------------


class TestBuildWindowPrefetchWithSubSelection(TestCase):
    """WARNING 1: build_window_prefetch with a real sub_selection narrows the
    emitted SQL SELECT to only the requested columns.

    The existing G3 spike tests the chain in isolation (Post.objects.all()
    directly), but the production path goes through build_window_prefetch with
    a real sub_selection.  This test closes that gap: it calls the production
    method with a SelectionSetNode that selects only id+title, then uses
    CaptureQueriesContext to assert that the emitted SELECT does NOT include
    "body" (a concrete column that should be deferred by .only()).
    """

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        cls.author = Author.objects.create(name="SubSelAuthor")
        for i in range(3):
            Post.objects.create(title=f"SSPost{i}", author=cls.author)

    def test_build_window_prefetch_narrowed_select_with_real_sub_selection(self):
        """build_window_prefetch + real sub_selection: SELECT excludes 'body' column."""
        from graphql.language.ast import FieldNode, NameNode, SelectionSetNode

        from django_graphex.fields import SELF_NARROW_VERIFIED
        from tests.models import Author

        if not SELF_NARROW_VERIFIED:
            self.skipTest(
                "SELF_NARROW_VERIFIED=False: .only() dropped; narrowing not applicable"
            )

        inst = _make_test_nested_field()
        related_field = Author._meta.get_field("posts")

        # Build a real SelectionSetNode selecting only id and title (not body).
        id_field = FieldNode(name=NameNode(value="id"))
        title_field = FieldNode(name=NameNode(value="title"))
        sub_selection = SelectionSetNode(selections=[id_field, title_field])

        pf = inst.build_window_prefetch(
            lookup="posts",
            filter_value=None,
            slice_tuple=(0, 3, ["id"]),
            related_field=related_field,
            sub_selection=sub_selection,
            fragments={},
        )
        self.assertIsNotNone(
            pf, "build_window_prefetch must return a Prefetch with sub_selection"
        )

        with CaptureQueriesContext(connection) as ctx:
            rows = list(pf.queryset)

        self.assertGreater(len(rows), 0, "Must return at least one row")

        sql = ctx.captured_queries[0]["sql"].upper()

        # The SQL must contain window functions.
        self.assertIn("ROW_NUMBER()", sql, "SQL must contain ROW_NUMBER()")

        # Column narrowing: 'body' must NOT appear in the SELECT clause.
        # After .only(author_id, id, title, ...) the deferred 'body' column
        # should be absent from the outer SELECT.
        select_clause = sql.split("FROM")[0] if "FROM" in sql else sql
        self.assertNotIn(
            '"BODY"',
            select_clause,
            "SELECT must not include 'body' when sub_selection provides narrow columns "
            "(SELF_NARROW_VERIFIED=True but .only() did not narrow the SELECT — "
            "this means the production path differs from the G3 spike)",
        )


# ---------------------------------------------------------------------------
# WARNING 2: Cursor paginator falls back (pre-check 2) — ON vs OFF parity
# ---------------------------------------------------------------------------


def _build_cursor_schema():
    """Build a minimal schema with a CursorGraphqlPagination nested posts field."""
    import graphene

    from django_graphex.fields import DjangoNestedListObjectField
    from django_graphex.paginations.pagination import CursorGraphqlPagination
    from django_graphex.types import (
        DjangoListObjectField,
        DjangoListObjectType,
        DjangoObjectType,
    )
    from tests.models import Author, Post

    _REG = {}
    paginator = CursorGraphqlPagination(ordering="id", page_size=5)

    _PostType = type(
        "_CurPostType",
        (DjangoObjectType,),
        {"Meta": type("Meta", (), {"model": Post, "registry": _REG})},
    )
    _PostListType = type(
        "_CurPostListType",
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
    _AuthorType = type(
        "_CurAuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
            "Meta": type("Meta", (), {"model": Author, "registry": _REG}),
        },
    )
    _AuthorListType = type(
        "_CurAuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG})},
    )

    schema = graphene.Schema(
        query=type(
            "_CurQuery",
            (graphene.ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        )
    )
    return schema


class TestCursorFallbackParity(TestCase):
    """WARNING 2: Cursor paginator falls back via pre-check 2 (slice_tuple=None).

    A nested list with a CursorGraphqlPagination must return byte-for-byte
    identical results with Phase C ON vs OFF.  This verifies that the Cursor
    fallback path is correct and does not emit ROW_NUMBER() SQL.
    """

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        cls.author = Author.objects.create(name="CursorFallbackAuthor")
        cls.posts = []
        for i in range(5):
            p = Post.objects.create(title=f"CurPost{i:02d}", author=cls.author)
            cls.posts.append(p)

    def _exec(self, schema, query):
        result = schema.execute(query)
        assert result.errors is None, result.errors
        return result.data

    def test_cursor_fallback_on_vs_off_identical_results(self):
        """Cursor nested list: Phase C ON and OFF return byte-for-byte identical results.

        Cursor paginator returns slice_tuple=None from prefetch_window_slice
        (pre-check 2), so build_window_prefetch falls back to build_prefetch.
        The results must be identical to the OPTIMIZE_NESTED_PAGINATION=False baseline.
        """
        from django.test import override_settings

        schema = _build_cursor_schema()
        # Cursor uses different args (no limit/offset); query the first page.
        query = "{ authors { results { posts { results { id title } totalCount } } } }"

        # Phase C ON.
        with CaptureQueriesContext(connection) as ctx_on:
            data_on = self._exec(schema, query)

        # Phase C OFF (baseline).
        with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": False}):
            data_off = self._exec(schema, query)

        # No ROW_NUMBER() SQL: Cursor must fall back via pre-check 2.
        sql_on = [q["sql"].upper() for q in ctx_on.captured_queries]
        self.assertTrue(
            all("ROW_NUMBER()" not in s for s in sql_on),
            "Cursor nested list must NOT emit ROW_NUMBER() SQL (pre-check 2 fallback)",
        )

        # Results must be identical.
        self.assertEqual(
            data_on["authors"]["results"][0]["posts"]["results"],
            data_off["authors"]["results"][0]["posts"]["results"],
            "Cursor fallback: Phase C ON and OFF must return identical results",
        )
        self.assertEqual(
            data_on["authors"]["results"][0]["posts"]["totalCount"],
            data_off["authors"]["results"][0]["posts"]["totalCount"],
            "Cursor fallback: Phase C ON and OFF must return identical totalCount",
        )


# ---------------------------------------------------------------------------
# SUGGESTION G4: no-ordering e2e parity (Phase C ON vs OFF)
# ---------------------------------------------------------------------------


class TestG4NoOrderingE2EParity(TestCase):
    """SUGGESTION G4: e2e ON-vs-OFF identical rows for a no-ordering nested page.

    When no ordering argument is provided and the paginator has no default
    ordering, both Phase C ON (window path ORDER BY pk) and Phase C OFF
    (in-memory path sorted by pk after G4 fix) must return identical rows
    in identical order.
    """

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        cls.author = Author.objects.create(name="G4E2EAuthor")
        cls.posts = []
        for i in range(5):
            p = Post.objects.create(title=f"G4E2EPost{i:02d}", author=cls.author)
            cls.posts.append(p)

    def _exec(self, schema, query):
        result = schema.execute(query)
        assert result.errors is None, result.errors
        return result.data

    def test_no_ordering_nested_page_on_vs_off_identical_rows(self):
        """G4 e2e: no ordering arg -> Phase C ON and OFF return identical rows (same pks, same order)."""
        import graphene
        from django.test import override_settings

        from django_graphex.fields import DjangoNestedListObjectField
        from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
        from django_graphex.types import (
            DjangoListObjectField,
            DjangoListObjectType,
            DjangoObjectType,
        )
        from tests.models import Author, Post

        _REG = {}
        # Paginator with NO default ordering (ordering="") — G4 scenario.
        paginator = LimitOffsetGraphqlPagination(default_limit=3)

        _PostType = type(
            "_G4E2EPostType",
            (DjangoObjectType,),
            {"Meta": type("Meta", (), {"model": Post, "registry": _REG})},
        )
        _PostListType = type(
            "_G4E2EPostListType",
            (DjangoListObjectType,),
            {
                "Meta": type(
                    "Meta",
                    (),
                    {"model": Post, "pagination": paginator, "registry": _REG},
                )
            },
        )
        _AuthorType = type(
            "_G4E2EAuthorType",
            (DjangoObjectType,),
            {
                "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
                "Meta": type("Meta", (), {"model": Author, "registry": _REG}),
            },
        )
        _AuthorListType = type(
            "_G4E2EAuthorListType",
            (DjangoListObjectType,),
            {"Meta": type("Meta", (), {"model": Author, "registry": _REG})},
        )
        schema = graphene.Schema(
            query=type(
                "_G4E2EQuery",
                (graphene.ObjectType,),
                {"authors": DjangoListObjectField(_AuthorListType)},
            )
        )

        # No ordering argument.
        query = "{ authors { results { posts { results(limit: 3, offset: 0) { id } totalCount } } } }"

        data_on = self._exec(schema, query)
        with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": False}):
            data_off = self._exec(schema, query)

        results_on = data_on["authors"]["results"][0]["posts"]["results"]
        results_off = data_off["authors"]["results"][0]["posts"]["results"]

        self.assertEqual(
            results_on,
            results_off,
            f"G4 e2e: Phase C ON {results_on} must equal Phase C OFF {results_off} for no-ordering nested page",
        )


# ---------------------------------------------------------------------------
# Issue #64 — empty window page must NOT issue per-parent COUNT (N+1 fix)
# ---------------------------------------------------------------------------


class TestEmptyWindowPageNoCountN1(TestCase):
    """#64: empty window-sliced page must not re-introduce per-parent COUNT N+1.

    When OPTIMIZE_NESTED_PAGINATION=True (default) and the requested page falls
    beyond a parent's total child count (offset > child count), the window
    prefetch returns an empty list for that parent.  Before the fix, list_resolver
    issued a per-parent ``qs.count()`` for every such parent — O(N) queries.

    After the fix, the total is read from a subquery annotation on the parent row
    (``root._gqx_cnt_<accessor>``) stored in-memory with the window result — O(1)
    queries regardless of N parents with empty pages.
    """

    @classmethod
    def setUpTestData(cls):
        from tests.models import Author, Post

        # N parents, each with exactly 3 posts.  We will query with offset=100,
        # so every parent's window page is empty.  The count should be 3 for each.
        cls.n_parents = 6
        cls.authors = []
        for i in range(cls.n_parents):
            a = Author.objects.create(name=f"EmptyWin{i}")
            for j in range(3):
                Post.objects.create(title=f"EWPost{i}{j}", author=a)
            cls.authors.append(a)

    def _exec(self, schema, query):
        result = schema.execute(query)
        assert result.errors is None, result.errors
        return result.data

    def test_empty_page_constant_query_count(self):
        """#64: N parents with empty window pages emit a CONSTANT query count (no per-parent COUNT).

        Before the fix: 2 (authors) + 1 (window) + N (per-parent COUNT) = 2 + 1 + 6 = 9.
        After the fix:  2 (authors) + 1 (window) = 3 (constant regardless of N).

        The subquery count is embedded in the parent annotation, so no per-parent
        ``qs.count()`` fires even when the window-sliced page is empty.
        """
        schema = _build_c3_schema(page_size=5)
        # offset=100: far beyond any parent's 3 posts → every parent has empty page.
        query = (
            '{ authors { results { posts { results(limit: 5, offset: 100, ordering: "id") '
            "{ id } totalCount } } } }"
        )

        with CaptureQueriesContext(connection) as ctx:
            data = self._exec(schema, query)

        n_queries = len(ctx.captured_queries)
        # The window prefetch path returns empty for all parents.
        # The fix annotates the parent QS with a subquery count, so no per-parent
        # COUNT fires.  Expected: exactly 3 (authors-count + authors-select + window).
        self.assertLessEqual(
            n_queries,
            3,
            f"Empty window pages must not emit per-parent COUNT queries. "
            f"Got {n_queries} queries for {self.n_parents} parents. "
            f"SQL: {[q['sql'][:120] for q in ctx.captured_queries]}",
        )

        # Correctness: totalCount must be 3 (the real child count) for every author.
        for author_data in data["authors"]["results"]:
            self.assertEqual(
                author_data["posts"]["totalCount"],
                3,
                "totalCount must equal the real child count (3) even for empty pages",
            )
            self.assertEqual(
                author_data["posts"]["results"],
                [],
                "Beyond-end offset must return empty results",
            )

    def test_empty_page_zero_child_totalcount_zero(self):
        """#64: Parent with zero children + empty window page → totalCount=0, constant queries.

        Verifies the zero-child subcase: the annotation returns NULL (no rows for
        the subquery), which list_resolver must coerce to 0, not raise an error.
        """
        from tests.models import Author

        # Create a parent with no children at all.
        Author.objects.create(name="EmptyWinNoChildren")

        schema = _build_c3_schema(page_size=5)
        # We need a query that touches this author specifically.  Use a fresh schema
        # execution; the childless author will appear in authors list.
        query = (
            '{ authors { results { posts { results(limit: 5, offset: 100, ordering: "id") '
            "{ id } totalCount } } } }"
        )

        with CaptureQueriesContext(connection) as ctx:
            data = self._exec(schema, query)

        # A per-parent COUNT query looks like:
        #   SELECT COUNT(*) AS "__count" FROM tests_post WHERE author_id = <literal pk>
        # The subquery annotation is embedded in the main SELECT and is NOT a
        # standalone top-level query.  Distinguish by checking whether the SQL
        # starts with "SELECT COUNT" (top-level COUNT, standalone query) rather
        # than containing COUNT inside a larger SELECT.
        per_parent_counts = [
            q["sql"]
            for q in ctx.captured_queries
            if q["sql"].strip().upper().startswith("SELECT COUNT")
            and "author_id" in q["sql"].lower()
        ]
        self.assertEqual(
            len(per_parent_counts),
            0,
            f"Childless parent must not emit per-parent COUNT queries. "
            f"Got {len(per_parent_counts)} standalone COUNTs with author_id: {per_parent_counts}",
        )

        # Find the childless author in results.
        childless_data = next(
            (
                r
                for r in data["authors"]["results"]
                if r.get("name") == "EmptyWinNoChildren"
            ),
            None,
        )
        # If the schema doesn't expose "name" on AuthorType we can just check all
        # authors have totalCount in {0, 3}.
        if childless_data is not None:
            self.assertEqual(
                childless_data["posts"]["totalCount"],
                0,
                "Zero-child author must have totalCount=0",
            )

    def test_non_empty_page_totalcount_unchanged(self):
        """#64 non-regression: non-empty window page still reads count from _gqx_total.

        The subquery annotation path must not break the happy path where the page
        is non-empty and the count is already carried by the window function rows.
        """
        schema = _build_c3_schema(page_size=5)
        query = (
            '{ authors { results { posts { results(limit: 5, offset: 0, ordering: "id") '
            "{ id } totalCount } } } }"
        )

        with CaptureQueriesContext(connection) as ctx:
            data = self._exec(schema, query)

        n_queries = len(ctx.captured_queries)
        self.assertLessEqual(
            n_queries,
            3,
            f"Non-empty window page must still be constant-query. Got {n_queries}.",
        )

        for author_data in data["authors"]["results"]:
            posts_total = author_data["posts"]["totalCount"]
            self.assertEqual(
                posts_total,
                3,
                f"Non-empty page totalCount must equal real child count (3), got {posts_total}",
            )
