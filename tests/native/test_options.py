"""TDD 1.3 RED — _options.py tests.

Tests:
- Each of the 4 Options subclasses is instantiable via _GdxOptions
- All declared attrs accessible as None
- Unknown attr access via _MetaView raises AttributeError naming the attr
- _MetaView delegates known attrs to the underlying Options object

Run: GDX_BACKEND=native .venv/bin/python -m pytest tests/native/test_options.py -q
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# _GdxOptions base
# ---------------------------------------------------------------------------


def test_gdx_options_base_instantiable():
    """_GdxOptions(cls) can be instantiated with any class."""
    from django_graphex._options import _GdxOptions

    class FakeClass:
        pass

    opts = _GdxOptions(FakeClass)
    assert opts.cls is FakeClass


def test_gdx_options_stores_cls():
    """_GdxOptions.cls is the class passed at construction."""
    from django_graphex._options import _GdxOptions

    class MyModel:
        pass

    opts = _GdxOptions(MyModel)
    assert opts.cls is MyModel


# ---------------------------------------------------------------------------
# DjangoObjectOptions (native variant)
# ---------------------------------------------------------------------------


def test_django_object_options_instantiable():
    """DjangoObjectOptions(cls) is instantiable from _GdxOptions hierarchy."""
    from django_graphex._options import DjangoObjectOptions

    class FakeCls:
        pass

    opts = DjangoObjectOptions(FakeCls)
    assert opts.cls is FakeCls


@pytest.mark.parametrize(
    "attr",
    [
        "fields",
        "input_fields",
        "interfaces",
        "model",
        "queryset",
        "registry",
        "connection",
        "create_container",
        "results_field_name",
        "filter_fields",
        "input_for",
        "max_deep",
        "complexity",
        "gfk_unions",
        "graphql_input_type",
        "graphql_output_type",
    ],
)
def test_django_object_options_attrs_default_none(attr):
    """All DjangoObjectOptions attrs default to None (or falsy default)."""
    from django_graphex._options import DjangoObjectOptions

    class FakeCls:
        pass

    opts = DjangoObjectOptions(FakeCls)
    # attrs should exist (not raise AttributeError)
    assert hasattr(opts, attr), f"DjangoObjectOptions missing attr: {attr!r}"
    # most default to None or empty
    val = getattr(opts, attr)
    assert val is None or val == () or val == {}, (
        f"DjangoObjectOptions.{attr} should default to None/empty, got {val!r}"
    )


# ---------------------------------------------------------------------------
# DjangoModelTypeOptions (native variant)
# ---------------------------------------------------------------------------


def test_django_model_type_options_instantiable():
    """DjangoModelTypeOptions(cls) is instantiable."""
    from django_graphex._options import DjangoModelTypeOptions

    class FakeCls:
        pass

    opts = DjangoModelTypeOptions(FakeCls)
    assert opts.cls is FakeCls


@pytest.mark.parametrize(
    "attr",
    [
        "model",
        "queryset",
        "backend",
        "arguments",
        "fields",
        "input_fields",
        "input_field_name",
        "mutation_output",
        "output_field_name",
        "output_type",
        "output_list_type",
        "nested_fields",
        "interfaces",
        "stream",
        "serialize_data",
        "subscription_index_fields",
        "max_deep",
        "complexity",
    ],
)
def test_django_model_type_options_attrs_default_none(attr):
    """All DjangoModelTypeOptions attrs default to None (or falsy default)."""
    from django_graphex._options import DjangoModelTypeOptions

    class FakeCls:
        pass

    opts = DjangoModelTypeOptions(FakeCls)
    assert hasattr(opts, attr), f"DjangoModelTypeOptions missing attr: {attr!r}"
    val = getattr(opts, attr)
    assert val is None or val == () or val == {}, (
        f"DjangoModelTypeOptions.{attr} should default to None/empty, got {val!r}"
    )


# ---------------------------------------------------------------------------
# SerializerMutationOptions (native variant)
# ---------------------------------------------------------------------------


def test_serializer_mutation_options_instantiable():
    """SerializerMutationOptions(cls) is instantiable."""
    from django_graphex._options import SerializerMutationOptions

    class FakeCls:
        pass

    opts = SerializerMutationOptions(FakeCls)
    assert opts.cls is FakeCls


@pytest.mark.parametrize(
    "attr",
    [
        "fields",
        "input_fields",
        "interfaces",
        "backend",
        "action",
        "arguments",
        "output",
        "resolver",
        "nested_fields",
        "model_operations",
    ],
)
def test_serializer_mutation_options_attrs_default_none(attr):
    """All SerializerMutationOptions attrs default to None or expected default."""
    from django_graphex._options import SerializerMutationOptions

    class FakeCls:
        pass

    opts = SerializerMutationOptions(FakeCls)
    assert hasattr(opts, attr), f"SerializerMutationOptions missing attr: {attr!r}"


# ---------------------------------------------------------------------------
# SubscriptionOptions (native variant)
# ---------------------------------------------------------------------------


def test_subscription_options_instantiable():
    """SubscriptionOptions(cls) is instantiable."""
    from django_graphex._options import SubscriptionOptions

    class FakeCls:
        pass

    opts = SubscriptionOptions(FakeCls)
    assert opts.cls is FakeCls


@pytest.mark.parametrize(
    "attr",
    [
        "output",
        "arguments",
        "model",
        "stream",
        "backend",
        "queryset",
        "serialize_data",
        "index_fields",
    ],
)
def test_subscription_options_attrs_default_none(attr):
    """All SubscriptionOptions attrs default to None or empty."""
    from django_graphex._options import SubscriptionOptions

    class FakeCls:
        pass

    opts = SubscriptionOptions(FakeCls)
    assert hasattr(opts, attr), f"SubscriptionOptions missing attr: {attr!r}"
    val = getattr(opts, attr)
    assert val is None or val == () or val == {}, (
        f"SubscriptionOptions.{attr} should default to None/empty, got {val!r}"
    )


# ---------------------------------------------------------------------------
# _MetaView — AttributeError on unknown attrs
# ---------------------------------------------------------------------------


def test_meta_view_raises_attribute_error_on_unknown():
    """_MetaView raises AttributeError for unknown attributes."""
    from django_graphex._options import DjangoObjectOptions, _MetaView

    class FakeCls:
        pass

    opts = DjangoObjectOptions(FakeCls)
    view = _MetaView(opts)

    with pytest.raises(AttributeError) as exc_info:
        _ = view.totally_unknown_attr

    assert "totally_unknown_attr" in str(exc_info.value), (
        "_MetaView AttributeError message must name the unknown attr"
    )


def test_meta_view_names_unknown_attr_in_error_message():
    """_MetaView error message includes the name of the unknown attribute."""
    from django_graphex._options import DjangoModelTypeOptions, _MetaView

    class FakeCls:
        pass

    opts = DjangoModelTypeOptions(FakeCls)
    view = _MetaView(opts)

    with pytest.raises(AttributeError) as exc_info:
        _ = view.non_existent_field

    error_msg = str(exc_info.value)
    assert "non_existent_field" in error_msg


def test_meta_view_delegates_known_attrs():
    """_MetaView delegates known attrs to the wrapped Options object."""
    from django_graphex._options import DjangoObjectOptions, _MetaView

    class FakeCls:
        pass

    opts = DjangoObjectOptions(FakeCls)
    opts.model = "FakeModel"  # type: ignore[assignment]
    view = _MetaView(opts)

    assert view.model == "FakeModel"


def test_meta_view_delegates_cls():
    """_MetaView exposes the .cls attr from the underlying Options."""
    from django_graphex._options import DjangoObjectOptions, _MetaView

    class FakeCls:
        pass

    opts = DjangoObjectOptions(FakeCls)
    view = _MetaView(opts)

    assert view.cls is FakeCls
