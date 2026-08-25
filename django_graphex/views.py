"""GraphQL views: a vendored base view plus the enhanced and authenticated views.

- "BaseGraphQLView" — a self-contained fork of graphene-django's "GraphQLView"
  (GET/POST, batch, variable parsing, schema/document validation, atomic
  mutations) so the package does not depend on the unmaintained "graphene-django".
  GraphiQL is served from a self-contained CDN page by default, overridable with a
  custom Django template via "graphiql_template" (for offline / strict-CSP setups).
- "GraphQLView" — adds response caching, query depth/cost validation rules and the
  "extensions.cost" payload.
- "AuthenticatedGraphQLView" — gates the whole endpoint behind the library's own
  permission classes (no DRF).

Reads the project's "DJANGO_GRAPHEX" Django setting ("SCHEMA", "MIDDLEWARE",
"SUBSCRIPTION_PATH", "MAX_VALIDATION_ERRORS", "ATOMIC_MUTATIONS") directly.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import threading
import weakref
from collections import OrderedDict
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from django.core.cache import caches
from django.db import connection, transaction
from django.http import HttpResponse, HttpResponseNotAllowed
from django.http.response import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.generic import View
from graphql import (
    ExecutionResult,
    OperationType,
    execute,
    get_operation_ast,
    parse,
    validate_schema,
)
from graphql.error import GraphQLError, GraphQLSyntaxError
from graphql.execution.middleware import MiddlewareManager
from graphql.validation import specified_rules, validate

from . import settings as _settings
from .core.permission_signature_cache import permission_signature, pruned_schema_for
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
    """Wrap an HTTP error response raised during request handling.

    Carries the Django response to return along with an optional message, so a
    handler can catch it and serialize the response into the GraphQL error
    envelope.
    """

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
            *args: Forwarded to "Exception".
            **kwargs: Forwarded to "Exception".
        """
        self.response = response
        self.message = message = message or response.content.decode()
        super().__init__(message, *args, **kwargs)


def get_accepted_content_types(request: Any) -> list[str]:
    """Return the request's accepted content types, most-preferred first.

    Parses the "Accept" header, honoring each entry's optional "q=" quality
    value, and orders the media types from highest to lowest preference. The
    quality value is read with or without whitespace after the semicolon
    ("text/html; q=0.1" and "text/html;q=0.1" are equivalent, as HTTP requires).

    Args:
        request: The incoming HTTP request whose "Accept" header is read.

    Returns:
        The accepted media types, most-preferred first.
    """

    def qualify(value: str) -> tuple[str, float]:
        parts = value.split(";", 1)
        if len(parts) == 2:
            # HTTP allows whitespace around the parameter separator, so
            # "text/html; q=0.1" must be read exactly like "text/html;q=0.1".
            match = re.match(
                r"(^|;)q=(0(\.\d{,3})?|1(\.0{,3})?)(;|$)", parts[1].strip()
            )
            if match:
                return parts[0].strip(), float(match.group(2))
        return parts[0].strip(), 1

    raw = request.META.get("HTTP_ACCEPT", "*/*").split(",")
    qualified = map(qualify, raw)
    return [x[0] for x in sorted(qualified, key=lambda x: x[1], reverse=True)]


def instantiate_middleware(middlewares: Any) -> Any:
    """Yield middleware instances, instantiating any classes.

    Class entries are instantiated with no arguments; already-instantiated
    entries are yielded unchanged.

    Args:
        middlewares: An iterable of middleware classes or instances.

    Returns:
        A generator yielding one middleware instance per input entry.
    """
    for middleware in middlewares:
        if inspect.isclass(middleware):
            yield middleware()
            continue
        yield middleware


def set_rollback() -> None:
    """Roll back the current request transaction when atomic requests are on.

    A no-op unless the connection has "ATOMIC_REQUESTS" enabled and is inside an
    atomic block; otherwise the request's transaction is marked for rollback.
    """
    atomic_requests = connection.settings_dict.get("ATOMIC_REQUESTS", False)
    if atomic_requests and connection.in_atomic_block:
        transaction.set_rollback(True)


# ---------------------------------------------------------------------------
# P3: bounded parse + validate document cache.
#
# graphql-core re-parses (~0.06-0.13 ms) and re-validates (~0.34-0.62 ms) the
# IDENTICAL document on EVERY request. Real APIs replay a small document set, so
# both are memoizable. Two independent bounded LRUs, both sized by the
# DOCUMENT_CACHE_MAXSIZE setting (0 disables BOTH):
#
#   * PARSE cache — global, keyed on the raw query string. The AST is immutable
#     and schema-independent, so a single DocumentNode is safe to share across
#     every request and every schema.
#   * VALIDATION cache — per-schema. Keyed by the schema OBJECT via a
#     WeakKeyDictionary so distinct (permission-pruned) GraphQLSchema objects
#     NEVER share a verdict: a query invalid on a pruned schema must never read a
#     full schema's cached "valid". Weakref keying also avoids the id() reuse
#     hazard (a GC'd schema drops its sub-cache instead of aliasing a new object
#     that happens to land on the same address). Each per-schema sub-cache is an
#     inner LRU bounded by the same maxsize; the pruned schemas are themselves
#     LRU-capped (PERMISSION_SCHEMA_CACHE_MAXSIZE ≤ 64), so total memory is
#     bounded by maxsize * (schemas ≤ 64).
#
# Thread-safety: an OrderedDict is not safe under concurrent mutation, so every
# read/write path takes a lock. The critical sections only touch the dict (no
# I/O), so contention is negligible.
# ---------------------------------------------------------------------------

#: Lock guarding the parse LRU.
_PARSE_CACHE_LOCK = threading.Lock()

#: Global parse LRU: query string -> DocumentNode (bounded by the setting).
_PARSE_CACHE: OrderedDict[str, Any] = OrderedDict()

#: Lock guarding the per-schema validation sub-caches (both the WeakKeyDictionary
#: and the inner OrderedDicts).
_VALIDATE_CACHE_LOCK = threading.Lock()

#: schema OBJECT -> inner LRU keyed by (query, rules token, max_errors) ->
#: tuple[GraphQLError, ...]. WeakKeyDictionary so a GC'd schema drops its verdicts.
_VALIDATE_CACHE: "weakref.WeakKeyDictionary[Any, OrderedDict[tuple, tuple]]" = (
    weakref.WeakKeyDictionary()
)


def _document_cache_maxsize() -> int:
    """Return the configured document-cache bound (0 disables both caches).

    Read per call (never memoized at import) so ``override_settings`` in tests —
    and a live settings reload — take effect immediately.
    """
    return int(graphql_api_settings.DOCUMENT_CACHE_MAXSIZE)


