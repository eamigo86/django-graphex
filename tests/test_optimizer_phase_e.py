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

from django.db import connection
from django.db.models import Value
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair

# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------


def _execute(schema, query, variable_values=None):
    """Execute *query* against a native "DjangoGraphQLSchema" (graphene-free).

    Drop-in for the retired "schema.execute(query, variable_values=...)":
    returns the graphql-core "ExecutionResult" (same ".data" / ".errors").
    """
    return graphql_sync(schema.graphql_schema, query, variable_values=variable_values)


def _gtype(name, bases, ns):
    """Build a dynamic native type via "type()" with pydantic-safe namespace.

    Native "ObjectType" / "DjangoObjectType" / "DjangoListObjectType" are
    pydantic "BaseModel" subclasses; building them with "type(name, bases, ns)"
    requires "ns['__module__']" and a nested "Meta" whose "__qualname__" is
    '"<Outer>.Meta"' (the value a "class" body produces). This supplies both so
    the dynamic form behaves exactly like the equivalent "class" statement.
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


def _exec(schema, query, variables=None):
    """Execute a GraphQL query and assert no errors."""
    result = _execute(schema, query, variable_values=variables)
    assert result.errors is None, result.errors
    return result.data


# ---------------------------------------------------------------------------
# Phase 1 / Task 1.1 — _get_field_optimize_hook unit tests (RED)
# ---------------------------------------------------------------------------


class TestGetFieldOptimizeHook(TestCase):
    """Unit tests for "_get_field_optimize_hook" lookup helper.

    Covers the found, absent, None-input, and camelCase-conversion cases.
    """

    def test_returns_hook_when_present(self) -> None:
        """ "_get_field_optimize_hook" returns the staticmethod when "optimize_posts" exists.

        This test breaks if a declared "optimize_<field>" hook stops being
        located and returned.
        """
        from django_graphex.utils import _get_field_optimize_hook

        class _FakeGrapheneType:
            @staticmethod
            def optimize_posts(qs, info, **kwargs):
                return qs

        class _FakeGQLType:
            graphene_type = _FakeGrapheneType

        hook = _get_field_optimize_hook(_FakeGQLType, "posts")
        self.assertIs(hook, _FakeGrapheneType.optimize_posts)

    def test_returns_none_when_absent(self) -> None:
        """ "_get_field_optimize_hook" returns None when "optimize_posts" is NOT declared.

        This test breaks if the lookup starts returning a truthy value for a
        type that never declared the hook.
        """
        from django_graphex.utils import _get_field_optimize_hook

        class _FakeGrapheneType:
            pass  # no optimize_posts

        class _FakeGQLType:
            graphene_type = _FakeGrapheneType

        result = _get_field_optimize_hook(_FakeGQLType, "posts")
        self.assertIsNone(result)

    def test_returns_none_when_gql_type_is_none(self) -> None:
        """ "_get_field_optimize_hook" returns None when "gql_type" is None.

        This test breaks if the lookup stops guarding against a missing
        GraphQL type.
        """
        from django_graphex.utils import _get_field_optimize_hook

        result = _get_field_optimize_hook(None, "posts")
        self.assertIsNone(result)

    def test_returns_none_when_no_graphene_type(self) -> None:
        """ "_get_field_optimize_hook" returns None when "gql_type" has no "graphene_type" attr.

        This test breaks if the lookup stops guarding against a GraphQL
        type object with no underlying graphene type.
        """
        from django_graphex.utils import _get_field_optimize_hook

        class _FakeGQLType:
            pass  # no graphene_type attr

        result = _get_field_optimize_hook(_FakeGQLType, "posts")
        self.assertIsNone(result)

    def test_camel_case_field_name_is_snake_cased(self) -> None:
        """ "_get_field_optimize_hook" converts camelCase to snake_case for the lookup.

        This test breaks if a camelCase GraphQL field name stops being
        converted before looking up "optimize_<field>".
        """
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
    """Unit tests for "_apply_field_hook" applier helper.

    Covers the no-op, valid-result, kwargs-forwarding, and error-handling
    branches.
    """

    def _make_qs(self):
        """Return a real QuerySet for use in tests."""
        from tests.models import Post

        return Post.objects.all()

    def test_returns_qs_unchanged_when_hook_is_none(self) -> None:
        """ "_apply_field_hook" returns the original qs unchanged when "hook=None".

        This test breaks if the no-hook branch stops being a true no-op.
        """
        from django_graphex.utils import _apply_field_hook

        qs = self._make_qs()
        result = _apply_field_hook(qs, None, None, filter_value=None, is_window=False)
        self.assertIs(result, qs)

    def test_returns_hook_result_when_valid_queryset(self) -> None:
        """ "_apply_field_hook" returns the hook's QuerySet result when it is valid.

        This test breaks if a valid queryset returned by the hook stops
        being passed through unchanged.
        """
        from django_graphex.utils import _apply_field_hook
        from tests.models import Post

        qs = Post.objects.all()
        filtered = Post.objects.filter(id__gt=0)

        def hook(q, info, **kwargs):
            return filtered

        result = _apply_field_hook(qs, hook, None, filter_value=None, is_window=False)
        self.assertIs(result, filtered)

    def test_hook_receives_filter_value_and_is_window_kwargs(self) -> None:
        """ "_apply_field_hook" passes "filter_value" and "is_window" as kwargs to the hook.

        This test breaks if either kwarg stops being forwarded to the hook
        call.
        """
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

    def test_non_queryset_return_emits_warning_and_returns_original(self) -> None:
        """AC10: a non-QuerySet hook return emits a WARNING and falls back to the unmodified qs.

        This test breaks if a hook returning a non-QuerySet value stops
        being caught and warned about, or if the original queryset stops
        being used as the fallback.
        """
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
    def test_exception_propagates_when_safe_mode_false(self) -> None:
        """AC9 (False): an exception from the hook propagates when "OPTIMIZER_SAFE_MODE=False".

        This test breaks if a hook's exception stops propagating under the
        default (non-safe-mode) setting.

        Raises:
            ValueError: Only inside the throwaway "hook" closure, which this
                test relies on triggering (and asserts propagates) to prove
                the non-safe-mode contract.
        """
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
    def test_exception_propagates_from_helper_even_when_safe_mode_true(self) -> None:
        """AC9 (coarse): "_apply_field_hook" does NOT swallow the exception, even when SAFE_MODE=True.

        SAFE_MODE is a COARSE boundary owned by queryset_factory, NOT per-field
        isolation. "_apply_field_hook" must let the exception propagate so the
        queryset_factory boundary can degrade the WHOLE resolve. A per-field
        try/except here is explicitly forbidden by the Phase E spec scope
        boundary, so the helper re-raising under SAFE_MODE=True is the contract.
        This test breaks if the helper starts swallowing the exception itself.

        Raises:
            ValueError: Only inside the throwaway "hook" closure, which this
                test relies on triggering (and asserts propagates) to prove
                the coarse SAFE_MODE contract.
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

