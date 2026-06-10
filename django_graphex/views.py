"""GraphQL views: a vendored base view plus the enhanced and authenticated views.

- ``BaseGraphQLView`` — a self-contained fork of graphene-django's ``GraphQLView``
  (GET/POST, batch, variable parsing, schema/document validation, atomic
  mutations) so the package does not depend on the unmaintained ``graphene-django``.
  GraphiQL is served from a self-contained CDN page by default, overridable with a
  custom Django template via ``graphiql_template`` (for offline / strict-CSP setups).
- ``GraphQLView`` — adds response caching, query depth/cost validation rules and the
  ``extensions.cost`` payload.
- ``AuthenticatedGraphQLView`` — gates the whole endpoint behind the library's own
  permission classes (no DRF).

Reads the project's ``GRAPHENE`` Django setting (``SCHEMA``, ``MIDDLEWARE``,
``SUBSCRIPTION_PATH``, ``MAX_VALIDATION_ERRORS``, ``ATOMIC_MUTATIONS``) directly.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from django.core.cache import caches
from django.db import connection, transaction
from django.http import HttpResponse, HttpResponseNotAllowed
from django.http.response import HttpResponseBadRequest
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.generic import View
from graphene import Schema
from graphql import (
    ExecutionResult,
    OperationType,
    Source,
    execute,
    get_operation_ast,
    parse,
    validate_schema,
)
from graphql.error import GraphQLError
from graphql.execution.middleware import MiddlewareManager
from graphql.validation import specified_rules, validate

from . import settings as _settings
from ._graphene_settings import graphene_settings
from .cost import CostLimitValidationRule, analyze_cost
from .permissions import IsAuthenticated
from .settings import graphql_api_settings
from .utils import clean_dict
from .validation import DepthLimitValidationRule

if TYPE_CHECKING:
    from django.http import HttpRequest

#: Request attribute set when a model mutation reported errors, so the
#: response can roll back an ATOMIC_MUTATIONS transaction.
MUTATION_ERRORS_FLAG = "graphene_mutation_has_errors"

#: Self-contained GraphiQL page (CDN). Avoids depending on graphene-django's
#: bundled template + static assets. Override per view with ``graphiql_template``.
GRAPHIQL_HTML = """<!DOCTYPE html>
<html lang="en">
  <head>
    <title>GraphiQL</title>
    <style>body { height: 100%; margin: 0; width: 100%; overflow: hidden; }
      #graphiql { height: 100vh; }</style>
    <link rel="stylesheet" href="https://unpkg.com/graphiql@3/graphiql.min.css" />
  </head>
  <body>
    <div id="graphiql">Loading...</div>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
    <script crossorigin src="https://unpkg.com/graphiql@3/graphiql.min.js"></script>
    <script>
      const root = ReactDOM.createRoot(document.getElementById('graphiql'));
      const fetcher = GraphiQL.createFetcher({ url: window.location.pathname });
      root.render(React.createElement(GraphiQL, { fetcher }));
    </script>
  </body>
</html>"""


class HttpError(Exception):
    """Wrap an HTTP error response raised during request handling."""

    def __init__(
        self,
        response: HttpResponse,
        message: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Store the response and message.

        Args:
            response: The Django response to return.
            message: An optional explicit message; defaults to the response body.
            *args: Forwarded to ``Exception``.
            **kwargs: Forwarded to ``Exception``.
        """
        self.response = response
        self.message = message = message or response.content.decode()
        super().__init__(message, *args, **kwargs)


def get_accepted_content_types(request: Any) -> list[str]:
    """Return the request's accepted content types, most-preferred first."""

    def qualify(value: str) -> tuple[str, float]:
        parts = value.split(";", 1)
        if len(parts) == 2:
            match = re.match(r"(^|;)q=(0(\.\d{,3})?|1(\.0{,3})?)(;|$)", parts[1])
            if match:
                return parts[0].strip(), float(match.group(2))
        return parts[0].strip(), 1

    raw = request.META.get("HTTP_ACCEPT", "*/*").split(",")
    qualified = map(qualify, raw)
    return [x[0] for x in sorted(qualified, key=lambda x: x[1], reverse=True)]


def instantiate_middleware(middlewares: Any) -> Any:
    """Yield middleware instances, instantiating any classes."""
    for middleware in middlewares:
        if inspect.isclass(middleware):
            yield middleware()
            continue
        yield middleware


