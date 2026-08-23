# -*- coding: utf-8 -*-
"""Regression tests for the CACHE_ACTIVE dispatch preamble (C10a / C10b).

Two independent defects in "GraphQLView.dispatch" when "CACHE_ACTIVE" is on:

(a) MALFORMED BODY 500: the preamble calls "get_operation_ast" (and therefore
    "parse_body") outside any "except HttpError", so an unauthenticated client
    posting "{not json", "[1, 2]" or "42" turns the clean 400 into an unhandled
    exception.  Fix: catch "HttpError" and fall through to "super_call", which
    already serializes it into the 400 envelope.

(b) LOST WRITE ON A MULTI-OPERATION DOCUMENT: the preamble asked graphql-core
    for the operation with a "None" operation name, which returns "None" as soon
    as the document declares more than one operation.  The request was therefore
    never classified as a mutation: the response was cached and replayed while
    the mutation ran only once (and the identity's version counter never moved).
    Fix: pass the request's "operationName" and bypass the cache whenever the
    operation still cannot be determined.
"""

from __future__ import annotations

import json
from typing import Any

from django.contrib.auth.models import AnonymousUser
from django.core.cache import caches
from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLBoolean, GraphQLResolveInfo, GraphQLString

from django_graphex.core import Mutation, ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView

from .cache_helpers import CACHE_ON

#: Per-operation call counters, reset by each test's "setUp".
CALLS: dict[str, int] = {"hello": 0, "mutate": 0}


class _CountingQuery(ObjectType):
    """Query root whose single field counts how often it is resolved."""

    hello = field(GraphQLString)

    def resolve_hello(root: Any, info: GraphQLResolveInfo) -> str:  # noqa: N805
        """Resolve "hello" and record the call.

        Args:
            root: The unused parent resolver value.
            info: The GraphQL execution info for the current field.

        Returns:
            The literal string "world".
        """
        CALLS["hello"] += 1
        return "world"


class _CountingMutation(Mutation):
    """A no-op mutation that records every execution."""

    class Arguments:
        """No arguments are accepted by this mutation."""

    ok = field(GraphQLBoolean)

    @classmethod
    def mutate(cls, root: Any, info: GraphQLResolveInfo) -> "_CountingMutation":
        """Run the no-op mutation and record the call.

        Args:
            root: The unused parent resolver value.
            info: The GraphQL execution info for the current field.

        Returns:
            A new instance with "ok" set to True.
        """
        CALLS["mutate"] += 1
        return cls(ok=True)


class _CountingMutationRoot(ObjectType):
    """Mutation root exposing the counting mutation."""

    do_thing = _CountingMutation.Field()


_schema = DjangoGraphQLSchema(query=_CountingQuery, mutation=_CountingMutationRoot)

#: A document declaring BOTH a query and a mutation, selected by operationName.
MULTI_OP_DOCUMENT = "query Ping { hello }\nmutation Go { doThing { ok } }"


class _CachePreambleTestCase(TestCase):
    """Shared scaffolding: a request factory, the counting schema, and a POST."""

    def setUp(self) -> None:
        """Reset the resolver counters and the cache before each test."""
        CALLS["hello"] = 0
        CALLS["mutate"] = 0
        caches["default"].clear()
        self.factory = RequestFactory()
        self.view = GraphQLView.as_view(schema=_schema)

    def post(self, body: bytes | str) -> Any:
        """Dispatch a JSON POST carrying "body" through the real view.

        Args:
            body: The raw request body, already JSON-encoded (or deliberately
                malformed).

        Returns:
            The HTTP response produced by the view.
        """
        request = self.factory.post("/graphql/", body, content_type="application/json")
        request.user = AnonymousUser()
        return self.view(request)


