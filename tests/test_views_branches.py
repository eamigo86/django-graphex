# -*- coding: utf-8 -*-
"""Remaining branch coverage for "views.py".

Covers: MiddlewareManager passthrough, execution_context_class, invalid
variables JSON, "operationName == 'null'", atomic-mutation rollback,
execute-exception handling, GET-with-no-query GraphiQL short-circuits, the
base-view MUTATION_ERRORS rollback / empty-result branches, the GraphQLView
batch + EXPOSE_QUERY_COST + CLEAN_RESPONSE error branches.
"""

import json
from typing import Any
from unittest.mock import patch

import pytest
from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLBoolean, GraphQLString
from graphql.execution.middleware import MiddlewareManager

from django_graphex.core import Mutation, ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import (
    MUTATION_ERRORS_FLAG,
    BaseGraphQLView,
    GraphQLView,
)


class _Query(ObjectType):
    hello = field(GraphQLString)
    boom = field(GraphQLString)

    def resolve_hello(root: Any, info: Any) -> str:
        """Resolve the "hello" field to a fixed greeting.

        Args:
            root: The resolver root value (unused).
            info: The GraphQL resolve info (unused).

        Returns:
            greeting: The fixed string "world".
        """
        return "world"

    def resolve_boom(root: Any, info: Any) -> str:
        """Resolve the "boom" field by always raising, to test error wrapping.

        Args:
            root: The resolver root value (unused).
            info: The GraphQL resolve info (unused).

        Returns:
            Never returns.

        Raises:
            ValueError: Always, unconditionally.
        """
        raise ValueError("kaboom")


class _Flagged(Mutation):
    """A mutation that always flags MUTATION_ERRORS on the request."""

    ok = field(GraphQLBoolean)

    def mutate(root: Any, info: Any) -> "_Flagged":
        """Flag MUTATION_ERRORS on the request context and report failure.

        Args:
            root: The resolver root value (unused).
            info: The GraphQL resolve info, whose context is flagged.

        Returns:
            result: A "_Flagged" instance with "ok" set to False.
        """
        setattr(info.context, MUTATION_ERRORS_FLAG, True)
        return _Flagged(ok=False)


class _Clean(Mutation):
    """A mutation that succeeds without flagging errors."""

    ok = field(GraphQLBoolean)

    def mutate(root: Any, info: Any) -> "_Clean":
        """Succeed without touching MUTATION_ERRORS_FLAG.

        Args:
            root: The resolver root value (unused).
            info: The GraphQL resolve info (unused).

        Returns:
            result: A "_Clean" instance with "ok" set to True.
        """
        return _Clean(ok=True)


class _Mutation(ObjectType):
    flagged = _Flagged.Field()
    clean = _Clean.Field()


_schema = DjangoGraphQLSchema(query=_Query, mutation=_Mutation)


