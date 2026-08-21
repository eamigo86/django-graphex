# -*- coding: utf-8 -*-
"""WARNING-1 close-out (verify #1522) — subscription.py branch coverage top-up.

"subscription.py" is the DUAL-BACKEND module (graphene base + native compile
path), measured COMBINED across both runs. Phase 6 verify flagged it at 84.44%
combined branch. The misses are: the Meta-validation TypeError guards, the
"_payload_is_full" global-setting fallback, the graphene-path
"_validate_filters" reject, the native "_pk_scalar" mro fallback, the
"_native_db_exists" pk-None guard, the native "_subscribe_source" no-channel
plus JSON-string-filters arms, and the "_enum_value" nested unwrap.

Backend-agnostic tests (Meta validation, payload-mode, validate-filters, enum)
run under BOTH backends and contribute to the COMBINED measurement; native-only
tests cover the native compile-path branches.

Each test asserts a real raised type / returned value / parsed result.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

pytest.importorskip("channels")

from django_graphex.subscriptions import Subscription  # noqa: E402
from tests.models import Author, Post  # noqa: E402


def _make_subscription(**meta: Any) -> type[Subscription]:
    """Build a fresh "PostSubscription" (native base, S6e re-parent).

    "Subscription" is now a pydantic ModelMetaclass type (S6e); a 3-arg
    type(name, bases, ns) build must inject __module__/__qualname__
    (and re-stamp the nested Meta qualname) or pydantic's
    inspect_namespace raises KeyError('__module__') — mirroring the
    production "DjangoModelType.subscription_type" builder.

    Args:
        meta: Extra attributes merged into the generated Meta class (model
            and stream are always set; overrides here win).

    Returns:
        PostSubscription: The freshly created Subscription subclass.
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


class _ResolveInfo:
    """A minimal "GraphQLResolveInfo" stand-in for direct subscribe-factory calls.

    The native subscribe factory runs the configured
    "DJANGO_GRAPHEX['MIDDLEWARE']" chain (2.0.1: the transports are the only
    subscription servers, so the chain is applied at the subscribe resolver), and
    the bundled directive middleware reads "info.field_nodes" — so the stand-in
    carries a directive-free field node.
    """

    context = None
    field_nodes = (SimpleNamespace(directives=()),)


# ---------------------------------------------------------------------------
# Meta validation guards (run at class-definition time; BOTH backends)
# ---------------------------------------------------------------------------


def test_non_string_stream_raises_type_error() -> None:
    """A non-string Meta.stream must raise TypeError at class-definition time.

    Contract: this test ships broken if a non-string stream value is
    silently accepted instead of raising.

    Covers subscription.py:165-166.
    """
    from django_graphex.subscriptions import Subscription

    with pytest.raises(TypeError) as exc_info:

        class _BadStream(Subscription):
            class Meta:
                model = Post
                stream = 123  # not a string

    assert "valid string stream name" in str(exc_info.value)


def test_queryset_model_mismatch_raises_type_error() -> None:
    """A Meta.queryset whose model differs from the backend model must raise.

    Contract: this test ships broken if a mismatched queryset model is
    silently accepted instead of raising TypeError.

    Covers subscription.py:171-173 — the "model != queryset.model" arm.
    """
    from django_graphex.subscriptions import Subscription

    with pytest.raises(TypeError) as exc_info:

        class _Mismatch(Subscription):
            class Meta:
                model = Post
                stream = "posts"
                queryset = Author.objects.all()  # wrong model

    assert "queryset model must correspond" in str(exc_info.value)


def test_matching_queryset_model_is_accepted() -> None:
    """A Meta.queryset whose model matches the backend model must be accepted.

    Contract: pins the "queryset is not None" True path with a matching
    model (the False arm of the mismatch check) so both sides of the guard
    are exercised — ships broken if a legitimate matching queryset starts
    raising.
    """
    from django_graphex.subscriptions import Subscription

    class _Ok(Subscription):
        class Meta:
            model = Post
            stream = "posts"
            queryset = Post.objects.all()

    assert _Ok._meta.queryset.model is Post


