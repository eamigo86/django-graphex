"""TDD A4.1 RED — native/compat.py tests.

Tests:
- _gdx_meta(t) returns t.graphene_type._meta when graphene_type attr exists.
- _gdx_meta(t) falls back to t.extensions["gdx"]._meta when no graphene_type.
- graphene_type alias property is reachable on a native type (does not raise).

Run: .venv/bin/python -m pytest -q tests/native/test_compat.py
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeMeta:
    """Stand-in for graphene's _meta or GdxPayload._meta."""
    max_deep = 5
    complexity = 10


class FakeGdxPayload:
    """Stand-in for GdxPayload on extensions['gdx']."""
    _meta = FakeMeta()


class FakeGrapheneType:
    """Stand-in for a graphene type with _meta."""
    _meta = FakeMeta()


class TypeWithGrapheneType:
    """A type-like object that has .graphene_type._meta (graphene path)."""
    graphene_type = FakeGrapheneType()


class TypeWithExtensions:
    """A type-like object that uses extensions['gdx']._meta (native path)."""
    extensions = {"gdx": FakeGdxPayload()}

    # Deliberately does NOT have graphene_type attribute


class TypeWithBothPaths:
    """A type with both graphene_type and extensions['gdx'] (graphene path wins)."""
    graphene_type = FakeGrapheneType()
    extensions = {"gdx": FakeGdxPayload()}


# ---------------------------------------------------------------------------
# A4.1: _gdx_meta fallback logic
# ---------------------------------------------------------------------------


def test_gdx_meta_returns_graphene_type_meta_when_available():
    """_gdx_meta(t) returns t.graphene_type._meta when graphene_type is present."""
    from django_graphex.native.compat import _gdx_meta

    t = TypeWithGrapheneType()
    result = _gdx_meta(t)
    assert result is FakeGrapheneType._meta, (
        "_gdx_meta must return t.graphene_type._meta when graphene_type is present"
    )


def test_gdx_meta_falls_back_to_extensions_when_no_graphene_type():
    """_gdx_meta(t) returns t.extensions['gdx']._meta when no graphene_type."""
    from django_graphex.native.compat import _gdx_meta

    t = TypeWithExtensions()
    result = _gdx_meta(t)
    assert result is FakeGdxPayload._meta, (
        "_gdx_meta must fall back to t.extensions['gdx']._meta when graphene_type absent"
    )


def test_gdx_meta_graphene_path_wins_when_both_present():
    """_gdx_meta(t) uses graphene_type._meta when both paths exist (graphene-first)."""
    from django_graphex.native.compat import _gdx_meta

    t = TypeWithBothPaths()
    result = _gdx_meta(t)
    assert result is FakeGrapheneType._meta, (
        "_gdx_meta must prefer graphene_type._meta over extensions['gdx']._meta"
    )


def test_gdx_meta_raises_on_neither_path():
    """_gdx_meta(t) raises AttributeError when neither path is available."""
    from django_graphex.native.compat import _gdx_meta

    class TypeWithNothing:
        pass

    with pytest.raises((AttributeError, KeyError)):
        _gdx_meta(TypeWithNothing())


# ---------------------------------------------------------------------------
# A4.2: graphene_type alias property on native type
# ---------------------------------------------------------------------------


def test_graphene_type_alias_on_native_type():
    """graphene_type alias property is reachable on a native type (does not raise)."""
    from django_graphex.native.compat import NativeTypeAliasMixin, _gdx_meta

    class NativeType(NativeTypeAliasMixin):
        """Minimal native type with extensions['gdx']."""
        extensions = {"gdx": FakeGdxPayload()}

    # Accessing graphene_type on a NativeTypeAliasMixin should not raise
    t = NativeType()
    # The alias should return some object (could be None or the gdx payload)
    try:
        alias = t.graphene_type
        # If it returns something, it's fine; the test just asserts no AttributeError
    except AttributeError as e:
        pytest.fail(f"graphene_type alias raised AttributeError: {e}")


