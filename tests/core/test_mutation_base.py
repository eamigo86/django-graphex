"""TDD WU-2 RED — core/mutation.py: Mutation base class.

Tests:
- "from django_graphex.core.mutation import Mutation" imports cleanly.
- "MyMutation(Mutation).Field()" returns a "GraphQLField".
- Field resolve is the "_adapt_self"-wrapped "cls.mutate".
- "args" on the field reflects "class Arguments" declarations.
- A plain "def mutate(root, info)" is passed through unshimmed.
- "from django_graphex import Mutation" works (public export).

Run:
    .venv/bin/python -m pytest -q tests/core/test_mutation_base.py
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# 2.3.1  Mutation can be imported from native module
# ---------------------------------------------------------------------------


def test_mutation_importable() -> None:
    """Assert that "Mutation" imports cleanly from "django_graphex.core.mutation".

    If this fails, the native mutation base class would not be importable
    from its declared module path.
    """
    from django_graphex.core.mutation import Mutation

    assert Mutation is not None


# ---------------------------------------------------------------------------
# 2.3.2  Field() returns a GraphQLField
# ---------------------------------------------------------------------------


def test_field_returns_graphql_field() -> None:
    """Assert that "MyMutation(Mutation).Field()" returns a GraphQLField instance.

    If this fails, a mutation subclass would not produce a usable
    GraphQLField for schema assembly.
    """
    from graphql import GraphQLArgument, GraphQLField, GraphQLString

    from django_graphex.core.mutation import Mutation

    class MyMutation(Mutation):
        class Arguments:
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


def test_field_resolve_wraps_self_first_mutate() -> None:
    """Assert that a self-first "mutate" is wrapped by the "_adapt_self" shim.

    If this fails, a legacy self-first mutate signature would not be
    adapted (or would not emit the expected deprecation warning), likely
    crashing at call time or hiding the migration path from users.
    """
    import warnings

    from graphql import GraphQLField

    from django_graphex.core.mutation import Mutation

    calls = []

    class MyMutation(Mutation):
        class Arguments:
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


def test_field_resolve_passthrough_for_root_first_mutate() -> None:
    """Assert that a root-first "mutate" resolves without the "_adapt_self" shim.

    If this fails, a modern root-first mutate would be needlessly wrapped
    or would spuriously emit a deprecation warning.
    """
    import warnings

    from graphql import GraphQLField

    from django_graphex.core.mutation import Mutation

    calls = []

    class MyMutation(Mutation):
        class Arguments:
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
# 2.3.4  args on the field reflects class Arguments declarations
# ---------------------------------------------------------------------------


def test_field_args_reflect_class_args() -> None:
    """Assert that "Field().args" holds a GraphQLArgument for each declared attribute.

    If this fails, argument declarations on the mutation's "Arguments"
    class would not be reflected onto the compiled field's args mapping.
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
    assert "name" in field.args, "Field args must contain 'name'"
    garg = field.args["name"]
    assert isinstance(garg, GraphQLArgument), (
        "Each arg must be a GraphQLArgument, not a graphene Argument"
    )
    assert isinstance(garg.type, GraphQLNonNull)
    assert garg.type.of_type is GraphQLString


def test_field_args_empty_when_class_args_is_empty() -> None:
    """Assert that "Field().args" is empty when "Arguments" declares nothing.

    If this fails, an empty Arguments class would spuriously produce args
    on the compiled field.
    """
    from graphql import GraphQLField

    from django_graphex.core.mutation import Mutation

    class MyMutation(Mutation):
        class Arguments:
            pass

        @staticmethod
        def mutate(root, info):
            return None

    field = MyMutation.Field()
    assert isinstance(field, GraphQLField)
    assert field.args == {}, (
        "Field args must be empty when class Arguments has no Argument declarations"
    )


def test_field_args_multiple_arguments() -> None:
    """Assert that "Field().args" contains every declared argument, not just one.

    If this fails, only a subset of the mutation's declared arguments
    would reach the compiled field.
    """
    from graphql import (
        GraphQLArgument,
        GraphQLField,
        GraphQLInt,
        GraphQLNonNull,
        GraphQLString,
    )

    from django_graphex.core.mutation import Mutation

    class MyMutation(Mutation):
        class Arguments:
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


def test_no_schema_assembly_needed() -> None:
    """Assert that "Field()" is inspectable in isolation without a GraphQLSchema.

    If this fails, mutation fields could only be exercised as part of a
    fully assembled schema, breaking isolated unit testing.
    """
    from graphql import GraphQLArgument, GraphQLField, GraphQLID, GraphQLNonNull

    from django_graphex.core.mutation import Mutation

    class MyMutation(Mutation):
        class Arguments:
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