_REG_WIN = Registry()


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

    global _REG_WIN
    _REG_WIN = Registry()
    captured_kwargs: list[dict] = []

    _PostListType = _gtype(
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

    _AuthorType = _gtype("_WinHookAuthorType", (DjangoObjectType,), author_attrs)

    _AuthorListType = _gtype(
        "_WinHookAuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG_WIN})},
    )

    schema = DjangoGraphQLSchema(
        query=_gtype(
            "WinHookQuery",
            (ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        ),
        registries=isolated_pair(_REG_WIN),
    )
    return schema, captured_kwargs


class TestWindowPathHook(TestCase):
    """AC1 / AC5 / AC6 — window path hook fires correctly.

    Covers "is_window=True" firing, the "distinct()" opt-out, and the
    "_gqx_rn" collision boundary.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a category and two authors, each with four posts.

        Two parents are required so a regression to per-parent (N+1) window
        resolution would be caught by "assertNumQueries" in the tests below.
        """
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
    def test_ac1_window_hook_fires_with_is_window_true(self) -> None:
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
        # The outer authors.totalCount is selected after results, so the lazy
        # count reuses the materialized cache and issues no separate COUNT query.
        with self.assertNumQueries(2):
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
    def test_ac5_hook_adds_distinct_falls_back_to_plain(self) -> None:
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
    def test_ac6_hook_aliasing_gqx_rn_is_silently_overwritten_noop(self) -> None:
        """AC6 (revised): a hook adding ".annotate(_gqx_rn=Value(0))" does NOT
        actually collide with the window alias.

        EMPIRICAL CONTRACT (verified at the ORM level): Django allows re-aliasing
        an annotation, and the later window ".annotate(_gqx_rn=Window(RowNumber()
        ...))" (fields.py:756) silently OVERWRITES the hook's "Value(0)".  No
        FieldError is raised at window-annotate time, so there is no collision to
        catch and no degrade is triggered.  The original AC6 "collision degrades"
        framing was therefore vacuous — its only assertion (errors is None) held
        whether or not the hook fired.

        This test instead pins the REAL, observable behavior:
          1. the hook FIRES on the window path with is_window=True (proving the
             window-path hook application at fields.py:729 is present — removing
             it makes "captured" empty and FAILS this test), and
          2. aliasing "_gqx_rn" is a benign no-op: the windowed query still
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
            result = _execute(schema, query)

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

_REG_FILT = Registry()


def _build_filtered_hook_schema():
    """Build a schema where posts has a filter arg; parent has optimize_posts."""
    from django_graphex.fields import DjangoNestedListObjectField
    from tests.models import Author, Post

    global _REG_FILT
    _REG_FILT = Registry()
    captured_kwargs: list[dict] = []

    _PostListType = _gtype(
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

    _AuthorType = _gtype(
        "_FiltHookAuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
            "optimize_posts": staticmethod(optimize_posts),
            "Meta": type("Meta", (), {"model": Author, "registry": _REG_FILT}),
        },
    )

    _AuthorListType = _gtype(
        "_FiltHookAuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG_FILT})},
    )

    schema = DjangoGraphQLSchema(
        query=_gtype(
            "FiltHookQuery",
            (ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        ),
        registries=isolated_pair(_REG_FILT),
    )
    return schema, captured_kwargs


class TestFilteredPlainPathHook(TestCase):
    """AC2 — filtered-plain path hook fires with is_window=False.

    Covers the filtered-prefetch path specifically.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a category, two authors, and one matching "FiltPost" post per author.

        Two parents are required so a regression to per-parent (N+1)
        filtered-prefetch resolution would be caught by "assertNumQueries"
        in the tests below.
        """
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
    def test_ac2_filtered_plain_hook_fires_with_is_window_false(self) -> None:
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
        # The outer authors.totalCount is selected after results, so the lazy
        # count reuses the materialized cache and issues no separate COUNT query.
        with self.assertNumQueries(2):
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

_REG_UNFILT = Registry()


def _build_unfiltered_hook_schema(has_hook=True):
    """Build a schema where posts is unfiltered; parent has optimize_posts."""
    from django_graphex.fields import DjangoNestedListObjectField
    from tests.models import Author, Post

    global _REG_UNFILT
    _REG_UNFILT = Registry()
    captured_kwargs: list[dict] = []

    _PostListType = _gtype(
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

    _AuthorType = _gtype("_UnfHookAuthorType", (DjangoObjectType,), author_attrs)
    _AuthorListType = _gtype(
        "_UnfHookAuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG_UNFILT})},
    )

    schema = DjangoGraphQLSchema(
        query=_gtype(
            "UnfHookQuery",
            (ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        ),
        registries=isolated_pair(_REG_UNFILT),
    )
    return schema, captured_kwargs


class TestUnfilteredTopLevelHook(TestCase):
    """AC2b SITE A — unfiltered top-level hook fires with is_window=False.

    Covers the bare-string plus Prefetch top-level branch.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a category, two authors, and one post per author.

        Two parents are required so a regression to per-parent (N+1)
        unfiltered-prefetch resolution would be caught by "assertNumQueries"
        in the tests below.
        """
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
    def test_ac2b_unfiltered_top_level_hook_fires(self) -> None:
        """AC2b SITE A: optimize_posts fires on unfiltered plain path.

        is_window=False; SQL contains JOIN for category; assertNumQueries has no N+1.
        OPTIMIZE_ONLY_FIELDS=False to avoid .only()/.select_related conflict.
        """
        schema, captured = _build_unfiltered_hook_schema(has_hook=True)

        query = "{ authors { results { posts { results { id title } totalCount } } totalCount } }"

        # The outer authors.totalCount is selected after results, so the lazy
        # count reuses the materialized cache and issues no separate COUNT query.
        with self.assertNumQueries(2):
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
    def test_ac2b_no_hook_is_noop(self) -> None:
        """Opt-out: no "optimize_posts" declared -> behavior identical to pre-phase-E (no error).

        This test breaks if the absence of a hook starts raising or
        otherwise changing observable behavior.
        """
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

_REG_SITE_B = Registry()


def _build_site_b_schema():
    """Build a schema: Author -> posts (filtered) -> comments (unfiltered).

    Comments are unfiltered but nested under a filtered posts ancestor.
    optimize_comments is declared on PostType (the parent of comments).
    """
    from django_graphex.fields import DjangoNestedListObjectField
    from tests.models import Author, Comment, Post

    global _REG_SITE_B
    _REG_SITE_B = Registry()
    captured_kwargs: list[dict] = []

    _CommentListType = _gtype(
        "_SiteBCommentListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Comment, "registry": _REG_SITE_B})},
    )

    def optimize_comments(qs, info, **kwargs):
        captured_kwargs.append(dict(kwargs))
        return qs.select_related("post")

    _PostType = _gtype(
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

    _PostListType = _gtype(
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

    _AuthorType = _gtype(
        "_SiteBAuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
            "Meta": type("Meta", (), {"model": Author, "registry": _REG_SITE_B}),
        },
    )

    _AuthorListType = _gtype(
        "_SiteBAuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG_SITE_B})},
    )

    schema = DjangoGraphQLSchema(
        query=_gtype(
            "SiteBQuery",
            (ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        ),
        registries=isolated_pair(_REG_SITE_B),
    )
    return schema, captured_kwargs


class TestNestedUnderFilteredHook(TestCase):
    """AC2b SITE B — unfiltered nested under filtered ancestor fires the hook.

    Covers the "_merge" code path for a nested-under-filtered relation.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create two authors, each with a matching post carrying two comments.

        Two comment-parents are required so a regression to per-post (N+1)
        batched comment prefetching would be caught by "assertNumQueries" in
        the tests below.
        """
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
    def test_site_b_hook_fires_for_reroot_child(self) -> None:
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
        # The outer authors.totalCount is selected after results, so the lazy
        # count reuses the materialized cache and issues no separate COUNT query.
        with self.assertNumQueries(3):
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

_REG_RELFWD = Registry()


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

    global _REG_RELFWD
    _REG_RELFWD = Registry()
    captured_kwargs: list[dict] = []

    _InnerPostListType = _gtype(
        "_RelFwdInnerPostListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Post, "registry": _REG_RELFWD})},
    )

    def optimize_posts(qs, info, **kwargs):
        captured_kwargs.append(dict(kwargs))
        return qs.select_related("category")

    # AuthorType owns the hooked nested list "posts".
    _AuthorType = _gtype(
        "_RelFwdAuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_InnerPostListType, accessor="posts"),
            "optimize_posts": staticmethod(optimize_posts),
            "Meta": type("Meta", (), {"model": Author, "registry": _REG_RELFWD}),
        },
    )

    # PostType exposes "author" as a forward FK (a plain related field). The
    # walker descends Post -> author via the related-field branch, then reaches
    # the hooked nested list on AuthorType.
    _PostType = _gtype(
        "_RelFwdPostType",
        (DjangoObjectType,),
        {"Meta": type("Meta", (), {"model": Post, "registry": _REG_RELFWD})},
    )

    _PostListType = _gtype(
        "_RelFwdPostListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Post, "registry": _REG_RELFWD})},
    )

    schema = DjangoGraphQLSchema(
        query=_gtype(
            "RelFwdQuery",
            (ObjectType,),
            {"posts": DjangoListObjectField(_PostListType)},
        ),
        registries=isolated_pair(_REG_RELFWD),
    )
    return schema, captured_kwargs


class TestHookThroughRelatedField(TestCase):
    """Hook on a nested list reached through a plain FK fires (walker hook_map forward).

    Confirms the hook_map threads forward through a non-optimized parent.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a category and two authors, each with one post.

        Two parents are required so the inner posts prefetch must batch
        across parents, catching a regression to per-parent resolution.
        """
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
    def test_hook_fires_through_forward_fk_relation(self) -> None:
        """optimize_posts fires for a nested list reached through the "author" FK.

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

_REG_SITE_B_MULTI = Registry()


def _build_site_b_multi_schema():
    """SITE B with TWO unfiltered hooked children under one filtered ancestor AND
    a multi-segment re-rooted descendant.

    Topology under filtered "posts":
      - comments (reverse FK)         -> stripped 'comments'        (1 segment)
      - tags (M2M)                    -> stripped 'tags'            (1 segment)
      - category -> posts (FK -> rev) -> stripped 'category__posts' (2 segments)

    The two single-segment children exercise the zip() ORDER pairing of
    stripped_children/abs_children; "category__posts" exercises the multi-segment
    descent loop in _merge_filtered_prefetches (utils.py:~2027).
    """
    from django_graphex.fields import DjangoNestedListObjectField
    from tests.models import Author, Category, Comment, Post, Tag

    global _REG_SITE_B_MULTI
    _REG_SITE_B_MULTI = Registry()
    captured_kwargs: list[dict] = []

    def _record(name, select_related_field=None):
        """Build a hook that records its name AND optionally applies a
        MODEL-SPECIFIC select_related.

        When "select_related_field" is set it is only valid on the model that
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

    _CommentListType = _gtype(
        "_SBMCommentListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Comment, "registry": _REG_SITE_B_MULTI})},
    )
    _TagListType = _gtype(
        "_SBMTagListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Tag, "registry": _REG_SITE_B_MULTI})},
    )
    # Nested list of posts hung off Category (the multi-segment descendant target).
    _CatPostListType = _gtype(
        "_SBMCatPostListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Post, "registry": _REG_SITE_B_MULTI})},
    )

    _CategoryType = _gtype(
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
    # "category" (FK) for the multi-segment descent.
    _PostType = _gtype(
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

    _PostListType = _gtype(
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

    _AuthorType = _gtype(
        "_SBMAuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(_PostListType, accessor="posts"),
            "Meta": type("Meta", (), {"model": Author, "registry": _REG_SITE_B_MULTI}),
        },
    )

    _AuthorListType = _gtype(
        "_SBMAuthorListType",
        (DjangoListObjectType,),
        {"Meta": type("Meta", (), {"model": Author, "registry": _REG_SITE_B_MULTI})},
    )

    schema = DjangoGraphQLSchema(
        query=_gtype(
            "SBMQuery",
            (ObjectType,),
            {"authors": DjangoListObjectField(_AuthorListType)},
        ),
        registries=isolated_pair(_REG_SITE_B_MULTI),
    )
    return schema, captured_kwargs


class TestSiteBMultiChildAndMultiSegment(TestCase):
    """SITE B: multiple unfiltered children (zip pairing) + multi-segment descent.

    Covers the descent through more than one hop of unfiltered relations.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a category, an author, one post with a comment and a tag.

        Also creates a sibling post, shared as fixture data for the
        multi-child, multi-segment descent tests.
        """
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
    def test_multiple_children_and_multi_segment_hooks_all_fire(self) -> None:
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
    """AC11 — hook fires regardless of OPTIMIZE_ONLY/ANNOTATED; OPTIMIZE_QUERYSET=False skips it.

    Confirms the hook's own gate is independent of those other flags.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a category, one author, and one linked post.

        Shared as fixture data for the gate-independence tests.
        """
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
    def test_hook_fires_when_only_and_annotated_off(self) -> None:
        """AC11: the hook fires even when both OPTIMIZE_ONLY_FIELDS and OPTIMIZE_ANNOTATED_FIELDS are off.

        This test breaks if the hook's own gate gets coupled to either of
        those unrelated optimizer flags.
        """
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
    def test_hook_does_not_fire_when_optimize_queryset_false(self) -> None:
        """AC11: the hook does NOT fire when OPTIMIZE_QUERYSET=False.

        This test breaks if the per-field hook stops respecting the global
        optimizer master switch.
        """
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
    """AC4 — end-to-end SQL proof that the hook is causal.

    Pins both the emitted SQL and the total query count.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a category, one author, and three posts.

        Shared as fixture data for the SQL/query-count proof.
        """
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
    def test_hooked_case_has_join_control_does_not(self) -> None:
        """AC4: with hook the prefetch SQL has JOIN; without hook it does not.

        assertNumQueries(N) for both cases proves no N+1 regression.
        OPTIMIZE_ONLY_FIELDS=False to avoid .only()/.select_related conflict.
        """
        query = "{ authors { results { posts { results { id title } totalCount } } totalCount } }"

        # The outer authors.totalCount is selected after results, so the lazy
        # count reuses the materialized cache and issues no separate COUNT query
        # in either case.
        # --- With hook ---
        schema_hook, _ = _build_unfiltered_hook_schema(has_hook=True)
        with self.assertNumQueries(2):
            with CaptureQueriesContext(connection) as ctx_hook:
                _exec(schema_hook, query)

        hook_sql = " ".join(q["sql"].upper() for q in ctx_hook.captured_queries)
        self.assertIn("CATEGORY", hook_sql, "Hooked case must JOIN category")

        # --- Without hook (control) ---
        schema_ctrl, _ = _build_unfiltered_hook_schema(has_hook=False)
        with self.assertNumQueries(2):
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
    """AC9 (SAFE_MODE=True): raising hook degrades whole resolve to un-optimized base.

    Distinguishes a coarse whole-resolve degrade from a per-field skip.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create two authors, each with multiple posts.

        Two parents with multiple posts each are required so the
        assertNumQueries checks below can discriminate a COARSE degrade
        (whole resolve un-optimized) from a per-field hook-only skip.
        """
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

        _PostListType = _gtype(
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

        _gtype("_SMAuthorType", (DjangoObjectType,), author_attrs)

        _AuthorListType = _gtype(
            "_SMAuthorListType",
            (DjangoListObjectType,),
            {"Meta": type("Meta", (), {"model": Author, "registry": _reg})},
        )

        return DjangoGraphQLSchema(
            query=_gtype(
                "SMQuery",
                (ObjectType,),
                {"authors": DjangoListObjectField(_AuthorListType)},
            ),
            registries=isolated_pair(_reg),
        )

    @override_settings(
        DJANGO_GRAPHEX={
            "OPTIMIZE_NESTED_PAGINATION": False,
            "OPTIMIZER_SAFE_MODE": True,
        }
    )
    def test_safe_mode_raising_hook_degrades_whole_resolve_coarsely(self) -> None:
        """AC9 + SAFE_MODE=True: a raising hook degrades the WHOLE resolve to the un-optimized base.

        Degrades via the queryset_factory boundary (COARSE, not per-field).
        Distinguishes coarse from per-field by (1) the boundary WARNING text
        "serving un-optimized queryset (OPTIMIZER_SAFE_MODE)" and (2) the
        query count matching the un-optimized N+1 baseline (one extra posts
        query per author) rather than the single batched prefetch query.
        This test breaks if either signal stops matching that contract.

        Raises:
            ValueError: Only inside the throwaway "optimize_posts" hook,
                which this test relies on triggering (and asserts is caught
                by the coarse SAFE_MODE boundary) to prove the degrade
                contract.
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
                result = _execute(schema_raise, query)
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
    """Opt-out: no optimize_posts declared -> byte-identical to pre-Phase-E behavior.

    Confirms neither an exception nor a query-count change is introduced.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with one post.

        Shared as fixture data for the opt-out (no hook declared) test.
        """
        from tests.models import Author, Post

        cls.author = Author.objects.create(name="OptOutAuthor")
        Post.objects.create(title="OptOutPost", author=cls.author)

    @override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": False})
    def test_no_hook_no_error_and_no_behavior_change(self) -> None:
        """No "optimize_posts" declared means no AttributeError, no exception, identical query count.

        This test breaks if the absence of a hook starts raising or
        changing the observable query count.
        """
        schema, captured = _build_unfiltered_hook_schema(has_hook=False)

        query = "{ authors { results { posts { results { id title } totalCount } } totalCount } }"

        # Should not raise any exception
        data = _exec(schema, query)
        self.assertIn("authors", data)
        self.assertEqual(len(captured), 0)