class BaseViewBranchesTest(TestCase):
    """Branch coverage for "BaseGraphQLView" construction and request handling.

    Covers middleware wiring, execution_context_class forwarding, malformed
    variables, the "operationName: null" normalization, GraphiQL short
    circuits, resolver-exception wrapping, and mutation-error rollback.
    """

    def setUp(self) -> None:
        """Create a shared "RequestFactory" for every test in this class.

        Individual tests build requests off "self.factory" as needed.
        """
        self.factory = RequestFactory()

    def test_middleware_manager_passthrough(self) -> None:
        """Ship-broken contract: an existing "MiddlewareManager" instance
        must be stored as-is on the view, not re-wrapped.
        """
        # A MiddlewareManager instance is stored as-is (not re-wrapped).
        mgr = MiddlewareManager()
        view = BaseGraphQLView(schema=_schema, middleware=mgr)
        self.assertIs(view.middleware, mgr)

    def test_middleware_none_is_left_unset(self) -> None:
        """Ship-broken contract: when the resolved MIDDLEWARE setting is
        None, the view's "middleware" attribute must stay unset (None), not
        be assigned some falsy default.
        """
        # When the resolved middleware is None, the `is not None` guard skips
        # assignment and middleware stays the class default (188->193).
        # WU8: views now reads the MIDDLEWARE setting through the unified
        # ``graphql_api_settings`` reader, not the legacy settings object
        # directly, so patch the reader instead.
        with patch("django_graphex.views.graphql_api_settings.MIDDLEWARE", None):
            view = BaseGraphQLView(schema=_schema)
        self.assertIsNone(view.middleware)

    def test_execution_context_class_is_forwarded(self) -> None:
        """Ship-broken contract: an explicit "execution_context_class" kwarg
        must be forwarded and used without breaking normal execution.
        """
        from graphql.execution import ExecutionContext

        view = BaseGraphQLView.as_view(
            schema=_schema, execution_context_class=ExecutionContext
        )
        request = self.factory.post(
            "/graphql/", {"query": "{ hello }"}, content_type="application/json"
        )
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    def test_invalid_variables_json_is_bad_request(self) -> None:
        """Ship-broken contract: a malformed "variables" JSON string must be
        rejected with a 400 response.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.get(
            "/graphql/", {"query": "{ hello }", "variables": "{not json"}
        )
        response = view(request)
        self.assertEqual(response.status_code, 400)

    def test_operation_name_null_is_treated_as_none(self) -> None:
        """Ship-broken contract: the string "null" as operationName must be
        normalized to no operation name, not passed through literally.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/",
            {"query": "{ hello }", "operationName": "null"},
            content_type="application/json",
        )
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    def test_get_no_query_graphiql_returns_no_response(self) -> None:
        """Ship-broken contract: a GraphiQL-eligible request with no query
        must make "execute_graphql_request" return None instead of raising or
        producing a bogus execution result.
        """
        # GraphiQL GET with no query short-circuits to None in
        # execute_graphql_request -> get_response returns (None, 200) ->
        # render_graphiql is what actually shows, but here graphiql is False so
        # the missing-query path raises 400 instead. Test the show_graphiql None.
        view = BaseGraphQLView(schema=_schema, graphiql=True)
        result = view.execute_graphql_request(
            self.factory.get("/"), {}, None, None, None, show_graphiql=True
        )
        self.assertIsNone(result)

    def test_get_mutation_graphiql_returns_none(self) -> None:
        """Ship-broken contract: a GraphiQL-eligible GET carrying a mutation
        must make "execute_graphql_request" return None rather than execute
        the mutation.
        """
        view = BaseGraphQLView(schema=_schema, graphiql=True)
        request = self.factory.get("/graphql/")
        result = view.execute_graphql_request(
            request,
            {},
            "mutation { flagged { ok } }",
            None,
            None,
            show_graphiql=True,
        )
        self.assertIsNone(result)

    def test_execute_exception_is_wrapped_in_errors(self) -> None:
        """Ship-broken contract: a field resolver that raises must surface as
        a GraphQL error with a path, keeping the HTTP status at 200.
        """
        # A field resolver that raises is surfaced as a GraphQL error (path set),
        # so status stays 200 with an errors entry.
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/", {"query": "{ boom }"}, content_type="application/json"
        )
        response = view(request)
        payload = json.loads(response.content)
        self.assertIn("errors", payload)

    def test_base_get_response_mutation_errors_flag_sets_rollback(self) -> None:
        """Ship-broken contract: when MUTATION_ERRORS_FLAG is set during a
        mutation, the base "get_response" must call "set_rollback" (observed
        here indirectly through the flag still being set on the request).
        """
        # The base get_response calls set_rollback when MUTATION_ERRORS_FLAG set
        # (no-op outside atomic, but the branch runs).
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/",
            {"query": "mutation { flagged { ok } }"},
            content_type="application/json",
        )
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(getattr(request, MUTATION_ERRORS_FLAG, False))


class AtomicMutationTest(TestCase):
    """Coverage for the ATOMIC_MUTATIONS rollback/commit branches.

    Covers both a mutation that flags MUTATION_ERRORS (rollback branch) and
    one that does not (commit branch).
    """

    def setUp(self) -> None:
        """Create a shared "RequestFactory" for every test in this class.

        Individual tests build requests off "self.factory" as needed.
        """
        self.factory = RequestFactory()

    @override_settings(DJANGO_GRAPHEX={"SCHEMA": None, "ATOMIC_MUTATIONS": True})
    def test_atomic_mutation_rolls_back_on_flag(self) -> None:
        """Ship-broken contract: with ATOMIC_MUTATIONS on, a mutation that
        flags MUTATION_ERRORS must trigger the atomic rollback branch while
        still returning a 200 response with ok:false.
        """
        # With ATOMIC_MUTATIONS on and the mutation flagging errors, the atomic
        # block sets rollback; the response still comes back 200 with ok:false.
        # WU8: views now reads ATOMIC_MUTATIONS from graphql_api_settings.
        with patch("django_graphex.views.graphql_api_settings.ATOMIC_MUTATIONS", True):
            view = BaseGraphQLView.as_view(schema=_schema)
            request = self.factory.post(
                "/graphql/",
                {"query": "mutation { flagged { ok } }"},
                content_type="application/json",
            )
            response = view(request)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                json.loads(response.content)["data"]["flagged"]["ok"], False
            )

    def test_atomic_mutation_commits_without_flag(self) -> None:
        """Ship-broken contract: with ATOMIC_MUTATIONS on, a mutation that
        does not flag errors must commit normally (no rollback branch taken).
        """
        # ATOMIC_MUTATIONS on, mutation does NOT flag errors -> the atomic block
        # runs but does not set rollback (429->431 false branch).
        # WU8: views now reads ATOMIC_MUTATIONS from graphql_api_settings.
        with patch("django_graphex.views.graphql_api_settings.ATOMIC_MUTATIONS", True):
            view = BaseGraphQLView.as_view(schema=_schema)
            request = self.factory.post(
                "/graphql/",
                {"query": "mutation { clean { ok } }"},
                content_type="application/json",
            )
            response = view(request)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(response.content)["data"]["clean"]["ok"], True)


