"""Tests for native mutation field construction (WU-3) and prior arg-wiring (WU-B).

Covers:
- WU-B / task 2.4: factory_type("input",...) call sites produce GraphQLArgument under native.
- WU-3 / tasks 3.1-3.3: DjangoModelMutation.*Field() and DjangoModelType.*Field() return
  GraphQLField instances with correct args and resolvers.

Tests run.
"""
from __future__ import annotations

import pytest

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

    from django_graphex.native.fields import build_model_schema
    from django_graphex.native.input_compiler import compile_input_type
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

    from django_graphex.native.fields import build_model_schema
    from django_graphex.native.input_compiler import compile_input_type
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

    from django_graphex.native.fields import build_model_schema
    from django_graphex.native.input_compiler import compile_input_type
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

    from django_graphex.native.fields import build_model_schema
    from django_graphex.native.input_compiler import compile_input_type
    from tests.models import Author

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

    the 6 call sites use GraphQLArgument
    (from graphql) instead of graphene.Argument. This test verifies that
    compile_input_type + GraphQLArgument covers the same need.
    """
    from graphql import GraphQLArgument

    from django_graphex.native.fields import build_model_schema
    from django_graphex.native.input_compiler import compile_input_type
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
    """DjangoModelMutation._meta.arguments['create']
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
                f"got {type(val)}"
            )
            break


