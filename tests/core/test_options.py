"""TDD 1.3 RED — _options.py tests.

Tests:
- Each of the 4 Options subclasses is instantiable via _GdxOptions
- All declared attrs accessible as None
- Unknown attr access via _MetaView raises AttributeError naming the attr
- _MetaView delegates known attrs to the underlying Options object

Run: .venv/bin/python -m pytest tests/core/test_options.py -q --no-cov
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# _GdxOptions base
# ---------------------------------------------------------------------------


def test_gdx_options_base_instantiable() -> None:
    """Assert that "_GdxOptions(cls)" can be instantiated with any class.

    If this fails, the base Options wrapper would reject arbitrary
    classes, breaking every subclass that relies on it.
    """
    from django_graphex._options import _GdxOptions

    class FakeClass:
        pass

    opts = _GdxOptions(FakeClass)
    assert opts.cls is FakeClass


def test_gdx_options_stores_cls() -> None:
    """Assert that "_GdxOptions.cls" is the class passed at construction.

    If this fails, the Options object would lose the reference to the
    class it describes, breaking any downstream code reading "opts.cls".
    """
    from django_graphex._options import _GdxOptions

    class MyModel:
        pass

    opts = _GdxOptions(MyModel)
    assert opts.cls is MyModel


# ---------------------------------------------------------------------------
# DjangoObjectOptions (native variant)
# ---------------------------------------------------------------------------


def test_django_object_options_instantiable() -> None:
    """Assert that "DjangoObjectOptions(cls)" is instantiable from the "_GdxOptions" hierarchy.

    If this fails, output types could not build their compiled Options
    object at all.
    """
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
        "max_depth",
        "complexity",
        "unions",
        "graphql_input_type",
        "graphql_output_type",
    ],
)
def test_django_object_options_attrs_default_none(attr: str) -> None:
    """Assert that a DjangoObjectOptions attribute defaults to None or another falsy value.

    Args:
        attr: The name of the DjangoObjectOptions attribute under test.

    If this fails, the named attribute would either be missing entirely
    or default to a non-empty, non-None value, surprising callers.
    """
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


def test_django_model_type_options_instantiable() -> None:
    """Assert that "DjangoModelTypeOptions(cls)" is instantiable.

    If this fails, model-type-driven mutation/type classes could not
    build their compiled Options object at all.
    """
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
        "payload_mode",
        "subscription_index_fields",
        "max_depth",
        "complexity",
    ],
)
def test_django_model_type_options_attrs_default_none(attr: str) -> None:
    """Assert that a DjangoModelTypeOptions attribute defaults to None or another falsy value.

    Args:
        attr: The name of the DjangoModelTypeOptions attribute under test.

    If this fails, the named attribute would either be missing entirely
    or default to a non-empty, non-None value, surprising callers.
    """
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


def test_serializer_mutation_options_instantiable() -> None:
    """Assert that "SerializerMutationOptions(cls)" is instantiable.

    If this fails, serializer-mutation classes could not build their
    compiled Options object at all.
    """
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
def test_serializer_mutation_options_attrs_default_none(attr: str) -> None:
    """Assert that a SerializerMutationOptions attribute exists on a fresh instance.

    Args:
        attr: The name of the SerializerMutationOptions attribute under test.

    If this fails, the named attribute would be missing entirely from a
    freshly constructed Options instance.
    """
    from django_graphex._options import SerializerMutationOptions

    class FakeCls:
        pass

    opts = SerializerMutationOptions(FakeCls)
    assert hasattr(opts, attr), f"SerializerMutationOptions missing attr: {attr!r}"


# ---------------------------------------------------------------------------
# SubscriptionOptions (native variant)
# ---------------------------------------------------------------------------


def test_subscription_options_instantiable() -> None:
    """Assert that "SubscriptionOptions(cls)" is instantiable.

    If this fails, subscription classes could not build their compiled
    Options object at all.
    """
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
        "payload_mode",
        "index_fields",
    ],
)
def test_subscription_options_attrs_default_none(attr: str) -> None:
    """Assert that a SubscriptionOptions attribute defaults to None or another falsy value.

    Args:
        attr: The name of the SubscriptionOptions attribute under test.

    If this fails, the named attribute would either be missing entirely
    or default to a non-empty, non-None value, surprising callers.
    """
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


def test_meta_view_raises_attribute_error_on_unknown() -> None:
    """Assert that "_MetaView" raises AttributeError for unknown attributes.

    If this fails, reading a typo'd or nonexistent Meta attribute would
    return a confusing value (or silently None) instead of failing loudly.
    """
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


def test_meta_view_names_unknown_attr_in_error_message() -> None:
    """Assert that "_MetaView"'s AttributeError message names the unknown attribute.

    If this fails, debugging a typo'd Meta attribute access would be
    harder because the error would not point at the offending name.
    """
    from django_graphex._options import DjangoModelTypeOptions, _MetaView

    class FakeCls:
        pass

    opts = DjangoModelTypeOptions(FakeCls)
    view = _MetaView(opts)

    with pytest.raises(AttributeError) as exc_info:
        _ = view.non_existent_field

    error_msg = str(exc_info.value)
    assert "non_existent_field" in error_msg


def test_meta_view_delegates_known_attrs() -> None:
    """Assert that "_MetaView" delegates known attributes to the wrapped Options object.

    If this fails, reading a valid Meta attribute through the view would
    not reflect the underlying Options object's current value.
    """
    from django_graphex._options import DjangoObjectOptions, _MetaView

    class FakeCls:
        pass

    opts = DjangoObjectOptions(FakeCls)
    opts.model = "FakeModel"  # type: ignore[assignment]
    view = _MetaView(opts)

    assert view.model == "FakeModel"


def test_meta_view_delegates_cls() -> None:
    """Assert that "_MetaView" exposes the "cls" attribute from the underlying Options.

    If this fails, code reading "meta.cls" through the view would not see
    the class the Options object was built for.
    """
    from django_graphex._options import DjangoObjectOptions, _MetaView

    class FakeCls:
        pass

    opts = DjangoObjectOptions(FakeCls)
    view = _MetaView(opts)

    assert view.cls is FakeCls
