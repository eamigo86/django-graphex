"""WU6b TDD RED/GREEN — Native DB-side window-prefetch optimizer port (B8 part 2).

Proves the CARDINAL WU6b property: a NESTED paginated
list query slices the page DB-SIDE via the window-function prefetch
(``ROW_NUMBER()`` + ``COUNT(*) OVER``), NOT in-memory after a full per-relation
load. The signal is the SQL: a windowable nested page MUST emit ``ROW_NUMBER()``
SQL exactly like the graphene backend, and the executed query count must be
BOUNDED (window-function prefetch, NOT N+1 one-query-per-parent).

The failure this guards against: WU6a wired native nested lists through the
STANDARD ``paginate_queryset`` (in-memory) path — the prefetch loads ALL children
of every parent, then slices in memory. For a deep page (offset large) that is a
correctness + perf gap: ``totalCount`` rides ``_gqx_total`` only on the window
path, and the unbounded load defeats the optimizer.

Run:
    .venv/bin/python -m pytest \
        tests/native/test_window_prefetch_native.py -q -o addopts=""
"""
from __future__ import annotations

import pytest


def _make_django_type(name: str, base: type, meta_attrs: dict, **extra) -> type:
    """Build a ``DjangoObjectType`` / ``DjangoListObjectType`` subclass dynamically.

    S6b re-parented these types onto the native (Pydantic ``ModelMetaclass``)
    base, so the bare ``type(name, (Base,), {"Meta": type("Meta", (), attrs)})``
    idiom now crashes: pydantic's ``inspect_namespace`` reads
    ``namespace['__module__']`` (KeyError when absent) and only ignores a nested
    ``Meta`` class when ``Meta.__qualname__.startswith(f"{namespace['__qualname__']}.")``.
    The 3-arg ``type()`` form does NOT auto-inject ``__module__`` / ``__qualname__``
    (unlike a real ``class`` statement), so we inject them and re-stamp the nested
    ``Meta`` qualname — the same fix ``base_types.factory_type`` applies in prod.
    """
    meta = type("Meta", (), meta_attrs)
    meta.__qualname__ = f"{name}.Meta"
    ns = {"__module__": __name__, "__qualname__": name, "Meta": meta, **extra}
    return type(name, (base,), ns)


# ---------------------------------------------------------------------------
# Shared native schema builder: Author list -> nested paginated Post list.
# ---------------------------------------------------------------------------


def _build_native_nested_schema(pagination=None):
    """Compile a native GraphQLSchema: authors -> posts (nested paginated list).

    Returns a ``graphql.GraphQLSchema`` assembled by ``compile_native_root``
    (NOT graphene.Schema). The ``posts`` field is a
    ``DjangoNestedListObjectField`` over the reverse FK ``Author.posts``.
    """
    from graphql import GraphQLSchema

    from django_graphex import ObjectType
    from django_graphex.fields import (
        DjangoListObjectField,
        DjangoNestedListObjectField,
    )
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.schema_compiler import compile_native_root
    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
    from django_graphex.types import DjangoListObjectType, DjangoObjectType
    from tests.models import Author, Post

    reg: dict = {}
    if pagination is None:
        pagination = LimitOffsetGraphqlPagination(default_limit=5, max_limit=100)

    _PostType = _make_django_type(
        "_WU6bPostType", DjangoObjectType, {"model": Post, "registry": reg}
    )
    _PostList = _make_django_type(
        "_WU6bPostList",
        DjangoListObjectType,
        {"model": Post, "pagination": pagination, "registry": reg},
    )
    _AuthorType = _make_django_type(
        "_WU6bAuthorType",
        DjangoObjectType,
        {"model": Author, "registry": reg},
        posts=DjangoNestedListObjectField(_PostList, accessor="posts"),
    )
    _AuthorList = _make_django_type(
        "_WU6bAuthorList", DjangoListObjectType, {"model": Author, "registry": reg}
    )

    compile_all_outputs()

    query_root = type(
        "_WU6bQuery",
        (ObjectType,),
        {"authors": DjangoListObjectField(_AuthorList)},
    )
    native_query = compile_native_root(query_root, name="Query")
    return GraphQLSchema(query=native_query)