def set_rollback() -> None:
    """Roll back the current request transaction when atomic requests are on."""
    atomic_requests = connection.settings_dict.get("ATOMIC_REQUESTS", False)
    if atomic_requests and connection.in_atomic_block:
        transaction.set_rollback(True)


class BaseGraphQLView(View):
    """Django view that executes GraphQL queries (forked, graphene-django-free)."""

    graphiql = False
    #: Optional Django template name to render instead of the built-in CDN page
    #: (lets you ship your own assets for offline / strict-CSP setups).
    graphiql_template = None
    middleware = None
    root_value = None
    pretty = False
    batch = False
    schema = None
    subscription_path = None
    execution_context_class = None
    validation_rules = None

    def __init__(
        self,
        schema: Any = None,
        middleware: Any = None,
        root_value: Any = None,
        graphiql: bool = False,
        graphiql_template: str | None = None,
        pretty: bool = False,
        batch: bool = False,
        subscription_path: str | None = None,
        execution_context_class: Any = None,
        validation_rules: Any = None,
    ) -> None:
        """Configure the view, falling back to the ``GRAPHENE`` setting.

        Args mirror graphene-django's ``GraphQLView`` (plus ``graphiql_template``).
        """
        if not schema:
            schema = graphene_settings.SCHEMA

        if middleware is None:
            middleware = graphene_settings.MIDDLEWARE

        self.schema = schema or self.schema
        if middleware is not None:
            if isinstance(middleware, MiddlewareManager):
                self.middleware = middleware
            else:
                self.middleware = list(instantiate_middleware(middleware))
        self.root_value = root_value
        self.pretty = pretty or self.pretty
        self.graphiql = graphiql or self.graphiql
        self.graphiql_template = graphiql_template or self.graphiql_template
        self.batch = batch or self.batch
        self.execution_context_class = (
            execution_context_class or self.execution_context_class
        )
        if subscription_path is None:
            self.subscription_path = graphene_settings.SUBSCRIPTION_PATH
        else:
            self.subscription_path = subscription_path

        assert isinstance(self.schema, Schema), (
            "A Schema is required to be provided to GraphQLView."
        )
        assert not all((graphiql, batch)), "Use either graphiql or batch processing"
        self.validation_rules = validation_rules or self.validation_rules

    def get_root_value(self, request: Any) -> Any:
        """Return the root value passed to execution."""
        return self.root_value

    def get_middleware(self, request: Any) -> Any:
        """Return the middleware applied during execution."""
        return self.middleware

    def get_context(self, request: Any) -> Any:
        """Return the GraphQL context (the request)."""
        return request

    @method_decorator(ensure_csrf_cookie)
    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        """Handle a GraphQL GET/POST request (and GraphiQL/batch)."""
        try:
            if request.method.lower() not in ("get", "post"):
                raise HttpError(
                    HttpResponseNotAllowed(
                        ["GET", "POST"], "GraphQL only supports GET and POST requests."
                    )
                )

            data = self.parse_body(request)
            show_graphiql = self.graphiql and self.can_display_graphiql(request, data)

            if show_graphiql:
                return self.render_graphiql(request)

            if self.batch:
                responses = [self.get_response(request, entry) for entry in data]
                result = "[{}]".format(",".join(r[0] for r in responses))
                status_code = responses and max(responses, key=lambda r: r[1])[1] or 200
            else:
                result, status_code = self.get_response(request, data, show_graphiql)

            return HttpResponse(
                status=status_code, content=result, content_type="application/json"
            )
        except HttpError as e:
            response = e.response
            response["Content-Type"] = "application/json"
            response.content = self.json_encode(
                request, {"errors": [self.format_error(e)]}
            )
            return response

    def get_response(
        self, request: Any, data: Any, show_graphiql: bool = False
    ) -> tuple[Any, int]:
        """Execute a single request and return the encoded body and status."""
        query, variables, operation_name, id = self.get_graphql_params(request, data)

        execution_result = self.execute_graphql_request(
            request, data, query, variables, operation_name, show_graphiql
        )

        if getattr(request, MUTATION_ERRORS_FLAG, False) is True:
            set_rollback()

        status_code = 200
        if execution_result:
            response: dict[str, Any] = {}

            if execution_result.errors:
                set_rollback()
                response["errors"] = [
                    self.format_error(e) for e in execution_result.errors
                ]

            if execution_result.errors and any(
                not getattr(e, "path", None) for e in execution_result.errors
            ):
                status_code = 400
            else:
                response["data"] = execution_result.data

            if self.batch:
                response["id"] = id
                response["status"] = status_code

            result = self.json_encode(request, response, pretty=show_graphiql)
        else:
            result = None
        return result, status_code

    def render_graphiql(self, request: Any, **data: Any) -> HttpResponse:
        """Return the GraphiQL page (the CDN page, or a custom template if set)."""
        if self.graphiql_template:
            return render(
                request,
                self.graphiql_template,
                {
                    "endpoint": request.path,
                    "subscription_path": self.subscription_path,
                },
            )
        return HttpResponse(content=GRAPHIQL_HTML, content_type="text/html")

    def json_encode(self, request: Any, d: Any, pretty: bool = False) -> str:
        """Encode a response dict to JSON (compact unless pretty)."""
        if not (self.pretty or pretty) and not request.GET.get("pretty"):
            return json.dumps(d, separators=(",", ":"))
        return json.dumps(d, sort_keys=True, indent=2, separators=(",", ": "))

    def parse_body(self, request: Any) -> Any:
        """Parse the request body into a query data mapping."""
        content_type = self.get_content_type(request)

        if content_type == "application/graphql":
            return {"query": request.body.decode()}
        elif content_type == "application/json":
            try:
                body = request.body.decode("utf-8")
            except Exception as e:
                raise HttpError(HttpResponseBadRequest(str(e)))
            try:
                request_json = json.loads(body)
                if self.batch:
                    assert isinstance(request_json, list), (
                        "Batch requests should receive a list, but received {}."
                    ).format(repr(request_json))
                    assert len(request_json) > 0, (
                        "Received an empty list in the batch request."
                    )
                else:
                    assert isinstance(request_json, dict), (
                        "The received data is not a valid JSON query."
                    )
                return request_json
            except AssertionError as e:
                raise HttpError(HttpResponseBadRequest(str(e)))
            except (TypeError, ValueError):
                raise HttpError(HttpResponseBadRequest("POST body sent invalid JSON."))
        elif content_type in (
            "application/x-www-form-urlencoded",
            "multipart/form-data",
        ):
            return request.POST
        return {}

    def execute_graphql_request(
        self,
        request: Any,
        data: Any,
        query: Any,
        variables: Any,
        operation_name: Any,
        show_graphiql: bool = False,
    ) -> Any:
        """Validate and execute a GraphQL request, returning an ExecutionResult."""
        if not query:
            if show_graphiql:
                return None
            raise HttpError(HttpResponseBadRequest("Must provide query string."))

        schema = self.schema.graphql_schema

        schema_validation_errors = validate_schema(schema)
        if schema_validation_errors:
            return ExecutionResult(data=None, errors=schema_validation_errors)

        try:
            document = parse(query)
        except Exception as e:
            return ExecutionResult(errors=[e])

        operation_ast = get_operation_ast(document, operation_name)

        if (
            request.method.lower() == "get"
            and operation_ast is not None
            and operation_ast.operation != OperationType.QUERY
        ):
            if show_graphiql:
                return None
            raise HttpError(
                HttpResponseNotAllowed(
                    ["POST"],
                    "Can only perform a {} operation from a POST request.".format(
                        operation_ast.operation.value
                    ),
                )
            )

        validation_errors = validate(
            schema,
            document,
            self.validation_rules,
            graphene_settings.MAX_VALIDATION_ERRORS,
        )
        if validation_errors:
            return ExecutionResult(data=None, errors=validation_errors)

        try:
            execute_options = {
                "root_value": self.get_root_value(request),
                "context_value": self.get_context(request),
                "variable_values": variables,
                "operation_name": operation_name,
                "middleware": self.get_middleware(request),
            }
            if self.execution_context_class:
                execute_options["execution_context_class"] = (
                    self.execution_context_class
                )

            if (
                operation_ast is not None
                and operation_ast.operation == OperationType.MUTATION
                and (
                    graphene_settings.ATOMIC_MUTATIONS is True
                    or connection.settings_dict.get("ATOMIC_MUTATIONS", False) is True
                )
            ):
                with transaction.atomic():
                    result = execute(schema, document, **execute_options)
                    if getattr(request, MUTATION_ERRORS_FLAG, False) is True:
                        transaction.set_rollback(True)
                return result

            return execute(schema, document, **execute_options)
        except Exception as e:
            return ExecutionResult(errors=[e])

    @classmethod
    def can_display_graphiql(cls, request: Any, data: Any) -> bool:
        """Whether GraphiQL should be shown for this request."""
        raw = "raw" in request.GET or "raw" in data
        return not raw and cls.request_wants_html(request)

    @classmethod
    def request_wants_html(cls, request: Any) -> bool:
        """Whether the client prefers an HTML response."""
        accepted = get_accepted_content_types(request)
        length = len(accepted)
        html = length - accepted.index("text/html") if "text/html" in accepted else 0
        js = (
            length - accepted.index("application/json")
            if "application/json" in accepted
            else 0
        )
        return html > js

    @staticmethod
    def get_graphql_params(request: Any, data: Any) -> tuple[Any, Any, Any, Any]:
        """Extract query, variables, operation name and id from a request."""
        query = request.GET.get("query") or data.get("query")
        variables = request.GET.get("variables") or data.get("variables")
        id = request.GET.get("id") or data.get("id")

        if variables and isinstance(variables, str):
            try:
                variables = json.loads(variables)
            except Exception:
                raise HttpError(HttpResponseBadRequest("Variables are invalid JSON."))

        operation_name = request.GET.get("operationName") or data.get("operationName")
        if operation_name == "null":
            operation_name = None
        return query, variables, operation_name, id

    @staticmethod
    def format_error(error: Any) -> dict:
        """Format an error for the response ``errors`` list."""
        if isinstance(error, GraphQLError):
            return error.formatted
        return {"message": str(error)}

    @staticmethod
    def get_content_type(request: Any) -> str:
        """Return the request content type without parameters."""
        meta = request.META
        content_type = meta.get("CONTENT_TYPE", meta.get("HTTP_CONTENT_TYPE", ""))
        return content_type.split(";", 1)[0].lower()


