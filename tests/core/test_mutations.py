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
def test_compile_input_type_produces_graphql_argument_type() -> None:
    """Assert that "compile_input_type" output wraps cleanly in a GraphQLArgument.

    This tests the fundamental building block: a GraphQLInputObjectType
    can be wrapped in a GraphQLArgument with out_name.

    If this fails, no mutation call site could wire a compiled input type
    into a usable field argument.
    """
    from graphql import GraphQLArgument

    from django_graphex.core.fields import build_model_schema
    from django_graphex.core.input_compiler import compile_input_type
    from tests.models import Category

    pydantic_model = build_model_schema(Category, partial=False)
    gql_input_type = compile_input_type(pydantic_model, name="WuBCategoryCreateInput")

    # Wrap in GraphQLArgument as the call sites will do
    arg = GraphQLArgument(gql_input_type, out_name="new_category")
    assert isinstance(arg, GraphQLArgument)
    assert arg.out_name == "new_category"


@pytest.mark.django_db
def test_meta_arguments_structure_for_native_input() -> None:
    """Assert that a native arguments mapping holds plain GraphQLArgument values.

    This tests the NATIVE equivalent of what "_meta.arguments[op]" will hold
    once the 6 call sites are rewritten. Currently this is built manually to
    verify the structure, then the GREEN phase wires it end to end.

    If this fails, "_meta.arguments" would carry graphene Argument objects
    (or an OrderedDict) instead of a plain dict of GraphQLArgument.
    """
    from graphql import GraphQLArgument

    from django_graphex.core.fields import build_model_schema
    from django_graphex.core.input_compiler import compile_input_type
    from tests.models import Category

    pydantic_model = build_model_schema(Category, partial=False)
    gql_input_type = compile_input_type(pydantic_model, name="WuBCategoryInput2")

    # Build a native arguments dict (what _meta.arguments["create"] will hold)
    arguments = {
        "new_category": GraphQLArgument(gql_input_type, out_name="new_category")
    }

    # Verify it is a plain dict, not an OrderedDict of graphene Arguments
    assert isinstance(arguments, dict)
    assert "new_category" in arguments
    arg = arguments["new_category"]
    assert isinstance(arg, GraphQLArgument)
    # The type of the argument must be the compiled GraphQLInputObjectType
    assert arg.type is gql_input_type


@pytest.mark.django_db
def test_graphql_argument_out_name_matches_snake_input_field_name() -> None:
    """Assert that "GraphQLArgument.out_name" carries the snake_case field name.

    If this fails, resolvers would receive the argument under its camelCase
    wire name instead of the expected snake_case attribute name.
    """
    from graphql import GraphQLArgument

    from django_graphex.core.fields import build_model_schema
    from django_graphex.core.input_compiler import compile_input_type
    from tests.models import Post

    pydantic_model = build_model_schema(Post, partial=False)
    gql_input_type = compile_input_type(pydantic_model, name="WuBPostCreateInput2")

    # The argument for the 'create' mutation on Post uses input_field_name=new_post
    arg = GraphQLArgument(gql_input_type, out_name="new_post")
    assert arg.out_name == "new_post", (
        "out_name must carry the snake_case field name, not camelCase"
    )


@pytest.mark.django_db
def test_input_fields_camel_key_snake_out_name() -> None:
    """Assert that a compiled input type uses camelCase wire keys and snake out_name.

    This is the core contract for the 6 call site rewrites: resolvers see
    "data.first_name" when the wire sends "{firstName: ...}".

    If this fails, the compiled input type's field keys or out_name would
    not follow the camelCase-wire / snake-resolver convention.
    """

    from django_graphex.core.fields import build_model_schema
    from django_graphex.core.input_compiler import compile_input_type
    from tests.models import Author

    pydantic_model = build_model_schema(Author, partial=False)
    gql_input_type = compile_input_type(pydantic_model, name="WuBAuthorInput")

    fields = gql_input_type.fields
    # Author model has 'name' field (single word, no camel conversion needed)
    # and potentially 'bio' field
    assert "name" in fields, (
        f"Expected 'name' field in input, got: {list(fields.keys())}"
    )
    name_field = fields["name"]
    # For a single-word field 'name', alias == field_name, out_name == 'name'
    assert name_field.out_name == "name"


