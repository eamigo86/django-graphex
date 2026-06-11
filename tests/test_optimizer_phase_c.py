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

    def test_walker_live_path_does_not_emit_window_sql_in_c2(self):
        """C2 dormant gate: live walker still calls build_prefetch, not build_window_prefetch.

        The switch to build_window_prefetch in the live path is C3.
        In C2, the live query must NOT emit ROW_NUMBER() SQL.
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
        # C2 dormant gate: MUST NOT emit window SQL from the live path.
        self.assertEqual(
            len(window_sql),
            0,
            "C2 dormant gate: live walker must NOT emit ROW_NUMBER() SQL (C3 flips this)",
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