def _seed(num_authors=3, posts_each=8):
    """Create ``num_authors`` authors each with ``posts_each`` posts."""
    from tests.models import Author, Post

    authors = []
    for a in range(num_authors):
        author = Author.objects.create(name=f"wu6b-author{a:02d}")
        for p in range(posts_each):
            Post.objects.create(title=f"a{a:02d}-post{p:02d}", author=author)
        authors.append(author)
    return authors


# ---------------------------------------------------------------------------
# CARDINAL: native nested paginated query emits DB-side window SQL (ROW_NUMBER).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_native_nested_pagination_emits_window_sql():
    """A native nested paginated list MUST emit ROW_NUMBER() SQL (DB-side window
    slicing), exactly like the graphene backend — NOT load every child in memory."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from graphql import graphql_sync

    _seed(num_authors=3, posts_each=8)
    schema = _build_native_nested_schema()

    query = """
    { authors { results {
        posts { results(limit: 3, offset: 0, ordering: "title") { title } totalCount }
    } totalCount } }
    """
    with CaptureQueriesContext(connection) as ctx:
        result = graphql_sync(schema, query)

    assert result.errors is None, result.errors
    sql_list = [q["sql"].upper() for q in ctx.captured_queries]
    window_sql = [s for s in sql_list if "ROW_NUMBER()" in s]
    assert len(window_sql) >= 1, (
        "WU6b: native nested paginated list MUST emit ROW_NUMBER() window SQL "
        "(DB-side slicing). Got NONE — the native path is still loading all "
        "children and slicing in memory. SQL emitted:\n" + "\n".join(sql_list)
    )


@pytest.mark.django_db
def test_native_nested_pagination_query_count_bounded_no_n_plus_1():
    """The executed query count MUST be BOUNDED (window-function prefetch), not
    N+1 (one COUNT/SELECT per parent). Bounded count == DB-side slicing works."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from graphql import graphql_sync

    # 5 parents: an N+1 path would scale with parent count; a window path is flat.
    _seed(num_authors=5, posts_each=10)
    schema = _build_native_nested_schema()

    query = """
    { authors { results {
        posts { results(limit: 2, offset: 0, ordering: "title") { title } totalCount }
    } totalCount } }
    """
    with CaptureQueriesContext(connection) as ctx:
        result = graphql_sync(schema, query)

    assert result.errors is None, result.errors
    n_queries = len(ctx.captured_queries)
    # Window-prefetch path: ~3-4 queries total (count authors, fetch authors,
    # window-prefetch posts, optional count subquery) regardless of parent count.
    # An N+1 path would be >= 5 (one per parent) + base queries.
    assert n_queries <= 5, (
        "WU6b: native nested paginated query is N+1 (scales with parent count). "
        f"Expected a BOUNDED window-prefetch count (<=5), got {n_queries}:\n"
        + "\n".join(q["sql"] for q in ctx.captured_queries)
    )


# ---------------------------------------------------------------------------
# Correctness: the window-sliced page returns the right rows and totalCount.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_native_nested_window_page_correct_rows_and_count():
    """DB-side window slice must return the correct page rows AND totalCount
    (count from _gqx_total / count-subquery, not len(loaded rows))."""
    from graphql import graphql_sync

    from tests.models import Author, Post

    author = Author.objects.create(name="wu6b-solo")
    for p in range(10):
        Post.objects.create(title=f"post{p:02d}", author=author)

    schema = _build_native_nested_schema()
    query = """
    { authors { results {
        posts { results(limit: 3, offset: 4, ordering: "title") { title } totalCount }
    } } }
    """
    result = graphql_sync(schema, query)
    assert result.errors is None, result.errors
    author_node = result.data["authors"]["results"][0]
    titles = [r["title"] for r in author_node["posts"]["results"]]
    assert titles == ["post04", "post05", "post06"], titles
    # totalCount must be the FULL count (10), not the sliced page size (3).
    assert author_node["posts"]["totalCount"] == 10, author_node["posts"]["totalCount"]


@pytest.mark.django_db
def test_native_nested_window_offset_beyond_end_count_correct():
    """Offset beyond the end yields an empty page but the FULL totalCount —
    proves the count-subquery / _gqx_cnt path works under native."""
    from graphql import graphql_sync

    from tests.models import Author, Post

    author = Author.objects.create(name="wu6b-beyond")
    for p in range(5):
        Post.objects.create(title=f"bpost{p:02d}", author=author)

    schema = _build_native_nested_schema()
    query = """
    { authors { results {
        posts { results(limit: 3, offset: 50, ordering: "title") { title } totalCount }
    } } }
    """
    result = graphql_sync(schema, query)
    assert result.errors is None, result.errors
    author_node = result.data["authors"]["results"][0]
    assert author_node["posts"]["results"] == []
    assert author_node["posts"]["totalCount"] == 5, author_node["posts"]["totalCount"]


