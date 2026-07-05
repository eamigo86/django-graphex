"""R6 coverage — behavioral tests for "native.descriptors" uncovered branches.

The descriptor classes ("NativeMountedField" / "NativeField" /
"NativeRelationField" / "NativeList" / "NativeNonNull") and the module
helpers ("_source_resolver" / "_resolve_thunk" / "_next_creation_counter")
are the graphene-free field-descriptor currency the duck-typed compiler consumes.
Their public-shape happy paths are covered by "test_s_roots_a_descriptors.py" and
"test_s8c_field_descriptor_graphene_free.py"; this file pins the remaining edge
branches by asserting their ACTUAL behaviour (not coverage no-ops):

- "_source_resolver": dict-key read, attribute read, and the call-when-callable arm.
- "_resolve_thunk": dotted-string import, zero-arg callable / partial, verbatim.
- "_next_creation_counter": strictly monotonic, process-global.
- "NativeMountedField": "required" -> "NativeNonNull" wrap, "source" -> resolver,
  "mounted" classmethod (graphene UnmountedType mount), "wrap_subscribe" passthrough,
  ordering dunders ("__eq__" / "__lt__" / "__hash__") used by "_yank_fields".
- "NativeRelationField": inert ".type" marker + carried creation counter.
- "NativeField.resolver" property.

Run: .venv/bin/python -m pytest \
    tests/core/test_descriptors_coverage.py -q -o addopts=""
"""

from __future__ import annotations

from functools import partial

import pytest

# ---------------------------------------------------------------------------
# _source_resolver — dict key, attribute, and call-when-callable
# ---------------------------------------------------------------------------


def test_source_resolver_reads_dict_key() -> None:
    """Ships broken if "_source_resolver" stops reading the key off a mapping root.

    A mapping root is the dict-shaped resolve arm graphene parity requires.
    """
    from django_graphex.core.descriptors import _source_resolver

    root = {"name": "Ada"}
    assert _source_resolver("name", root, None) == "Ada"


def test_source_resolver_reads_missing_dict_key_as_none() -> None:
    """Ships broken if a missing dict key stops resolving to None.

    This is the "dict.get" default arm; a KeyError would break resolution.
    """
    from django_graphex.core.descriptors import _source_resolver

    assert _source_resolver("absent", {"name": "Ada"}, None) is None


def test_source_resolver_reads_attribute_off_object() -> None:
    """Ships broken if "_source_resolver" stops reading the attribute off a
    non-mapping root.

    The plain-object resolve arm is distinct from the dict-key arm above.
    """
    from django_graphex.core.descriptors import _source_resolver

    class _Obj:
        """Plain attribute-holding object standing in for a resolver root."""

        title = "Compilers"

    assert _source_resolver("title", _Obj(), None) == "Compilers"


def test_source_resolver_calls_method_result() -> None:
    """Ships broken if a source pointing at a zero-arg method stops being
    CALLED (graphene parity)."""
    from django_graphex.core.descriptors import _source_resolver

    class _Obj:
        """Object exposing a zero-arg method as the resolved source."""

        def display_name(self):
            """Return a fixed marker string identifying this method was called."""
            return "called!"

    # The bound method is detected as a method and invoked.
    assert _source_resolver("display_name", _Obj(), None) == "called!"


def test_source_resolver_calls_function_attribute() -> None:
    """Ships broken if a source pointing at a plain function attribute stops
    being CALLED.

    Plain functions set on an instance must be invoked, not returned as-is.
    """
    from django_graphex.core.descriptors import _source_resolver

    def _fn():
        """Return a fixed marker value identifying this function was called."""
        return 42

    class _Obj:
        """Empty object used to host a plain function attribute at runtime."""

        pass

    obj = _Obj()
    obj.compute = _fn  # plain function set on the instance
    assert _source_resolver("compute", obj, None) == 42


# ---------------------------------------------------------------------------
# _resolve_thunk — dotted string import, callable, partial, verbatim
# ---------------------------------------------------------------------------


def test_resolve_thunk_imports_dotted_string() -> None:
    """Ships broken if a dotted import-path string stops resolving to the
    imported object.

    This is the string-thunk arm ("module.path.Name") of "_resolve_thunk".
    """
    from django_graphex.core.descriptors import _resolve_thunk

    resolved = _resolve_thunk("graphql.GraphQLString")
    from graphql import GraphQLString

    assert resolved is GraphQLString


