"""WU6a TDD RED/GREEN — Native pagination resolver path (B8 part 1).

Proves the GENUINE native pagination seam: a native-compiled GraphQLSchema with
a paginated/filtered list field BUILDS (compile_native_root no longer raises for
list/filter/pagination field kinds) AND EXECUTES end-to-end via graphql_sync.

The CARDINAL SIN this guards against: SDL-visible pagination/filter args that
DON'T actually filter/slice (a silent no-op). Every assertion here EXECUTES a
query and inspects the returned data — not just the SDL/type shape.

Gate (per the Phase-5 plan, WU6a):
- filter arg actually filters (returns only matching rows),
- pagination args actually slice (first:5/limit:5 returns <=5; offset/page work),
- ordering applies,
- relation-spanning ordering is REJECTED (_validate_ordering_terms fires),
- already_paginated prevents double-pagination.

Run:
    GDX_BACKEND=native .venv/bin/python -m pytest \
        tests/native/test_pagination_resolver_native.py -q -o addopts=""
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# Shared native schema builder (one paginated+filtered list field).
# ---------------------------------------------------------------------------


def _build_native_schema(pagination=None, results_field_name=None):
    """Compile a native GraphQLSchema exposing a paginated, filtered Author list.

    Returns ``(schema, list_type)``. ``schema`` is a ``graphql.GraphQLSchema``
    assembled by ``compile_native_root`` (NOT graphene.Schema).
    """
    from graphql import GraphQLSchema

    from django_graphex import ObjectType
    from django_graphex.fields import DjangoListObjectField
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.schema_compiler import compile_native_root
    from django_graphex.types import DjangoListObjectType
    from tests.models import Author

    meta_kwargs: dict = {"model": Author, "filter_fields": ["name"]}
    if pagination is not None:
        meta_kwargs["pagination"] = pagination
    if results_field_name is not None:
        meta_kwargs["results_field_name"] = results_field_name

    # S6b: DjangoListObjectType is re-parented onto the native Pydantic base, so
    # the bare ``type(name, (Base,), {"Meta": type("Meta", (), attrs)})`` idiom
    # crashes in pydantic's inspect_namespace (missing __module__ / qualname
    # mismatch). Inject __module__ / __qualname__ and re-stamp the nested Meta
    # qualname — the same fix base_types.factory_type applies in production.
    _meta_cls = type("Meta", (), meta_kwargs)
    _meta_cls.__qualname__ = "_WU6aAuthorList.Meta"
    list_type = type(
        "_WU6aAuthorList",
        (DjangoListObjectType,),
        {
            "__module__": __name__,
            "__qualname__": "_WU6aAuthorList",
            "Meta": _meta_cls,
        },
    )

    compile_all_outputs()

    query_root = type(
        "_WU6aQuery",
        (ObjectType,),
        {"authors": DjangoListObjectField(list_type)},
    )

    native_query = compile_native_root(query_root, name="Query")
    schema = GraphQLSchema(query=native_query)
    return schema, list_type


# ---------------------------------------------------------------------------
# BUILD: compile_native_root no longer raises for list/pagination/filter kinds.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_compile_native_root_builds_paginated_list_field():
    """compile_native_root must build (not raise) a DjangoListObjectField with
    a paginating container, replacing the WU5/WU6 NotImplementedError."""
    from graphql import GraphQLObjectType

    from django_graphex import LimitOffsetGraphqlPagination

    schema, _ = _build_native_schema(
        LimitOffsetGraphqlPagination(default_limit=5, max_limit=20)
    )
    assert isinstance(schema.query_type, GraphQLObjectType)
    assert "authors" in schema.query_type.fields


@pytest.mark.django_db
def test_results_field_carries_pagination_args():
    """The container's results field must expose the paginator's args
    (limit/offset/ordering) — proven on the compiled schema, not the source."""
    from django_graphex import LimitOffsetGraphqlPagination

    schema, _ = _build_native_schema(
        LimitOffsetGraphqlPagination(default_limit=5, max_limit=20)
    )
    list_container = schema.query_type.fields["authors"].type
    results_field = list_container.fields["results"]
    arg_names = set(results_field.args.keys())
    assert {"limit", "offset", "ordering"} <= arg_names, (
        f"results field is missing pagination args; got {arg_names}"
    )


@pytest.mark.django_db
def test_list_field_carries_filter_arg():
    """The list field must expose the native filter input arg (WU3 input)."""
    from graphql import GraphQLInputObjectType

    from django_graphex import LimitOffsetGraphqlPagination

    schema, _ = _build_native_schema(
        LimitOffsetGraphqlPagination(default_limit=5, max_limit=20)
    )
    list_field = schema.query_type.fields["authors"]
    assert "filter" in list_field.args, (
        f"list field is missing filter arg; got {set(list_field.args.keys())}"
    )
    filter_type = list_field.args["filter"].type
    assert isinstance(filter_type, GraphQLInputObjectType), (
        f"filter arg must be a native GraphQLInputObjectType; got {filter_type!r}"
    )


# ---------------------------------------------------------------------------
# EXECUTION: pagination args actually slice.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_limit_actually_slices():
    """EXECUTION: limit:5 returns at most 5 rows (arg is NOT a silent no-op)."""
    from graphql import graphql_sync

    from django_graphex import LimitOffsetGraphqlPagination
    from tests.models import Author

    for i in range(12):
        Author.objects.create(name=f"author{i:02d}")

    schema, _ = _build_native_schema(
        LimitOffsetGraphqlPagination(default_limit=50, max_limit=100)
    )
    result = graphql_sync(
        schema, "{ authors { results(limit: 5) { name } totalCount } }"
    )
    assert result.errors is None, result.errors
    rows = result.data["authors"]["results"]
    assert len(rows) == 5, f"limit:5 must return 5 rows, got {len(rows)}"
    assert result.data["authors"]["totalCount"] == 12


@pytest.mark.django_db
def test_offset_actually_slices():
    """EXECUTION: offset shifts the page window."""
    from graphql import graphql_sync

    from django_graphex import LimitOffsetGraphqlPagination
    from tests.models import Author

    for i in range(12):
        Author.objects.create(name=f"author{i:02d}")

    schema, _ = _build_native_schema(
        LimitOffsetGraphqlPagination(default_limit=50, max_limit=100)
    )
    result = graphql_sync(
        schema,
        '{ authors { results(limit: 3, offset: 5, ordering: "name") { name } } }',
    )
    assert result.errors is None, result.errors
    names = [r["name"] for r in result.data["authors"]["results"]]
    assert names == ["author05", "author06", "author07"], names


@pytest.mark.django_db
def test_page_pagination_actually_slices():
    """EXECUTION: PageGraphqlPagination page/pageSize args slice."""
    from graphql import graphql_sync

    from django_graphex import PageGraphqlPagination
    from tests.models import Author

    for i in range(10):
        Author.objects.create(name=f"author{i:02d}")

    schema, _ = _build_native_schema(
        PageGraphqlPagination(page_size=3, page_size_query_param="pageSize")
    )
    result = graphql_sync(
        schema,
        '{ authors { results(page: 2, pageSize: 3, ordering: "name") { name } } }',
    )
    assert result.errors is None, result.errors
    names = [r["name"] for r in result.data["authors"]["results"]]
    assert names == ["author03", "author04", "author05"], names


# ---------------------------------------------------------------------------
# EXECUTION: filter arg actually filters.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_filter_actually_filters():
    """EXECUTION: a filter arg returns ONLY matching rows (not a silent no-op)."""
    from graphql import graphql_sync

    from django_graphex import LimitOffsetGraphqlPagination
    from tests.models import Author

    Author.objects.create(name="alice")
    Author.objects.create(name="alistair")
    Author.objects.create(name="bob")

    schema, _ = _build_native_schema(
        LimitOffsetGraphqlPagination(default_limit=50, max_limit=100)
    )
    result = graphql_sync(
        schema,
        '{ authors(filter: {name: {icontains: "ali"}}) '
        "{ results { name } totalCount } }",
    )
    assert result.errors is None, result.errors
    names = sorted(r["name"] for r in result.data["authors"]["results"])
    assert names == ["alice", "alistair"], names
    assert result.data["authors"]["totalCount"] == 2


# ---------------------------------------------------------------------------
# EXECUTION: ordering applies.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_ordering_applies():
    """EXECUTION: ordering arg sorts the results."""
    from graphql import graphql_sync

    from django_graphex import LimitOffsetGraphqlPagination
    from tests.models import Author

    for name in ("charlie", "alice", "bob"):
        Author.objects.create(name=name)

    schema, _ = _build_native_schema(
        LimitOffsetGraphqlPagination(default_limit=50, max_limit=100)
    )
    result = graphql_sync(
        schema, '{ authors { results(ordering: "name") { name } } }'
    )
    assert result.errors is None, result.errors
    names = [r["name"] for r in result.data["authors"]["results"]]
    assert names == ["alice", "bob", "charlie"], names


# ---------------------------------------------------------------------------
# EXECUTION: relation-spanning ordering REJECTED (_validate_ordering_terms).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_relation_spanning_ordering_rejected():
    """EXECUTION: a relation-spanning ordering term must produce a GraphQL error
    (the _validate_ordering_terms security guard must fire on the native path)."""
    from graphql import graphql_sync

    from django_graphex import LimitOffsetGraphqlPagination
    from tests.models import Author

    Author.objects.create(name="alice")

    schema, _ = _build_native_schema(
        LimitOffsetGraphqlPagination(default_limit=50, max_limit=100)
    )
    result = graphql_sync(
        schema, '{ authors { results(ordering: "posts__title") { name } } }'
    )
    assert result.errors, (
        "relation-spanning ordering MUST be rejected (security guard) — "
        "got no errors, meaning _validate_ordering_terms did not fire"
    )
    assert any("ordering" in str(e).lower() for e in result.errors), result.errors


# ---------------------------------------------------------------------------
# results_field_name rename flows through the native field + resolver (WU5 SUGG b).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_renamed_results_field_name_flows_through():
    """EXECUTION: a renamed results_field_name ('items') is the wire key AND the
    paginating field — args + slicing follow the renamed field, not 'results'."""
    from graphql import graphql_sync

    from django_graphex import LimitOffsetGraphqlPagination
    from tests.models import Author

    for i in range(8):
        Author.objects.create(name=f"author{i:02d}")

    schema, _ = _build_native_schema(
        LimitOffsetGraphqlPagination(default_limit=50, max_limit=100),
        results_field_name="items",
    )
    container = schema.query_type.fields["authors"].type
    assert "items" in container.fields, set(container.fields.keys())
    assert "results" not in container.fields
    # The renamed field carries the pagination args.
    assert {"limit", "offset"} <= set(container.fields["items"].args.keys())

    result = graphql_sync(
        schema, "{ authors { items(limit: 3) { name } totalCount } }"
    )
    assert result.errors is None, result.errors
    assert len(result.data["authors"]["items"]) == 3
    assert result.data["authors"]["totalCount"] == 8


# ---------------------------------------------------------------------------
# Dataclass extraction (B8 part 1): NativePaginationField is a plain dataclass.
# ---------------------------------------------------------------------------


def test_native_pagination_field_is_dataclass_no_graphene():
    """NativePaginationField is a plain dataclass (type, paginator) with the
    list_resolver/wrap_resolve logic extracted from the graphene field."""
    import dataclasses

    from django_graphex.paginations.utils import NativePaginationField

    assert dataclasses.is_dataclass(NativePaginationField)
    field_names = {f.name for f in dataclasses.fields(NativePaginationField)}
    assert {"type", "paginator"} <= field_names, field_names


def test_native_pagination_field_already_paginated_no_double_slice():
    """already_paginated=True → list_resolver returns rows unsliced (no double
    pagination)."""
    from django_graphex.base_types import DjangoListObjectBase
    from django_graphex.paginations.utils import NativePaginationField

    class _SpyPaginator:
        __name__ = "Spy"
        called = False

        def paginate_queryset(self, qs, **kwargs):
            self.called = True
            return list(qs)[:1]

    paginator = _SpyPaginator()
    field = NativePaginationField(type=object(), paginator=paginator)
    rows = ["a", "b", "c"]
    base = DjangoListObjectBase(
        count=3, results=rows, results_field_name="results", already_paginated=True
    )
    out = field.list_resolver(None, base, None)
    assert out == rows, "already_paginated must return the rows unsliced"
    assert paginator.called is False, "paginator must NOT be called when already_paginated"


def test_native_pagination_field_paginates_when_not_already():
    """already_paginated=False → list_resolver delegates to paginate_queryset."""
    from django_graphex.base_types import DjangoListObjectBase
    from django_graphex.paginations.utils import NativePaginationField

    class _SlicePaginator:
        __name__ = "Slice"

        def paginate_queryset(self, qs, **kwargs):
            limit = kwargs.get("limit", len(qs))
            return list(qs)[:limit]

    field = NativePaginationField(type=object(), paginator=_SlicePaginator())
    base = DjangoListObjectBase(
        count=5, results=[1, 2, 3, 4, 5], results_field_name="results"
    )
    out = field.list_resolver(None, base, None, limit=2)
    assert out == [1, 2], out
