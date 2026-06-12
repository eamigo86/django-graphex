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
import uuid
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
from graphql.error import GraphQLError, GraphQLSyntaxError
from graphql.execution.middleware import MiddlewareManager
from graphql.validation import specified_rules, validate

from . import settings as _settings
from .cost import CostLimitValidationRule, analyze_cost
from .permissions import IsAuthenticated
from .settings import graphene_settings, graphql_api_settings
from .utils import clean_dict
from .validation import DepthLimitValidationRule

if TYPE_CHECKING:
    from django.http import HttpRequest

#: Request attribute set when a model mutation reported errors, so the
#: response can roll back an ATOMIC_MUTATIONS transaction.
MUTATION_ERRORS_FLAG = "graphene_mutation_has_errors"

#: Self-contained GraphiQL page (CDN). Avoids depending on graphene-django's
#: bundled template + static assets. Override per view with ``graphiql_template``.
#:
#: CDN asset versions are PINNED to specific patch versions and protected by
#: Subresource Integrity (SRI) hashes (sha384) so a CDN compromise or
#: unexpected version bump cannot inject malicious JavaScript into the
#: GraphiQL playground.
#:
#: Pinned versions (update SRI hashes when bumping):
#:   react          18.3.1
#:   react-dom      18.3.1
#:   graphiql       3.7.1
#:
#: To recompute hashes after a version bump:
#:   curl -sL <url> | openssl dgst -sha384 -binary | openssl base64 -A
#:   then prefix the output with "sha384-".
GRAPHIQL_HTML = """<!DOCTYPE html>
<html lang="en">
  <head>
    <title>GraphiQL</title>
    <style>body { height: 100%; margin: 0; width: 100%; overflow: hidden; }
      #graphiql { height: 100vh; }</style>
    <link
      rel="stylesheet"
      href="https://unpkg.com/graphiql@3.7.1/graphiql.min.css"
      integrity="sha384-Mq3vbRBY71jfjQAt/DcjxUIYY33ksal4cgdRt9U/hNPvHBCaT2JfJ/PTRiPKf0aM"
      crossorigin="anonymous"
    />
  </head>
  <body>
    <div id="graphiql">Loading...</div>
    <script
      crossorigin="anonymous"
      src="https://unpkg.com/react@18.3.1/umd/react.production.min.js"
      integrity="sha384-DGyLxAyjq0f9SPpVevD6IgztCFlnMF6oW/XQGmfe+IsZ8TqEiDrcHkMLKI6fiB/Z"
    ></script>
    <script
      crossorigin="anonymous"
      src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js"
      integrity="sha384-gTGxhz21lVGYNMcdJOyq01Edg0jhn/c22nsx0kyqP0TxaV5WVdsSH1fSDUf5YJj1"
    ></script>
    <script
      crossorigin="anonymous"
      src="https://unpkg.com/graphiql@3.7.1/graphiql.min.js"
      integrity="sha384-w0cGClNeNvIYIRVmYrv5kmQ6CEat8jJb0XBczOFPeWlVjzeMNJBaoeEcWFD8Gad4"
    ></script>
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
                max_batch = graphql_api_settings.MAX_BATCH_SIZE
                if max_batch is not None and len(data) > max_batch:
                    raise HttpError(
                        HttpResponseBadRequest(
                            self.json_encode(
                                request,
                                {
                                    "errors": [
                                        {
                                            "message": (
                                                f"Batch size {len(data)} exceeds the "
                                                f"MAX_BATCH_SIZE limit of {max_batch}. "
                                                "Reduce the number of operations per "
                                                "request or set MAX_BATCH_SIZE=None to "
                                                "disable the limit."
                                            )
                                        }
                                    ]
                                },
                            )
                        )
                    )
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
        document: Any = None,
    ) -> Any:
        """Validate and execute a GraphQL request, returning an ExecutionResult.

        Args:
            request: The incoming HTTP request.
            data: The parsed request body.
            query: The raw GraphQL query string.
            variables: The bound variable values.
            operation_name: The selected operation name, if any.
            show_graphiql: Whether the GraphiQL interface is being rendered.
            document: An already-parsed ``DocumentNode``.  When provided,
                ``parse()`` is not called again (avoids a double-parse per
                request).  Pass ``None`` (the default) to parse ``query``
                internally.
        """
        if not query:
            if show_graphiql:
                return None
            raise HttpError(HttpResponseBadRequest("Must provide query string."))

        schema = self.schema.graphql_schema

        schema_validation_errors = validate_schema(schema)
        if schema_validation_errors:
            return ExecutionResult(data=None, errors=schema_validation_errors)

        if document is None:
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

        Returns ``None`` when there is no query or when the query is
        syntactically invalid (a malformed document must not raise here;
        ``dispatch`` falls through to ``super_call`` which returns a 400).

        Args:
            request: The incoming HTTP request.

        Returns:
            The operation AST node, or None when there is no query or the
            query cannot be parsed.
        """
        data = self.parse_body(request)
        query = request.GET.get("query") or data.get("query")

        if not query:
            return None

        source = Source(query, name="GraphQL request")

        try:
            document_ast = parse(source)
        except GraphQLSyntaxError:
            return None

        operation_ast = get_operation_ast(document_ast, None)

        return operation_ast

    @staticmethod
    def fetch_cache_key(request: HttpRequest) -> str:
        """Return a hashed cache key built from the request body.

        Subclasses may override this staticmethod to derive the body hash
        differently (e.g. normalising whitespace or extracting the operation
        name). The returned value is composed into the full cache key by
        ``dispatch`` together with the identity prefix, so overrides do not
        need to incorporate user identity — that is handled automatically.
        """
        m = hashlib.sha256()
        m.update(request.body)

        return m.hexdigest()

    @staticmethod
    def cache_key_prefix(request: HttpRequest) -> str:
        """Return a stable per-identity token used to namespace cache keys.

        Authenticated requests are partitioned by ``request.user.pk``.
        Anonymous requests that carry an ``Authorization`` header are
        partitioned by a hash of that header so token-auth clients without a
        resolved ``request.user`` are still isolated from each other.
        Fully anonymous, credential-free requests share a single ``"anon"``
        partition (their responses contain no private data).

        Subclasses may override this staticmethod to use a different identity
        source (e.g. a session key or a tenant identifier).

        Args:
            request: The incoming HTTP request.

        Returns:
            A short string identifying the request's principal.
        """
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            return f"u{user.pk}"
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header:
            h = hashlib.sha256(auth_header.encode(), usedforsecurity=False).hexdigest()[
                :16
            ]
            return f"t{h}"
        return "anon"

    #: Sentinel used by ``dispatch`` to distinguish a cache miss from a cached
    #: falsy value (e.g. an empty-body response).  Using ``cache.get(key)``
    #: with a default of ``None`` and then checking ``if not response:`` would
    #: treat a legitimately cached empty response as a miss.
    _CACHE_MISS = object()

    #: Template for the per-identity namespace version counter cache key.
    #: ``{identity}`` is substituted with the value returned by
    #: ``cache_key_prefix``; this scopes invalidation to the issuing user's
    #: namespace only so that a mutation by user A does not flush user B's cache.
    _CACHE_VERSION_KEY_TEMPLATE = "_graphql_cacheversion_{identity}"

    def _get_cache_version(self, _cache: Any, identity: str) -> str:
        """Return the current namespace version token for *identity*.

        If no version exists yet, initialise it to a fresh UUID and persist it.

        Args:
            _cache: The Django cache backend instance.
            identity: The per-request identity token from ``cache_key_prefix``.

        Returns:
            The current version string (a UUID hex or an integer string).
        """
        version_key = self._CACHE_VERSION_KEY_TEMPLATE.format(identity=identity)
        version = _cache.get(version_key)
        if version is None:
            version = uuid.uuid4().hex
            _cache.set(version_key, version)
        return str(version)

    def _bump_cache_version(self, _cache: Any, identity: str) -> None:
        """Invalidate the issuing user's cached responses by advancing their version token.

        Uses ``cache.incr`` when available (atomic on Redis / Memcached) and
        falls back to setting a fresh UUID when the backend does not support
        atomic increment (e.g. Django's local-memory cache raises
        ``ValueError`` on a non-existent key).

        Only the requesting user's namespace is touched; other users' cache
        entries carry a different identity prefix and are not affected.

        Args:
            _cache: The Django cache backend instance.
            identity: The per-request identity token from ``cache_key_prefix``.
        """
        version_key = self._CACHE_VERSION_KEY_TEMPLATE.format(identity=identity)
        try:
            _cache.incr(version_key)
        except (ValueError, Exception):
            # Backend does not support incr (e.g. LocMemCache before the key
            # exists), or the key has already expired.  A fresh UUID ensures
            # old keys are no longer returned.
            _cache.set(version_key, uuid.uuid4().hex)

    def super_call(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        """Call the parent dispatch method."""
        response = super().dispatch(request, *args, **kwargs)

        return response

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        """Fetch queried data from GraphQL and return the cached response.

        When ``CACHE_ACTIVE`` is ``True``:

        * Cache keys are partitioned by user identity (see
          ``cache_key_prefix``) so one user's cached response is never served
          to another user.
        * Mutations advance a global namespace version counter instead of
          calling ``cache.clear()``, which would flush unrelated cache entries
          shared by other users or other cache clients.
        * A sentinel object detects cache misses so a legitimately cached
          falsy or empty body is not re-executed on every request.
        * A malformed GraphQL document (``GraphQLSyntaxError`` during
          ``get_operation_ast``) falls through to ``super_call``, which
          returns the appropriate HTTP 400 response.
        """
        if not graphql_api_settings.CACHE_ACTIVE:
            return self.super_call(request, *args, **kwargs)

        _cache = caches["default"]
        identity = self.cache_key_prefix(request)
        operation_ast = self.get_operation_ast(request)
        # ``operation`` is a graphql-core ``OperationType`` enum; compare its
        # ``.value`` string — a bare ``== "mutation"`` is always ``False``
        # because the enum instance is never equal to the plain string.
        operation = getattr(getattr(operation_ast, "operation", None), "value", None)
        if operation == "mutation":
            self._bump_cache_version(_cache, identity)
            return self.super_call(request, *args, **kwargs)

        version = self._get_cache_version(_cache, identity)
        cache_key = f"_graphql_{identity}_{version}_{self.fetch_cache_key(request)}"
        response = _cache.get(cache_key, self._CACHE_MISS)

        if response is self._CACHE_MISS:
            response = self.super_call(request, *args, **kwargs)
            _cache.set(cache_key, response, timeout=graphql_api_settings.CACHE_TIMEOUT)

        return response

    @classmethod
    def as_view(cls, *args: Any, **kwargs: Any) -> Any:
        """Create the view with CSRF exemption."""
        view = super().as_view(*args, **kwargs)
        view = csrf_exempt(view)
        return view

    @staticmethod
    def _is_introspection_document(document: Any) -> bool:
        """Return True when *document* is an introspection query.

        Detects introspection by inspecting the AST rather than matching the
        raw query string. A document is treated as introspection when ALL of
        its top-level selections are ``__schema`` or ``__type`` fields (the
        two standard introspection entry-points). This correctly handles any
        formatting, named or anonymous operations, and mixed inline fragments.

        Args:
            document: A parsed graphql-core ``DocumentNode``.

        Returns:
            ``True`` when every top-level selection is a meta-field
            (``__schema`` / ``__type``), ``False`` otherwise.
        """
        if document is None:
            return False
        from graphql.language.ast import FieldNode, OperationDefinitionNode

        for definition in document.definitions:
            if not isinstance(definition, OperationDefinitionNode):
                continue
            selections = getattr(
                getattr(definition, "selection_set", None), "selections", ()
            )
            if not selections:
                continue
            # If any top-level selection is NOT a meta-field, it's not introspection.
            for selection in selections:
                if isinstance(selection, FieldNode):
                    if selection.name.value not in ("__schema", "__type"):
                        return False
                # InlineFragment / FragmentSpread at top level are unusual; treat
                # conservatively (not pure introspection).
                else:
                    return False
            # All selections were meta-fields for this operation — it's introspection.
            return True
        return False

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

        # Parse the document once and reuse it for introspection detection,
        # query-cost reporting, AND execution — eliminating duplicate parses.
        parsed_document: Any = None
        if query:
            try:
                parsed_document = parse(query)
            except Exception:
                # Malformed query: pass document=None so execute_graphql_request
                # re-attempts and returns the proper error response.
                pass

        execution_result = self.execute_graphql_request(
            request,
            data,
            query,
            variables,
            operation_name,
            show_graphiql,
            document=parsed_document,
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

            # AST-based introspection detection: bypass clean_dict for queries
            # whose top-level selections are exclusively __schema / __type.
            # This is whitespace- and formatter-independent, unlike the previous
            # startswith("\n  query IntrospectionQuery") string match.
            if (
                graphql_api_settings.CLEAN_RESPONSE
                and not self._is_introspection_document(parsed_document)
            ):
                if response.get("data", None):
                    response["data"] = clean_dict(response["data"])

            if _settings.graphql_api_settings.EXPOSE_QUERY_COST and query:
                # Reuse the already-parsed document to avoid a second parse()
                # call. Fall back to string-based parsing only when
                # parsed_document is None (malformed query — cost is skipped).
                cost = self.get_query_cost(
                    query, variables, operation_name, document=parsed_document
                )
                if cost is not None:
                    response.setdefault("extensions", {})["cost"] = cost

            result = self.response_json_encode(request, response, pretty=show_graphiql)
        else:
            result = None

        return result, status_code

    def get_query_cost(
        self,
        query: str,
        variables: Any,
        operation_name: str | None,
        document: Any = None,
    ) -> dict[str, Any] | None:
        """Estimate the query's cost for the ``extensions.cost`` payload.

        Args:
            query: The raw GraphQL query string (used as fallback when
                *document* is ``None``).
            variables: The bound variable values (for exact page sizes).
            operation_name: The selected operation name, if any.
            document: An already-parsed ``DocumentNode``.  When provided,
                ``parse()`` is not called again (avoids a double-parse per
                request when ``EXPOSE_QUERY_COST`` is ``True``).

        Returns:
            A ``{"requestedCost": int, "maxCost": int | None}`` mapping, or
            ``None`` when the query can't be parsed/analyzed.
        """
        try:
            doc = document if document is not None else parse(query)
            report = analyze_cost(
                self.schema.graphql_schema,
                doc,
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