def test_resolve_thunk_calls_zero_arg_lambda() -> None:
    """Ships broken if a zero-arg callable (lazy forward ref) stops being
    invoked with its result returned."""
    from django_graphex.core.descriptors import _resolve_thunk

    sentinel = object()
    assert _resolve_thunk(lambda: sentinel) is sentinel


def test_resolve_thunk_calls_partial() -> None:
    """Ships broken if a "functools.partial" stops being invoked (graphene
    "get_type" parity)."""
    from django_graphex.core.descriptors import _resolve_thunk

    def _identity(x):
        """Return the argument unchanged, used to verify partial invocation."""
        return x

    sentinel = object()
    assert _resolve_thunk(partial(_identity, sentinel)) is sentinel


def test_resolve_thunk_returns_non_thunk_verbatim() -> None:
    """Ships broken if a concrete type (graphql-core scalar) stops being
    returned unchanged."""
    from graphql import GraphQLInt

    from django_graphex.core.descriptors import _resolve_thunk

    assert _resolve_thunk(GraphQLInt) is GraphQLInt


# ---------------------------------------------------------------------------
# _next_creation_counter — strictly monotonic, process-global
# ---------------------------------------------------------------------------


def test_next_creation_counter_is_strictly_monotonic() -> None:
    """Ships broken if successive counters stop increasing by exactly 1
    (declaration-order parity)."""
    from django_graphex.core.descriptors import _next_creation_counter

    a = _next_creation_counter()
    b = _next_creation_counter()
    c = _next_creation_counter()
    assert b == a + 1
    assert c == b + 1


# ---------------------------------------------------------------------------
# NativeMountedField — required wrap, source resolver, mounted, subscribe, order
# ---------------------------------------------------------------------------


def test_mounted_field_required_wraps_type_in_native_nonnull() -> None:
    """Ships broken if "required=True" stops wrapping the declared type in a
    "NativeNonNull"."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import NativeMountedField, NativeNonNull

    f = NativeMountedField(GraphQLString, required=True)
    # ``.type`` resolves the thunk; the wrapper is a NativeNonNull over the scalar.
    resolved = f.type
    assert isinstance(resolved, NativeNonNull)
    assert resolved.of_type is GraphQLString


def test_mounted_field_source_becomes_resolver() -> None:
    """Ships broken if a "source=" (with no explicit resolver) stops installing
    a source resolver."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import NativeMountedField

    f = NativeMountedField(GraphQLString, source="name")
    assert f.resolver is not None

    # The installed resolver reads ``name`` off the root.
    resolver = f.wrap_resolve(parent_resolver=None)
    assert resolver({"name": "Grace"}, None) == "Grace"


def test_mounted_field_explicit_resolver_wins_over_source() -> None:
    """Ships broken if an explicit resolver is overridden by a "source" kwarg.

    Precedence must favor the explicit resolver, never the source-derived one.
    """
    from graphql import GraphQLString

    from django_graphex.core.descriptors import NativeMountedField

    def _explicit(root, info):  # pragma: no cover - identity only
        """Return a fixed marker string identifying the explicit resolver ran."""
        return "explicit"

    f = NativeMountedField(GraphQLString, resolver=_explicit, source="name")
    assert f.resolver is _explicit


def test_mounted_field_merges_extra_args() -> None:
    """Ships broken if extra "name=arg" kwargs stop merging into "args"
    (graphene Field parity)."""
    from graphql import GraphQLArgument, GraphQLID, GraphQLString

    from django_graphex.core.descriptors import NativeMountedField

    id_arg = GraphQLArgument(GraphQLID)
    f = NativeMountedField(
        GraphQLString, args={"limit": GraphQLArgument(GraphQLID)}, id=id_arg
    )
    assert f.args["id"] is id_arg
    assert "limit" in f.args


def test_mounted_field_mounted_classmethod_carries_unmounted_kwargs() -> None:
    """Ships broken if "NativeMountedField.mounted" stops mounting an
    UnmountedType-shaped scalar.

    Simulates a graphene "UnmountedType" (the transitional converter scalar):
    it exposes "get_type()" (its class), a "kwargs" dict carrying
    "required" / "description" / "name" / "source", and a
    "creation_counter". "mounted" must lift each across.
    """
    from django_graphex.core.descriptors import NativeMountedField, NativeNonNull

    class _FakeScalarClass:
        """Stand-in scalar class returned by the fake UnmountedType's get_type."""

        pass

    class _FakeUnmounted:
        """Stand-in for a graphene UnmountedType carrying mount-time kwargs."""

        kwargs = {
            "required": True,
            "description": "a mounted scalar",
            "name": "scalarName",
        }
        creation_counter = 4242

        def get_type(self):
            """Return the fake scalar class this unmounted type wraps."""
            return _FakeScalarClass

    mounted = NativeMountedField.mounted(_FakeUnmounted())
    # required → NativeNonNull wrapping the scalar class.
    assert isinstance(mounted.type, NativeNonNull)
    assert mounted.type.of_type is _FakeScalarClass
    assert mounted.description == "a mounted scalar"
    assert mounted.name == "scalarName"
    # The unmounted creation counter is preserved for stable ordering.
    assert mounted.creation_counter == 4242


