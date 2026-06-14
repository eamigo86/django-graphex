"""TDD A1.1 RED — _MetaView allowlist coverage for Phase-3 output attrs.

Tests that:
- Known output attrs (output_type, output_list_type, baseType, mutation_output,
  model_operations) are accessible via _MetaView.
- Unknown attrs raise AttributeError immediately (no silent None).
- All 4 Options subclasses' valid attrs do NOT raise.

Run: .venv/bin/python -m pytest -q tests/native/test_bridge_output_attrs.py
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_spec(**kwargs):
    """Build a simple namespace object with the given kwargs as attributes."""
    from types import SimpleNamespace
    return SimpleNamespace(**kwargs)


# ---------------------------------------------------------------------------
# A1.1: Phase-3 output attrs are accessible via _MetaView
# ---------------------------------------------------------------------------


def test_meta_view_output_type():
    """_MetaView.output_type returns the spec value."""
    from django_graphex.native.bridge import _MetaView

    spec = make_spec(output_type="SomeType")
    view = _MetaView(spec)
    assert view.output_type == "SomeType"


def test_meta_view_output_list_type():
    """_MetaView.output_list_type returns the spec value."""
    from django_graphex.native.bridge import _MetaView

    spec = make_spec(output_list_type="SomeListType")
    view = _MetaView(spec)
    assert view.output_list_type == "SomeListType"


def test_meta_view_base_type():
    """_MetaView.baseType returns the spec value."""
    from django_graphex.native.bridge import _MetaView

    spec = make_spec(baseType="BaseType")
    view = _MetaView(spec)
    assert view.baseType == "BaseType"


def test_meta_view_mutation_output():
    """_MetaView.mutation_output returns the spec value."""
    from django_graphex.native.bridge import _MetaView

    spec = make_spec(mutation_output="MutationOutput")
    view = _MetaView(spec)
    assert view.mutation_output == "MutationOutput"


def test_meta_view_model_operations():
    """_MetaView.model_operations returns the spec value."""
    from django_graphex.native.bridge import _MetaView

    spec = make_spec(model_operations=["create", "update"])
    view = _MetaView(spec)
    assert view.model_operations == ["create", "update"]


# ---------------------------------------------------------------------------
# A1.2: Unknown attr raises AttributeError (never silent None)
# ---------------------------------------------------------------------------


def test_meta_view_unknown_attr_raises():
    """_MetaView raises AttributeError on an unknown attribute."""
    from django_graphex.native.bridge import _MetaView

    spec = make_spec()
    view = _MetaView(spec)
    with pytest.raises(AttributeError):
        _ = view.bogus_output_attr


def test_meta_view_unknown_attr_is_not_none():
    """_MetaView does not silently return None for unknown attrs."""
    from django_graphex.native.bridge import _MetaView

    spec = make_spec()
    view = _MetaView(spec)
    raised = False
    try:
        result = view.nonexistent_attr_xyz
        # If no exception, ensure it's not silently None
        assert result is not None, "_MetaView must not silently return None"
    except AttributeError:
        raised = True
    assert raised, "_MetaView must raise AttributeError for unknown attrs"


# ---------------------------------------------------------------------------
# A1.3: DjangoObjectOptions attrs accessible
# ---------------------------------------------------------------------------


def test_meta_view_django_object_options_attrs():
    """All DjangoObjectOptions attrs that are in _GDX_ALLOWLIST do not raise."""
    from django_graphex.native.bridge import _MetaView, _GDX_ALLOWLIST

    # Attrs used by DjangoObjectOptions (from types.py inspection)
    object_options_attrs = [
        "model", "name", "fields", "only_fields", "exclude_fields",
        "skip_registry", "registry", "filter_fields", "max_deep",
        "complexity", "gfk_unions", "interfaces", "connection",
        "results_field_name", "pagination",
    ]
    spec = make_spec(**{attr: f"val_{attr}" for attr in object_options_attrs})
    view = _MetaView(spec)
    for attr in object_options_attrs:
        assert attr in _GDX_ALLOWLIST, (
            f"'{attr}' should be in _GDX_ALLOWLIST"
        )
        assert getattr(view, attr) == f"val_{attr}"


# ---------------------------------------------------------------------------
# A1.4: DjangoModelTypeOptions attrs accessible
# ---------------------------------------------------------------------------


def test_meta_view_django_model_type_options_attrs():
    """DjangoModelTypeOptions attrs are covered by _GDX_ALLOWLIST."""
    from django_graphex.native.bridge import _MetaView, _GDX_ALLOWLIST

    model_type_attrs = [
        "model", "queryset", "backend", "arguments", "fields", "input_fields",
        "input_field_name", "mutation_output", "output_field_name", "output_type",
        "output_list_type", "nested_fields", "interfaces", "stream",
        "serialize_data", "subscription_index_fields", "max_deep", "complexity",
        "model_operations",
    ]
    spec = make_spec(**{attr: f"val_{attr}" for attr in model_type_attrs})
    view = _MetaView(spec)
    for attr in model_type_attrs:
        assert attr in _GDX_ALLOWLIST, (
            f"DjangoModelTypeOptions attr '{attr}' must be in _GDX_ALLOWLIST"
        )
        assert getattr(view, attr) == f"val_{attr}"


# ---------------------------------------------------------------------------
# A1.5: graphql_output_type — Phase-3 new attr in allowlist
# ---------------------------------------------------------------------------


def test_meta_view_graphql_output_type():
    """graphql_output_type must be accessible via _MetaView (Phase 3)."""
    from django_graphex.native.bridge import _MetaView

    spec = make_spec(graphql_output_type="MockGQLType")
    view = _MetaView(spec)
    assert view.graphql_output_type == "MockGQLType"