# ---------------------------------------------------------------------------
# Ordering security on the window path under native (dual-backend parity).
#
# A relation-spanning ordering term ("author__name") is a DoS vector (arbitrary
# join chains). On the window path it must DECLINE the DB-side window opt
# (pre-check 5 in build_window_prefetch rejects non-concrete attnames) and fall
# back safely WITHOUT emitting ROW_NUMBER() SQL and WITHOUT crashing — exactly
# what the graphene backend does. This is the genuine window-path security
# behavior; the hard-raise validation (_validate_ordering_terms) fires on the
# queryset paginate_queryset path (top-level lists, covered by WU6a's
# test_relation_spanning_ordering_rejected).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_native_nested_window_relation_spanning_ordering_declines_window():
    """Relation-spanning ordering must DECLINE the window opt (no ROW_NUMBER SQL,
    no arbitrary-join DoS) and fall back safely under native — matching graphene."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from graphql import graphql_sync

    from tests.models import Author, Post

    author = Author.objects.create(name="wu6b-sec")
    Post.objects.create(title="p", author=author)

    schema = _build_native_nested_schema()
    query = """
    { authors { results {
        posts { results(ordering: "author__name") { title } }
    } } }
    """
    with CaptureQueriesContext(connection) as ctx:
        result = graphql_sync(schema, query)

    assert result.errors is None, result.errors
    sql_list = [q["sql"].upper() for q in ctx.captured_queries]
    window_sql = [s for s in sql_list if "ROW_NUMBER()" in s]
    assert len(window_sql) == 0, (
        "relation-spanning ordering must DECLINE the window opt (no arbitrary "
        "join chain via ROW_NUMBER); got window SQL:\n" + "\n".join(sql_list)
    )


@pytest.mark.django_db
def test_native_nested_window_invalid_ordering_does_not_leak_or_crash():
    """An invalid concrete-looking ordering term on the native window path must
    not crash with a raw FieldError 500 (CWE-209 field-list leak)."""
    from graphql import graphql_sync

    from tests.models import Author, Post

    author = Author.objects.create(name="wu6b-inv")
    Post.objects.create(title="p", author=author)

    schema = _build_native_nested_schema()
    query = """
    { authors { results {
        posts { results(ordering: "nonexistent_field") { title } }
    } } }
    """
    result = graphql_sync(schema, query)
    # Either a clean GraphQLError or graceful empty/ignored ordering — never a
    # raw 500 with the model field list leaked. Parity with graphene.
    if result.errors:
        for e in result.errors:
            assert "fielderror" not in str(e).lower(), e


# ---------------------------------------------------------------------------
# Cursor paginator: prefetch_window_slice returns None -> in-memory fallback,
# no window SQL, no error (keyset is opaque).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_native_nested_cursor_falls_back_without_window():
    """A Cursor-paginated native nested list must NOT emit window SQL (keyset is
    opaque, prefetch_window_slice returns None) and must execute without error."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from graphql import graphql_sync

    from django_graphex.paginations.pagination import CursorGraphqlPagination
    from tests.models import Author, Post

    author = Author.objects.create(name="wu6b-cursor")
    for p in range(6):
        Post.objects.create(title=f"cpost{p:02d}", author=author)

    schema = _build_native_nested_schema(
        pagination=CursorGraphqlPagination(ordering="title", page_size=3)
    )
    query = """
    { authors { results {
        posts { results(first: 3) { title } totalCount }
    } } }
    """
    with CaptureQueriesContext(connection) as ctx:
        result = graphql_sync(schema, query)

    assert result.errors is None, result.errors
    sql_list = [q["sql"].upper() for q in ctx.captured_queries]
    window_sql = [s for s in sql_list if "ROW_NUMBER()" in s]
    assert len(window_sql) == 0, (
        "Cursor nested list must NOT use the window optimizer (keyset opaque); "
        "got ROW_NUMBER() SQL:\n" + "\n".join(sql_list)
    )
