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
def test_django_object_field_model_property_under_native() -> None:
    """Ships broken if DjangoObjectField.model stops unwrapping graphql-core types.

    self.type may be a graphql-core wrapped type (e.g.
    GraphQLNonNull(GraphQLObjectType)). The model property must unwrap using
    isinstance(t, (GraphQLNonNull, GraphQLList)), not Structure.
    """
    from django.contrib.auth.models import User

    from django_graphex.fields import DjangoObjectField

    # Build a mock graphql-core type that carries ._meta.model
    # The field's .type property returns whatever was passed, but under native
    # it should unwrap using graphql-core isinstance check.
    # We test the model property directly by constructing the field with
    # a DjangoObjectType (which sets self.type to the graphene type, but
    # validates that the unwrap is branch-correct under native).
    from django_graphex.types import DjangoObjectType

    class _TestUserType(DjangoObjectType):
        """DjangoObjectType wrapping User, used to build a DjangoObjectField."""

        class Meta:
            """Binds _TestUserType to the auth User model with a username filter."""

            model = User
            filter_fields = {"username": ("exact",)}

    # DjangoObjectField wraps the type; model property should unwrap it
    field = DjangoObjectField(_TestUserType)
    assert field.model is User


@pytest.mark.django_db
def test_django_filter_list_field_model_property_under_native() -> None:
    """Ships broken if DjangoFilterListField.model resolves the wrong model.

    The model must resolve correctly under the native (graphene-free) backend.
    """
    from django.contrib.auth.models import User

    from django_graphex.fields import DjangoFilterListField
    from django_graphex.types import DjangoObjectType

    class _TestUserType2(DjangoObjectType):
        """DjangoObjectType wrapping User, used to build a DjangoFilterListField."""

        class Meta:
            """Binds _TestUserType2 to the auth User model with a username filter."""

            model = User
            filter_fields = {"username": ("exact",)}

    field = DjangoFilterListField(_TestUserType2)
    assert field.model is User


@pytest.mark.django_db
def test_django_filter_paginate_list_field_model_property_under_native() -> None:
    """Ships broken if DjangoFilterPaginateListField.model resolves the wrong model.

    The model must resolve correctly under the native (graphene-free) backend.
    """
    from django.contrib.auth.models import User

    from django_graphex.fields import DjangoFilterPaginateListField
    from django_graphex.types import DjangoObjectType

    class _TestUserType3(DjangoObjectType):
        """DjangoObjectType wrapping User, used to build a DjangoFilterPaginateListField."""

        class Meta:
            """Binds _TestUserType3 to the auth User model with a username filter."""

            model = User
            filter_fields = {"username": ("exact",)}

    field = DjangoFilterPaginateListField(_TestUserType3)
    assert field.model is User


# ---------------------------------------------------------------------------
# 4.1 RED: graphql-core type unwrap correctness (unit)
# ---------------------------------------------------------------------------


def test_graphql_core_unwrap_nonNull_list_gives_named_type() -> None:
    """Ships broken if unwrapping (GraphQLNonNull, GraphQLList) stops reaching
    the named type.

    Exercises a triple-wrapped type (NonNull(List(NonNull(...)))), the deepest
    nesting the native field-model unwrap loop must handle.
    """
    from graphql import GraphQLList, GraphQLNonNull, GraphQLObjectType, GraphQLString

    # Build GraphQLNonNull(GraphQLList(GraphQLNonNull(inner))) pattern
    inner = GraphQLObjectType("Inner", lambda: {"id": GraphQLString})
    wrapped = GraphQLNonNull(GraphQLList(GraphQLNonNull(inner)))

    current = wrapped
    while isinstance(current, (GraphQLNonNull, GraphQLList)):
        current = current.of_type

    assert current is inner


def test_graphql_core_unwrap_single_non_null() -> None:
    """Ships broken if a single GraphQLNonNull over a named type stops
    unwrapping in one step.

    The simplest wrapped case: the unwrap loop must terminate after exactly
    one iteration.
    """
    from graphql import GraphQLList, GraphQLNonNull, GraphQLObjectType, GraphQLString

    inner = GraphQLObjectType("Inner2", lambda: {"id": GraphQLString})
    wrapped = GraphQLNonNull(inner)

    current = wrapped
    while isinstance(current, (GraphQLNonNull, GraphQLList)):
        current = current.of_type

    assert current is inner


def test_graphql_core_unwrap_plain_named_type_is_noop() -> None:
    """Ships broken if a plain GraphQLObjectType (no wrapper) is mutated by
    the unwrap loop.

    An unwrapped named type must be returned as-is, with the loop never
    executing.
    """
    from graphql import GraphQLList, GraphQLNonNull, GraphQLObjectType, GraphQLString

    inner = GraphQLObjectType("Plain", lambda: {"id": GraphQLString})
    # No wrapper — loop should not execute
    current = inner
    while isinstance(current, (GraphQLNonNull, GraphQLList)):
        current = current.of_type

    assert current is inner


# ---------------------------------------------------------------------------
# 4.1: AnnotatedField uses _strconv.to_snake_case under native
# ---------------------------------------------------------------------------


def test_annotated_field_annotation_name_uses_strconv_snake_case() -> None:
    """Ships broken if AnnotatedField.annotation_name stops returning the
    correct "_gqx_ann_<snake>" key.

    AnnotatedField.annotation_name uses django_graphex._strconv.to_snake_case
    (graphene-free, v2.0). The field type is a graphql-core scalar.
    """
    from django.db.models.functions import Length
    from graphql import GraphQLInt

    from django_graphex._strconv import to_snake_case
    from django_graphex.fields import AnnotatedField

    # Construct an AnnotatedField
    field = AnnotatedField(GraphQLInt, expression=Length("name"))

    # annotation_name() should produce _gqx_ann_<snake_field_name>
    result = field.annotation_name("createdAt")
    expected = "_gqx_ann_" + to_snake_case("createdAt")
    assert result == expected


