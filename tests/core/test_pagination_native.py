"""WU5 TDD RED/GREEN — Native pagination building blocks.

Tests the three WU5 building blocks:

B7  CursorPageInfo is a GraphQLObjectType with 4 fields + extensions['gdx'].
B9  Each paginator's to_graphql_fields() returns {name: GraphQLArgument(GraphQLInt)}
    on the native path.  to_dict() contract is UNCHANGED.
B10 _nested_list_object_field result type carries extensions['gdx'] with
    results_field_name so WU6a resolver + WU6b window-prefetch can read it.

Run:
    .venv/bin/python -m pytest tests/core/test_pagination_native.py --no-cov \
        -q --no-cov
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# B7 — CursorPageInfo is a native GraphQLObjectType with extensions['gdx']
# ---------------------------------------------------------------------------


def test_cursor_page_info_is_graphql_object_type() -> None:
    """NATIVE_CURSOR_PAGE_INFO must be a GraphQLObjectType.

    Contract: native pagination ships broken if the page-info singleton is a
    graphene ObjectType instead of a native GraphQLObjectType.
    """
    from graphql import GraphQLObjectType

    from django_graphex.paginations.pagination import NATIVE_CURSOR_PAGE_INFO

    assert isinstance(NATIVE_CURSOR_PAGE_INFO, GraphQLObjectType), (
        f"NATIVE_CURSOR_PAGE_INFO must be GraphQLObjectType, got {type(NATIVE_CURSOR_PAGE_INFO)}"
    )


def test_cursor_page_info_carries_extensions_gdx() -> None:
    """NATIVE_CURSOR_PAGE_INFO must carry a non-null extensions["gdx"] entry.

    Contract: schema introspection tooling that reads the "gdx" extension
    ships broken if the page-info type omits it.
    """
    from django_graphex.paginations.pagination import NATIVE_CURSOR_PAGE_INFO

    assert "gdx" in (NATIVE_CURSOR_PAGE_INFO.extensions or {}), (
        "NATIVE_CURSOR_PAGE_INFO.extensions must contain 'gdx'"
    )
    assert NATIVE_CURSOR_PAGE_INFO.extensions["gdx"] is not None


def test_cursor_page_info_has_four_fields() -> None:
    """NATIVE_CURSOR_PAGE_INFO must expose all four cursor page-info fields.

    Contract: cursor pagination clients ship broken if hasNextPage,
    hasPreviousPage, startCursor, or endCursor is missing from the type.
    """
    from django_graphex.paginations.pagination import NATIVE_CURSOR_PAGE_INFO

    fields = NATIVE_CURSOR_PAGE_INFO.fields  # forces thunk eval
    expected = {"hasNextPage", "hasPreviousPage", "startCursor", "endCursor"}
    actual = set(fields.keys())
    assert expected <= actual, f"Missing fields: {expected - actual}. Got: {actual}"


def test_cursor_page_info_boolean_fields_are_non_null() -> None:
    """hasNextPage and hasPreviousPage must be non-null (required=True).

    Contract: cursor pagination clients ship broken if either boolean flag
    is nullable, since callers rely on always getting a definite value.
    """
    from graphql import GraphQLNonNull

    from django_graphex.paginations.pagination import NATIVE_CURSOR_PAGE_INFO

    fields = NATIVE_CURSOR_PAGE_INFO.fields
    assert isinstance(fields["hasNextPage"].type, GraphQLNonNull), (
        "hasNextPage must be GraphQLNonNull(GraphQLBoolean)"
    )
    assert isinstance(fields["hasPreviousPage"].type, GraphQLNonNull), (
        "hasPreviousPage must be GraphQLNonNull(GraphQLBoolean)"
    )


# ---------------------------------------------------------------------------
# B9 — paginator to_graphql_fields() returns GraphQLArgument(GraphQLInt)
#      on the native path; to_dict() is UNCHANGED
# ---------------------------------------------------------------------------


def test_limit_offset_to_graphql_fields_native_returns_graphql_arguments() -> None:
    """LimitOffsetGraphqlPagination.to_graphql_fields() must return GraphQLArguments.

    Contract: native schema compilation ships broken if the limit/offset
    paginator's fields are not name-to-GraphQLArgument mappings.
    """
    from graphql import GraphQLArgument

    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination

    p = LimitOffsetGraphqlPagination()
    fields = p.to_graphql_fields()

    assert isinstance(fields, dict), "to_graphql_fields() must return a dict"
    assert len(fields) >= 1, "to_graphql_fields() must return at least one field"
    for name, value in fields.items():
        assert isinstance(value, GraphQLArgument), (
            f"Field {name!r} must be GraphQLArgument on native, got {type(value)}"
        )


def test_limit_offset_to_graphql_fields_native_has_correct_names() -> None:
    """LimitOffsetGraphqlPagination must expose limit/offset/ordering args.

    Contract: limit-offset pagination ships broken if any of the three
    expected argument names is missing from the compiled field map.
    """
    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination

    p = LimitOffsetGraphqlPagination()
    fields = p.to_graphql_fields()
    assert "limit" in fields
    assert "offset" in fields
    assert "ordering" in fields


def test_limit_offset_to_graphql_fields_native_int_types() -> None:
    """limit and offset args must wrap GraphQLInt on native.

    Contract: limit-offset pagination ships broken if either argument's
    underlying scalar type is not GraphQLInt.
    """
    from graphql import GraphQLInt, GraphQLNonNull

    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination

    p = LimitOffsetGraphqlPagination()
    fields = p.to_graphql_fields()

    def unwrap(t: object) -> object:
        """Strip a GraphQLNonNull wrapper, returning the inner type.

        Args:
            t: The GraphQL type to unwrap, possibly non-null.

        Returns:
            inner: The wrapped type if "t" was non-null, otherwise "t" itself.
        """
        return t.of_type if isinstance(t, GraphQLNonNull) else t

    assert unwrap(fields["limit"].type) is GraphQLInt, (
        f"limit arg must be GraphQLInt, got {fields['limit'].type}"
    )
    assert unwrap(fields["offset"].type) is GraphQLInt, (
        f"offset arg must be GraphQLInt, got {fields['offset'].type}"
    )


def test_limit_offset_to_dict_unchanged() -> None:
    """to_dict() must NOT change — it is a graphene-path invariant.

    Contract: the legacy graphene pagination path ships broken if to_dict()
    drops or renames any of its existing keys during the native migration.
    """
    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination

    p = LimitOffsetGraphqlPagination(default_limit=5, max_limit=20)
    d = p.to_dict()
    assert d["default_limit"] == 5
    assert d["max_limit"] == 20
    assert "limit_query_param" in d
    assert "offset_query_param" in d


def test_page_to_graphql_fields_native_returns_graphql_arguments() -> None:
    """PageGraphqlPagination.to_graphql_fields() must return GraphQLArguments.

    Contract: native schema compilation ships broken if the page paginator's
    fields are not GraphQLArgument instances.
    """
    from graphql import GraphQLArgument

    from django_graphex.paginations.pagination import PageGraphqlPagination

    p = PageGraphqlPagination()
    fields = p.to_graphql_fields()
    for name, value in fields.items():
        assert isinstance(value, GraphQLArgument), (
            f"Field {name!r} must be GraphQLArgument on native, got {type(value)}"
        )


def test_page_to_graphql_fields_native_has_page_arg() -> None:
    """PageGraphqlPagination must expose at least a "page" arg.

    Contract: page-number pagination ships broken if the compiled field map
    omits the "page" argument clients rely on.
    """
    from django_graphex.paginations.pagination import PageGraphqlPagination

    p = PageGraphqlPagination()
    fields = p.to_graphql_fields()
    assert "page" in fields


def test_page_to_graphql_fields_native_with_page_size_param() -> None:
    """When page_size_query_param is set, the extra arg must be a GraphQLArgument.

    Contract: page-size overrides ship broken if the "page_size" argument
    compiles to something other than a native GraphQLArgument.
    """
    from graphql import GraphQLArgument

    from django_graphex.paginations.pagination import PageGraphqlPagination

    p = PageGraphqlPagination(page_size_query_param="page_size")
    fields = p.to_graphql_fields()
    assert "page_size" in fields
    assert isinstance(fields["page_size"], GraphQLArgument)


def test_page_to_dict_unchanged() -> None:
    """PageGraphqlPagination.to_dict() must remain unchanged.

    Contract: the legacy graphene pagination path ships broken if to_dict()
    drops or renames its existing keys during the native migration.
    """
    from django_graphex.paginations.pagination import PageGraphqlPagination

    p = PageGraphqlPagination(page_size=10)
    d = p.to_dict()
    assert d["page_size"] == 10
    assert "page_query_param" in d


def test_cursor_to_graphql_fields_native_returns_graphql_arguments() -> None:
    """CursorGraphqlPagination.to_graphql_fields() must return GraphQLArguments.

    Contract: native schema compilation ships broken if the cursor
    paginator's "first"/"cursor" fields are not GraphQLArgument instances.
    """
    from graphql import GraphQLArgument

    from django_graphex.paginations.pagination import CursorGraphqlPagination

    p = CursorGraphqlPagination()
    fields = p.to_graphql_fields()
    for name, value in fields.items():
        assert isinstance(value, GraphQLArgument), (
            f"Field {name!r} must be GraphQLArgument on native, got {type(value)}"
        )


def test_cursor_to_graphql_fields_native_has_first_and_cursor() -> None:
    """Cursor paginator must expose "first" and "cursor" args.

    Contract: cursor pagination ships broken if either argument is missing
    from the compiled field map.
    """
    from django_graphex.paginations.pagination import CursorGraphqlPagination

    p = CursorGraphqlPagination()
    fields = p.to_graphql_fields()
    assert "first" in fields
    assert "cursor" in fields


def test_cursor_to_dict_unchanged() -> None:
    """CursorGraphqlPagination.to_dict() must remain unchanged.

    Contract: the legacy graphene pagination path ships broken if to_dict()
    drops or renames its existing keys during the native migration.
    """
    from django_graphex.paginations.pagination import CursorGraphqlPagination

    p = CursorGraphqlPagination(ordering="-id")
    d = p.to_dict()
    assert d["ordering"] == "-id"
    assert "cursor_query_param" in d
    assert "first_query_param" in d


# ---------------------------------------------------------------------------
# B10 — _nested_list_object_field result type carries extensions['gdx']
#        with results_field_name
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_nested_list_object_field_container_type_carries_gdx_extensions() -> None:
    """The nested list container type must carry a "gdx" extension with metadata.

    Contract: WU6a's resolver and WU6b's window-prefetch ship broken if the
    compiled container GraphQLObjectType is missing extensions["gdx"] or its
    "results_field_name" metadata.
    """
    from graphql import GraphQLObjectType

    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.types import DjangoListObjectType
    from tests.models import Category

    class _CatList(DjangoListObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    meta = _CatList._meta
    gql_type = getattr(meta, "graphql_output_type", None)
    assert gql_type is not None, "_CatList.graphql_output_type must not be None"
    assert isinstance(gql_type, GraphQLObjectType)

    # B10: the container type must carry extensions['gdx'] with results_field_name
    ext = gql_type.extensions or {}
    assert "gdx" in ext, (
        "DjangoListObjectType native output must carry extensions['gdx']; "
        f"got extensions={ext!r}"
    )
    gdx = ext["gdx"]
    # GdxPayload exposes metadata via _meta (a _MetaView over GdxMeta).
    # results_field_name must be accessible via gdx._meta.results_field_name.
    assert hasattr(gdx, "_meta"), (
        f"extensions['gdx'] must be a GdxPayload with ._meta; got {type(gdx)}"
    )
    assert hasattr(gdx._meta, "results_field_name"), (
        f"gdx._meta must have results_field_name; got {gdx!r}"
    )


@pytest.mark.django_db
def test_nested_list_object_field_results_field_name_value() -> None:
    """extensions["gdx"].results_field_name must match Meta.results_field_name.

    Contract: window-prefetch resolution ships broken if the default
    results_field_name ("results") is not reflected on the compiled
    extension metadata.
    """
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.types import DjangoListObjectType
    from tests.models import Category

    class _CatListDefault(DjangoListObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    meta = _CatListDefault._meta
    gql_type = meta.graphql_output_type
    gdx = gql_type.extensions["gdx"]
    # GdxPayload exposes metadata via ._meta (_MetaView over GdxMeta).
    rfn = gdx._meta.results_field_name
    # Default results_field_name is "results"
    assert rfn == "results", f"results_field_name must be 'results', got {rfn!r}"