def _dynamic_limits_key() -> tuple:
    """Return the runtime limit inputs folded into the validation cache key.

    "GraphQLView"'s default validation rules include "DepthLimitValidationRule"
    and "CostLimitValidationRule", both of which read their limits from
    "graphql_api_settings" DYNAMICALLY at validation time rather than from the
    rules collection. If those values were not part of the cache key, a verdict
    computed under one limit would be served after the limit changes, silently
    bypassing the depth/cost guard until eviction or restart.

    Every setting that can flip a verdict is included:

    * "MAX_QUERY_DEPTH" — the depth budget.
    * "MAX_QUERY_COST" — the cost budget.
    * "MAX_PAGE_SIZE", "DEFAULT_PAGE_SIZE", "DEFAULT_LIST_MULTIPLIER",
      "COST_PAGINATION_ARGS" — inputs to the cost estimate itself (variables are
      unbound during validation, so page sizes come from these), which changes
      the "total" compared against "MAX_QUERY_COST".

    The key stays cheap: plain ints, "None", and a small tuple of argument names.

    Returns:
        A hashable tuple of the runtime limit inputs, in a stable order.
    """
    return (
        graphql_api_settings.MAX_QUERY_DEPTH,
        graphql_api_settings.MAX_QUERY_COST,
        graphql_api_settings.MAX_PAGE_SIZE,
        graphql_api_settings.DEFAULT_PAGE_SIZE,
        graphql_api_settings.DEFAULT_LIST_MULTIPLIER,
        tuple(graphql_api_settings.COST_PAGINATION_ARGS or ()),
    )


def _rules_key(rules: Any) -> Any:
    """Return a content token identifying a validation-rules collection.

    Each rule contributes its dotted "module.qualname" so the token depends on
    WHICH rules run, never on where the collection happens to live in memory.
    Order is preserved because it decides the order of the reported errors.

    Args:
        rules: The validation-rules collection passed to "validate" (None means
            graphql-core's default rules).

    Returns:
        None when "rules" is None, otherwise a tuple of one name per rule.
    """
    if rules is None:
        return None
    return tuple(
        f"{getattr(rule, '__module__', '')}.{rule.__qualname__}"
        if isinstance(rule, type)
        else repr(rule)
        for rule in rules
    )


def cached_parse(query: str) -> Any:
    """Return the parsed "DocumentNode" for the query, memoized in a bounded LRU.

    When the cache is disabled ("DOCUMENT_CACHE_MAXSIZE" == 0) this is a plain
    "parse(query)". A parse error propagates to the caller exactly as an
    uncached "parse" would — failures are NOT cached.

    The returned AST is immutable and shared across callers/schemas; it must not
    be mutated.

    Args:
        query: The raw GraphQL query string.

    Returns:
        The parsed "DocumentNode".
    """
    maxsize = _document_cache_maxsize()
    if maxsize <= 0:
        return parse(query)

    with _PARSE_CACHE_LOCK:
        cached = _PARSE_CACHE.get(query)
        if cached is not None:
            _PARSE_CACHE.move_to_end(query)
            return cached

    # Parse OUTSIDE the lock (tokenizing can be relatively expensive); a benign
    # duplicate parse under concurrency just overwrites with an equivalent AST.
    document = parse(query)

    with _PARSE_CACHE_LOCK:
        _PARSE_CACHE[query] = document
        _PARSE_CACHE.move_to_end(query)
        while len(_PARSE_CACHE) > maxsize:
            _PARSE_CACHE.popitem(last=False)
    return document


def cached_validate(
    schema: Any,
    query: str,
    document: Any,
    rules: Any,
    max_errors: Any,
) -> tuple:
    """Return the validation errors for the document against the schema, memoized.

    The verdict is keyed by the schema OBJECT (a per-schema sub-cache), the query
    string, a stable token of the rules, the max-errors cap, and the runtime
    depth/cost limits the bundled rules read dynamically (see
    "_dynamic_limits_key") — every input that can change the verdict. An empty
    tuple means "valid". The SAME "GraphQLError" objects are reused across cache
    hits, so "error.formatted" serializes identically to a fresh run.

    When the cache is disabled ("DOCUMENT_CACHE_MAXSIZE" == 0) this is a plain
    "validate(...)" returning a fresh tuple.

    Args:
        schema: The "GraphQLSchema" validated against (identity of the verdict).
        query: The raw query string (part of the sub-cache key).
        document: The parsed "DocumentNode" to validate.
        rules: The validation-rules collection passed to "validate".
        max_errors: The "MAX_VALIDATION_ERRORS" cap passed to "validate".

    Returns:
        A tuple of "GraphQLError" (empty tuple when the document is valid).
    """
    maxsize = _document_cache_maxsize()
    if maxsize <= 0:
        return tuple(validate(schema, document, rules, max_errors))

    # Rules identity: a CONTENT token (the dotted name of every rule, in order),
    # never id(rules). An address is only unique while the object is alive: a
    # per-request `validation_rules=` tuple is freed as soon as the request ends
    # and CPython hands the same address to the next tuple, so an id()-keyed
    # verdict computed under one rule set was served to a DIFFERENT one — a
    # stricter rule set silently never ran. Folding max_errors in keeps two
    # different caps from sharing a truncated verdict.
    #
    # The depth/cost rules read their limits from graphql_api_settings DYNAMICALLY
    # at validation time (not from `rules`), so those runtime values must be part
    # of the key too — otherwise a "valid" verdict computed under a permissive
    # limit would survive a limit tightening and silently bypass the guard until
    # eviction/restart. `_dynamic_limits_key` folds in every setting that can flip
    # a verdict (kept cheap: plain ints/None and a small tuple).
    key = (query, _rules_key(rules), max_errors, _dynamic_limits_key())

    with _VALIDATE_CACHE_LOCK:
        sub = _VALIDATE_CACHE.get(schema)
        if sub is not None:
            cached = sub.get(key)
            if cached is not None:
                sub.move_to_end(key)
                return cached

    # Validate OUTSIDE the lock; store the result as a tuple.
    errors = tuple(validate(schema, document, rules, max_errors))

    with _VALIDATE_CACHE_LOCK:
        sub = _VALIDATE_CACHE.get(schema)
        if sub is None:
            sub = OrderedDict()
            _VALIDATE_CACHE[schema] = sub
        sub[key] = errors
        sub.move_to_end(key)
        while len(sub) > maxsize:
            sub.popitem(last=False)
    return errors


def clear_document_caches() -> None:
    """Empty both document caches (parse + validation).

    Clears the global parse LRU and every per-schema validation sub-cache under
    their respective locks. Used by tests and by a live settings reload so a
    stale cached AST or verdict never survives a schema change.
    """
    with _PARSE_CACHE_LOCK:
        _PARSE_CACHE.clear()
    with _VALIDATE_CACHE_LOCK:
        _VALIDATE_CACHE.clear()