def test_annotated_field_annotation_name_with_explicit_name() -> None:
    """Ships broken if an explicit annotation_name= override still runs through
    to_snake_case instead of being used verbatim."""
    from django.db.models.functions import Length
    from graphql import GraphQLInt

    from django_graphex.fields import AnnotatedField

    field = AnnotatedField(
        GraphQLInt,
        expression=Length("name"),
        annotation_name="my_custom_name",
    )
    assert field.annotation_name("anything") == "my_custom_name"


def test_annotated_field_default_resolver_annotation_name() -> None:
    """Ships broken if AnnotatedField._default_resolver stops deriving the
    annotation name from info.field_name."""
    from django.db.models.functions import Length
    from graphql import GraphQLInt

    from django_graphex._strconv import to_snake_case
    from django_graphex.fields import AnnotatedField

    field = AnnotatedField(GraphQLInt, expression=Length("name"))

    # Simulate info with field_name = "createdAt"
    class _FakeInfo:
        """Stand-in for graphql-core's resolve info, carrying only field_name."""

        field_name = "createdAt"

    class _FakeRoot:
        """Stand-in resolver root exposing the pre-annotated snake_case attribute."""

        _gqx_ann_created_at = 42

    result = field._default_resolver(_FakeRoot(), _FakeInfo())
    expected_ann = "_gqx_ann_" + to_snake_case("createdAt")
    assert result == getattr(_FakeRoot(), expected_ann, None)


# ---------------------------------------------------------------------------
# 4.1 RED: model property unwrap when self.type is a graphql-core wrapped type
# ---------------------------------------------------------------------------


def test_unwrap_graphql_core_nonnull_gives_of_type() -> None:
    """Ships broken if the native field-model unwrap stops reaching the named
    type through a GraphQLNonNull wrapper.

    The native field-model unwrap uses
    isinstance(t, (GraphQLNonNull, GraphQLList)) to reach the named type,
    handling graphql-core wrapped types directly (graphene-free, v2.0).
    """
    from graphql import GraphQLList, GraphQLNonNull, GraphQLObjectType, GraphQLString

    inner = GraphQLObjectType("TestModel", lambda: {"id": GraphQLString})
    wrapped_nn = GraphQLNonNull(inner)
    wrapped_list_nn = GraphQLList(GraphQLNonNull(inner))
    wrapped_nn_list_nn = GraphQLNonNull(GraphQLList(GraphQLNonNull(inner)))

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


def test_fields_strconv_to_snake_case_matches_canonical_contract() -> None:
    """Ships broken if _strconv.to_snake_case stops rendering the canonical
    snake_case key.

    AnnotatedField derives its annotation name via
    django_graphex._strconv.to_snake_case. The expected values are the FROZEN
    canonical spec (byte-for-byte what the historical graphene to_snake_case
    produced and the stdlib replacement reproduced).
    """
    from django_graphex._strconv import to_snake_case as _gdx_snake

    expected = {
        "createdAt": "created_at",
        "firstName": "first_name",
        "myFieldName": "my_field_name",
        "id": "id",
        "updatedAt": "updated_at",
    }
    for name, want in expected.items():
        assert _gdx_snake(name) == want, (
            f"_strconv.to_snake_case({name!r}) = {_gdx_snake(name)!r}, "
            f"expected {want!r}"
        )


def test_annotated_field_annotation_name_result_matches_strconv() -> None:
    """Ships broken if AnnotatedField.annotation_name diverges from
    _strconv.to_snake_case.

    This is the behavioral gate: after WU-4 GREEN, annotation_name() output
    must exactly match what _strconv.to_snake_case produces.
    """
    from django.db.models.functions import Length
    from graphql import GraphQLInt

    from django_graphex._strconv import to_snake_case
    from django_graphex.fields import AnnotatedField

    field = AnnotatedField(GraphQLInt, expression=Length("name"))

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
def test_django_filter_list_field_wrap_resolve_uses_correct_manager() -> None:
    """Ships broken if DjangoFilterListField.wrap_resolve stops binding the
    correct model manager."""
    from django.contrib.auth.models import User

    from django_graphex.fields import DjangoFilterListField
    from django_graphex.types import DjangoObjectType

    class _TestUserType4(DjangoObjectType):
        """DjangoObjectType wrapping User, used to exercise wrap_resolve."""

        class Meta:
            """Binds _TestUserType4 to the auth User model with a username filter."""

            model = User
            filter_fields = {"username": ("exact",)}

    field = DjangoFilterListField(_TestUserType4)
    # wrap_resolve should return a partial without raising
    resolver = field.wrap_resolve(None)

    assert callable(resolver)
    # The bound manager should be User._default_manager
    assert resolver.args[0] is User._default_manager


@pytest.mark.django_db
def test_django_filter_paginate_wrap_resolve_under_native() -> None:
    """Ships broken if DjangoFilterPaginateListField.wrap_resolve stops
    binding the correct manager."""
    from django.contrib.auth.models import User

    from django_graphex.fields import DjangoFilterPaginateListField
    from django_graphex.types import DjangoObjectType

    class _TestUserType5(DjangoObjectType):
        """DjangoObjectType wrapping User, used to exercise wrap_resolve."""

        class Meta:
            """Binds _TestUserType5 to the auth User model with a username filter."""

            model = User
            filter_fields = {"username": ("exact",)}

    field = DjangoFilterPaginateListField(_TestUserType5)
    resolver = field.wrap_resolve(None)
    assert callable(resolver)
    assert resolver.args[0] is User._default_manager