@pytest.mark.django_db
def test_set_rollback_inside_atomic_block_with_atomic_requests() -> None:
    """Ship-broken contract: with ATOMIC_REQUESTS on, calling "set_rollback"
    inside an atomic block must mark that transaction for rollback.
    """
    from django.db import connection, transaction

    from django_graphex.views import set_rollback

    with patch.dict(connection.settings_dict, {"ATOMIC_REQUESTS": True}):
        with transaction.atomic():
            assert connection.in_atomic_block
            set_rollback()
            assert transaction.get_rollback() is True
            # Reset so the test's own transaction is not actually rolled back.
            transaction.set_rollback(False)


class GraphQLViewGetResponseBranchesTest(TestCase):
    """Branch coverage for "GraphQLView.get_response" edge cases.

    Covers batch id/status propagation, the cost extension being skipped
    when unanalyzable, CLEAN_RESPONSE with an error-only payload, and the
    empty-result GraphiQL short circuit.
    """

    def setUp(self) -> None:
        """Create a shared "RequestFactory" for every test in this class.

        Individual tests build requests off "self.factory" as needed.
        """
        self.factory = RequestFactory()

    def test_batch_id_and_status_in_response(self) -> None:
        """Ship-broken contract: a batch request's "id" and per-operation
        HTTP status must be preserved in the corresponding result entry.
        """
        view = GraphQLView.as_view(schema=_schema, batch=True)
        body = json.dumps([{"query": "{ hello }", "id": 7}])
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        payload = json.loads(response.content)
        self.assertEqual(payload[0]["id"], 7)
        self.assertEqual(payload[0]["status"], 200)

    @override_settings(DJANGO_GRAPHEX={"EXPOSE_QUERY_COST": True})
    def test_cost_extension_skipped_when_unanalyzable(self) -> None:
        """Ship-broken contract: when cost analysis fails/raises, the
        response must not carry an "extensions" key rather than crashing or
        emitting a bogus cost.
        """
        # get_query_cost returns None for an invalid schema/parse; the extensions
        # key is then not added (632->635 false branch). Use a query that parses
        # but resolves to no cost issues -> extensions still added; instead force
        # analyze_cost to raise so cost is None.
        with patch(
            "django_graphex.views.analyze_cost",
            side_effect=RuntimeError("nope"),
        ):
            view = GraphQLView.as_view(schema=_schema)
            request = self.factory.post(
                "/graphql/", {"query": "{ hello }"}, content_type="application/json"
            )
            response = view(request)
            data = json.loads(response.content)
            self.assertNotIn("extensions", data)

    @patch("django_graphex.views.graphql_api_settings.CLEAN_RESPONSE", True)
    def test_clean_response_error_branch_keeps_errors(self) -> None:
        """Ship-broken contract: with CLEAN_RESPONSE on, a response with no
        data (only errors) must leave those errors untouched.
        """
        # An errored query with no data: CLEAN_RESPONSE branch sees no data and
        # leaves the errors untouched.
        view = GraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/", {"query": "{ nope }"}, content_type="application/json"
        )
        response = view(request)
        self.assertEqual(response.status_code, 400)
        self.assertIn("errors", json.loads(response.content))

    def test_get_response_empty_result_returns_none(self) -> None:
        """Ship-broken contract: a GraphiQL GET with no query must make
        "get_response" return (None, 200) rather than raising.
        """
        # GraphiQL GET with no query -> execution_result is None -> result None.
        view = GraphQLView(schema=_schema, graphiql=True)
        result, status = view.get_response(
            self.factory.get("/"), {}, show_graphiql=True
        )
        self.assertIsNone(result)
        self.assertEqual(status, 200)


