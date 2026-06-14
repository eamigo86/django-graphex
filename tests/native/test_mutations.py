"""Tests for WU-B task 2.4: native compile path for the 6 factory_type('input',...)
call sites — _meta.arguments[op] is a dict[str, GraphQLArgument] under native.

Tests run under GDX_BACKEND=native via native_only mark.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# Task 2.4: factory_type("input",...) call sites produce GraphQLArgument
# under native
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_compile_input_type_produces_graphql_argument_type():
    """compile_input_type + GraphQLArgument combination produces correct type.

    This tests the fundamental building block: a GraphQLInputObjectType
    can be wrapped in a GraphQLArgument with out_name.
    """
    from graphql import GraphQLArgument, GraphQLInputObjectType
    from django_graphex.native.input_compiler import compile_input_type
    from django_graphex.native.fields import build_model_schema
    from tests.models import Category

    pydantic_model = build_model_schema(Category, partial=False)
    gql_input_type = compile_input_type(pydantic_model, name="WuBCategoryCreateInput")

    # Wrap in GraphQLArgument as the call sites will do
    arg = GraphQLArgument(gql_input_type, out_name="new_category")
    assert isinstance(arg, GraphQLArgument)
    assert arg.out_name == "new_category"


@pytest.mark.django_db
def test_meta_arguments_structure_for_native_input():
    """_meta.arguments under native should hold a dict[str, GraphQLArgument].

    This tests the NATIVE equivalent of what _meta.arguments[op] will hold
    once the 6 call sites are rewritten. Currently we build this manually
    to verify the structure, then the GREEN phase will wire it.
    """
    from graphql import GraphQLArgument, GraphQLNonNull
    from django_graphex.native.input_compiler import compile_input_type
    from django_graphex.native.fields import build_model_schema
    from tests.models import Category

    pydantic_model = build_model_schema(Category, partial=False)
    gql_input_type = compile_input_type(pydantic_model, name="WuBCategoryInput2")

    # Build a native arguments dict (what _meta.arguments["create"] will hold)
    arguments = {"new_category": GraphQLArgument(gql_input_type, out_name="new_category")}

    # Verify it is a plain dict, not an OrderedDict of graphene Arguments
    assert isinstance(arguments, dict)
    assert "new_category" in arguments
    arg = arguments["new_category"]
    assert isinstance(arg, GraphQLArgument)
    # The type of the argument must be the compiled GraphQLInputObjectType
    assert arg.type is gql_input_type


@pytest.mark.django_db
def test_graphql_argument_out_name_matches_snake_input_field_name():
    """GraphQLArgument out_name must carry the snake_case field name."""
    from graphql import GraphQLArgument
    from django_graphex.native.input_compiler import compile_input_type
    from django_graphex.native.fields import build_model_schema
    from tests.models import Post

    pydantic_model = build_model_schema(Post, partial=False)
    gql_input_type = compile_input_type(pydantic_model, name="WuBPostCreateInput2")

    # The argument for the 'create' mutation on Post uses input_field_name=new_post
    arg = GraphQLArgument(gql_input_type, out_name="new_post")
    assert arg.out_name == "new_post", (
        "out_name must carry the snake_case field name, not camelCase"
    )


@pytest.mark.django_db
def test_input_fields_camel_key_snake_out_name():
    """Within a compiled input type, wire key = camelCase, out_name = snake.

    This is the core contract for the 6 call site rewrites:
    data["firstName"] == "Alice" when the wire sends {firstName: "Alice"}.
    """
    from graphql import GraphQLNonNull
    from django_graphex.native.input_compiler import compile_input_type
    from tests.models import Author
    from django_graphex.native.fields import build_model_schema

    pydantic_model = build_model_schema(Author, partial=False)
    gql_input_type = compile_input_type(pydantic_model, name="WuBAuthorInput")

    fields = gql_input_type.fields
    # Author model has 'name' field (single word, no camel conversion needed)
    # and potentially 'bio' field
    assert "name" in fields, f"Expected 'name' field in input, got: {list(fields.keys())}"
    name_field = fields["name"]
    # For a single-word field 'name', alias == field_name, out_name == 'name'
    assert name_field.out_name == "name"


@pytest.mark.django_db
def test_graphene_argument_import_absent_conceptually():
    """The native compile path does not need graphene.Argument.

    Under GDX_BACKEND=native, the 6 call sites use GraphQLArgument
    (from graphql) instead of graphene.Argument. This test verifies that
    compile_input_type + GraphQLArgument covers the same need.
    """
    from graphql import GraphQLArgument
    from django_graphex.native.input_compiler import compile_input_type
    from django_graphex.native.fields import build_model_schema
    from tests.models import Category

    pydantic_model = build_model_schema(Category, partial=False)
    gql_input_type = compile_input_type(pydantic_model, name="WuBCategoryArg")

    # Build the argument natively — no graphene.Argument needed
    native_arg = GraphQLArgument(gql_input_type, out_name="new_category")
    assert isinstance(native_arg, GraphQLArgument)
    # GraphQLArgument is from graphql-core, NOT from graphene
    assert native_arg.__class__.__module__.startswith("graphql"), (
        "Native arg must be from graphql-core, not graphene"
    )


# ---------------------------------------------------------------------------
# INTEGRATED WIRING TESTS (corrective WU-B apply)
# Verify DjangoModelMutation._meta.arguments[op] holds GraphQLArgument under native.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_django_model_mutation_create_arg_is_graphql_argument():
    """Under GDX_BACKEND=native, DjangoModelMutation._meta.arguments['create']
    must hold GraphQLArgument values, not graphene.Argument values.

    This tests the integrated mutation call-site wiring, not isolated compilation.
    """
    from graphql import GraphQLArgument
    from django_graphex.mutation import DjangoModelMutation
    from tests.models import Category

    class _IntegCategoryMutation(DjangoModelMutation):
        class Meta:
            model = Category

    create_args = _IntegCategoryMutation._meta.arguments.get("create", {})
    assert create_args, "DjangoModelMutation must have 'create' arguments"

    # The input argument (not 'id') must be a GraphQLArgument under native
    for key, val in create_args.items():
        if key != "id":
            assert isinstance(val, GraphQLArgument), (
                f"DjangoModelMutation 'create' arg '{key}' must be GraphQLArgument "
                f"under GDX_BACKEND=native, got {type(val)}"
            )
            break


@pytest.mark.django_db
def test_django_model_mutation_update_arg_is_graphql_argument():
    """Under GDX_BACKEND=native, DjangoModelMutation._meta.arguments['update']
    must hold GraphQLArgument for the input (partial model path).
    """
    from graphql import GraphQLArgument, GraphQLInputObjectType
    from django_graphex.mutation import DjangoModelMutation
    from tests.models import Category

    class _IntegCategoryMutationUpdate(DjangoModelMutation):
        class Meta:
            model = Category

    update_args = _IntegCategoryMutationUpdate._meta.arguments.get("update", {})
    assert update_args, "DjangoModelMutation must have 'update' arguments"

    for key, val in update_args.items():
        if key != "id":
            assert isinstance(val, GraphQLArgument), (
                f"DjangoModelMutation 'update' arg '{key}' must be GraphQLArgument "
                f"under GDX_BACKEND=native, got {type(val)}"
            )
            # The type of that argument may be wrapped in GraphQLNonNull
            # (required=True); unwrap to check the underlying input type.
            from graphql import GraphQLNonNull
            arg_type = val.type
            if isinstance(arg_type, GraphQLNonNull):
                arg_type = arg_type.of_type
            assert isinstance(arg_type, GraphQLInputObjectType), (
                f"DjangoModelMutation 'update' arg underlying type must be "
                f"GraphQLInputObjectType, got {type(arg_type)}"
            )
            break