class GraphQLView(BaseGraphQLView):
    """Enhanced GraphQL view: response caching + depth/cost rules + cost payload."""

    #: Standard validation plus query-depth limiting (`Meta.max_deep` /
    #: `MAX_QUERY_DEPTH`) and cost analysis (`Meta.complexity` / `MAX_QUERY_COST`).
    #: Both are no-ops until configured.
    validation_rules = (
        *specified_rules,
        DepthLimitValidationRule,
        CostLimitValidationRule,
    )

    def get_operation_ast(self, request: HttpRequest) -> Any:
        """Get the AST of the GraphQL operation from the request.

        Args:
            request: The incoming HTTP request.

        Returns:
            The operation AST node, or None when there is no query.
        """
        data = self.parse_body(request)
        query = request.GET.get("query") or data.get("query")

        if not query:
            return None

        source = Source(query, name="GraphQL request")

        document_ast = parse(source)
        operation_ast = get_operation_ast(document_ast, None)

        return operation_ast

    @staticmethod
    def fetch_cache_key(request: HttpRequest) -> str:
        """Return a hashed cache key built from the request body."""
        m = hashlib.sha256()
        m.update(request.body)

        return m.hexdigest()

    def super_call(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        """Call the parent dispatch method."""
        response = super().dispatch(request, *args, **kwargs)

        return response

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        """Fetch queried data from GraphQL and return the cached response."""
        if not graphql_api_settings.CACHE_ACTIVE:
            return self.super_call(request, *args, **kwargs)

        cache = caches["default"]
        operation_ast = self.get_operation_ast(request)
        # `operation` is a graphql-core ``OperationType`` enum, so compare its
        # value (a bare ``== "mutation"`` is always False and would skip the
        # cache invalidation, serving stale results after a mutation).
        operation = getattr(getattr(operation_ast, "operation", None), "value", None)
        if operation == "mutation":
            cache.clear()
            return self.super_call(request, *args, **kwargs)

        cache_key = f"_graplql_{self.fetch_cache_key(request)}"
        response = cache.get(cache_key)

        if not response:
            response = self.super_call(request, *args, **kwargs)

            # cache key and value
            cache.set(cache_key, response, timeout=graphql_api_settings.CACHE_TIMEOUT)

        return response

    @classmethod
    def as_view(cls, *args: Any, **kwargs: Any) -> Any:
        """Create the view with CSRF exemption."""
        view = super().as_view(*args, **kwargs)
        view = csrf_exempt(view)
        return view

    def get_response(
        self, request: HttpRequest, data: Any, show_graphiql: bool = False
    ) -> tuple[Any, int]:
        """Build the GraphQL response with error handling and data cleaning.

        Args:
            request: The incoming HTTP request.
            data: The parsed request body.
            show_graphiql: Whether the GraphiQL interface is being rendered.

        Returns:
            A pair of the encoded response (or None) and the HTTP status code.
        """
        query, variables, operation_name, id = self.get_graphql_params(request, data)

        execution_result = self.execute_graphql_request(
            request, data, query, variables, operation_name, show_graphiql
        )

        status_code = 200
        if execution_result:
            response: dict[str, Any] = {}

            if execution_result.errors:
                response["errors"] = [
                    self.format_error(e) for e in execution_result.errors
                ]

            if execution_result.errors and not execution_result.data:
                # If there are errors and no data, consider it invalid.
                status_code = 400
            else:
                response["data"] = execution_result.data

            if self.batch:
                response["id"] = id
                response["status"] = status_code

            if graphql_api_settings.CLEAN_RESPONSE and not (query or "").startswith(
                "\n  query IntrospectionQuery"
            ):
                if response.get("data", None):
                    response["data"] = clean_dict(response["data"])

            if _settings.graphql_api_settings.EXPOSE_QUERY_COST and query:
                cost = self.get_query_cost(query, variables, operation_name)
                if cost is not None:
                    response.setdefault("extensions", {})["cost"] = cost

            result = self.response_json_encode(request, response, pretty=show_graphiql)
        else:
            result = None

        return result, status_code

    def get_query_cost(
        self, query: str, variables: Any, operation_name: str | None
    ) -> dict[str, Any] | None:
        """Estimate the query's cost for the ``extensions.cost`` payload.

        Args:
            query: The raw GraphQL query string.
            variables: The bound variable values (for exact page sizes).
            operation_name: The selected operation name, if any.

        Returns:
            A ``{"requestedCost": int, "maxCost": int | None}`` mapping, or
            ``None`` when the query can't be parsed/analyzed.
        """
        try:
            report = analyze_cost(
                self.schema.graphql_schema,
                parse(query),
                operation_name,
                variables if isinstance(variables, dict) else None,
            )
        except Exception:
            return None
        return {"requestedCost": report.total, "maxCost": report.max_cost}

    def response_json_encode(
        self, request: HttpRequest, response: Any, pretty: bool
    ) -> str:
        """Encode the response to JSON."""
        return self.json_encode(request, response, pretty)


class AuthenticatedGraphQLView(GraphQLView):
    """Gate the whole endpoint behind the library's own permission classes (no DRF).

    A coarse, endpoint-level guard: every request must satisfy each permission in
    ``permission_classes`` (the same :class:`~django_graphex.permissions.
    BasePermission` subclasses used at the resolver level), evaluated against the
    request's user. For finer, per-field control use ``AuthenticatedFieldsMiddleware``
    / ``DjangoGraphQLSchema`` or a type's ``permission_classes`` instead.
    """

    #: Permission classes every request must satisfy (default: must be logged in).
    permission_classes = (IsAuthenticated,)

    def __init__(
        self, *args: Any, permission_classes: Any = None, **kwargs: Any
    ) -> None:
        """Accept ``permission_classes`` via ``as_view``/subclass, then configure."""
        super().__init__(*args, **kwargs)
        if permission_classes is not None:
            self.permission_classes = permission_classes

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        """Enforce ``permission_classes`` before handling the request."""
        info = SimpleNamespace(context=request)
        for permission in self.permission_classes:
            if not permission().has_permission(info, "view", None):
                return HttpResponse(
                    self.json_encode(
                        request,
                        {
                            "errors": [
                                {
                                    "message": "You do not have permission to "
                                    "access this endpoint."
                                }
                            ]
                        },
                    ),
                    status=403,
                    content_type="application/json",
                )
        return super().dispatch(request, *args, **kwargs)