def test_invalid_payload_mode_raises() -> None:
    """A Meta.payload_mode outside None/full/id_only must raise ImproperlyConfigured.

    Contract: this test ships broken if an invalid payload_mode value is
    silently accepted instead of raising with both valid values named.

    Covers subscription.py:234-238.
    """
    from django_graphex.subscriptions import Subscription

    with pytest.raises(ImproperlyConfigured) as exc_info:

        class _BadPayloadMode(Subscription):
            class Meta:
                model = Post
                stream = "posts"
                payload_mode = "everything"  # not None/"full"/"id_only"

    message = str(exc_info.value)
    assert "full" in message
    assert "id_only" in message


# ---------------------------------------------------------------------------
# _payload_is_full — global setting fallback
# ---------------------------------------------------------------------------


def test_payload_is_full_falls_back_to_global_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """payload_mode=None must defer to the global SUBSCRIPTION_PAYLOAD_MODE setting.

    Contract: this test ships broken if an unset Meta.payload_mode ignores
    the global setting instead of following it.

    Covers subscription.py:315-317 — the "value is None" arm reads the global
    setting. With the Meta value unset (None), the global drives the result.

    Args:
        monkeypatch: The pytest fixture used to patch the global
            SUBSCRIPTION_PAYLOAD_MODE setting.
    """
    from django_graphex.subscriptions import subscription as sub_mod

    sub = _make_subscription()  # payload_mode unset → None
    assert sub._meta.payload_mode is None

    monkeypatch.setattr(
        sub_mod.graphql_api_settings, "SUBSCRIPTION_PAYLOAD_MODE", "full"
    )
    assert sub._payload_is_full() is True

    monkeypatch.setattr(
        sub_mod.graphql_api_settings, "SUBSCRIPTION_PAYLOAD_MODE", "id_only"
    )
    assert sub._payload_is_full() is False


def test_payload_mode_meta_value_wins() -> None:
    """An explicit Meta.payload_mode must win over the global setting.

    Contract: pins the "value is None" False arm (the Meta value is used
    directly) — ships broken if an explicit per-subscription value is
    overridden by the global default.
    """
    sub_true = _make_subscription(payload_mode="full")
    assert sub_true._payload_is_full() is True
    sub_false = _make_subscription(payload_mode="id_only")
    assert sub_false._payload_is_full() is False


# ---------------------------------------------------------------------------
# _validate_filters — graphene-path filter-key validation
# ---------------------------------------------------------------------------


def test_validate_filters_rejects_undeclared_root_field() -> None:
    """A filter key rooting on an undeclared output field must raise GraphQLError.

    Contract: this test ships broken if an undeclared filter root is
    silently accepted instead of raising.

    Covers subscription.py:392-398 — the reject arm. "not_a_field" is not a
    declared output field of the Post subscription.
    """
    from graphql import GraphQLError

    sub = _make_subscription(payload_mode="full")
    with pytest.raises(GraphQLError) as exc_info:
        sub._validate_filters({"not_a_field__icontains": "x"})
    assert "not a declared output field" in str(exc_info.value)


def test_validate_filters_accepts_declared_root_and_empty() -> None:
    """A declared filter root, and an empty filter set, must both pass validation.

    Contract: pins the "not client_filters" early-return (392-393) and the
    declared-root accept arm (the "root not in declared" False path) —
    ships broken if either legitimate case starts raising.
    """
    sub = _make_subscription(payload_mode="full")
    # Empty filters → early return, no raise.
    assert sub._validate_filters({}) is None
    assert sub._validate_filters(None) is None
    # A declared field root with an ORM lookup suffix is accepted.
    sub._validate_filters({"id": 1})
    sub._validate_filters({"title__icontains": "hi"})


# ---------------------------------------------------------------------------
# _enum_value — nested unwrap
# ---------------------------------------------------------------------------


def test_enum_value_unwraps_nested_value_holders() -> None:
    """ "_enum_value" must unwrap nested .value holders down to the raw value.

    Contract: this test ships broken if a doubly-wrapped enum-like value
    stops fully unwrapping to its raw string.

    Covers subscription.py:49-51 — the "while hasattr(value, 'value')" loop body.
    """
    from django_graphex.subscriptions.subscription import _enum_value

    class _Holder:
        """A minimal stand-in exposing a nested .value attribute."""

        def __init__(self, value: object) -> None:
            self.value = value

    # Nested holders unwrap fully; a plain string passes through unchanged.
    assert _enum_value(_Holder(_Holder("create"))) == "create"
    assert _enum_value("update") == "update"