class BaseGraphQLView(View):
    """Django view that executes GraphQL queries (forked, graphene-django-free).

    A self-contained fork of graphene-django's "GraphQLView" covering GET/POST,
    batch requests, variable parsing, schema/document validation and atomic
    mutations, with GraphiQL served from a built-in CDN page. Reads its defaults
    from the "DJANGO_GRAPHEX" setting. Subclasses layer on caching, cost rules
    and endpoint-level authorization.
    """

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
        """Configure the view, reading defaults from the "DJANGO_GRAPHEX" setting.

        The arguments mirror the classic "GraphQLView" signature (plus
        "graphiql_template"). Any argument left at its default is filled from the
        setting or the class attribute.

        Args:
            schema: The schema to serve; falls back to the "SCHEMA" setting or
                the class attribute. Must expose a "graphql_schema".
            middleware: The GraphQL execution middleware (classes or instances,
                or a "MiddlewareManager"); falls back to the "MIDDLEWARE" setting.
            root_value: The root value passed to execution.
            graphiql: Whether to serve the GraphiQL interface.
            graphiql_template: An optional Django template name rendered instead
                of the built-in CDN page (for offline / strict-CSP setups).
            pretty: Whether to pretty-print JSON responses.
            batch: Whether to accept batched request lists.
            subscription_path: The advertised subscription endpoint path; falls
                back to the "SUBSCRIPTION_PATH" setting.
            execution_context_class: An optional custom execution context class.
            validation_rules: The validation-rules collection passed to
                "validate".

        Raises:
            AssertionError: When the schema does not expose "graphql_schema", or
                when both "graphiql" and "batch" are requested together.
        """
        if not schema:
            schema = graphql_api_settings.SCHEMA

        if middleware is None:
            middleware = graphql_api_settings.MIDDLEWARE

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
            self.subscription_path = graphql_api_settings.SUBSCRIPTION_PATH
        else:
            self.subscription_path = subscription_path

        # The view executes against ``self.schema.graphql_schema`` (the
        # graphql-core ``GraphQLSchema``). We therefore duck-type on that
        # attribute: a native ``DjangoGraphQLSchema`` exposes ``graphql_schema``
        # and must be accepted, and any schema object exposing it works too.
        assert hasattr(self.schema, "graphql_schema"), (
            "A Schema exposing `graphql_schema` is required to be provided to "
            "GraphQLView."
        )
        assert not all((graphiql, batch)), "Use either graphiql or batch processing"
        self.validation_rules = validation_rules or self.validation_rules

    def get_root_value(self, request: Any) -> Any:
        """Return the root value passed to execution.

        Args:
            request: The incoming HTTP request.

        Returns:
            The configured root value.
        """
        return self.root_value

    def get_middleware(self, request: Any) -> Any:
        """Return the middleware applied during execution.

        Args:
            request: The incoming HTTP request.

        Returns:
            The configured execution middleware.
        """
        return self.middleware

    def get_context(self, request: Any) -> Any:
        """Return the GraphQL context (the request).

        Args:
            request: The incoming HTTP request.

        Returns:
            The context value passed to execution (the request itself).
        """
        return request

    @method_decorator(ensure_csrf_cookie)
    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        """Handle a GraphQL GET/POST request (and GraphiQL/batch).

        Body-size guard: when "MAX_REQUEST_BODY_SIZE" is configured (not None)
        and the request body length exceeds the limit, the request is rejected
        with HTTP 413 (Content Too Large) BEFORE the JSON body is parsed. This is
        the primary memory-safety cap for base64 file uploads: the entire base64
        payload sits in the JSON body, so rejecting before "parse_body" prevents
        it from ever being allocated. The per-field decoded-size pre-check in
        "decode_base64_file" is a secondary guard.

        The guard uses a two-stage strategy:

        1. Fast-reject (O(1)): if "Content-Length" is present AND already exceeds
           "MAX_REQUEST_BODY_SIZE", reject immediately without reading the body —
           avoids buffering an honest large upload.
        2. Authoritative check: always verify "len(request.body) <= max_body"
           regardless of the "Content-Length" header. This prevents a client from
           spoofing a low "Content-Length" to bypass the guard.

        Args:
            request: The incoming HTTP request.
            *args: Extra positional arguments forwarded from the URL resolver.
            **kwargs: Extra keyword arguments forwarded from the URL resolver.

        Returns:
            The HTTP response (JSON payload, GraphiQL page, or an error
            response).

        Raises:
            HttpError: When the method is unsupported, the body exceeds
                "MAX_REQUEST_BODY_SIZE", or a batch endpoint receives a body that
                is not a list (any content type); caught internally and
                serialized into the GraphQL error envelope before the response is
                returned.
        """
        try:
            if request.method.lower() not in ("get", "post"):
                raise HttpError(
                    HttpResponseNotAllowed(
                        ["GET", "POST"], "GraphQL only supports GET and POST requests."
                    )
                )

            # Body-size guard: reject before JSON parsing when
            # MAX_REQUEST_BODY_SIZE is configured and the body exceeds it.
            #
            # Security note: Content-Length is a CLIENT-SUPPLIED header and
            # MUST NOT be trusted to pass the guard.  A spoofed low value
            # would let an oversized body bypass the check entirely.
            #
            # Two-stage strategy:
            #   1. Fast-reject: if Content-Length is present AND already
            #      exceeds the cap, reject immediately without reading the
            #      body (avoids buffering an honest large upload).
            #   2. Authoritative check: always verify len(request.body) ≤
            #      max_body.  This catches spoofed-low / absent / garbage
            #      Content-Length values.
            #
            # Accessing request.body here is safe: dispatch runs before
            # parse_body, so the stream has not been consumed yet.  Django
            # caches the result in request._body on first access.  If the
            # body is so large that Django itself raises RequestDataTooBig /
            # SuspiciousOperation (DATA_UPLOAD_MAX_MEMORY_SIZE), that
            # exception surfaces as Django's own 400 response — we do not
            # mask it, but we also do not let the guard 500 on it.
            max_body = graphql_api_settings.MAX_REQUEST_BODY_SIZE
            if max_body is not None and request.method.lower() == "post":
                from django.http import HttpResponse as _HR

                # --- Stage 1: fast-reject on honest oversized Content-Length ---
                content_length_str = request.META.get("CONTENT_LENGTH", "")
                try:
                    declared_length = int(content_length_str)
                except (ValueError, TypeError):
                    declared_length = None

                if declared_length is not None and declared_length > max_body:
                    raise HttpError(
                        _HR(status=413),
                        message=(
                            f"Request body ({declared_length} bytes) exceeds the "
                            f"MAX_REQUEST_BODY_SIZE limit of {max_body} bytes. "
                            "Split the request or increase the limit."
                        ),
                    )

                # --- Stage 2: authoritative check on the actual body length ---
                # This ALWAYS runs so that a spoofed-low / absent / garbage
                # Content-Length cannot bypass the guard. If reading the body
                # raises Django's RequestDataTooBig / SuspiciousOperation, that
                # propagates as Django's own response (we neither mask it nor
                # 500 on it).
                actual_length = len(request.body)
                if actual_length > max_body:
                    raise HttpError(
                        _HR(status=413),
                        message=(
                            f"Request body ({actual_length} bytes) exceeds the "
                            f"MAX_REQUEST_BODY_SIZE limit of {max_body} bytes. "
                            "Split the request or increase the limit."
                        ),
                    )

            data = self.parse_body(request)
            show_graphiql = self.graphiql and self.can_display_graphiql(request, data)

            if show_graphiql:
                return self.render_graphiql(request)

            if self.batch:
                # "parse_body" only list-checks an application/json body; every
                # other content type yields a string or a QueryDict, which the
                # loop below would iterate into an AttributeError (HTTP 500).
                # Reject any non-list body here — the single point every batch
                # request routes through, whatever its content type.
                if not isinstance(data, list):
                    raise HttpError(
                        HttpResponseBadRequest(),
                        message=(
                            "Batch requests should receive a list, but received {}.".format(
                                repr(data)
                            )
                        ),
                    )
                max_batch = graphql_api_settings.MAX_BATCH_SIZE
                if max_batch is not None and len(data) > max_batch:
                    # Pass `message=` explicitly so the `except HttpError` handler
                    # wraps the plain string — not a pre-encoded JSON body — into the
                    # single outer {"errors":[{"message":"..."}]} envelope.
                    raise HttpError(
                        HttpResponseBadRequest(),
                        message=(
                            f"Batch size {len(data)} exceeds the "
                            f"MAX_BATCH_SIZE limit of {max_batch}. "
                            "Reduce the number of operations per "
                            "request or set MAX_BATCH_SIZE=None to "
                            "disable the limit."
                        ),
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
        """Execute a single request and return the encoded body and status.

        Args:
            request: The incoming HTTP request.
            data: The parsed request body.
            show_graphiql: Whether the GraphiQL interface is being rendered.

        Returns:
            A pair of the encoded response body (or None) and the HTTP status
            code.
        """
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
        """Return the GraphiQL page (the CDN page, or a custom template if set).

        Args:
            request: The incoming HTTP request.
            **data: Extra template context (unused by the built-in CDN page).

        Returns:
            The rendered GraphiQL HTTP response.
        """
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
        """Encode a response dict to JSON (compact unless pretty).

        Pretty output (sorted keys, two-space indent) is used when the view is
        pretty, the caller passes "pretty=True", or the request carries a
        "pretty" query parameter; otherwise the output is compact.

        Args:
            request: The incoming HTTP request (its "pretty" GET param is read).
            d: The response mapping to encode.
            pretty: Whether to force pretty-printed output.

        Returns:
            The JSON-encoded string.
        """
        if not (self.pretty or pretty) and not request.GET.get("pretty"):
            return json.dumps(d, separators=(",", ":"))
        return json.dumps(d, sort_keys=True, indent=2, separators=(",", ": "))

    def parse_body(self, request: Any) -> Any:
        """Parse the request body into a query data mapping.

        Dispatches on the content type: "application/graphql" yields a
        "{'query': ...}" dict, "application/json" is decoded and (for batch
        views) required to be a non-empty list, form-encoded/multipart bodies
        return "request.POST", and any other type yields an empty dict.

        Args:
            request: The incoming HTTP request.

        Returns:
            The parsed request data (a mapping, or a list for batch requests).

        Raises:
            HttpError: When the body is not valid JSON, or when a batch view
                receives a non-list or empty-list body.
        """
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
                    if not isinstance(request_json, list):
                        raise HttpError(
                            HttpResponseBadRequest(),
                            message=(
                                "Batch requests should receive a list, but received {}.".format(
                                    repr(request_json)
                                )
                            ),
                        )
                    if len(request_json) == 0:
                        raise HttpError(
                            HttpResponseBadRequest(),
                            message="Received an empty list in the batch request.",
                        )
                else:
                    if not isinstance(request_json, dict):
                        raise HttpError(
                            HttpResponseBadRequest(),
                            message="The received data is not a valid JSON query.",
                        )
                return request_json
            except (TypeError, ValueError):
                raise HttpError(HttpResponseBadRequest("POST body sent invalid JSON."))
        elif content_type in (
            "application/x-www-form-urlencoded",
            "multipart/form-data",
        ):
            return request.POST
        return {}

    def _graphql_schema_for(self, request: Any) -> Any:
        """Return the graphql-core schema this request validates/executes against.

        The base view always serves the FULL configured schema. Subclasses may
        override this single choke point to select a per-request schema (both
        ``validate`` and ``execute`` read the value it returns).

        Args:
            request: The incoming HTTP request.

        Returns:
            The ``GraphQLSchema`` to validate and execute against.
        """
        return self.schema.graphql_schema

    def _cache_key_signature(self, request: Any) -> str:
        """Return the per-request segment folded into the response-cache key.

        The base view returns the empty string, so its cache key is unchanged
        (identity + version + body hash). Subclasses that serve a per-request
        schema (see :meth:`_graphql_schema_for`) override this to return a token
        that varies with the served schema — otherwise two callers who share an
        identity partition but see DIFFERENT schemas could read each other's
        cached response bodies. An empty return keeps the key byte-identical.

        Args:
            request: The incoming HTTP request.

        Returns:
            A cache-key segment (empty on the base view).
        """
        return ""

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
            document: An already-parsed "DocumentNode". When provided, "parse()"
                is not called again (avoids a double-parse per request). Pass
                None (the default) to parse the query internally.

        Returns:
            The "ExecutionResult", or None when there is no query and GraphiQL is
            being rendered.

        Raises:
            HttpError: When no query is provided (and GraphiQL is not shown), or
                when a non-query operation is attempted over GET.
        """
        if not query:
            if show_graphiql:
                return None
            raise HttpError(HttpResponseBadRequest("Must provide query string."))

        schema = self._graphql_schema_for(request)

        schema_validation_errors = validate_schema(schema)
        if schema_validation_errors:
            return ExecutionResult(data=None, errors=schema_validation_errors)

        if document is None:
            try:
                document = cached_parse(query)
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

        validation_errors = cached_validate(
            schema,
            query,
            document,
            self.validation_rules,
            graphql_api_settings.MAX_VALIDATION_ERRORS,
        )
        if validation_errors:
            return ExecutionResult(data=None, errors=list(validation_errors))

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
                    graphql_api_settings.ATOMIC_MUTATIONS is True
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
        """Return whether GraphiQL should be shown for this request.

        GraphiQL is shown only when the request does not opt out with a "raw"
        flag and the client prefers HTML over JSON.

        Args:
            request: The incoming HTTP request.
            data: The parsed request body.

        Returns:
            True when the GraphiQL interface should be rendered.
        """
        raw = "raw" in request.GET or "raw" in data
        return not raw and cls.request_wants_html(request)

    @classmethod
    def request_wants_html(cls, request: Any) -> bool:
        """Return whether the client prefers an HTML response.

        Compares the "Accept" header preference of "text/html" against
        "application/json".

        Args:
            request: The incoming HTTP request.

        Returns:
            True when HTML is preferred over JSON.
        """
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
        """Extract query, variables, operation name and id from a request.

        Values come from the query string when present, otherwise from the
        parsed body. A string "variables" value is JSON-decoded, and a literal
        "null" operation name is normalized to None.

        Args:
            request: The incoming HTTP request.
            data: The parsed request body.

        Returns:
            A "(query, variables, operation_name, id)" tuple.

        Raises:
            HttpError: When the "variables" value is a string that is not valid
                JSON.
        """
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
        """Format an error for the response "errors" list.

        A "GraphQLError" is serialized via its "formatted" mapping; any other
        exception is wrapped as a "{'message': str(error)}" entry.

        Args:
            error: The error (or exception) to format.

        Returns:
            The error mapping suitable for the response "errors" list.
        """
        if isinstance(error, GraphQLError):
            return error.formatted
        return {"message": str(error)}

    @staticmethod
    def get_content_type(request: Any) -> str:
        """Return the request content type without parameters.

        Reads "CONTENT_TYPE" (falling back to "HTTP_CONTENT_TYPE"), strips any
        trailing parameters (e.g. "; charset=utf-8") and lower-cases the result.

        Args:
            request: The incoming HTTP request.

        Returns:
            The bare, lower-cased content type (empty string when absent).
        """
        meta = request.META
        content_type = meta.get("CONTENT_TYPE", meta.get("HTTP_CONTENT_TYPE", ""))
        return content_type.split(";", 1)[0].lower()


class GraphQLView(BaseGraphQLView):
    """Enhanced GraphQL view: response caching + depth/cost rules + cost payload.

    Extends the base view with per-request response caching (partitioned by
    caller identity), the depth-limit and cost-limit validation rules, and an
    optional "extensions.cost" payload. Each addition is inert until its
    corresponding "DJANGO_GRAPHEX" setting is configured.
    """

    #: Standard validation plus query-depth limiting ("Meta.max_depth" /
    #: "MAX_QUERY_DEPTH") and cost analysis ("Meta.complexity" / "MAX_QUERY_COST").
    #: Both are no-ops until configured.
    validation_rules = (
        *specified_rules,
        DepthLimitValidationRule,
        CostLimitValidationRule,
    )

    def get_operation_ast(self, request: HttpRequest) -> Any:
        """Get the AST of the GraphQL operation from the request.

        Returns None when there is no query, when the query is syntactically
        invalid (a malformed document must not raise here; "dispatch" falls
        through to "super_call" which returns a 400), or when the document
        declares several operations and the request does not name one — the
        caller must then treat the operation as undeterminable.

        The operation name is read through "get_graphql_params", the same
        helper the execution path uses, so the operation classified here is the
        operation actually executed. Passing None instead would make
        graphql-core give up on ANY multi-operation document.

        Args:
            request: The incoming HTTP request.

        Returns:
            The operation AST node, or None when there is no query, the query
            cannot be parsed, or the operation cannot be determined.

        Raises:
            HttpError: When the body or the "variables" parameter is malformed.
        """
        data = self.parse_body(request)
        query = request.GET.get("query") or data.get("query")

        if not query:
            return None

        try:
            # Reuse the shared parse cache (keyed on the query string) so the
            # CACHE_ACTIVE path does not double-parse: get_response and
            # execute_graphql_request read the same cached DocumentNode. The
            # immutable AST is identical to parsing a Source(query); only error
            # location labels would differ, and a syntax error is swallowed here.
            document_ast = cached_parse(query)
        except GraphQLSyntaxError:
            return None

        _, _, operation_name, _ = self.get_graphql_params(request, data)
        operation_ast = get_operation_ast(document_ast, operation_name)

        return operation_ast

    @staticmethod
    def fetch_cache_key(request: HttpRequest) -> str:
        """Return a hashed cache key built from the request body and GET params.

        For POST requests the GraphQL payload lives in "request.body", which is
        hashed directly. For GET requests "request.body" is always empty, so the
        query, variables, and operationName query-string parameters are
        incorporated into the hash instead. Without this, every distinct GET
        query for the same identity would produce the empty-body hash and share a
        single cache slot — causing a different query's cached response to be
        returned.

        Subclasses may override this staticmethod to derive the body hash
        differently (e.g. normalising whitespace or extracting the operation
        name). The returned value is composed into the full cache key by
        "dispatch" together with the identity prefix, so overrides do not need to
        incorporate user identity — that is handled automatically.

        Args:
            request: The incoming HTTP request.

        Returns:
            The hex-encoded SHA-256 digest used as the body segment of the cache
            key.
        """
        m = hashlib.sha256()
        m.update(request.body)
        # For GET requests, request.body is b'' — incorporate the GraphQL
        # query-string parameters so different GET queries get distinct keys.
        get_query = request.GET.get("query") or ""
        get_variables = request.GET.get("variables") or ""
        get_operation = request.GET.get("operationName") or ""
        if get_query or get_variables or get_operation:
            m.update(get_query.encode())
            m.update(get_variables.encode())
            m.update(get_operation.encode())

        return m.hexdigest()

    @staticmethod
    def cache_key_prefix(request: HttpRequest) -> str:
        """Return a stable per-identity token used to namespace cache keys.

        Authenticated requests are partitioned by "request.user.pk".
        Anonymous requests that carry an "Authorization" header are partitioned
        by a hash of that header so token-auth clients without a resolved
        "request.user" are still isolated from each other. Fully anonymous,
        credential-free requests share a single "anon" partition (their responses
        contain no private data).

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

        If no version exists yet, initialise it to ``1`` (integer) and persist
        it with ``timeout=None`` (never expires independently of its response
        entries).  Seeding with an integer — rather than a UUID hex string —
        ensures that ``cache.incr`` works atomically on all standard backends
        (Redis, Memcached, LocMemCache) without first deleting and re-setting
        the key.

        The initial value is ``1`` (not ``0``) so the first bump goes to ``2``,
        ensuring that version ``0`` is never used as a live cache key (closes the
        ambiguous zero-state described in issue #60c).

        The key is stored with ``timeout=None`` (permanent) to prevent the
        version counter from expiring before its associated response entries when
        ``CACHE_TIMEOUT`` exceeds the backend's own default TTL (issue #60b).

        Args:
            _cache: The Django cache backend instance.
            identity: The per-request identity token from ``cache_key_prefix``.

        Returns:
            The current version as a string (``"1"``, ``"2"``, …).  Integer
            versions stringify fine and compose cleanly into the cache key.
        """
        version_key = self._CACHE_VERSION_KEY_TEMPLATE.format(identity=identity)
        version = _cache.get(version_key)
        if version is None:
            # Seed to 1 (not 0) so the first bump reaches 2 and version 0 is
            # never used as a live cache key.  timeout=None: the counter never
            # expires independently (fixes TTL-skew when CACHE_TIMEOUT > backend
            # default).
            version = 1
            _cache.set(version_key, version, timeout=None)
        return str(version)

    def _bump_cache_version(self, _cache: Any, identity: str) -> None:
        """Invalidate the issuing user's cached responses by advancing their version token.

        Callers MUST invoke this AFTER the mutation has been executed (see
        ``dispatch``): scheduling it beforehand made the deferral below inert,
        because ``ATOMIC_MUTATIONS`` opens its atomic block inside
        ``execute_graphql_request`` — later than this call — so ``on_commit``
        found no open transaction and ran the bump immediately.

        The bump is deferred via ``transaction.on_commit`` so it only fires once
        the mutation's database write is durable.  This eliminates the
        bump-before-commit TOCTOU window (issue #60a) where a concurrent query
        could cache pre-mutation data at the new version key.  If the surrounding
        transaction is rolled back, ``on_commit`` is never invoked, so a failed
        mutation does not advance the counter.  When there is no open transaction
        (``ATOMIC_MUTATIONS`` is off) Django executes ``on_commit`` immediately
        after the current statement — behaviour is unchanged for that case.

        Residual microsecond window (audit rank 10 — ACCEPTABLE).  There is a
        tiny gap between the moment ``on_commit`` is SCHEDULED (here) and the
        moment it actually FIRES (right after the DB commit).  A concurrent reader
        that commits and reads in that sub-millisecond window could momentarily
        miss the bumped version.  This is correctness-SAFE: the data is already
        durable, and a stale version key only causes a cache MISS that re-reads the
        (now-current) data from the database — never a stale-but-cached read.  The
        invalidation always converges; at worst one request pays a cache miss.  A
        very-high-concurrency deployment that wants to close even this microsecond
        window can add a cross-process barrier (e.g. a short read-side version
        re-check or a distributed lock) around the read path — not needed for
        correctness, only to shave the rare extra miss.

        Uses ``cache.incr`` for an atomic increment on Redis / Memcached /
        LocMemCache.  Because the key is seeded with integer ``1`` by
        ``_get_cache_version``, ``incr`` always finds an integer value and
        succeeds on all standard backends.  Two recoverable failure modes are
        caught and healed by resetting the key to integer ``1`` (not ``0``) so
        the next bump never produces the ambiguous zero-state (issue #60c):

        * ``ValueError`` — the key has expired (Django's documented behaviour
          for a missing key on all standard backends).
        * ``TypeError`` — the key exists but holds a non-integer value (e.g. a
          uuid-hex string from an older deploy).  LocMemCache raises
          ``TypeError`` in this case; healing it to ``1`` lets the next incr
          succeed on every backend.

        The heal value is stored with ``timeout=None`` to match the seed policy
        in ``_get_cache_version`` (issue #60b).

        Truly unexpected backend errors (e.g. connection failure) are not
        suppressed and propagate normally.

        Only the requesting user's namespace is touched; other users' cache
        entries carry a different identity prefix and are not affected.

        Args:
            _cache: The Django cache backend instance.
            identity: The per-request identity token from ``cache_key_prefix``.
        """
        version_key = self._CACHE_VERSION_KEY_TEMPLATE.format(identity=identity)

        def _do_bump() -> None:
            try:
                _cache.incr(version_key)
            except (ValueError, TypeError):
                # ``ValueError``: the key has expired (or was never set) —
                # Django's documented behaviour for a missing key on all
                # standard backends.
                # ``TypeError``: the key exists but holds a non-integer value,
                # e.g. a uuid-hex string planted by an older deploy's except
                # branch.  LocMemCache.incr raises TypeError in that case.
                # Heal to 1 (not 0) with timeout=None so the version counter
                # never enters the ambiguous zero-state and never expires
                # independently of its response entries.
                _cache.set(version_key, 1, timeout=None)

        transaction.on_commit(_do_bump)

    def super_call(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        """Call the parent dispatch method.

        Args:
            request: The incoming HTTP request.
            *args: Extra positional arguments forwarded to the parent.
            **kwargs: Extra keyword arguments forwarded to the parent.

        Returns:
            The response produced by the base view's "dispatch".
        """
        response = super().dispatch(request, *args, **kwargs)

        return response

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        """Fetch queried data from GraphQL and return the cached response.

        When "CACHE_ACTIVE" is True:

        * Cache keys are partitioned by user identity (see "cache_key_prefix") so
          one user's cached response is never served to another user.
        * Mutations advance a global namespace version counter instead of calling
          "cache.clear()", which would flush unrelated cache entries shared by
          other users or other cache clients. The counter is advanced AFTER the
          mutation has run, so a concurrent reader can never cache pre-mutation
          data under the new version (issue #60a).
        * A request that would render GraphiQL (the view serves it and the client
          prefers HTML) bypasses the cache entirely, so an HTML page and the JSON
          answer for the same query never share a cache slot.
        * A sentinel object detects cache misses so a legitimately cached falsy or
          empty body is not re-executed on every request.
        * A malformed GraphQL document ("GraphQLSyntaxError" during
          "get_operation_ast") falls through to "super_call", which returns the
          appropriate HTTP 400 response.
        * Multipart/form-data requests bypass the cache entirely because
          "parse_body" for that content type consumes the WSGI input stream via
          "request.POST", making "request.body" (needed to compute the cache key
          in "fetch_cache_key") unavailable. Bypassing is safe: multipart GraphQL
          is used almost exclusively for file uploads, which are never idempotent
          queries worth caching (issue #53a).
        * Only "(body, status_code, content_type)" is stored — never the live
          "HttpResponse" object. The base "dispatch" is decorated with
          "@ensure_csrf_cookie", which attaches a per-request CSRF secret as a
          "Set-Cookie" header. By storing a bare tuple and reconstructing a fresh
          "HttpResponse" on cache hits, the CSRF cookie is stripped from all
          cached responses (it only appears on the original cache-miss response).
          Subsequent clients in the same identity namespace therefore never
          receive another client's CSRF token (issue #53b).

        Args:
            request: The incoming HTTP request.
            *args: Extra positional arguments forwarded to the base view.
            **kwargs: Extra keyword arguments forwarded to the base view.

        Returns:
            The (possibly cached) HTTP response.
        """
        if not graphql_api_settings.CACHE_ACTIVE:
            return self.super_call(request, *args, **kwargs)

        # Batch requests contain a list body — caching individual operations
        # inside a batch is not meaningful (each op may be different), and the
        # body-is-a-list would cause AttributeError in get_operation_ast /
        # fetch_cache_key which assume a dict body.  Bypass the cache entirely.
        if self.batch:
            return self.super_call(request, *args, **kwargs)

        # Multipart/form-data requests bypass the cache to avoid
        # RawPostDataException: parse_body reads request.POST (consuming the
        # WSGI stream) so request.body is no longer accessible for cache-key
        # hashing.  Fall through to super_call uncached (issue #53a).
        content_type = self.get_content_type(request)
        if content_type == "multipart/form-data":
            return self.super_call(request, *args, **kwargs)

        # A request that may render GraphiQL bypasses the cache entirely: the
        # cache key is content-negotiation blind, so an HTML render and the JSON
        # answer for the same query share one slot and whoever warms it decides
        # what everybody else receives.  A GraphiQL render is a static page —
        # caching it buys nothing.
        if self.graphiql and self.request_wants_html(request):
            return self.super_call(request, *args, **kwargs)

        _cache = caches["default"]
        identity = self.cache_key_prefix(request)
        try:
            operation_ast = self.get_operation_ast(request)
        except HttpError:
            # Malformed body / parameters: the base dispatch already turns this
            # into the clean 400 envelope.  Raising here would turn ordinary bad
            # client input into an unhandled 500.
            return self.super_call(request, *args, **kwargs)
        # ``operation`` is a graphql-core ``OperationType`` enum; compare its
        # ``.value`` string — a bare ``== "mutation"`` is always ``False``
        # because the enum instance is never equal to the plain string.
        operation = getattr(getattr(operation_ast, "operation", None), "value", None)
        if operation is None:
            # Fail closed: no query, an unparsable document, or a multi-operation
            # document with no operationName.  The request could be a mutation,
            # so it must never be answered from — or stored in — the cache.
            return self.super_call(request, *args, **kwargs)
        if operation == "mutation":
            try:
                return self.super_call(request, *args, **kwargs)
            finally:
                # Scheduled AFTER the mutation has run.  Scheduling it before
                # made the ``transaction.on_commit`` deferral inert: the atomic
                # block ``ATOMIC_MUTATIONS`` opens lives INSIDE ``super_call``
                # (see ``execute_graphql_request``), so at that point there was
                # no open transaction and Django ran the bump immediately —
                # re-opening the very #60a TOCTOU window it was meant to close.
                # Here the mutation's own transaction has already committed, and
                # under ``ATOMIC_REQUESTS`` the request-level block is still
                # open so the bump remains deferred to its commit.
                self._bump_cache_version(_cache, identity)

        version = self._get_cache_version(_cache, identity)
        # ``_cache_key_signature`` is empty on the base view (byte-identical to
        # today) and, on ``AuthenticatedGraphQLView`` with ``PERMISSION_SCOPED_
        # SCHEMA`` active, the caller's permission signature. Folding it in keeps
        # a low-permission caller from ever reading a high-permission caller's
        # cached body for the same query (their pruned schemas — and therefore
        # their responses — differ).
        signature = self._cache_key_signature(request)
        cache_key = (
            f"_graphql_{identity}_{version}_{signature}_{self.fetch_cache_key(request)}"
            if signature
            else f"_graphql_{identity}_{version}_{self.fetch_cache_key(request)}"
        )
        response = _cache.get(cache_key, self._CACHE_MISS)

        if response is self._CACHE_MISS:
            response = self.super_call(request, *args, **kwargs)
            # Store only the serialisable response data — not the live
            # HttpResponse object.  The base dispatch is decorated with
            # @ensure_csrf_cookie, which attaches a per-client CSRF secret as
            # Set-Cookie.  Caching the whole HttpResponse and returning it
            # verbatim to subsequent clients in the same identity namespace
            # would replay one client's CSRF token to others (issue #53b).
            # By storing (body, status, content_type) and reconstructing a
            # fresh HttpResponse on cache hits, each client that hits a cached
            # entry receives a response with no Set-Cookie — the CSRF token is
            # only set on cache-miss responses (which go through super_call →
            # ensure_csrf_cookie normally).  The GraphQL endpoint is
            # csrf_exempt so this does not affect CSRF protection of the
            # endpoint itself.
            cached_payload = (
                response.content,
                response.status_code,
                response.get("Content-Type", "application/json"),
            )
            _cache.set(
                cache_key, cached_payload, timeout=graphql_api_settings.CACHE_TIMEOUT
            )
        else:
            # Cache hit: reconstruct a fresh HttpResponse from the stored
            # (body, status, content_type) tuple so no stale Set-Cookie header
            # is replayed to this client.
            body, status_code, content_type = response
            response = HttpResponse(body, status=status_code, content_type=content_type)

        return response

    @classmethod
    def as_view(cls, *args: Any, **kwargs: Any) -> Any:
        """Create the view with CSRF exemption.

        The GraphQL endpoint is CSRF-exempt because it authenticates each request
        explicitly rather than relying on session-cookie CSRF protection.

        Args:
            *args: Positional arguments forwarded to Django's "View.as_view".
            **kwargs: Keyword arguments forwarded to Django's "View.as_view".

        Returns:
            The CSRF-exempt view callable.
        """
        view = super().as_view(*args, **kwargs)
        view = csrf_exempt(view)
        return view

    @staticmethod
    def _is_introspection_document(document: Any) -> bool:
        """Return True when the document is an introspection query.

        Detects introspection by inspecting the AST rather than matching the raw
        query string. A document is treated as introspection when ALL of its
        top-level selections are "__schema" or "__type" fields (the two standard
        introspection entry-points). This correctly handles any formatting, named
        or anonymous operations, and mixed inline fragments.

        Args:
            document: A parsed graphql-core "DocumentNode".

        Returns:
            True when every top-level selection is a meta-field ("__schema" /
            "__type"), False otherwise.
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
                parsed_document = cached_parse(query)
            except Exception:  # nosec B110
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

            if (
                _settings.graphql_api_settings.EXPOSE_QUERY_COST
                and query
                and status_code == 200
            ):
                # Reuse the already-parsed document to avoid a second parse()
                # call. Fall back to string-based parsing only when
                # parsed_document is None (malformed query — cost is skipped).
                #
                # Skipped entirely when the request produced errors and no data
                # (status 400): the cost of a document that never validated is
                # computed from the fields it NAMES, so attaching it to a
                # "Cannot query field" error turns the payload into a
                # schema-existence oracle — a field pruned out of the caller's
                # permission-scoped schema costs more than one that never
                # existed.
                cost = self.get_query_cost(
                    query,
                    variables,
                    operation_name,
                    document=parsed_document,
                    request=request,
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
        request: HttpRequest | None = None,
    ) -> dict[str, Any] | None:
        """Estimate the query's cost for the "extensions.cost" payload.

        The estimate is computed against the schema the REQUEST is served (see
        "_graphql_schema_for"), so a caller whose schema is permission-pruned is
        never costed against fields their schema does not contain. When no
        request is given the full configured schema is used.

        Args:
            query: The raw GraphQL query string (used as fallback when the
                document is None).
            variables: The bound variable values (for exact page sizes).
            operation_name: The selected operation name, if any.
            document: An already-parsed "DocumentNode". When provided, "parse()"
                is not called again (avoids a double-parse per request when
                "EXPOSE_QUERY_COST" is True).
            request: The incoming HTTP request, used to select the per-request
                schema; None falls back to the full configured schema.

        Returns:
            A "{'requestedCost': int, 'maxCost': int | None}" mapping, or None
            when the query can't be parsed/analyzed.
        """
        try:
            doc = document if document is not None else parse(query)
            schema = (
                self.schema.graphql_schema
                if request is None
                else self._graphql_schema_for(request)
            )
            report = analyze_cost(
                schema,
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
        """Encode the response to JSON.

        A thin seam over "json_encode" so subclasses can customize the enhanced
        view's response serialization independently of the base encoder.

        Args:
            request: The incoming HTTP request.
            response: The response mapping to encode.
            pretty: Whether to force pretty-printed output.

        Returns:
            The JSON-encoded response string.
        """
        return self.json_encode(request, response, pretty)


class AuthenticatedGraphQLView(GraphQLView):
    """Gate the whole endpoint behind the library's own permission classes (no DRF).

    A coarse, endpoint-level guard: every request must satisfy each permission in
    "permission_classes" (the same "BasePermission" subclasses used at the
    resolver level), evaluated against the request's user. For finer, per-field
    control use "AuthenticatedFieldsMiddleware" / "DjangoGraphQLSchema" or a
    type's "permission_classes" instead.
    """

    #: Permission classes every request must satisfy (default: must be logged in).
    permission_classes = (IsAuthenticated,)

    #: The generic message returned for ANY permission failure on this endpoint
    #: (the "permission_classes" loop, the "API_ACCESS_GROUP" gate, and the
    #: empty-pruned-root case all reuse it verbatim so none of them leaks WHY).
    _FORBIDDEN_MESSAGE = "You do not have permission to access this endpoint."

    def __init__(
        self, *args: Any, permission_classes: Any = None, **kwargs: Any
    ) -> None:
        """Accept "permission_classes" via "as_view"/subclass, then configure.

        Args:
            *args: Positional arguments forwarded to "GraphQLView.__init__".
            permission_classes: The permission classes every request must
                satisfy; None keeps the class default.
            **kwargs: Keyword arguments forwarded to "GraphQLView.__init__".
        """
        super().__init__(*args, **kwargs)
        if permission_classes is not None:
            self.permission_classes = permission_classes

    def _graphql_schema_for(self, request: HttpRequest) -> Any:
        """Select the per-request schema, pruned to the caller's permissions.

        When ``PERMISSION_SCOPED_SCHEMA`` is False (default, read per-request) the
        FULL schema is served unchanged — byte-identical to the base view. When
        True, an ACTIVE superuser still gets the FULL schema (no signature); every
        other user gets the LRU-cached schema pruned to their permission
        signature. If that pruned schema has an EMPTY Query root (every root field
        was pruned) the request is denied with the endpoint's generic 403 —
        raised HERE, before ``validate``/``execute``, so no field existence leaks.

        Args:
            request: The incoming HTTP request (its ``user`` drives pruning).

        Returns:
            The full or per-request-pruned ``GraphQLSchema``.

        Raises:
            HttpError: A generic 403 when the caller's pruned Query root is empty.
        """
        full = self.schema.graphql_schema
        if not graphql_api_settings.PERMISSION_SCOPED_SCHEMA:
            return full
        user = getattr(request, "user", None)
        if user is None:
            return full
        pruned = pruned_schema_for(user, full)
        if pruned is not full and pruned.query_type is None:
            raise HttpError(HttpResponseForbidden(), message=self._FORBIDDEN_MESSAGE)
        return pruned

    def _cache_key_signature(self, request: HttpRequest) -> str:
        """Return the caller's permission signature for the response-cache key.

        This mirrors :meth:`_graphql_schema_for`'s selection so the cache key
        varies with the schema the caller actually validates/executes against:

        - ``PERMISSION_SCOPED_SCHEMA`` False (default): returns ``""`` — the key
          is byte-identical to the base view (feature inert).
        - An ACTIVE superuser: returns ``""`` — they always get the FULL schema
          (no signature computed), so their key needs no signature segment.
        - Any other caller: returns the SHA-256 permission signature (the same
          projection the LRU keys on: ``perms ∩ schema label-set``), so two
          callers who share a cache identity but hold DIFFERENT relevant perms
          never collide on one cached response body.

        Args:
            request: The incoming HTTP request (its ``user`` drives the signature).

        Returns:
            The permission signature, or ``""`` when no signature applies.
        """
        if not graphql_api_settings.PERMISSION_SCOPED_SCHEMA:
            return ""
        user = getattr(request, "user", None)
        if user is None:
            return ""
        if getattr(user, "is_active", False) and getattr(user, "is_superuser", False):
            return ""
        full = self.schema.graphql_schema
        label_set = frozenset((full.extensions or {}).get("gdx_label_set") or ())
        granted = frozenset(user.get_all_permissions())
        return permission_signature(granted, label_set)

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        """Enforce "permission_classes" and the access-group gate, then dispatch.

        Every permission in "permission_classes" must pass, and (when
        "API_ACCESS_GROUP" is set) the caller must be a member of that group or
        an active superuser; any failure returns the endpoint's generic 403.
        Both gates are read per-request so an "as_view" override still applies.

        Args:
            request: The incoming HTTP request.
            *args: Extra positional arguments forwarded to the parent dispatch.
            **kwargs: Extra keyword arguments forwarded to the parent dispatch.

        Returns:
            The generic 403 response when a gate fails, otherwise the response
            produced by the parent view's dispatch.
        """
        info = SimpleNamespace(context=request)
        for permission in self.permission_classes:
            if not permission().has_permission(info, "view", None):
                return self._forbidden_response(request)
        # Settings-driven access-group gate (read per-request, never at import).
        # Non-empty API_ACCESS_GROUP restricts the endpoint to members of that
        # Django auth Group; an active superuser always bypasses it. Fail-closed:
        # a missing/anonymous user is denied. Runs on top of permission_classes so
        # it holds even when a caller overrides them via as_view(). The 403 reuses
        # the generic message above so the group requirement never leaks.
        group_name = graphql_api_settings.API_ACCESS_GROUP
        if group_name and not self._passes_access_group(request, group_name):
            return self._forbidden_response(request)
        return super().dispatch(request, *args, **kwargs)

    def _forbidden_response(self, request: HttpRequest) -> HttpResponse:
        """Return the endpoint's generic 403 (single source of the message).

        Every endpoint-level denial (``permission_classes``, ``API_ACCESS_GROUP``,
        empty pruned root) shares this exact body so none of them leaks its cause.
        """
        return HttpResponse(
            self.json_encode(
                request, {"errors": [{"message": self._FORBIDDEN_MESSAGE}]}
            ),
            status=403,
            content_type="application/json",
        )

    @staticmethod
    def _passes_access_group(request: HttpRequest, group_name: str) -> bool:
        """Return whether ``request.user`` may access the group-gated endpoint.

        An active superuser always passes (hardcoded invariant). Otherwise the
        user must be authenticated and belong to ``group_name``. A missing or
        anonymous user is denied (fail-closed).
        """
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        if user.is_active and user.is_superuser:
            return True
        return user.groups.filter(name=group_name).exists()