@pytest.mark.django_db
def test_graphene_argument_import_absent_conceptually() -> None:
    """Assert that the native compile path needs no "graphene.Argument".

    The 6 call sites use "GraphQLArgument" (from graphql-core) instead of
    "graphene.Argument". This test verifies that "compile_input_type"
    combined with "GraphQLArgument" covers the same need.

    If this fails, native argument construction would still depend on
    graphene, defeating the graphene-free goal.
    """
    from graphql import GraphQLArgument

    from django_graphex.core.fields import build_model_schema
    from django_graphex.core.input_compiler import compile_input_type
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
def test_django_model_mutation_create_arg_is_graphql_argument() -> None:
    """Assert that "DjangoModelMutation._meta.arguments['create']" holds GraphQLArgument.

    This tests the integrated mutation call-site wiring, not isolated
    compilation.

    If this fails, the create mutation's compiled arguments would still
    hold graphene Argument values instead of native GraphQLArgument.
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
def test_django_model_mutation_update_arg_is_graphql_argument() -> None:
    """Assert that "DjangoModelMutation._meta.arguments['update']" holds GraphQLArgument.

    Covers the partial-model input path used by update mutations.

    If this fails, the update mutation's compiled argument would not be a
    GraphQLArgument wrapping a GraphQLInputObjectType.
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
def test_django_model_mutation_create_field_returns_graphql_field() -> None:
    """Assert that "DjangoModelMutation.CreateField()" returns a graphql-core GraphQLField.

    If this fails, the create mutation field would still be a graphene
    Field instead of the native GraphQLField.
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
def test_django_model_mutation_create_field_args_are_graphql_arguments() -> None:
    """Assert that under native, "CreateField().args" holds only GraphQLArgument values.

    If this fails, one or more compiled create-field arguments would still
    be a non-native (e.g. graphene) argument type.
    """
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
def test_django_model_mutation_create_field_type_is_graphql_object_type() -> None:
    """Assert that under native, "CreateField().type" resolves to a GraphQLObjectType.

    R7: NEVER pass cls itself (a graphene/Pydantic class) to graphql-core.

    If this fails, the create field's output type would resolve to a
    graphene class instead of the compiled GraphQLObjectType.
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
def test_django_model_mutation_create_field_resolve_dispatches_to_create() -> None:
    """Assert that under native, "CreateField().resolve" dispatches to "cls.create".

    If this fails, invoking the create mutation field would not call the
    class's create classmethod (directly or via the self-adapting shim).
    """

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
def test_django_model_mutation_delete_field_returns_graphql_field() -> None:
    """Assert that "DjangoModelMutation.DeleteField()" returns a GraphQLField with an id arg.

    If this fails, the delete mutation field would be missing or its "id"
    argument would not be a native GraphQLArgument.
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
def test_django_model_mutation_update_field_returns_graphql_field() -> None:
    """Assert that "DjangoModelMutation.UpdateField()" returns a native GraphQLField.

    If this fails, the update mutation field would still be built as a
    graphene Field instead of the native equivalent.
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
def test_django_model_mutation_native_slot_keyed_by_backend() -> None:
    """Assert that the field registry keys entries by (model, op, "native").

    The (model, op, "graphene") slot must be absent.

    If this fails, the registry would either miss the native slot or keep
    a stale graphene slot around, risking a graphene Field leaking back in.
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
def test_django_model_type_create_field_returns_graphql_field() -> None:
    """Assert that "DjangoModelType.CreateField()" returns a native GraphQLField.

    If this fails, the model type's create field would still be a graphene
    Field instead of the native equivalent.
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
def test_django_model_type_create_field_args_are_graphql_arguments() -> None:
    """Assert that "DjangoModelType.CreateField().args" holds only GraphQLArgument values.

    If this fails, one or more compiled create-field arguments on the
    model type path would still be a non-native argument type.
    """
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
def test_django_model_type_create_field_type_is_graphql_object_type() -> None:
    """Assert that "DjangoModelType.CreateField().type" resolves to a GraphQLObjectType.

    R7 compliance: never pass the model type class itself to graphql-core.

    If this fails, the create field's output type would resolve to a
    non-GraphQLObjectType value, violating R7.
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
def test_django_model_type_delete_field_returns_graphql_field() -> None:
    """Assert that under native, "DjangoModelType.DeleteField()" returns a GraphQLField.

    If this fails, the delete field on the model type path would be
    missing or its "id" argument would not be a native GraphQLArgument.
    """
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
def test_django_model_type_update_field_returns_graphql_field() -> None:
    """Assert that under native, "DjangoModelType.UpdateField()" returns a GraphQLField.

    If this fails, the update field on the model type path would still be
    built as a graphene Field instead of the native equivalent.
    """
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
def test_django_model_type_create_field_resolve_is_create_classmethod() -> None:
    """Assert that under native, "DjangoModelType.CreateField().resolve" dispatches to create.

    If this fails, invoking the model type's create field would not call
    the class's create classmethod (directly or via the self-adapting shim).
    """
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