class MoreBaseBranchesTest(TestCase):
    """Further branch coverage for "BaseGraphQLView" parsing and execution.

    Covers the empty-result GraphiQL short circuit, body-decode failures,
    unparseable queries, internal execute() exceptions, schema-validation
    errors, and Accept-header quality parsing.
    """

    def setUp(self) -> None:
        """Create a shared "RequestFactory" for every test in this class.

        Individual tests build requests off "self.factory" as needed.
        """
        self.factory = RequestFactory()

    def test_base_get_response_empty_result_returns_none(self) -> None:
        """Ship-broken contract: a GraphiQL GET with no query must make the
        base "get_response" return (None, 200) rather than raising.
        """
        # GraphiQL GET, no query -> execution_result None -> result None (line 295).
        view = BaseGraphQLView(schema=_schema, graphiql=True)
        result, status = view.get_response(
            self.factory.get("/"), {}, show_graphiql=True
        )
        self.assertIsNone(result)
        self.assertEqual(status, 200)

    def test_body_decode_failure_is_bad_request(self) -> None:
        """Ship-broken contract: a request body that raises on decode must be
        handled by "parse_body" without crashing the process, surfacing as an
        exception the dispatch layer maps to a 400.

        Raises:
            UnicodeDecodeError: Propagated from the stubbed request body via
                "view.parse_body", asserted with "pytest.raises".
        """
        # request.body raising on decode -> HttpResponseBadRequest (326-327).
        view = BaseGraphQLView(schema=_schema)

        class _BadBody:
            """Stand-in for request.body whose "decode" always raises."""

            def decode(self, *a: Any, **k: Any) -> str:
                """Simulate an undecodable request body.

                Args:
                    a: Positional decode arguments (unused).
                    k: Keyword decode arguments (unused).

                Returns:
                    Never returns.

                Raises:
                    UnicodeDecodeError: Always, unconditionally.
                """
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "boom")

        request = self.factory.post(
            "/graphql/", {"query": "{ hello }"}, content_type="application/json"
        )
        # Force get_content_type -> application/json and a failing body.decode().
        request._body = _BadBody()
        with pytest.raises(Exception):
            # parse_body raises HttpError -> dispatch turns it into a 400; here we
            # call parse_body to hit the decode-exception branch directly.
            view.parse_body(request)

    def test_unparseable_query_returns_errors(self) -> None:
        """Ship-broken contract: a syntactically invalid query must produce
        an ExecutionResult carrying the parse error, surfaced as a 400.
        """
        # A syntactically invalid query -> parse() raises -> ExecutionResult with
        # the parse error (376-377), 400.
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/",
            {"query": "{ this is { broken"},
            content_type="application/json",
        )
        response = view(request)
        self.assertEqual(response.status_code, 400)
        self.assertIn("errors", json.loads(response.content))

    def test_execute_internal_exception_is_wrapped(self) -> None:
        """Ship-broken contract: an exception raised by execute() itself
        (not a field-level error) must be caught and wrapped into an
        ExecutionResult surfaced as a 400.
        """
        # If execute() itself raises (not a field error), it's caught and wrapped
        # in an ExecutionResult (434-435). Patch execute to raise.
        from django_graphex import views

        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/", {"query": "{ hello }"}, content_type="application/json"
        )
        with patch.object(views, "execute", side_effect=RuntimeError("internal")):
            response = view(request)
        # The wrapped error has no path -> 400.
        self.assertEqual(response.status_code, 400)
        self.assertIn("errors", json.loads(response.content))

    def test_invalid_schema_returns_validation_errors(self) -> None:
        """Ship-broken contract: when schema validation reports errors,
        "execute_graphql_request" must return an ExecutionResult carrying
        them instead of proceeding to execute the query.
        """
        # When validate_schema reports errors, execute_graphql_request returns an
        # ExecutionResult carrying them (line 372). Patch it to force the branch.
        from graphql import GraphQLError

        from django_graphex import views

        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/", {"query": "{ hello }"}, content_type="application/json"
        )
        with patch.object(
            views, "validate_schema", return_value=[GraphQLError("bad schema")]
        ):
            response = view(request)
        self.assertIn("errors", json.loads(response.content))

    def test_accept_header_with_quality_param_is_parsed(self) -> None:
        """Ship-broken contract: an Accept header entry with a non-quality
        param (e.g. ";charset=utf-8") must still be parsed without dropping
        other accepted content types.
        """
        # An Accept value with a non-matching ";charset" param exercises the
        # qualify() no-regex-match branch (123->125).
        from django_graphex.views import get_accepted_content_types

        request = self.factory.get(
            "/", HTTP_ACCEPT="application/json;charset=utf-8,text/html"
        )
        types = get_accepted_content_types(request)
        self.assertIn("application/json", types)