def test_mounted_field_wrap_subscribe_passthrough() -> None:
    """Ships broken if "wrap_subscribe" stops returning the parent subscribe
    unchanged (graphene parity)."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import NativeMountedField

    f = NativeMountedField(GraphQLString)
    sentinel = object()
    assert f.wrap_subscribe(sentinel) is sentinel


def test_mounted_field_ordering_dunders() -> None:
    """Ships broken if "__eq__" / "__lt__" / "__hash__" stop ordering by
    "creation_counter".

    These power "_yank_fields"' declaration-order sort, so they must compare
    by counter and be hashable by it.
    """
    from graphql import GraphQLString

    from django_graphex.core.descriptors import NativeMountedField

    first = NativeMountedField(GraphQLString)
    second = NativeMountedField(GraphQLString)

    # second was created after first → strictly greater counter.
    assert first < second
    assert not (second < first)
    assert first != second

    # Equality is by counter: a copy carrying the same counter compares equal.
    same = NativeMountedField(GraphQLString, _creation_counter=first.creation_counter)
    assert same == first
    assert hash(same) == hash(first)

    # sorting a shuffled list restores declaration order.
    assert sorted([second, first]) == [first, second]


def test_mounted_field_eq_with_non_descriptor_is_not_implemented() -> None:
    """Ships broken if comparing to a non-descriptor stops falling back to
    Python's default (not equal)."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import NativeMountedField

    f = NativeMountedField(GraphQLString)
    # __eq__ returns NotImplemented → Python yields False for ==.
    assert (f == object()) is False


def test_mounted_field_lt_with_no_counter_object_raises_typeerror() -> None:
    """Ships broken if "__lt__" against an object lacking "creation_counter"
    stops raising TypeError (unorderable)."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import NativeMountedField

    f = NativeMountedField(GraphQLString)
    with pytest.raises(TypeError):
        _ = f < object()


# ---------------------------------------------------------------------------
# NativeRelationField — inert marker, carried counter
# ---------------------------------------------------------------------------


def test_relation_field_is_inert_marker_with_counter() -> None:
    """Ships broken if "NativeRelationField" stops carrying a counter and an
    inert None type."""
    from django_graphex.core.descriptors import (
        NativeMountedField,
        NativeRelationField,
    )

    class _RelatedModel:
        """Stand-in related model class for the relation marker under test."""

        pass

    marker = NativeRelationField(_RelatedModel, _creation_counter=99)
    # It is a NativeMountedField subclass so _yank_fields keeps it.
    assert isinstance(marker, NativeMountedField)
    assert marker.related_model is _RelatedModel
    assert marker.creation_counter == 99
    # The type is inert (never read on the native output path).
    assert marker.type is None


def test_relation_field_allocates_counter_when_unset() -> None:
    """Ships broken if a relation marker without an explicit counter stops
    getting a fresh monotonic one."""
    from django_graphex.core.descriptors import NativeRelationField

    a = NativeRelationField()
    b = NativeRelationField()
    assert b.creation_counter > a.creation_counter


# ---------------------------------------------------------------------------
# NativeField.resolver property
# ---------------------------------------------------------------------------


def test_native_field_resolver_property_returns_own_resolver() -> None:
    """Ships broken if "NativeField.resolver" stops returning the resolver
    passed at construction."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import NativeField

    def _r(root, info):  # pragma: no cover - identity only
        """Return a fixed marker string identifying this resolver ran."""
        return "x"

    f = NativeField(GraphQLString, resolver=_r)
    assert f.resolver is _r


def test_native_field_resolver_property_none_by_default() -> None:
    """Ships broken if "NativeField.resolver" stops defaulting to None when
    no resolver was supplied."""
    from graphql import GraphQLString

    from django_graphex.core.descriptors import NativeField

    assert NativeField(GraphQLString).resolver is None
