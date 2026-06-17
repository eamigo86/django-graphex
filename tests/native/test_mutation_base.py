"""TDD WU-2 RED — native/mutation.py: Mutation base class.

Tests:
- ``from django_graphex.native.mutation import Mutation`` imports cleanly.
- ``MyMutation(Mutation).Field()`` returns a ``GraphQLField``.
- Field resolve is the ``_adapt_self``-wrapped ``cls.mutate``.
- ``args`` on the field reflects ``class args`` declarations.
- A plain ``def mutate(root, info)`` is passed through unshimmed.
- ``from django_graphex import Mutation`` works (public export).

Run:
    GDX_BACKEND=native .venv/bin/python -m pytest -q tests/native/test_mutation_base.py
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# 2.3.1  Mutation can be imported from native module
# ---------------------------------------------------------------------------


def test_mutation_importable():
    """Mutation can be imported from django_graphex.native.mutation."""
    from django_graphex.native.mutation import Mutation
    assert Mutation is not None


# ---------------------------------------------------------------------------
# 2.3.2  Field() returns a GraphQLField
# ---------------------------------------------------------------------------


def test_field_returns_graphql_field():
    """MyMutation(Mutation).Field() returns a GraphQLField instance."""
    from graphql import GraphQLArgument, GraphQLField, GraphQLString

    from django_graphex.native.mutation import Mutation

    class MyMutation(Mutation):
        class args:
            name = GraphQLArgument(GraphQLString)

        @staticmethod
        def mutate(root, info, name=None):
            return name

    result = MyMutation.Field()
    assert isinstance(result, GraphQLField), (
        "Mutation.Field() must return a GraphQLField"
    )


# ---------------------------------------------------------------------------
# 2.3.3  Field resolve dispatches mutate (self→root via _adapt_self)
# ---------------------------------------------------------------------------


def test_field_resolve_wraps_self_first_mutate():
    """If mutate uses 'self' as first param, resolve is the _adapt_self shim."""
    import warnings

    from graphql import GraphQLField

    from django_graphex.native.mutation import Mutation

    calls = []

    class MyMutation(Mutation):
        class args:
            pass

        def mutate(self, info, **kw):
            calls.append((self, info))
            return "ok"

    field = MyMutation.Field()
    assert isinstance(field, GraphQLField)

    fake_root = object()
    fake_info = object()

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = field.resolve(fake_root, fake_info)

    assert result == "ok"
    # _adapt_self shim should emit DeprecationWarning
    assert any(issubclass(warning.category, DeprecationWarning) for warning in w), (
        "A self-first mutate must trigger DeprecationWarning via _adapt_self"
    )


def test_field_resolve_passthrough_for_root_first_mutate():
    """If mutate uses 'root' as first param, resolve is passed through (no shim)."""
    import warnings

    from graphql import GraphQLField

    from django_graphex.native.mutation import Mutation

    calls = []

    class MyMutation(Mutation):
        class args:
            pass

        @staticmethod
        def mutate(root, info, **kw):
            calls.append((root, info))
            return "called"

    field = MyMutation.Field()
    assert isinstance(field, GraphQLField)

    fake_root = object()
    fake_info = object()

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = field.resolve(fake_root, fake_info)

    assert result == "called"
    # No DeprecationWarning for (root, info) first params
    assert not any(issubclass(warning.category, DeprecationWarning) for warning in w), (
        "No DeprecationWarning should be emitted for root-first mutate"
    )


# ---------------------------------------------------------------------------
# 2.3.4  args on the field reflects class args declarations
# ---------------------------------------------------------------------------


def test_field_args_reflect_class_args():
    """Field().args contains GraphQLArgument instances for each class args annotation."""
    from graphql import GraphQLArgument, GraphQLField, GraphQLNonNull, GraphQLString

    from django_graphex.native.mutation import Mutation

    class MyMutation(Mutation):
        class args:
            name = GraphQLArgument(GraphQLNonNull(GraphQLString))

        @staticmethod
        def mutate(root, info, name=None):
            return name

    field = MyMutation.Field()
    assert isinstance(field, GraphQLField)
    assert "name" in field.args, "Field args must contain 'name'"
    garg = field.args["name"]
    assert isinstance(garg, GraphQLArgument), (
        "Each arg must be a GraphQLArgument, not a graphene Argument"
    )
    assert isinstance(garg.type, GraphQLNonNull)
    assert garg.type.of_type is GraphQLString


def test_field_args_empty_when_class_args_is_empty():
    """Field().args is empty when class args has no attributes."""
    from graphql import GraphQLField

    from django_graphex.native.mutation import Mutation

    class MyMutation(Mutation):
        class args:
            pass

        @staticmethod
        def mutate(root, info):
            return None

    field = MyMutation.Field()
    assert isinstance(field, GraphQLField)
    assert field.args == {}, (
        "Field args must be empty when class args has no Argument declarations"
    )


def test_field_args_multiple_arguments():
    """Field().args contains all declared arguments."""
    from graphql import (
        GraphQLArgument,
        GraphQLField,
        GraphQLInt,
        GraphQLNonNull,
        GraphQLString,
    )

    from django_graphex.native.mutation import Mutation

    class MyMutation(Mutation):
        class args:
            name = GraphQLArgument(GraphQLNonNull(GraphQLString))
            age = GraphQLArgument(GraphQLInt)

        @staticmethod
        def mutate(root, info, name=None, age=None):
            return name

    field = MyMutation.Field()
    assert isinstance(field, GraphQLField)
    assert "name" in field.args
    assert "age" in field.args
    assert isinstance(field.args["name"], GraphQLArgument)
    assert isinstance(field.args["age"], GraphQLArgument)


# ---------------------------------------------------------------------------
# 2.3.5  No schema assembly — inspection only (Phase 5 boundary)
# ---------------------------------------------------------------------------


def test_no_schema_assembly_needed():
    """Field() is inspectable in isolation — no GraphQLSchema required."""
    from graphql import GraphQLArgument, GraphQLField, GraphQLID, GraphQLNonNull

    from django_graphex.native.mutation import Mutation

    class MyMutation(Mutation):
        class args:
            pk = GraphQLArgument(GraphQLNonNull(GraphQLID))

        @staticmethod
        def mutate(root, info, pk=None):
            return pk

    # Should succeed without building a schema
    field = MyMutation.Field()
    assert isinstance(field, GraphQLField)
    assert "pk" in field.args


# ---------------------------------------------------------------------------
# 6.3 RED — from django_graphex import Mutation (public API)
# ---------------------------------------------------------------------------


def test_mutation_importable_from_public_api():
    """from django_graphex import Mutation raises no ImportError."""
    try:
        from django_graphex import Mutation  # noqa: F401
    except ImportError as e:
        pytest.fail(f"Importing Mutation from django_graphex raised ImportError: {e}")


def test_public_mutation_is_native_mutation():
    """django_graphex.Mutation is the same class as native/mutation.py Mutation."""
    from django_graphex import Mutation as PublicMutation
    from django_graphex.native.mutation import Mutation as NativeMutation

    assert PublicMutation is NativeMutation, (
        "django_graphex.Mutation must be the native Mutation class"
    )


# ---------------------------------------------------------------------------
# Coverage gap: mutate defined on parent (MRO walk), and no mutate at all
# ---------------------------------------------------------------------------


def test_field_uses_mutate_from_parent_via_mro():
    """Field() finds mutate through MRO when not defined directly on the subclass."""
    from graphql import GraphQLField

    from django_graphex.native.mutation import Mutation

    class Base(Mutation):
        @staticmethod
        def mutate(root, info):
            return "from-base"

    class Child(Base):
        class args:
            pass

        # No mutate defined here — should walk MRO to find Base.mutate

    field = Child.Field()
    assert isinstance(field, GraphQLField)
    assert field.resolve(object(), object()) == "from-base"


def test_field_raises_when_no_mutate_defined():
    """Field() raises AttributeError when no mutate is defined anywhere in MRO."""
    from django_graphex.native.mutation import Mutation

    class NoMutate(Mutation):
        class args:
            pass

        # Deliberately no mutate

    with pytest.raises(AttributeError, match="must define a 'mutate'"):
        NoMutate.Field()


def test_class_args_public_non_argument_attr_fails_loudly():
    """A PUBLIC non-arg attr in ``class args`` now FAILS LOUDLY (CLEAN BREAK).

    Pre-FIX-1 ``_compile_args`` SILENTLY SKIPPED any non-native value (so a stray
    ``graphene.Argument`` — or any junk — vanished with no error, defeating the
    advertised clean break). The 2.0 contract (decision #1603) treats every PUBLIC
    attribute of ``class args`` as an arg declaration: a non-native value raises a
    clear ``TypeError`` naming the offending key. A genuine helper must be
    underscore-prefixed (``props`` strips it) — see the companion test below.
    """
    import pytest
    from graphql import GraphQLArgument, GraphQLString

    from django_graphex.native.mutation import Mutation

    class MyMutation(Mutation):
        class args:
            # A plain public string attr — no longer silently ignored.
            helper_text = "not an argument"
            name = GraphQLArgument(GraphQLString)

        @staticmethod
        def mutate(root, info, name=None):
            return name

    with pytest.raises(TypeError) as exc:
        MyMutation.Field()
    assert "helper_text" in str(exc.value)


def test_class_args_underscore_helper_is_ignored():
    """An UNDERSCORE-prefixed helper in ``class args`` is tolerated (props strips it).

    The CLEAN-BREAK loud-fail targets PUBLIC arg declarations only; a private
    helper (``_helper_text``) is filtered out by ``props`` and never reaches the
    arg normaliser, so it does not become a compiled arg and does not error.
    """
    from graphql import GraphQLArgument, GraphQLField, GraphQLString

    from django_graphex.native.mutation import Mutation

    class MyMutation(Mutation):
        class args:
            _helper_text = "not an argument"  # underscore → stripped by props()
            name = GraphQLArgument(GraphQLString)

        @staticmethod
        def mutate(root, info, name=None):
            return name

    field = MyMutation.Field()
    assert isinstance(field, GraphQLField)
    assert "name" in field.args
    assert "_helper_text" not in field.args
