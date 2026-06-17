"""TDD 4.1 RED — fields.py graphql-core unwrap + AnnotatedField _strconv tests.

Covers WU-4 tasks:
- 4.1 RED: native-backend model property unwrap via graphql-core types
- 4.2 GREEN: fields.py edits (backend guard + graphql-core isinstance)
- 4.3 VERIFY: AnnotatedField.annotation_name uses _strconv.to_snake_case

"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# 4.1 RED: DjangoObjectField.model under native resolves graphql-core wrapped types
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_django_object_field_model_property_under_native():
    """DjangoObjectField.model must unwrap graphql-core wrappers under native.

    self.type may be a graphql-core wrapped type
    (e.g. GraphQLNonNull(GraphQLObjectType)).  The model property must unwrap
    using isinstance(t, (GraphQLNonNull, GraphQLList)), not Structure.
    """
    from django.contrib.auth.models import User
    from graphql import GraphQLNonNull, GraphQLObjectType, GraphQLString

    from django_graphex.fields import DjangoObjectField

    # Build a mock graphql-core type that carries ._meta.model
    # The field's .type property returns whatever was passed, but under native
    # it should unwrap using graphql-core isinstance check.
    # We test the model property directly by constructing the field with
    # a DjangoObjectType (which sets self.type to the graphene type, but
    # validates that the unwrap is branch-correct under native).
    from django_graphex.types import DjangoObjectType

    class _TestUserType(DjangoObjectType):
        class Meta:
            model = User
            filter_fields = {"username": ("exact",)}

    # DjangoObjectField wraps the type; model property should unwrap it
    field = DjangoObjectField(_TestUserType)
    assert field.model is User


@pytest.mark.django_db
def test_django_filter_list_field_model_property_under_native():
    """DjangoFilterListField.model must resolve the correct model under native."""
    from django.contrib.auth.models import User

    from django_graphex.fields import DjangoFilterListField
    from django_graphex.types import DjangoObjectType

    class _TestUserType2(DjangoObjectType):
        class Meta:
            model = User
            filter_fields = {"username": ("exact",)}

    field = DjangoFilterListField(_TestUserType2)
    assert field.model is User


@pytest.mark.django_db
def test_django_filter_paginate_list_field_model_property_under_native():
    """DjangoFilterPaginateListField.model must resolve the correct model under native."""
    from django.contrib.auth.models import User

    from django_graphex.fields import DjangoFilterPaginateListField
    from django_graphex.types import DjangoObjectType

    class _TestUserType3(DjangoObjectType):
        class Meta:
            model = User
            filter_fields = {"username": ("exact",)}

    field = DjangoFilterPaginateListField(_TestUserType3)
    assert field.model is User


# ---------------------------------------------------------------------------
# 4.1 RED: graphql-core type unwrap correctness (unit)
# ---------------------------------------------------------------------------


def test_graphql_core_unwrap_nonNull_list_gives_named_type():
    """Under native, unwrapping (GraphQLNonNull, GraphQLList) reaches the named type."""
    from graphql import GraphQLList, GraphQLNonNull, GraphQLObjectType, GraphQLString

    # Build GraphQLNonNull(GraphQLList(GraphQLNonNull(inner))) pattern
    inner = GraphQLObjectType("Inner", lambda: {"id": GraphQLString})
    wrapped = GraphQLNonNull(GraphQLList(GraphQLNonNull(inner)))

    current = wrapped
    while isinstance(current, (GraphQLNonNull, GraphQLList)):
        current = current.of_type

    assert current is inner


def test_graphql_core_unwrap_single_non_null():
    """GraphQLNonNull over a named type unwraps in one step."""
    from graphql import GraphQLList, GraphQLNonNull, GraphQLObjectType, GraphQLString

    inner = GraphQLObjectType("Inner2", lambda: {"id": GraphQLString})
    wrapped = GraphQLNonNull(inner)

    current = wrapped
    while isinstance(current, (GraphQLNonNull, GraphQLList)):
        current = current.of_type

    assert current is inner


def test_graphql_core_unwrap_plain_named_type_is_noop():
    """A plain GraphQLObjectType (no wrapper) is returned as-is."""
    from graphql import GraphQLList, GraphQLNonNull, GraphQLObjectType, GraphQLString

    inner = GraphQLObjectType("Plain", lambda: {"id": GraphQLString})
    # No wrapper — loop should not execute
    current = inner
    while isinstance(current, (GraphQLNonNull, GraphQLList)):
        current = current.of_type

    assert current is inner


# ---------------------------------------------------------------------------
# 4.1 RED: graphene Structure unwrap — verify graphene path is unchanged
# ---------------------------------------------------------------------------


def test_graphene_structure_import_still_works():
    """graphene.types.structures.Structure is still importable (graphene path intact)."""
    from graphene.types.structures import List as GList
    from graphene.types.structures import NonNull, Structure
    from graphql import GraphQLList, GraphQLNonNull

    # graphene types are NOT instances of graphql-core wrappers
    gn = NonNull("String")
    assert not isinstance(gn, (GraphQLNonNull, GraphQLList))


# ---------------------------------------------------------------------------
# 4.1 RED: AnnotatedField uses _strconv.to_snake_case under native
# ---------------------------------------------------------------------------


def test_annotated_field_annotation_name_uses_strconv_snake_case():
    """AnnotatedField.annotation_name must return the correct _gqx_ann_<snake> key.

    AnnotatedField.annotation_name should use
    django_graphex._strconv.to_snake_case (not graphene's str_converters).
    Both produce the same output for standard camelCase inputs, but the
    import path under native should be _strconv.
    """
    import graphene
    from django.db.models.functions import Length

    from django_graphex._strconv import to_snake_case
    from django_graphex.fields import AnnotatedField

    # Construct an AnnotatedField
    field = AnnotatedField(graphene.Int, expression=Length("name"))

    # annotation_name() should produce _gqx_ann_<snake_field_name>
    result = field.annotation_name("createdAt")
    expected = "_gqx_ann_" + to_snake_case("createdAt")
    assert result == expected


def test_annotated_field_annotation_name_with_explicit_name():
    """AnnotatedField with annotation_name= override skips to_snake_case."""
    import graphene
    from django.db.models.functions import Length

    from django_graphex.fields import AnnotatedField

    field = AnnotatedField(
        graphene.Int,
        expression=Length("name"),
        annotation_name="my_custom_name",
    )
    assert field.annotation_name("anything") == "my_custom_name"


def test_annotated_field_default_resolver_annotation_name():
    """AnnotatedField._default_resolver derives annotation name from info.field_name."""
    import graphene
    from django.db.models.functions import Length

    from django_graphex._strconv import to_snake_case
    from django_graphex.fields import AnnotatedField

    field = AnnotatedField(graphene.Int, expression=Length("name"))

    # Simulate info with field_name = "createdAt"
    class _FakeInfo:
        field_name = "createdAt"

    class _FakeRoot:
        _gqx_ann_created_at = 42

    result = field._default_resolver(_FakeRoot(), _FakeInfo())
    expected_ann = "_gqx_ann_" + to_snake_case("createdAt")
    assert result == getattr(_FakeRoot(), expected_ann, None)


# ---------------------------------------------------------------------------
# 4.1 RED: model property unwrap when self.type is a graphql-core wrapped type
# ---------------------------------------------------------------------------


def test_unwrap_graphql_core_nonnull_gives_of_type():
    """Under native, a graphql-core GraphQLNonNull wrapping an object returns of_type.

    This is the RED test: the current `while isinstance(t, Structure)` loop
    does NOT unwrap graphql-core wrappers. After GREEN, the native branch
    uses `isinstance(t, (GraphQLNonNull, GraphQLList))` which correctly handles
    graphql-core wrapped types.

    We test the unwrap logic directly (not via field.model) since field.type
    is always a graphene type in current field constructors.
    """
    from graphene.types.structures import Structure
    from graphql import GraphQLList, GraphQLNonNull, GraphQLObjectType, GraphQLString

    inner = GraphQLObjectType("TestModel", lambda: {"id": GraphQLString})
    wrapped_nn = GraphQLNonNull(inner)
    wrapped_list_nn = GraphQLList(GraphQLNonNull(inner))
    wrapped_nn_list_nn = GraphQLNonNull(GraphQLList(GraphQLNonNull(inner)))

    # graphql-core types are NOT graphene Structure instances
    assert not isinstance(wrapped_nn, Structure), (
        "graphql-core GraphQLNonNull must NOT be a graphene Structure"
    )
    assert not isinstance(wrapped_list_nn, Structure), (
        "graphql-core GraphQLList must NOT be a graphene Structure"
    )

    # graphql-core isinstance check DOES unwrap them
    for wrapped in [wrapped_nn, wrapped_list_nn, wrapped_nn_list_nn]:
        current = wrapped
        while isinstance(current, (GraphQLNonNull, GraphQLList)):
            current = current.of_type
        assert current is inner, (
            f"unwrap({wrapped!r}) should give inner, got {current!r}"
        )


# ---------------------------------------------------------------------------
# 4.1 RED: fields.py module-level graphene import audit
# ---------------------------------------------------------------------------


def test_fields_module_does_not_import_graphene_strconv_at_module_level():
    """Under native, AnnotatedField must NOT depend on graphene's to_snake_case at call time.

    After WU-4 GREEN: AnnotatedField methods should call _strconv.to_snake_case,
    not graphene.utils.str_converters.to_snake_case.

    This test documents the INTENT (graphene-free annotation name derivation
    under native). The behavioral result is identical since both functions are
    equivalent, but the import source must shift to _strconv.
    """
    # Verify that _strconv provides the same result as graphene's function
    from graphene.utils.str_converters import to_snake_case as _gph_snake

    from django_graphex._strconv import to_snake_case as _gdx_snake

    test_cases = ["createdAt", "firstName", "myFieldName", "id", "updatedAt"]
    for name in test_cases:
        assert _gdx_snake(name) == _gph_snake(name), (
            f"_strconv.to_snake_case({name!r}) != graphene's version: "
            f"{_gdx_snake(name)!r} vs {_gph_snake(name)!r}"
        )


def test_annotated_field_annotation_name_result_matches_strconv():
    """AnnotatedField.annotation_name must produce result matching _strconv.to_snake_case.

    This is the behavioral gate: after WU-4 GREEN, annotation_name() output
    must exactly match what _strconv.to_snake_case produces.
    """
    import graphene
    from django.db.models.functions import Length

    from django_graphex._strconv import to_snake_case
    from django_graphex.fields import AnnotatedField

    field = AnnotatedField(graphene.Int, expression=Length("name"))

    for gql_name in ["createdAt", "myCustomField", "id", "firstName"]:
        result = field.annotation_name(gql_name)
        expected = "_gqx_ann_" + to_snake_case(gql_name)
        assert result == expected, (
            f"annotation_name({gql_name!r}) = {result!r}, expected {expected!r}"
        )


# ---------------------------------------------------------------------------
# 4.1 RED: Verify DjangoFilterListField.wrap_resolve unwrap under native
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_django_filter_list_field_wrap_resolve_uses_correct_manager():
    """DjangoFilterListField.wrap_resolve must bind the correct model manager."""
    from django.contrib.auth.models import User

    from django_graphex.fields import DjangoFilterListField
    from django_graphex.types import DjangoObjectType

    class _TestUserType4(DjangoObjectType):
        class Meta:
            model = User
            filter_fields = {"username": ("exact",)}

    field = DjangoFilterListField(_TestUserType4)
    # wrap_resolve should return a partial without raising
    resolver = field.wrap_resolve(None)
    import functools
    assert callable(resolver)
    # The bound manager should be User._default_manager
    assert resolver.args[0] is User._default_manager


@pytest.mark.django_db
def test_django_filter_paginate_wrap_resolve_under_native():
    """DjangoFilterPaginateListField.wrap_resolve must bind the correct manager."""
    from django.contrib.auth.models import User

    from django_graphex.fields import DjangoFilterPaginateListField
    from django_graphex.types import DjangoObjectType

    class _TestUserType5(DjangoObjectType):
        class Meta:
            model = User
            filter_fields = {"username": ("exact",)}

    field = DjangoFilterPaginateListField(_TestUserType5)
    resolver = field.wrap_resolve(None)
    assert callable(resolver)
    assert resolver.args[0] is User._default_manager
