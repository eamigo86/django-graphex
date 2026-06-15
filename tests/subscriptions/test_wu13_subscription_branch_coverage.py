# -*- coding: utf-8 -*-
"""WARNING-1 close-out (verify #1522) — subscription.py branch coverage top-up.

``subscription.py`` is the DUAL-BACKEND module (graphene base + native compile
path), measured COMBINED across both runs. Phase 6 verify flagged it at 84.44%
combined branch. The misses are: the Meta-validation ``TypeError`` guards, the
``_should_serialize_data`` global-setting fallback, the graphene-path
``_validate_filters`` reject, the native ``_pk_scalar`` mro fallback, the
``_native_db_exists`` pk-None guard, the native ``_subscribe_source`` no-channel
+ JSON-string-filters arms, and the ``_enum_value`` nested unwrap.

Backend-agnostic tests (Meta validation, serialize-data, validate-filters, enum)
run under BOTH backends and contribute to the COMBINED measurement; native-only
tests cover the native compile-path branches under ``GDX_BACKEND=native``.

Each test asserts a real raised type / returned value / parsed result.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("channels")

from tests.models import Author, Post  # noqa: E402

_NATIVE = os.environ.get("GDX_BACKEND", "graphene") == "native"

native_only = pytest.mark.skipif(
    not _NATIVE, reason="native compile path (GDX_BACKEND=native)"
)


def _make_subscription(**meta):
    """Build a fresh ``PostSubscription`` (native base, S6e re-parent).

    ``Subscription`` is now a pydantic ``ModelMetaclass`` type (S6e); a 3-arg
    ``type(name, bases, ns)`` build must inject ``__module__``/``__qualname__``
    (and re-stamp the nested ``Meta`` qualname) or pydantic's
    ``inspect_namespace`` raises ``KeyError('__module__')`` — mirroring the
    production ``DjangoModelType.subscription_type`` builder.
    """
    from django_graphex.subscriptions import Subscription

    meta_cls = type("Meta", (), {"model": Post, "stream": "posts", **meta})
    meta_cls.__qualname__ = "PostSubscription.Meta"
    meta_cls.__module__ = __name__
    return type(
        "PostSubscription",
        (Subscription,),
        {"__module__": __name__, "__qualname__": "PostSubscription", "Meta": meta_cls},
    )


# ---------------------------------------------------------------------------
# Meta validation guards (run at class-definition time; BOTH backends)
# ---------------------------------------------------------------------------


def test_non_string_stream_raises_type_error():
    """A non-string ``Meta.stream`` raises ``TypeError`` at definition time.

    Covers subscription.py:165-166.
    """
    from django_graphex.subscriptions import Subscription

    with pytest.raises(TypeError) as exc_info:

        class _BadStream(Subscription):
            class Meta:
                model = Post
                stream = 123  # not a string

    assert "valid string stream name" in str(exc_info.value)


def test_queryset_model_mismatch_raises_type_error():
    """A ``Meta.queryset`` whose model differs from the backend model raises.

    Covers subscription.py:171-173 — the ``model != queryset.model`` arm.
    """
    from django_graphex.subscriptions import Subscription

    with pytest.raises(TypeError) as exc_info:

        class _Mismatch(Subscription):
            class Meta:
                model = Post
                stream = "posts"
                queryset = Author.objects.all()  # wrong model

    assert "queryset model must correspond" in str(exc_info.value)


def test_matching_queryset_model_is_accepted():
    """A ``Meta.queryset`` whose model MATCHES the backend model is accepted.

    Pins the ``queryset is not None`` True path with a matching model (the False
    arm of the mismatch check) so both sides of the guard are exercised.
    """
    from django_graphex.subscriptions import Subscription

    class _Ok(Subscription):
        class Meta:
            model = Post
            stream = "posts"
            queryset = Post.objects.all()

    assert _Ok._meta.queryset.model is Post


def test_invalid_serialize_data_raises_type_error():
    """A ``Meta.serialize_data`` that is not None/True/False raises ``TypeError``.

    Covers subscription.py:184-185.
    """
    from django_graphex.subscriptions import Subscription

    with pytest.raises(TypeError) as exc_info:

        class _BadSerialize(Subscription):
            class Meta:
                model = Post
                stream = "posts"
                serialize_data = "yes"  # not None/True/False

    assert "serialize_data must be None, True or False" in str(exc_info.value)


# ---------------------------------------------------------------------------
# _should_serialize_data — global setting fallback
# ---------------------------------------------------------------------------


def test_should_serialize_data_falls_back_to_global_setting(monkeypatch):
    """``serialize_data=None`` defers to ``SUBSCRIPTION_SERIALIZE_DATA``.

    Covers subscription.py:251-252 — the ``value is None`` arm reads the global
    setting. With the Meta value unset (None), the global drives the result.
    """
    from django_graphex.subscriptions import subscription as sub_mod

    sub = _make_subscription()  # serialize_data unset → None
    assert sub._meta.serialize_data is None

    monkeypatch.setattr(
        sub_mod.graphql_api_settings, "SUBSCRIPTION_SERIALIZE_DATA", True
    )
    assert sub._should_serialize_data() is True

    monkeypatch.setattr(
        sub_mod.graphql_api_settings, "SUBSCRIPTION_SERIALIZE_DATA", False
    )
    assert sub._should_serialize_data() is False


def test_should_serialize_data_meta_value_wins():
    """An explicit ``Meta.serialize_data`` wins over the global setting.

    Pins the ``value is None`` False arm (the Meta value is used directly).
    """
    sub_true = _make_subscription(serialize_data=True)
    assert sub_true._should_serialize_data() is True
    sub_false = _make_subscription(serialize_data=False)
    assert sub_false._should_serialize_data() is False


# ---------------------------------------------------------------------------
# _validate_filters — graphene-path filter-key validation
# ---------------------------------------------------------------------------


def test_validate_filters_rejects_undeclared_root_field():
    """A filter key rooting on an undeclared output field raises ``GraphQLError``.

    Covers subscription.py:392-398 — the reject arm. ``not_a_field`` is not a
    declared output field of the Post subscription.
    """
    from graphql import GraphQLError

    sub = _make_subscription(serialize_data=True)
    with pytest.raises(GraphQLError) as exc_info:
        sub._validate_filters({"not_a_field__icontains": "x"})
    assert "not a declared output field" in str(exc_info.value)


def test_validate_filters_accepts_declared_root_and_empty():
    """A declared root (and an empty filter set) pass validation.

    Pins the ``not client_filters`` early-return (392-393) AND the declared-root
    accept arm (the ``root not in declared`` False path).
    """
    sub = _make_subscription(serialize_data=True)
    # Empty filters → early return, no raise.
    assert sub._validate_filters({}) is None
    assert sub._validate_filters(None) is None
    # A declared field root with an ORM lookup suffix is accepted.
    sub._validate_filters({"id": 1})
    sub._validate_filters({"title__icontains": "hi"})


# ---------------------------------------------------------------------------
# _enum_value — nested unwrap
# ---------------------------------------------------------------------------


def test_enum_value_unwraps_nested_value_holders():
    """``_enum_value`` unwraps nested ``.value`` holders down to the raw value.

    Covers subscription.py:49-51 — the ``while hasattr(value, 'value')`` loop body.
    """
    from django_graphex.subscriptions.subscription import _enum_value

    class _Holder:
        def __init__(self, value):
            self.value = value

    # Nested holders unwrap fully; a plain string passes through unchanged.
    assert _enum_value(_Holder(_Holder("create"))) == "create"
    assert _enum_value("update") == "update"


# ---------------------------------------------------------------------------
# NATIVE: _pk_scalar mro fallback, _native_db_exists pk-None, _subscribe_source
# ---------------------------------------------------------------------------


@native_only
def test_native_pk_scalar_falls_back_to_id_for_unmapped_pk(monkeypatch):
    """``_pk_scalar`` returns ``GraphQLID`` when the pk type is not in the mapping.

    Covers subscription.py:516-519 — the mro walk exhausts with no match and falls
    back to ``_GraphQLID``. We monkeypatch the django→gql mapping (imported inside
    ``_build_native_event_type`` from ``native.output_compiler``) to be EMPTY so no
    pk class matches, forcing the fallback for the FK pk scalar.
    """
    from graphql import GraphQLID

    from django_graphex.native import output_compiler as oc

    # Force an empty mapping → every pk class misses → the ID fallback.
    monkeypatch.setattr(oc, "_get_django_to_gql", lambda: {})

    sub = _make_subscription()
    event_type = sub._build_native_event_type()
    # The FK ``author`` is rendered as the deliverable pk scalar; with an empty
    # mapping the _pk_scalar fallback makes it GraphQLID.
    assert event_type.fields["author"].type is GraphQLID


@native_only
async def test_native_db_exists_returns_false_when_event_has_no_pk():
    """``_native_db_exists`` returns False (no query) when the event has no ``id``.

    Covers subscription.py:650-652 — the ``pk is None`` guard short-circuits to a
    False-resolving awaitable without touching the ORM.
    """
    sub = _make_subscription()
    result = sub._native_db_exists({"author__name": "ada"}, {"title": "no-pk"})
    assert await result is False


@native_only
async def test_native_subscribe_source_raises_without_channel_layer(monkeypatch):
    """The native subscribe factory raises ``RuntimeError`` with no channel layer.

    Covers subscription.py:788-793 — ``get_channel_layer() is None`` → RuntimeError.
    The factory is the ``subscribe`` callable on the native field.
    """
    from graphql import parse

    from django_graphex.subscriptions import subscription as sub_mod

    sub = _make_subscription()
    schema = None
    document = parse("subscription { postEvent { id } }")
    field = sub._build_native_field(schema, document)

    # No channel layer configured → the factory must raise.
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda *a, **k: None
    )

    class _Info:
        context = None

    with pytest.raises(RuntimeError) as exc_info:
        await field.subscribe(None, _Info(), action="create")
    assert "No channel layer configured" in str(exc_info.value)
    assert sub_mod  # module referenced


@native_only
async def test_native_subscribe_source_parses_json_string_filters(monkeypatch):
    """A JSON-STRING ``filters`` arg is decoded before reaching the engine.

    Covers subscription.py:796-800 — the ``isinstance(client_filters, str)`` arm
    decodes the JSON into a dict. We capture the filters the engine receives by
    intercepting ``_native_subscribe``.
    """
    import json

    from channels.layers import InMemoryChannelLayer
    from graphql import parse

    sub = _make_subscription()
    document = parse("subscription { postEvent { id } }")
    field = sub._build_native_field(None, document)

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    captured: dict = {}

    async def _capture_native_subscribe(channel_layer, schema, doc, **kwargs):
        captured.update(kwargs)
        # Return something truthy so the factory completes; the source object is
        # not driven here (we only assert the decoded filters reached the engine).
        return object()

    # Patch the bound classmethod the factory delegates to.
    sub._native_subscribe = classmethod(  # type: ignore[assignment]
        lambda cls, *a, **k: _capture_native_subscribe(*a, **k)
    )

    class _Info:
        context = None

    await field.subscribe(
        None, _Info(), action="create", filters=json.dumps({"id": 7})
    )
    # The JSON string was decoded to a dict before reaching the engine.
    assert captured["filters"] == {"id": 7}


@native_only
async def test_native_subscribe_source_blank_filters_skip_json_branch(monkeypatch):
    """A falsy ``filters`` arg (``""``) is normalized to ``None`` BEFORE the JSON arm.

    Pins subscription.py:796 — ``kwargs.get('filters') or None`` coerces a blank
    string to ``None``, so the ``isinstance(client_filters, str)`` JSON-decode arm
    is NOT entered (the engine receives ``None``). This documents why the
    ``else None`` sub-arm of line 800 is defensively unreachable (a non-empty
    string is always truthy at that point).
    """
    from channels.layers import InMemoryChannelLayer
    from graphql import parse

    sub = _make_subscription()
    document = parse("subscription { postEvent { id } }")
    field = sub._build_native_field(None, document)

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    captured: dict = {}

    async def _capture(channel_layer, schema, doc, **kwargs):
        captured.update(kwargs)
        return object()

    sub._native_subscribe = classmethod(  # type: ignore[assignment]
        lambda cls, *a, **k: _capture(*a, **k)
    )

    class _Info:
        context = None

    # filters="" → coerced to None by ``or None`` (never enters the str branch).
    await field.subscribe(None, _Info(), action="create", filters="")
    assert captured["filters"] is None