def test_mutation_importable_from_public_api() -> None:
    """Assert that "from django_graphex import Mutation" raises no ImportError.

    If this fails, the documented public import path for Mutation would be
    broken.
    """
    try:
        from django_graphex.core import Mutation  # noqa: F401
    except ImportError as e:
        pytest.fail(f"Importing Mutation from django_graphex raised ImportError: {e}")


def test_public_mutation_is_native_mutation() -> None:
    """Assert that "django_graphex.Mutation" is identical to the native "Mutation" class.

    If this fails, the public export would be a distinct (or stale) class
    rather than an alias of the native implementation, breaking isinstance
    checks against either path.
    """
    from django_graphex.core import Mutation as PublicMutation
    from django_graphex.core.mutation import Mutation as NativeMutation

    assert PublicMutation is NativeMutation, (
        "django_graphex.Mutation must be the native Mutation class"
    )


# ---------------------------------------------------------------------------
# Coverage gap: mutate defined on parent (MRO walk), and no mutate at all
# ---------------------------------------------------------------------------


def test_field_uses_mutate_from_parent_via_mro() -> None:
    """Assert that "Field()" resolves "mutate" via MRO when not defined on the subclass.

    If this fails, a mutation subclass that inherits its mutate
    implementation from a parent would fail to build a field at all.
    """
    from graphql import GraphQLField

    from django_graphex.core.mutation import Mutation

    class Base(Mutation):
        @staticmethod
        def mutate(root, info):
            return "from-base"

    class Child(Base):
        class Arguments:
            pass

        # No mutate defined here — should walk MRO to find Base.mutate

    field = Child.Field()
    assert isinstance(field, GraphQLField)
    assert field.resolve(object(), object()) == "from-base"


def test_field_raises_when_no_mutate_defined() -> None:
    """Assert that "Field()" raises AttributeError when no "mutate" exists in the MRO.

    If this fails, a mutation missing an implementation would fail later
    (e.g. at resolve time) with a confusing error instead of failing fast
    at field-build time.
    """
    from django_graphex.core.mutation import Mutation

    class NoMutate(Mutation):
        class Arguments:
            pass

        # Deliberately no mutate

    with pytest.raises(AttributeError, match="must define a 'mutate'"):
        NoMutate.Field()


def test_class_args_public_non_argument_attr_fails_loudly() -> None:
    """Assert that a public non-arg attribute in "class Arguments" fails loudly.

    Pre-FIX-1 "_compile_args" SILENTLY SKIPPED any non-native value (so a
    stray "graphene.Argument" — or any junk — vanished with no error,
    defeating the advertised clean break). The 2.0 contract (decision
    #1603) treats every PUBLIC attribute of "class Arguments" as an arg
    declaration: a non-native value raises a clear "TypeError" naming the
    offending key. A genuine helper must be underscore-prefixed ("props"
    strips it) — see the companion test below.

    If this fails, junk attributes on "Arguments" would silently vanish
    instead of failing the mutation build with a clear error.
    """
    import pytest
    from graphql import GraphQLArgument, GraphQLString

    from django_graphex.core.mutation import Mutation

    class MyMutation(Mutation):
        class Arguments:
            # A plain public string attr — no longer silently ignored.
            helper_text = "not an argument"
            name = GraphQLArgument(GraphQLString)

        @staticmethod
        def mutate(root, info, name=None):
            return name

    with pytest.raises(TypeError) as exc:
        MyMutation.Field()
    assert "helper_text" in str(exc.value)


def test_class_args_underscore_helper_is_ignored() -> None:
    """Assert that an underscore-prefixed helper in "class Arguments" is tolerated.

    The clean-break loud-fail targets PUBLIC arg declarations only; a
    private helper ("_helper_text") is filtered out by "props" and never
    reaches the arg normaliser, so it does not become a compiled arg and
    does not error.

    If this fails, a private helper attribute would either error out the
    build or leak into the compiled field's args.
    """
    from graphql import GraphQLArgument, GraphQLField, GraphQLString

    from django_graphex.core.mutation import Mutation

    class MyMutation(Mutation):
        class Arguments:
            _helper_text = "not an argument"  # underscore → stripped by props()
            name = GraphQLArgument(GraphQLString)

        @staticmethod
        def mutate(root, info, name=None):
            return name

    field = MyMutation.Field()
    assert isinstance(field, GraphQLField)
    assert "name" in field.args
    assert "_helper_text" not in field.args
