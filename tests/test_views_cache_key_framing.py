"""Public HTTP and default-key regression for ambiguous GET components."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.http import HttpRequest
from django.test import RequestFactory, override_settings
from graphql import GraphQLField, GraphQLObjectType, GraphQLSchema, GraphQLString

from django_graphex.views import GraphQLView


@pytest.mark.parametrize("reverse_order", [False, True])
@override_settings(
    DJANGO_GRAPHEX={
        "CACHE_ACTIVE": True,
        "CACHE_INVALIDATION_SCOPE": "global",
        "DOCUMENT_CACHE_MAXSIZE": 0,
        "REQUIRE_CSRF_HEADER": True,
        "ALLOW_INTROSPECTION": True,
    }
)
def test_comment_boundary_cannot_select_another_cached_operation(
    reverse_order: bool,
) -> None:
    """Distinct selected operations retain their own cached HTTP responses.

    Args:
        reverse_order: Whether to warm the other operation first.
    """
    calls = {"alpha": 0, "bravo": 0}

    def resolve_alpha(*_args: object) -> str:
        calls["alpha"] += 1
        return "alpha-value"

    def resolve_bravo(*_args: object) -> str:
        calls["bravo"] += 1
        return "bravo-value"

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "Query",
            {
                "alpha": GraphQLField(GraphQLString, resolve=resolve_alpha),
                "bravo": GraphQLField(GraphQLString, resolve=resolve_bravo),
            },
        )
    )
    view = GraphQLView.as_view(schema=SimpleNamespace(graphql_schema=schema))
    factory = RequestFactory()
    base = "query A { alpha } query BA { bravo }"
    variants = [
        (base + "#", "BA", {"bravo": "bravo-value"}),
        (base + "#B", "A", {"alpha": "alpha-value"}),
    ]
    assert variants[0][0] + variants[0][1] == variants[1][0] + variants[1][1]
    if reverse_order:
        variants.reverse()
    cache.clear()
    requests = [
        factory.get("/graphql/", {"query": query, "operationName": name})
        for query, name, _expected in variants
    ]
    keys = [GraphQLView.fetch_cache_key(request) for request in requests]
    for request, (_query, _name, expected) in zip(requests, variants, strict=True):
        response = view(request)
        assert response.status_code == 200
        assert json.loads(response.content)["data"] == expected
    assert len(set(keys)) == 2
    repeat = view(
        factory.get(
            "/graphql/", {"query": variants[0][0], "operationName": variants[0][1]}
        )
    )
    assert json.loads(repeat.content)["data"] == variants[0][2]
    assert calls == {"alpha": 1, "bravo": 1}


def test_get_components_and_body_have_unambiguous_boundaries() -> None:
    """Keep body and GET component boundaries unambiguous.

    Distinct component tuples must produce distinct digests even when their
    unframed concatenations would match.
    """
    factory = RequestFactory()
    requests = [
        factory.get("/graphql/", {"query": "ab", "variables": "c"}),
        factory.get("/graphql/", {"query": "a", "variables": "bc"}),
        factory.get("/graphql/", {"query": "ab", "operationName": "c"}),
        factory.get("/graphql/", {"query": "a", "operationName": "bc"}),
        factory.post("/graphql/", data="abc", content_type="application/graphql"),
    ]
    keys = [GraphQLView.fetch_cache_key(request) for request in requests]
    assert len(set(keys)) == len(keys)
    assert all(len(key) == 64 for key in keys)
    assert all(set(key) <= set("0123456789abcdef") for key in keys)


def test_get_raw_body_is_documented_and_changes_default_cache_key() -> None:
    """Keep the cache-key contract aligned with raw GET body hashing.

    A nonempty GET body is unusual, but it contributes to the digest whenever
    one is present. Repeated requests with identical bytes stay deterministic.
    """
    factory = RequestFactory()
    url = "/graphql/?query=%7B%20alpha%20%7D"
    first = factory.generic(
        "GET", url, data=b"first", content_type="application/graphql"
    )
    second = factory.generic(
        "GET", url, data=b"second", content_type="application/graphql"
    )
    repeat = factory.generic(
        "GET", url, data=b"first", content_type="application/graphql"
    )
    assert first.GET == second.GET == repeat.GET
    assert first.body == b"first"
    assert second.body == b"second"
    assert GraphQLView.fetch_cache_key(first) != GraphQLView.fetch_cache_key(second)
    assert GraphQLView.fetch_cache_key(first) == GraphQLView.fetch_cache_key(repeat)

    description = GraphQLView.fetch_cache_key.__doc__ or ""
    assert "including GET requests" in description
    assert "GET requests have an empty body" not in description


def test_utf8_and_framing_like_text_cannot_cross_get_components() -> None:
    """Keep multibyte and framing-like text within its own component.

    The input strings intentionally share ambiguous unframed boundaries.
    """
    factory = RequestFactory()
    requests = [
        factory.get("/graphql/", {"query": "ébody:xy", "variables": "z"}),
        factory.get("/graphql/", {"query": "ébody:x", "variables": "yz"}),
        factory.get("/graphql/", {"query": "é", "variables": "body:xyz"}),
    ]
    assert len({GraphQLView.fetch_cache_key(request) for request in requests}) == 3


def test_frame_length_counts_utf8_bytes() -> None:
    """Use encoded byte lengths rather than Unicode code-point lengths.

    The two-byte query checks the exact framing of this built-in digest.
    """
    request = RequestFactory().get("/graphql/", {"query": "é"})
    frame = b"django-graphex-cache-key-v1\0"
    for tag, value in (
        (b"body", b""),
        (b"query", "é".encode("utf-8")),
        (b"variables", b""),
        (b"operationName", b""),
    ):
        frame += tag + len(value).to_bytes(8, "big") + value
    assert GraphQLView.fetch_cache_key(request) == hashlib.sha256(frame).hexdigest()


def test_missing_and_empty_get_parameters_remain_equivalent() -> None:
    """Retain the previous missing-versus-empty GET parameter behavior.

    Both forms resolve to the same empty string before framing.
    """
    factory = RequestFactory()
    absent = factory.get("/graphql/", {"query": "{ alpha }"})
    empty = factory.get(
        "/graphql/",
        {"query": "{ alpha }", "variables": "", "operationName": ""},
    )
    assert GraphQLView.fetch_cache_key(absent) == GraphQLView.fetch_cache_key(empty)


def test_custom_fetch_cache_key_override_remains_in_dispatch() -> None:
    """Keep the supported override wired into response-cache dispatch.

    The subclass records both requests while its fixed key yields a cache hit.
    """
    calls: list[str] = []

    class CustomView(GraphQLView):
        """Track invocations of the supported cache-key extension hook."""

        @staticmethod
        def fetch_cache_key(request: HttpRequest) -> str:
            """Return a deliberately fixed body segment for this test."""
            calls.append(request.GET.get("query", ""))
            return "custom-body-segment"

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "Query",
            {"alpha": GraphQLField(GraphQLString, resolve=lambda *_: "ok")},
        )
    )
    view = CustomView.as_view(schema=SimpleNamespace(graphql_schema=schema))
    factory = RequestFactory()
    cache.clear()
    with override_settings(
        DJANGO_GRAPHEX={
            "CACHE_ACTIVE": True,
            "CACHE_INVALIDATION_SCOPE": "global",
            "DOCUMENT_CACHE_MAXSIZE": 0,
            "REQUIRE_CSRF_HEADER": True,
        }
    ):
        for _ in range(2):
            response = view(factory.get("/graphql/", {"query": "{ alpha }"}))
            assert response.status_code == 200
            assert json.loads(response.content)["data"] == {"alpha": "ok"}
    assert calls == ["{ alpha }", "{ alpha }"]


def test_pretty_parameter_is_part_of_the_cache_key() -> None:
    """A pretty-printed response is never served to a compact request.

    "json_encode" formats the body by the GET "pretty" parameter, so the cached
    body differs by it. An empty value is compact and shares the plain key.
    """
    factory = RequestFactory()
    url = "/graphql/?query=%7B%20alpha%20%7D"
    plain = factory.get(url)
    pretty = factory.get(url + "&pretty=1")
    empty = factory.get(url + "&pretty=")

    assert GraphQLView.fetch_cache_key(plain) != GraphQLView.fetch_cache_key(pretty)
    assert GraphQLView.fetch_cache_key(plain) == GraphQLView.fetch_cache_key(empty)