@override_settings(**CACHE_ON)
class TestMalformedBodyWithCacheActive(_CachePreambleTestCase):
    """A malformed body must still return 400 when the cache is active.

    Every body here is rejected by "parse_body", which raises "HttpError" from
    inside the cache preamble. Only "super_call" knows how to serialize that
    into the 400 envelope.
    """

    def test_invalid_json_returns_400(self) -> None:
        """A syntactically invalid JSON body must return a clean 400.

        If this fails, "parse_body" raises "HttpError" out of the cache
        preamble and the client gets an unhandled 500 instead.
        """
        response = self.post(b"{not json")
        assert response.status_code == 400
        assert b"invalid JSON" in response.content

    def test_json_list_body_returns_400(self) -> None:
        """A JSON list body on a non-batch view must return a clean 400.

        If this fails, the list body escapes the preamble as an unhandled
        "HttpError".
        """
        response = self.post(b"[1, 2]")
        assert response.status_code == 400
        assert b"not a valid JSON query" in response.content

    def test_json_scalar_body_returns_400(self) -> None:
        """A bare JSON scalar body must return a clean 400.

        If this fails, the scalar body escapes the preamble as an unhandled
        "HttpError".
        """
        response = self.post(b"42")
        assert response.status_code == 400
        assert b"not a valid JSON query" in response.content

    def test_invalid_variables_json_returns_400(self) -> None:
        """A non-JSON "variables" string must return a clean 400.

        The preamble now resolves the operation name through
        "get_graphql_params", which validates "variables" and raises
        "HttpError" for a malformed value; that must not escape either.
        """
        response = self.post(
            json.dumps({"query": "{ hello }", "variables": "{not json"})
        )
        assert response.status_code == 400
        assert b"Variables are invalid JSON" in response.content


@override_settings(**CACHE_ON)
class TestMultiOperationDocumentIsNotReplayed(_CachePreambleTestCase):
    """The request's operationName must drive the mutation classification.

    The document below declares a query AND a mutation, so the operation the
    client selects is the only thing that says whether the response may be
    cached.
    """

    def test_named_mutation_in_multi_operation_document_always_executes(self) -> None:
        """Three POSTs of the same named mutation must run the mutation 3 times.

        If this fails, the multi-operation document is misclassified as a
        non-mutation, its response is cached, and the second and third POSTs
        replay a fabricated success while the write never happens.
        """
        for _ in range(3):
            response = self.post(
                json.dumps({"query": MULTI_OP_DOCUMENT, "operationName": "Go"})
            )
            assert response.status_code == 200
            assert json.loads(response.content) == {"data": {"doThing": {"ok": True}}}

        assert CALLS["mutate"] == 3

    def test_named_query_in_multi_operation_document_is_still_cached(self) -> None:
        """A named QUERY in the same document must still be served from cache.

        If this fails, honouring the operation name would have disabled caching
        for every multi-operation document instead of only for the ambiguous
        ones.
        """
        for _ in range(3):
            response = self.post(
                json.dumps({"query": MULTI_OP_DOCUMENT, "operationName": "Ping"})
            )
            assert response.status_code == 200
            assert json.loads(response.content) == {"data": {"hello": "world"}}

        assert CALLS["hello"] == 1

    def test_operation_name_from_the_query_string_is_honoured(self) -> None:
        """An operationName passed as a GET parameter must classify the request.

        If this fails, a client that selects the operation via the query string
        (the GET transport spelling) still has its mutation cached.
        """
        request = self.factory.post(
            "/graphql/?operationName=Go",
            json.dumps({"query": MULTI_OP_DOCUMENT}),
            content_type="application/json",
        )
        request.user = AnonymousUser()
        self.view(request)
        self.view(request)

        assert CALLS["mutate"] == 2

    def test_undeterminable_operation_is_never_cached(self) -> None:
        """An ambiguous document must bypass the cache entirely (fail closed).

        Without an operationName graphql-core cannot pick an operation, so the
        request could be a mutation. If this fails, such a request is cached and
        a later mutation-bearing document with the same body is replayed.
        """
        backend = caches["default"]
        stored: list[Any] = []
        original_set = backend.set

        def _record(*args: Any, **kwargs: Any) -> Any:
            stored.append(args[0])
            return original_set(*args, **kwargs)

        backend.set = _record  # type: ignore[method-assign]
        try:
            response = self.post(json.dumps({"query": MULTI_OP_DOCUMENT}))
        finally:
            backend.set = original_set  # type: ignore[method-assign]

        assert response.status_code == 400
        assert stored == []
