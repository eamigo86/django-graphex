# -*- coding: utf-8 -*-
"""Coverage for the vendored ``BaseGraphQLView`` error/batch/parse branches.

Exercises method-not-allowed, batch mode, invalid JSON, application/graphql and
form bodies, missing-query, GET-mutation rejection, and content-type negotiation
helpers, all through the concrete ``BaseGraphQLView``.
"""

import json

import graphene
import pytest
from django.test import RequestFactory, TestCase

from django_graphex.views import (
    BaseGraphQLView,
    HttpError,
    get_accepted_content_types,
    instantiate_middleware,
    set_rollback,
)


class _Query(graphene.ObjectType):
    hello = graphene.String()

    def resolve_hello(root, info):
        return "world"


_schema = graphene.Schema(query=_Query)


class ViewBaseTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_method_not_allowed(self):
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.put("/graphql/", {}, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 405)

    def test_batch_mode_returns_list(self):
        view = BaseGraphQLView.as_view(schema=_schema, batch=True)
        body = json.dumps([{"query": "{ hello }"}, {"query": "{ hello }"}])
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["data"]["hello"], "world")

    def test_batch_empty_list_is_bad_request(self):
        view = BaseGraphQLView.as_view(schema=_schema, batch=True)
        request = self.factory.post("/graphql/", "[]", content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 400)

    def test_invalid_json_body(self):
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/", "{not json", content_type="application/json"
        )
        response = view(request)
        self.assertEqual(response.status_code, 400)

    def test_application_graphql_content_type(self):
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/", "{ hello }", content_type="application/graphql"
        )
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    def test_form_urlencoded_body(self):
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/",
            "query=" + "%7B+hello+%7D",  # urlencoded "{ hello }"
            content_type="application/x-www-form-urlencoded",
        )
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_missing_query_is_bad_request(self):
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post("/graphql/", {}, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 400)

    def test_get_mutation_is_rejected(self):
        view = BaseGraphQLView.as_view(schema=_schema)
        # A non-dict JSON body asserts -> bad request (covers the dict assertion).
        request = self.factory.post(
            "/graphql/", "[1, 2]", content_type="application/json"
        )
        response = view(request)
        self.assertEqual(response.status_code, 400)

    def test_pretty_view_pretty_prints(self):
        view = BaseGraphQLView.as_view(schema=_schema, pretty=True)
        request = self.factory.get("/graphql/", {"query": "{ hello }"})
        response = view(request)
        self.assertEqual(response.status_code, 200)
        # Pretty output is indented (contains newlines).
        self.assertIn(b"\n", response.content)


# --------------------------------------------------------------------------- #
# Module-level helpers                                                          #
# --------------------------------------------------------------------------- #
def test_get_accepted_content_types_orders_by_quality():
    factory = RequestFactory()
    request = factory.get("/", HTTP_ACCEPT="text/html;q=0.8,application/json;q=0.9")
    types = get_accepted_content_types(request)
    # The higher-quality type comes first.
    assert types[0] == "application/json"


def test_get_accepted_content_types_default():
    factory = RequestFactory()
    request = factory.get("/")
    assert "*/*" in get_accepted_content_types(request)


def test_instantiate_middleware_handles_classes_and_instances():
    class _MW:
        pass

    instance = _MW()
    out = list(instantiate_middleware([_MW, instance]))
    assert isinstance(out[0], _MW)  # class -> instantiated
    assert out[1] is instance  # instance -> passed through


def test_set_rollback_noop_outside_atomic():
    # Not in an atomic block / ATOMIC_REQUESTS off -> no error, no effect.
    set_rollback()


def test_http_error_carries_response():
    from django.http import HttpResponseBadRequest

    resp = HttpResponseBadRequest("boom")
    err = HttpError(resp)
    assert err.response is resp


def test_view_rejects_graphiql_and_batch_together():
    with pytest.raises(AssertionError):
        BaseGraphQLView(schema=_schema, graphiql=True, batch=True)


# --------------------------------------------------------------------------- #
# The base BaseGraphQLView.get_response (BaseGraphQLView overrides it)            #
# --------------------------------------------------------------------------- #
class BaseGraphQLViewTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_base_view_get_response_ok(self):
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/", {"query": "{ hello }"}, content_type="application/json"
        )
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    def test_base_view_errors_set_400(self):
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/", {"query": "{ nope }"}, content_type="application/json"
        )
        response = view(request)
        self.assertEqual(response.status_code, 400)
        self.assertIn("errors", json.loads(response.content))

    def test_base_view_batch(self):
        view = BaseGraphQLView.as_view(schema=_schema, batch=True)
        body = json.dumps([{"query": "{ hello }", "id": 1}])
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload[0]["id"], 1)
        self.assertEqual(payload[0]["status"], 200)

    def test_base_view_graphiql_renders_html(self):
        view = BaseGraphQLView.as_view(schema=_schema, graphiql=True)
        request = self.factory.get("/graphql/", HTTP_ACCEPT="text/html")
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])

    def test_base_view_get_mutation_rejected(self):
        view = BaseGraphQLView.as_view(schema=_schema)
        # A GET carrying a mutation is rejected with 405.
        request = self.factory.get("/graphql/", {"query": "mutation { __typename }"})
        response = view(request)
        self.assertEqual(response.status_code, 405)
