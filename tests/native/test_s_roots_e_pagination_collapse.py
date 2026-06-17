"""S-ROOTS-e RED/GREEN — pagination descriptor collapse (native).

Phase 7 graphene-removal, sub-slice (e). The
``DjangoListObjectType`` must STOP building the dead graphene pagination
descriptors into ``_meta.fields``:

- ``pagination.get_pagination_field(baseType)`` -> a graphene
  ``GenericPaginationField`` (``results`` key) — DEAD on native; the native
  list container is thunk-built separately on ``_meta.graphql_output_type``.
- ``paginator.get_page_info_field(baseType)`` -> a graphene ``Field`` wrapping
  ``CursorPageInfo`` (``page_info`` key) — DEAD on native; the native cursor
  ``pageInfo`` field comes from ``get_native_page_info_field``.

The native compiler reads ``cls._meta.graphql_output_type`` (the thunk-built
``GraphQLObjectType``), NEVER ``_meta.fields``, so the graphene descriptors are
pure overhead on native. This slice skips them on native.

PARAMOUNT: the native pagination container SDL (results args, totalCount,
cursor pageInfo) MUST be byte-identical after the collapse — these guards
assert the native container is unchanged.

Run:
    .venv/bin/python -m pytest \
        tests/native/test_s_roots_e_pagination_collapse.py -q -o addopts=""
"""
from __future__ import annotations

import pytest


def _build_list_types():
    """Build LimitOffset / Page / Cursor list types and compile outputs."""
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.paginations.pagination import (
        CursorGraphqlPagination,
        LimitOffsetGraphqlPagination,
        PageGraphqlPagination,
    )
    from django_graphex.types import DjangoListObjectType
    from tests.models import Category

    class _LOList(DjangoListObjectType):
        class Meta:
            model = Category
            pagination = LimitOffsetGraphqlPagination()

    class _PageList(DjangoListObjectType):
        class Meta:
            model = Category
            pagination = PageGraphqlPagination(page_size_query_param="page_size")

    class _CursorList(DjangoListObjectType):
        class Meta:
            model = Category
            pagination = CursorGraphqlPagination(ordering="-id")

    compile_all_outputs()
    return _LOList, _PageList, _CursorList


# ---------------------------------------------------------------------------
# RED: the dead graphene pagination descriptors must NOT be built on native
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_results_is_not_graphene_pagination_field_on_native():
    """On native, the list type must NOT build a graphene pagination descriptor
    into ``_meta.fields``.

    S-del-backend-11: the graphene ``GenericPaginationField`` was DELETED with the
    graphene backend. The native container is thunk-built on
    ``_meta.graphql_output_type``; assert the deleted class is gone and that the
    ``results`` descriptor is not a graphene ``GenericPaginationField`` (by name).
    """
    from django_graphex.paginations import utils

    assert not hasattr(utils, "GenericPaginationField"), (
        "graphene GenericPaginationField must be deleted in S-del-backend-11"
    )

    lo, page, cursor = _build_list_types()
    for cls in (lo, page, cursor):
        results = cls._meta.fields.get("results")
        assert type(results).__name__ != "GenericPaginationField", (
            f"{cls.__name__}: graphene GenericPaginationField must NOT be built "
            f"on native (dead descriptor); got {type(results)!r}"
        )


@pytest.mark.django_db
def test_cursor_page_info_graphene_field_not_built_on_native():
    """On native, the cursor list type must NOT build a graphene ``CursorPageInfo``
    ``page_info`` field.

    S-del-backend-11: the graphene ``CursorPageInfo`` ``ObjectType`` was DELETED;
    assert it is gone and that any ``page_info`` field is not named CursorPageInfo
    from the (deleted) graphene module.
    """
    from django_graphex.paginations import pagination as ppag

    assert not hasattr(ppag, "CursorPageInfo"), (
        "graphene CursorPageInfo must be deleted in S-del-backend-11"
    )

    _lo, _page, cursor = _build_list_types()
    page_info = cursor._meta.fields.get("page_info")
    if page_info is not None:
        ftype = getattr(page_info, "type", None) or getattr(page_info, "_type", None)
        # Whatever the page_info field is, it must be the native CursorPageInfo
        # (the graphql-core NATIVE_CURSOR_PAGE_INFO), never a graphene descriptor.
        assert type(ftype).__module__.startswith("graphql") or ftype is None, (
            f"page_info field type must be graphql-core native; got {ftype!r}"
        )


# ---------------------------------------------------------------------------
# GUARD: the native container (graphql_output_type) is UNCHANGED
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_native_container_results_totalcount_present():
    """All three native containers must still expose results + totalCount with
    the paginator's args wired onto results."""
    lo, page, cursor = _build_list_types()

    expected_args = {
        "_LOList": {"limit", "offset", "ordering"},
        "_PageList": {"page", "ordering", "page_size"},
        "_CursorList": {"first", "cursor"},
    }
    for cls in (lo, page, cursor):
        gql = cls._meta.graphql_output_type
        fields = gql.fields  # force thunk
        assert "results" in fields, f"{cls.__name__}: native results field missing"
        assert "totalCount" in fields, (
            f"{cls.__name__}: native totalCount field missing"
        )
        results_args = set(fields["results"].args.keys())
        assert results_args == expected_args[cls.__name__], (
            f"{cls.__name__}: native results args changed: {results_args}"
        )


@pytest.mark.django_db
def test_native_cursor_page_info_present():
    """The cursor native container must still expose the native ``pageInfo``
    field of type ``CursorPageInfo`` with first/cursor args."""
    _lo, _page, cursor = _build_list_types()
    gql = cursor._meta.graphql_output_type
    fields = gql.fields
    assert "pageInfo" in fields, "native cursor pageInfo field missing"
    page_info_type = fields["pageInfo"].type
    inner = getattr(page_info_type, "of_type", page_info_type)
    assert getattr(inner, "name", None) == "CursorPageInfo", (
        f"native pageInfo must be CursorPageInfo, got {inner!r}"
    )
    assert set(fields["pageInfo"].args.keys()) == {"first", "cursor"}


@pytest.mark.django_db
def test_native_non_cursor_has_no_page_info():
    """LimitOffset / Page native containers must NOT expose a pageInfo field
    (only cursor paginators carry pagination metadata)."""
    lo, page, _cursor = _build_list_types()
    for cls in (lo, page):
        gql = cls._meta.graphql_output_type
        fields = gql.fields
        assert "pageInfo" not in fields, (
            f"{cls.__name__}: non-cursor native container must have no pageInfo"
        )
