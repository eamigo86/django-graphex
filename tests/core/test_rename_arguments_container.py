"""TDD RED — Rename 1: core "Mutation" argument container "class args" -> "class Arguments".

v2.0 HARD rename (no alias). Native hand-written "Mutation" subclasses now
declare their input arguments in a "class Arguments" inner class (unifying with
"DjangoModelMutation" / "DjangoModelType" which already use "Arguments").

Tests:
- "class Arguments" is read by "Mutation.Field()" (new name works).
- A subclass that (legacy) defines "class args" and NO "Arguments" raises a
  helpful "TypeError" naming the rename (guard).
- "class Arguments" follows the same resolution semantics as before
  ("cls.__dict__" override wins, empty default on the base).

Run:
    .venv/bin/python -m pytest -q tests/core/test_rename_arguments_container.py --no-cov
"""

from __future__ import annotations

import pytest


def test_field_reads_class_arguments() -> None:
    """Ships broken if "Mutation.Field()" stops compiling args from
    "class Arguments" (the new name).
    """
    from graphql import GraphQLArgument, GraphQLField, GraphQLNonNull, GraphQLString

    from django_graphex.core.mutation import Mutation

    class MyMutation(Mutation):
        class Arguments:
            name = GraphQLArgument(GraphQLNonNull(GraphQLString))

        @staticmethod
        def mutate(root, info, name=None):
            return name

    field = MyMutation.Field()
    assert isinstance(field, GraphQLField)
    assert "name" in field.args
    assert isinstance(field.args["name"], GraphQLArgument)
    assert isinstance(field.args["name"].type, GraphQLNonNull)
    assert field.args["name"].type.of_type is GraphQLString


def test_field_empty_when_arguments_absent() -> None:
    """Ships broken if a mutation without "Arguments" stops having an empty
    args dict (base default).
    """
    from graphql import GraphQLField

    from django_graphex.core.mutation import Mutation

    class MyMutation(Mutation):
        @staticmethod
        def mutate(root, info):
            return None

    field = MyMutation.Field()
    assert isinstance(field, GraphQLField)
    assert field.args == {}


def test_legacy_class_args_raises_helpful_typeerror() -> None:
    """Ships broken if a subclass defining legacy "class args" and NO
    "Arguments" fails silently instead of LOUDLY.

    HARD rename guard: the old inner-class name must not silently no-op (it would
    have compiled zero arguments before). Building the field raises a "TypeError"
    that names the rename so users know exactly what to do.
    """
    from graphql import GraphQLArgument, GraphQLNonNull, GraphQLString

    from django_graphex.core.mutation import Mutation

    class LegacyMutation(Mutation):
        class args:  # legacy name — should be rejected
            name = GraphQLArgument(GraphQLNonNull(GraphQLString))

        @staticmethod
        def mutate(root, info, name=None):
            return name

    with pytest.raises(TypeError) as exc:
        LegacyMutation.Field()
    msg = str(exc.value)
    assert "args" in msg
    assert "Arguments" in msg


def test_arguments_override_wins_over_base_default() -> None:
    """Ships broken if "cls.__dict__['Arguments']" (the subclass override)
    stops being used in favor of the base's Arguments.
    """
    from graphql import GraphQLArgument, GraphQLField, GraphQLInt

    from django_graphex.core.mutation import Mutation

    class MyMutation(Mutation):
        class Arguments:
            age = GraphQLArgument(GraphQLInt)

        @staticmethod
        def mutate(root, info, age=None):
            return age

    field = MyMutation.Field()
    assert isinstance(field, GraphQLField)
    assert "age" in field.args


def test_arguments_and_legacy_args_together_prefers_arguments() -> None:
    """Ships broken if, with BOTH "Arguments" and "args" present, "Arguments"
    stops winning (no guard should fire in this case).

    The guard only fires when "args" is present WITHOUT "Arguments" — a user
    who has migrated to "Arguments" but left a stray "args" helper class around
    still gets the correct (new) behavior.
    """
    from graphql import GraphQLArgument, GraphQLField, GraphQLString

    from django_graphex.core.mutation import Mutation

    class MyMutation(Mutation):
        class Arguments:
            name = GraphQLArgument(GraphQLString)

        class args:  # noqa: N801 - stray legacy leftover, must be ignored
            should_not_appear = GraphQLArgument(GraphQLString)

        @staticmethod
        def mutate(root, info, name=None):
            return name

    field = MyMutation.Field()
    assert isinstance(field, GraphQLField)
    assert "name" in field.args
    assert "should_not_appear" not in field.args