def test_gdx_meta_works_with_native_type_alias():
    """_gdx_meta works on a type that uses the graphene_type alias (returns gdx._meta)."""
    from django_graphex.native.compat import NativeTypeAliasMixin, _gdx_meta

    class NativeType(NativeTypeAliasMixin):
        extensions = {"gdx": FakeGdxPayload()}

    t = NativeType()
    # _gdx_meta should return the gdx payload's _meta
    result = _gdx_meta(t)
    assert result is FakeGdxPayload._meta, (
        "_gdx_meta via alias should return extensions['gdx']._meta"
    )


# ---------------------------------------------------------------------------
# TDD 1.5 RED — _adapt_self (native/_compat.py)
# ---------------------------------------------------------------------------


def test_adapt_self_wraps_self_first_fn_and_warns():
    """_adapt_self wraps a self-first function and emits DeprecationWarning."""
    import warnings
    from django_graphex.native._compat import _adapt_self

    def mutate(self, info, pk=None):
        return (self, info, pk)

    adapted = _adapt_self(mutate)

    fake_root = object()
    fake_info = object()

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = adapted(fake_root, fake_info, pk=42)

    assert result == (fake_root, fake_info, 42), (
        "_adapt_self shim should call the underlying fn with (root, info, **kw)"
    )
    assert len(w) == 1, "_adapt_self should emit exactly one DeprecationWarning"
    assert issubclass(w[0].category, DeprecationWarning)


def test_adapt_self_warns_exactly_once_per_call():
    """_adapt_self emits DeprecationWarning exactly once per invocation."""
    import warnings
    from django_graphex.native._compat import _adapt_self

    def mutate(self, info):
        return "ok"

    adapted = _adapt_self(mutate)

    # Call twice — should warn once per call (not globally suppressed)
    for _ in range(2):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            adapted(object(), object())
        assert len(w) == 1, "Each call should emit exactly one warning"


def test_adapt_self_classmethod_passthrough_no_shim():
    """_adapt_self returns classmethods unmodified (no shim, no warning)."""
    import inspect
    import warnings
    from django_graphex.native._compat import _adapt_self

    class Owner:
        @classmethod
        def create(cls, root, info, **kw):
            return (cls, root, info)

    bound_method = Owner.create  # inspect.ismethod(Owner.create) is True

    adapted = _adapt_self(bound_method)

    assert adapted is bound_method, (
        "_adapt_self must return the original classmethod unmodified"
    )

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = adapted(object(), object())
    assert len(w) == 0, "No warning should be emitted for classmethods"


def test_adapt_self_staticmethod_passthrough():
    """_adapt_self passes through a plain (root, info) function without shimming."""
    import warnings
    from django_graphex.native._compat import _adapt_self

    def resolver(root, info, **kw):
        return (root, info)

    adapted = _adapt_self(resolver)

    fake_root = object()
    fake_info = object()

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = adapted(fake_root, fake_info)

    assert result == (fake_root, fake_info), (
        "_adapt_self must not modify a (root, info) function"
    )
    assert len(w) == 0, "No DeprecationWarning for (root, info) functions"


def test_adapt_self_bare_root_info_fn_passthrough():
    """_adapt_self does NOT shim a function whose first param is NOT 'self'."""
    import warnings
    from django_graphex.native._compat import _adapt_self

    def mutate(root, info, name=None):
        return (root, info, name)

    adapted = _adapt_self(mutate)

    # Should be identity passthrough
    assert adapted is mutate, (
        "_adapt_self should return the original function when first param != 'self'"
    )


def test_adapt_self_no_params_passthrough():
    """_adapt_self passes through a zero-param function unchanged."""
    from django_graphex.native._compat import _adapt_self

    def no_params():
        return "noop"

    adapted = _adapt_self(no_params)
    assert adapted is no_params, (
        "_adapt_self must passthrough functions with no parameters"
    )


def test_adapt_self_meta_view_setattr_coverage():
    """_MetaView.__setattr__ delegates to the wrapped Options object."""
    from django_graphex._options import DjangoObjectOptions, _MetaView

    class FakeCls:
        pass

    opts = DjangoObjectOptions(FakeCls)
    view = _MetaView(opts)

    # This exercises _MetaView.__setattr__
    view.model = "TestModel"
    assert opts.model == "TestModel"