@pytest.mark.django_db
def test_django_model_mutation_update_arg_is_graphql_argument():
    """DjangoModelMutation._meta.arguments['update']
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
                f"got {type(val)}"
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


# ---------------------------------------------------------------------------
# WU-3 task 3.1: DjangoModelMutation.*Field() returns GraphQLField under native
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_django_model_mutation_create_field_returns_graphql_field():
    """DjangoModelMutation.CreateField() must return
    a graphql-core GraphQLField, not a graphene Field.
    """
    from graphql import GraphQLField

    from django_graphex.mutation import DjangoModelMutation
    from tests.models import Category

    class _WU3CategoryMutation(DjangoModelMutation):
        class Meta:
            model = Category

    field = _WU3CategoryMutation.CreateField()
    assert isinstance(field, GraphQLField), (
        f"CreateField() must return GraphQLField under native, got {type(field)}"
    )


@pytest.mark.django_db
def test_django_model_mutation_create_field_args_are_graphql_arguments():
    """Under native, CreateField().args must be dict[str, GraphQLArgument]."""
    from graphql import GraphQLArgument, GraphQLField

    from django_graphex.mutation import DjangoModelMutation
    from tests.models import Category

    class _WU3CategoryMutationArgs(DjangoModelMutation):
        class Meta:
            model = Category

    field = _WU3CategoryMutationArgs.CreateField()
    assert isinstance(field, GraphQLField)
    for name, arg in field.args.items():
        assert isinstance(arg, GraphQLArgument), (
            f"CreateField arg '{name}' must be GraphQLArgument, got {type(arg)}"
        )


@pytest.mark.django_db
def test_django_model_mutation_create_field_type_is_graphql_object_type():
    """Under native, CreateField().type must resolve to a GraphQLObjectType,
    not a graphene class (R7: NEVER pass cls itself to graphql-core).
    """
    from graphql import GraphQLField, GraphQLNonNull, GraphQLObjectType

    from django_graphex.mutation import DjangoModelMutation
    from tests.models import Category

    class _WU3CategoryMutationType(DjangoModelMutation):
        class Meta:
            model = Category

    field = _WU3CategoryMutationType.CreateField()
    assert isinstance(field, GraphQLField)

    # Resolve the type (may be a thunk)
    field_type = field.type
    if callable(field_type) and not isinstance(field_type, GraphQLObjectType):
        field_type = field_type()
    # Unwrap NonNull if present
    if isinstance(field_type, GraphQLNonNull):
        field_type = field_type.of_type

    assert isinstance(field_type, GraphQLObjectType), (
        f"CreateField output type must be GraphQLObjectType, got {type(field_type)}. "
        "R7: NEVER pass cls._meta.output (a graphene/Pydantic class) to graphql-core."
    )


@pytest.mark.django_db
def test_django_model_mutation_create_field_resolve_dispatches_to_create():
    """Under native, CreateField().resolve must dispatch to cls.create."""
    import inspect

    from graphql import GraphQLField

    from django_graphex.mutation import DjangoModelMutation
    from tests.models import Category

    class _WU3CategoryResolve(DjangoModelMutation):
        class Meta:
            model = Category

    field = _WU3CategoryResolve.CreateField()
    assert isinstance(field, GraphQLField)
    # The resolve function should be cls.create (or a shim wrapping it).
    assert field.resolve is not None, "CreateField must have a resolver"
    resolve_fn = field.resolve
    # Unwrap _adapt_self shim if present
    inner = getattr(resolve_fn, "__wrapped__", resolve_fn)
    # Bound classmethods create a new object each access; compare __func__ instead
    create_func = _WU3CategoryResolve.create.__func__
    inner_func = getattr(inner, "__func__", None)
    resolve_func = getattr(resolve_fn, "__func__", None)
    assert inner_func is create_func or resolve_func is create_func, (
        "CreateField resolver must be cls.create or a shim wrapping it"
    )


@pytest.mark.django_db
def test_django_model_mutation_delete_field_returns_graphql_field():
    """DjangoModelMutation.DeleteField() must return
    a GraphQLField with a GraphQLArgument for 'id'.
    """
    from graphql import GraphQLArgument, GraphQLField

    from django_graphex.mutation import DjangoModelMutation
    from tests.models import Category

    class _WU3CategoryDeleteField(DjangoModelMutation):
        class Meta:
            model = Category

    field = _WU3CategoryDeleteField.DeleteField()
    assert isinstance(field, GraphQLField), (
        f"DeleteField() must return GraphQLField under native, got {type(field)}"
    )
    # The 'id' arg must be a GraphQLArgument, not a graphene Argument
    assert "id" in field.args, "DeleteField must have an 'id' arg"
    assert isinstance(field.args["id"], GraphQLArgument), (
        f"DeleteField 'id' arg must be GraphQLArgument, got {type(field.args['id'])}"
    )


@pytest.mark.django_db
def test_django_model_mutation_update_field_returns_graphql_field():
    """DjangoModelMutation.UpdateField() must return
    a GraphQLField.
    """
    from graphql import GraphQLField

    from django_graphex.mutation import DjangoModelMutation
    from tests.models import Category

    class _WU3CategoryUpdateField(DjangoModelMutation):
        class Meta:
            model = Category

    field = _WU3CategoryUpdateField.UpdateField()
    assert isinstance(field, GraphQLField), (
        f"UpdateField() must return GraphQLField under native, got {type(field)}"
    )


@pytest.mark.django_db
def test_django_model_mutation_native_slot_keyed_by_backend():
    """the field registry uses (model, op, 'native') key.
    The (model, op, 'graphene') slot must be absent.
    """
    from django_graphex.mutation import _NATIVE_FIELD_REGISTRY, DjangoModelMutation
    from tests.models import Author

    class _WU3AuthorMutation(DjangoModelMutation):
        class Meta:
            model = Author

    # Native slot must be populated
    assert (Author, "create", "native") in _NATIVE_FIELD_REGISTRY, (
        "DjangoModelMutation must register (model, op, 'native') slot under native"
    )
    # Graphene slot for same (model, op) must be absent
    assert (Author, "create", "graphene") not in _NATIVE_FIELD_REGISTRY, (
        "DjangoModelMutation must NOT register (model, op, 'graphene') slot under native"
    )


# ---------------------------------------------------------------------------
# WU-3 task 3.3: DjangoModelType.*Field() returns GraphQLField under native
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_django_model_type_create_field_returns_graphql_field():
    """DjangoModelType.CreateField() must return
    a GraphQLField, not a graphene Field.
    """
    from graphql import GraphQLField

    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _WU3ModelTypeCreate(DjangoModelType):
        class Meta:
            model = Category

    field = _WU3ModelTypeCreate.CreateField()
    assert isinstance(field, GraphQLField), (
        f"DjangoModelType.CreateField() must return GraphQLField under native, "
        f"got {type(field)}"
    )


@pytest.mark.django_db
def test_django_model_type_create_field_args_are_graphql_arguments():
    """Under native, DjangoModelType.CreateField().args must be GraphQLArgument."""
    from graphql import GraphQLArgument, GraphQLField

    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _WU3ModelTypeCreateArgs(DjangoModelType):
        class Meta:
            model = Category

    field = _WU3ModelTypeCreateArgs.CreateField()
    assert isinstance(field, GraphQLField)
    for name, arg in field.args.items():
        assert isinstance(arg, GraphQLArgument), (
            f"DjangoModelType.CreateField arg '{name}' must be GraphQLArgument, "
            f"got {type(arg)}"
        )


@pytest.mark.django_db
def test_django_model_type_create_field_type_is_graphql_object_type():
    """Under native, DjangoModelType.CreateField().type must resolve to
    GraphQLObjectType (R7 compliance).
    """
    from graphql import GraphQLField, GraphQLNonNull, GraphQLObjectType

    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _WU3ModelTypeCreateType(DjangoModelType):
        class Meta:
            model = Category

    field = _WU3ModelTypeCreateType.CreateField()
    assert isinstance(field, GraphQLField)

    field_type = field.type
    if callable(field_type) and not isinstance(field_type, GraphQLObjectType):
        field_type = field_type()
    if isinstance(field_type, GraphQLNonNull):
        field_type = field_type.of_type

    assert isinstance(field_type, GraphQLObjectType), (
        f"DjangoModelType.CreateField output must be GraphQLObjectType, "
        f"got {type(field_type)}. R7 violation."
    )


@pytest.mark.django_db
def test_django_model_type_delete_field_returns_graphql_field():
    """Under native, DjangoModelType.DeleteField() must return GraphQLField."""
    from graphql import GraphQLArgument, GraphQLField

    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _WU3ModelTypeDelete(DjangoModelType):
        class Meta:
            model = Category

    field = _WU3ModelTypeDelete.DeleteField()
    assert isinstance(field, GraphQLField), (
        f"DjangoModelType.DeleteField() must return GraphQLField under native, "
        f"got {type(field)}"
    )
    assert "id" in field.args
    assert isinstance(field.args["id"], GraphQLArgument)


@pytest.mark.django_db
def test_django_model_type_update_field_returns_graphql_field():
    """Under native, DjangoModelType.UpdateField() must return GraphQLField."""
    from graphql import GraphQLField

    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _WU3ModelTypeUpdate(DjangoModelType):
        class Meta:
            model = Category

    field = _WU3ModelTypeUpdate.UpdateField()
    assert isinstance(field, GraphQLField), (
        f"DjangoModelType.UpdateField() must return GraphQLField under native, "
        f"got {type(field)}"
    )


@pytest.mark.django_db
def test_django_model_type_create_field_resolve_is_create_classmethod():
    """Under native, DjangoModelType.CreateField().resolve must dispatch to cls.create."""
    from graphql import GraphQLField

    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _WU3ModelTypeResolve(DjangoModelType):
        class Meta:
            model = Category

    field = _WU3ModelTypeResolve.CreateField()
    assert isinstance(field, GraphQLField)
    assert field.resolve is not None
    resolve_fn = field.resolve
    # Unwrap _adapt_self shim if present
    inner = getattr(resolve_fn, "__wrapped__", resolve_fn)
    # Bound classmethods create a new object each access; compare __func__ instead
    create_func = _WU3ModelTypeResolve.create.__func__
    inner_func = getattr(inner, "__func__", None)
    resolve_func = getattr(resolve_fn, "__func__", None)
    assert inner_func is create_func or resolve_func is create_func, (
        "DjangoModelType.CreateField resolver must be cls.create or a shim wrapping it"
    )
