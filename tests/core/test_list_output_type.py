"""WU1b TDD RED — DjangoListObjectType native output compilation.

Tests (WU1b gate, task 1.7):
  (a) A DjangoListObjectType subclass has non-None _meta.graphql_output_type
      (GraphQLObjectType) after app-ready compilation.
  (b) extensions['gdx'] contains pagination arg metadata (results_field_name).
  (c) 'results' and 'totalCount' (exposed as 'totalCount' SDL name) fields are
      present in the compiled container GraphQLObjectType.
  (d) The results field element type IS the single canonical node
      GraphQLObjectType (identity, NOT GraphQLString / a duplicate).
  (e) Schema-assembly smoke: assemble a GraphQLSchema with a list type +
      its node + a node-referencing mutation → NO duplicate-name TypeError,
      mirroring test_output_identity_invariant.py pattern for list containers.

Run:
    .venv/bin/python -m pytest tests/core/test_list_output_type.py \
        -q -o addopts=""
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# (a) + (b) + (c): list type has graphql_output_type with gdx + required fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_output_type_has_graphql_output_type() -> None:
    """Assert that "DjangoListObjectType._meta.graphql_output_type" compiles.

    If this fails, a list container subclass would have no compiled
    GraphQLObjectType (or the wrong type) after "compile_all_outputs" runs.
    """
    from graphql import GraphQLObjectType

    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.types import DjangoListObjectType
    from tests.models import Category

    class _CategoryListType(DjangoListObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    meta = _CategoryListType._meta
    gql_type = getattr(meta, "graphql_output_type", None)

    assert gql_type is not None, (
        "_CategoryListType._meta.graphql_output_type is None after "
        "compile_all_outputs() — WU1b native branch missing in DjangoListObjectType"
    )
    assert isinstance(gql_type, GraphQLObjectType), (
        f"_meta.graphql_output_type must be GraphQLObjectType, got {type(gql_type)}"
    )


@pytest.mark.django_db
def test_list_output_type_has_gdx_extensions() -> None:
    """Assert that the compiled list container carries gdx pagination metadata.

    If this fails, "extensions['gdx']" would be missing (or its
    results_field_name would be missing) on the compiled list container
    GraphQLObjectType, breaking the pagination resolver path.
    """
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.types import DjangoListObjectType
    from tests.models import Category

    class _CategoryListGdxType(DjangoListObjectType):
        class Meta:
            model = Category
            results_field_name = "items"

    compile_all_outputs()

    meta = _CategoryListGdxType._meta
    gql_type = getattr(meta, "graphql_output_type", None)
    assert gql_type is not None, "_meta.graphql_output_type must not be None"

    extensions = gql_type.extensions or {}
    assert "gdx" in extensions, (
        "Compiled list container GraphQLObjectType missing extensions['gdx']. "
        "WU1b must call GdxPayload with GdxMeta(results_field_name=...) "
        "so pagination resolvers (WU5+) can read it."
    )

    gdx = extensions["gdx"]
    # The gdx payload must expose results_field_name via its _meta shim
    results_field_name = gdx._meta.results_field_name
    assert results_field_name is not None, (
        "extensions['gdx']._meta.results_field_name must not be None — "
        "it is required for the pagination resolver path (WU5+)"
    )
    assert results_field_name == "items", (
        f"results_field_name must be 'items' (from Meta), got {results_field_name!r}"
    )


@pytest.mark.django_db
def test_list_output_type_has_results_and_totalcount_fields() -> None:
    """Assert that the compiled container exposes results and totalCount fields.

    If this fails, the compiled list container GraphQLObjectType would be
    missing its results field (or a custom results_field_name) or the
    "totalCount" pagination field.
    """
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.types import DjangoListObjectType
    from tests.models import Author

    class _AuthorListFieldsType(DjangoListObjectType):
        class Meta:
            model = Author

    compile_all_outputs()

    meta = _AuthorListFieldsType._meta
    gql_type = getattr(meta, "graphql_output_type", None)
    assert gql_type is not None

    # Force thunk evaluation
    fields = gql_type.fields

    rfn = _AuthorListFieldsType._meta.results_field_name or "results"
    assert rfn in fields, (
        f"Container must have results field ('{rfn}'); got {sorted(fields.keys())}"
    )
    assert "totalCount" in fields, (
        f"Container must have 'totalCount' field; got {sorted(fields.keys())}"
    )


# ---------------------------------------------------------------------------
# (d): results element type IS the canonical node GraphQLObjectType (identity)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_output_type_results_element_is_canonical_node() -> None:
    """Assert that the results element type is the same instance as the node type.

    If this fails, the results field's element type would be a
    GraphQLString, a duplicate, or a second instance instead of the single
    canonical GraphQLObjectType shared with "node._meta.graphql_output_type".
    """
    from graphql import GraphQLObjectType

    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.types import DjangoListObjectType, DjangoObjectType
    from tests.models import Post

    class _PostNodeType(DjangoObjectType):
        class Meta:
            model = Post

    class _PostListType(DjangoListObjectType):
        class Meta:
            model = Post

    compile_all_outputs()

    node_gql = _PostNodeType._meta.graphql_output_type
    assert isinstance(node_gql, GraphQLObjectType), "Node must be GraphQLObjectType"

    list_gql = _PostListType._meta.graphql_output_type
    assert list_gql is not None, "List container must have graphql_output_type"

    rfn = _PostListType._meta.results_field_name or "results"
    results_field = list_gql.fields[rfn]

    # Unwrap NonNull and List wrappers to get the element type
    element_type = results_field.type
    while hasattr(element_type, "of_type"):
        element_type = element_type.of_type

    assert isinstance(element_type, GraphQLObjectType), (
        f"Results element type must be GraphQLObjectType (the node), "
        f"got {element_type!r} (GraphQLString means the shared registry thunk failed)"
    )
    assert element_type is node_gql, (
        "Results element type MUST be the SAME identity as "
        "_PostNodeType._meta.graphql_output_type (single canonical instance). "
        f"Got element_type={element_type!r}, node_gql={node_gql!r}"
    )


# ---------------------------------------------------------------------------
# (e): schema-assembly smoke — list + node + mutation → no duplicate-name TypeError
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_output_type_schema_assembly_no_duplicate() -> None:
    """Assert that assembling list container + node + mutation raises no duplicate-name error.

    This mirrors "test_output_identity_invariant.py" but for the list
    container path: a GraphQLSchema built from a list container type, its
    node, and a mutation referencing that node must construct without a
    duplicate-name TypeError.
    """
    from graphql import GraphQLField, GraphQLObjectType, GraphQLSchema

    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.mutation import _NATIVE_FIELD_REGISTRY, DjangoModelMutation
    from django_graphex.types import DjangoListObjectType, DjangoObjectType
    from tests.models import Author

    class _SmokeAuthorType(DjangoObjectType):
        class Meta:
            model = Author

    class _SmokeAuthorListType(DjangoListObjectType):
        class Meta:
            model = Author

    class _SmokeAuthorMutation(DjangoModelMutation):
        class Meta:
            model = Author
            model_operations = ("create",)

    compile_all_outputs()

    author_gql = _SmokeAuthorType._meta.graphql_output_type
    list_gql = _SmokeAuthorListType._meta.graphql_output_type

    assert author_gql is not None
    assert list_gql is not None

    pinned_field = _NATIVE_FIELD_REGISTRY.get((Author, "create", "native"))
    assert pinned_field is not None, "mutation native create field must be registered"

    query_root = GraphQLObjectType(
        name="Query",
        fields={
            "authors": GraphQLField(list_gql),
            "author": GraphQLField(author_gql),
        },
    )
    mutation_root = GraphQLObjectType(
        name="Mutation",
        fields={
            "createAuthor": pinned_field,
        },
    )

    # This is the load-bearing assertion: no duplicate-name TypeError allowed.
    schema = GraphQLSchema(query=query_root, mutation=mutation_root)

    type_map = schema.type_map
    assert type_map[author_gql.name] is author_gql, (
        "Schema type_map must hold the single Author node instance"
    )
    assert type_map[list_gql.name] is list_gql, (
        "Schema type_map must hold the single list container instance"
    )
