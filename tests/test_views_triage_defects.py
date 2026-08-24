# -*- coding: utf-8 -*-
"""Regression tests for the six view-layer defects found by the 2.1 triage.

Each test pins ONE reported symptom so the defect cannot come back:

1. "cached_validate" keyed its per-schema sub-cache on "id(rules)", so a freed
   rules tuple whose address was reused served the PREVIOUS rule set's verdict.
2. The caching view scheduled the namespace version bump BEFORE running the
   mutation, so the "transaction.on_commit" deferral was inert and the counter
   advanced while the mutation body was still executing.
3. A batch view fed a non-JSON content type iterated whatever "parse_body"
   returned (a string / QueryDict) and raised "AttributeError" -> HTTP 500.
4. The response cache key ignored content negotiation, so a cached GraphiQL
   page was replayed to an "Accept: application/json" client.
5. "get_accepted_content_types" ignored a q-value written with a space after
   the semicolon ("; q=0.1"), which HTTP allows.
6. "extensions.cost" was computed against the FULL schema and attached even to
   a failed validation, turning the payload into a schema-existence oracle for
   a permission-pruned caller.
"""

import json
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import caches
from django.db import connection
from django.test import (
    RequestFactory,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from graphql import GraphQLBoolean, GraphQLError, GraphQLString, parse
from graphql.validation import ValidationRule
from graphql.validation.rules.fields_on_correct_type import FieldsOnCorrectTypeRule

from django_graphex import views as views_module
from django_graphex.core import Mutation, ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import (
    AuthenticatedGraphQLView,
    GraphQLView,
    get_accepted_content_types,
)

#: The Django permission gating the pruned field in the defect-6 schema.
_SECRET_PERM = "auth.view_permission"

#: Version-counter cache key for the anonymous identity partition.
_ANON_VERSION_KEY = "_graphql_cacheversion_anon"


class _Query(ObjectType):
    """Query root exposing a single constant field."""

    hello = field(GraphQLString)

    def resolve_hello(root: Any, info: Any) -> str:  # noqa: N805
        """Resolve the "hello" field to a constant greeting.

        Args:
            root: The unused parent resolver value.
            info: The GraphQL resolve info (unused).

        Returns:
            The literal string "hi".
        """
        return "hi"


_schema = DjangoGraphQLSchema(query=_Query)


class _BanHello(ValidationRule):
    """Validation rule that rejects any selection of the "hello" field."""

    def enter_field(self, node: Any, *args: Any) -> None:
        """Report an error when the visited field is named "hello".

        Args:
            node: The visited field AST node.
            *args: The remaining visitor arguments (unused).
        """
        if node.name.value == "hello":
            self.report_error(GraphQLError("Field 'hello' is banned.", node))


def test_validation_cache_is_not_keyed_on_the_rules_address() -> None:
    """A recycled rules-tuple address must not serve the previous verdict.

    CPython reuses the memory of a freed one-tuple for the next one-tuple, so a
    cache keyed on "id(rules)" hands a stricter rule set the permissive verdict
    computed for the rule set that used to live at that address.
    """
    document = parse("{ hello }")
    schema = _schema.graphql_schema

    for _ in range(200):
        views_module.clear_document_caches()
        permissive = (FieldsOnCorrectTypeRule,)
        address = id(permissive)
        assert (
            views_module.cached_validate(
                schema, "{ hello }", document, permissive, None
            )
            == ()
        )
        del permissive

        strict = (_BanHello,)
        if id(strict) != address:
            del strict
            continue

        errors = views_module.cached_validate(
            schema, "{ hello }", document, strict, None
        )
        assert errors, (
            "the recycled rules address served the previous (permissive) verdict "
            "— _BanHello never ran"
        )
        assert "banned" in errors[0].message
        return

    pytest.skip("this interpreter did not recycle the rules-tuple address")


def test_accept_header_honors_a_q_value_written_with_a_space() -> None:
    """Assert a spaced q-value ranks exactly like an unspaced one.

    HTTP allows whitespace after the semicolon, so a client that writes
    "text/html; q=0.1" must be served JSON just like one that writes
    "text/html;q=0.1".
    """
    spaced = RequestFactory().get(
        "/graphql/", HTTP_ACCEPT="text/html; q=0.1, application/json"
    )
    unspaced = RequestFactory().get(
        "/graphql/", HTTP_ACCEPT="text/html;q=0.1, application/json"
    )

    assert get_accepted_content_types(spaced) == get_accepted_content_types(unspaced)
    assert get_accepted_content_types(spaced) == ["application/json", "text/html"]
    assert GraphQLView.request_wants_html(spaced) is False


def test_batch_view_rejects_a_non_json_body_with_400() -> None:
    """Assert an "application/graphql" body on a batch endpoint yields 400.

    The body parses into a plain string, which the batch loop used to iterate
    into an "AttributeError" and an HTTP 500.
    """
    view = GraphQLView(schema=_schema, batch=True)
    request = RequestFactory().post(
        "/graphql/", "{ hello }", content_type="application/graphql"
    )

    response = view.dispatch(request)

    assert response.status_code == 400
    assert b"list" in response.content


def test_batch_view_rejects_a_form_encoded_body_with_400() -> None:
    """Assert a form-encoded body on a batch endpoint yields 400.

    The body parses into a "QueryDict", which the batch loop used to iterate
    into an "AttributeError" and an HTTP 500.
    """
    view = GraphQLView(schema=_schema, batch=True)
    request = RequestFactory().post("/graphql/", {"query": "{ hello }"})

    response = view.dispatch(request)

    assert response.status_code == 400
    assert b"list" in response.content


@override_settings(DJANGO_GRAPHEX={"CACHE_ACTIVE": True, "CACHE_TIMEOUT": 60})
class GraphiQLCacheIsolationTests(TestCase):
    """Pin the cache isolation between the GraphiQL page and the JSON answer.

    Both are produced by the same view for the same query, so a
    negotiation-blind cache key would let either one answer the other's client.
    """

    def setUp(self) -> None:
        """Start every test from an empty response cache.

        Cached entries survive between tests, so a stale slot would decide the
        outcome instead of the code under test.
        """
        caches["default"].clear()

    @staticmethod
    def _get(accept: str) -> Any:
        """Build an anonymous GET carrying the given "Accept" header.

        Args:
            accept: The value of the request's "Accept" header.

        Returns:
            The GET request for the shared "{ hello }" query.
        """
        request = RequestFactory().get(
            "/graphql/", {"query": "{ hello }"}, HTTP_ACCEPT=accept
        )
        request.user = AnonymousUser()
        return request

    def test_html_render_is_not_served_to_a_json_client(self) -> None:
        """Assert a warmed GraphiQL page does not poison the JSON answer.

        The browser request runs first, then the API client asks for the same
        query and must still receive JSON.
        """
        view = GraphQLView(schema=_schema, graphiql=True)

        html_response = view.dispatch(self._get("text/html"))
        self.assertEqual(html_response["Content-Type"], "text/html")

        json_response = view.dispatch(self._get("application/json"))
        self.assertIn("application/json", json_response["Content-Type"])
        self.assertEqual(json.loads(json_response.content), {"data": {"hello": "hi"}})

    def test_json_answer_is_not_served_to_a_browser(self) -> None:
        """Assert a warmed JSON answer does not replace the GraphiQL page.

        The reverse order of the previous test: the API client runs first, then
        the browser must still receive the GraphiQL page.
        """
        view = GraphQLView(schema=_schema, graphiql=True)

        json_response = view.dispatch(self._get("application/json"))
        self.assertIn("application/json", json_response["Content-Type"])

        html_response = view.dispatch(self._get("text/html"))
        self.assertEqual(html_response["Content-Type"], "text/html")
        self.assertIn(b"<!DOCTYPE html>", html_response.content)


#: Observations recorded from inside the mutation body by "_Bump.mutate".
_OBSERVED: dict[str, Any] = {}


class _Bump(Mutation):
    """No-op mutation that records the cache state seen from its own body."""

    class Arguments:
        """No arguments are accepted by this mutation."""

    ok = field(GraphQLBoolean)

    @classmethod
    def mutate(cls, root: Any, info: Any) -> "_Bump":
        """Record the in-flight transaction and version state, then succeed.

        Args:
            root: The unused parent resolver value.
            info: The GraphQL execution info for the current field.

        Returns:
            A new instance with "ok" set to True.
        """
        _OBSERVED["in_atomic_block"] = connection.in_atomic_block
        _OBSERVED["version"] = caches["default"].get(_ANON_VERSION_KEY)
        return cls(ok=True)


class _MutationRoot(ObjectType):
    """Mutation root exposing the observing mutation."""

    do_thing = _Bump.Field()


_mutation_schema = DjangoGraphQLSchema(query=_Query, mutation=_MutationRoot)


@override_settings(
    DJANGO_GRAPHEX={
        "CACHE_ACTIVE": True,
        "CACHE_TIMEOUT": 60,
        "ATOMIC_MUTATIONS": True,
    }
)
class MutationVersionBumpOrderingTests(TransactionTestCase):
    """Pin the ordering between the mutation and its cache-version bump.

    Uses "TransactionTestCase" so "transaction.on_commit" callbacks really fire;
    under "TestCase" the surrounding atomic block would swallow them and hide
    the defect.
    """

    @staticmethod
    def _post(query: str) -> Any:
        """Build an anonymous JSON POST for the given query.

        Args:
            query: The GraphQL document to send.

        Returns:
            The POST request carrying the query.
        """
        request = RequestFactory().post(
            "/graphql/",
            json.dumps({"query": query}),
            content_type="application/json",
        )
        request.user = AnonymousUser()
        return request

    def test_version_bump_happens_after_the_mutation_body(self) -> None:
        """Assert the version counter advances only after the mutation body.

        The mutation records the counter it sees from inside its own atomic
        block; a bump scheduled before the mutation would already be visible
        there, which is the #60a TOCTOU window.
        """
        caches["default"].clear()
        _OBSERVED.clear()
        view = GraphQLView(schema=_mutation_schema)

        view.dispatch(self._post("{ hello }"))
        seeded = caches["default"].get(_ANON_VERSION_KEY)
        self.assertEqual(int(seeded), 1)

        response = view.dispatch(self._post("mutation { doThing { ok } }"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(_OBSERVED["in_atomic_block"])
        self.assertEqual(
            int(_OBSERVED["version"]),
            1,
            "the version bump fired before the mutation body — the #60a TOCTOU "
            "window is still open",
        )
        self.assertEqual(int(caches["default"].get(_ANON_VERSION_KEY)), 2)


class _Book(ObjectType):
    """Object type reached only through the permission-gated field."""

    title = field(GraphQLString)


class _ScopedQuery(ObjectType):
    """Query root with one public field and one permission-gated field."""

    public = field(GraphQLString)
    secret = field(_Book, required_perms=[_SECRET_PERM])

    def resolve_public(root: Any, info: Any) -> str:  # noqa: N805
        """Resolve the "public" field, visible to every caller.

        Args:
            root: The unused parent resolver value.
            info: The GraphQL resolve info (unused).

        Returns:
            The literal string "public-data".
        """
        return "public-data"


_scoped_schema = DjangoGraphQLSchema(query=_ScopedQuery)


@override_settings(
    DJANGO_GRAPHEX={"PERMISSION_SCOPED_SCHEMA": True, "EXPOSE_QUERY_COST": True}
)
class QueryCostDisclosureTests(TestCase):
    """Pin the disclosure boundary of the "extensions.cost" payload.

    With "PERMISSION_SCOPED_SCHEMA" the caller is served a pruned schema, so the
    cost payload must not report on the fields that were pruned away.
    """

    def _post(self, query: str, user: Any) -> Any:
        """Dispatch a JSON POST for the given query as the given user.

        Args:
            query: The GraphQL document to send.
            user: The user attached to the request.

        Returns:
            The decoded JSON response body.
        """
        request = RequestFactory().post(
            "/graphql/", json.dumps({"query": query}), content_type="application/json"
        )
        request.user = user
        view = AuthenticatedGraphQLView(schema=_scoped_schema)
        return json.loads(view.dispatch(request).content)

    def test_cost_is_not_attached_to_a_failed_validation(self) -> None:
        """A pruned field and an unknown field must be indistinguishable.

        Apart from the field name each error message echoes back, the two
        responses have to carry exactly the same keys: a cost payload only the
        pruned-but-real field earns is a schema-existence oracle.
        """
        user = User.objects.create_user("cost-oracle")

        pruned = self._post("{ secret { title } }", user)
        unknown = self._post("{ nope { title } }", user)

        self.assertNotIn("extensions", pruned)
        self.assertNotIn("extensions", unknown)
        self.assertEqual(sorted(pruned), sorted(unknown))
        self.assertEqual(
            pruned["errors"][0]["message"].replace("'secret'", "'X'"),
            unknown["errors"][0]["message"].replace("'nope'", "'X'"),
        )

    def test_cost_is_still_reported_for_a_successful_query(self) -> None:
        """Assert a successful query still reports its cost.

        Guards the fix against over-reaching: only failed validations lose the
        payload.
        """
        user = User.objects.create_user("cost-happy")

        payload = self._post("{ public }", user)

        self.assertEqual(payload["data"], {"public": "public-data"})
        self.assertIn("cost", payload["extensions"])