# ---------------------------------------------------------------------------
# NATIVE: _pk_scalar mro fallback, _native_db_exists pk-None, _subscribe_source
# ---------------------------------------------------------------------------


def test_native_pk_scalar_falls_back_to_id_for_unmapped_pk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "_pk_scalar" must return GraphQLID when the pk type is not in the mapping.

    Contract: this test ships broken if an unmapped pk class crashes instead
    of degrading to the GraphQLID fallback.

    Covers subscription.py:516-519 — the mro walk exhausts with no match and falls
    back to "_GraphQLID". We monkeypatch the django-to-gql mapping (imported
    inside "_build_native_event_type" from "core.output_compiler") to be EMPTY
    so no pk class matches, forcing the fallback for the FK pk scalar.

    Args:
        monkeypatch: The pytest fixture used to empty the django-to-gql
            scalar mapping.
    """
    from graphql import GraphQLID

    from django_graphex.core import output_compiler as oc

    # Force an empty mapping → every pk class misses → the ID fallback.
    monkeypatch.setattr(oc, "_get_django_to_gql", lambda: {})

    sub = _make_subscription()
    event_type = sub._build_native_event_type()
    # The FK ``author`` is rendered as the deliverable pk scalar; with an empty
    # mapping the _pk_scalar fallback makes it GraphQLID.
    assert event_type.fields["author"].type is GraphQLID


async def test_native_db_exists_returns_false_when_event_has_no_pk() -> None:
    """ "_native_db_exists" must return False, without querying, when the event has no id.

    Contract: this test ships broken if a pk-less event either raises or
    touches the ORM instead of short-circuiting to False.

    Covers subscription.py:650-652 — the "pk is None" guard short-circuits to a
    False-resolving awaitable without touching the ORM.
    """
    sub = _make_subscription()
    result = sub._native_db_exists({"author__name": "ada"}, {"title": "no-pk"})
    assert await result is False


async def test_native_subscribe_source_raises_without_channel_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The native subscribe factory must raise RuntimeError with no channel layer.

    Contract: this test ships broken if the subscribe factory hangs or
    silently no-ops instead of raising when no channel layer is configured.

    Covers subscription.py:788-793 — "get_channel_layer() is None" -> RuntimeError.
    The factory is the "subscribe" callable on the native field.

    Args:
        monkeypatch: The pytest fixture used to force get_channel_layer to
            return None.
    """
    from graphql import parse

    from django_graphex.subscriptions import subscription as sub_mod

    sub = _make_subscription()
    schema = None
    document = parse("subscription { postEvent { id } }")
    field = sub._build_native_field(schema, document)

    # No channel layer configured → the factory must raise.
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: None)

    with pytest.raises(RuntimeError) as exc_info:
        await field.subscribe(None, _ResolveInfo(), action="create")
    assert "No channel layer configured" in str(exc_info.value)
    assert sub_mod  # module referenced


async def test_native_subscribe_source_parses_json_string_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A JSON-string filters argument must be decoded before reaching the engine.

    Contract: this test ships broken if a JSON-encoded filters string reaches
    the subscription engine undecoded instead of as a parsed dict.

    Covers subscription.py:796-800 — the "isinstance(client_filters, str)" arm
    decodes the JSON into a dict. We capture the filters the engine receives by
    intercepting "_native_subscribe".

    Args:
        monkeypatch: The pytest fixture used to configure an in-memory
            channel layer.
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

    await field.subscribe(
        None, _ResolveInfo(), action="create", filters=json.dumps({"id": 7})
    )
    # The JSON string was decoded to a dict before reaching the engine.
    assert captured["filters"] == {"id": 7}


async def test_native_subscribe_source_blank_filters_skip_json_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blank filters string ("") must normalize to None before the JSON arm.

    Contract: pins subscription.py:796 — "kwargs.get('filters') or None"
    coerces a blank string to None, so the "isinstance(client_filters, str)"
    JSON-decode arm is NOT entered (the engine receives None). This
    documents why the "else None" sub-arm of line 800 is defensively
    unreachable (a non-empty string is always truthy at that point). Ships
    broken if a blank filters string reaches the JSON-decode branch instead.

    Args:
        monkeypatch: The pytest fixture used to configure an in-memory
            channel layer.
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

    # filters="" → coerced to None by ``or None`` (never enters the str branch).
    await field.subscribe(None, _ResolveInfo(), action="create", filters="")
    assert captured["filters"] is None
