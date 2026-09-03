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
import os
import re
import sys
import threading
import weakref
from collections import OrderedDict
from functools import wraps
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
from graphql.execution.middleware import MiddlewareManager
from graphql.validation import specified_rules, validate

from . import settings as _settings
from .core.permission_signature_cache import permission_signature, pruned_schema_for
from .cost import CostLimitValidationRule, analyze_cost
from .permissions import IsAuthenticated
from .security import format_graphql_error
from .settings import graphql_api_settings
from .utils import clean_dict
from .validation import DepthLimitValidationRule

if TYPE_CHECKING:
    from django.http import HttpRequest

#: Request attribute set when a model mutation reported errors, so the
#: response can roll back an ATOMIC_MUTATIONS transaction.
MUTATION_ERRORS_FLAG = "graphene_mutation_has_errors"

#: Request attribute set once a mutation has reached execution and its work may
#: be durable.  The response-cache layer reads this marker after the base view
#: returns; merely parsing a mutation is not enough because GET rejection and
#: validation failures never run a resolver and therefore cannot stale data.
_CACHE_MUTATION_EXECUTED_FLAG = "_django_graphex_cache_mutation_executed"

#: Header a caller must send to POST one of the CORS-simple content types. The
#: name is not on the CORS-safelist, so a cross-origin request carrying it is
#: forced through a preflight — which is what actually stops the attack; the
#: value is never inspected. "X-Requested-With" is preferred over a
#: library-specific name because many HTTP clients already set it.
CSRF_GUARD_HEADER = "X-Requested-With"

#: The WSGI META key for that header, derived so the two can never drift apart.
_CSRF_GUARD_META_KEY = "HTTP_" + CSRF_GUARD_HEADER.upper().replace("-", "_")

#: Content types a browser can POST cross-site with NO preflight (the CORS
#: "simple request" set). The empty string is in the set on purpose: a body-less
#: cross-site POST carries no Content-Type at all and can still execute a query
#: taken from the query string. Everything else (notably "application/json" and
#: "application/graphql") already forces a preflight and is left alone.
_CORS_SIMPLE_CONTENT_TYPES = frozenset(
    {
        "",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
        "text/plain",
    }
)

#: Body of the 403 the cross-site POST guard returns. Constant on purpose: a
#: caller must not be able to learn from it whether the query it sent would
#: have been valid. Shared with the SSE subscription transport, which is
#: csrf_exempt and reads form-encoded bodies out of "request.POST" too.
CSRF_GUARD_MESSAGE = (
    f"This content type requires the {CSRF_GUARD_HEADER} header. A browser can "
    "POST it cross-site without a CORS preflight, so the header is what proves "
    f"the request was not forged. Send '{CSRF_GUARD_HEADER}: XMLHttpRequest', "
    "post 'application/json' instead, or set REQUIRE_CSRF_HEADER=False to opt "
    "out."
)


def csrf_header_missing(request: Any, content_type: str) -> bool:
    """Return whether this POST must be refused for lacking the guard header.

    The verdict, without the response: the HTTP views answer it with a JSON
    "errors" envelope while the SSE transport answers it with the plain text
    every other rejection on that endpoint uses, so only the decision is shared.

    Args:
        request: The incoming HTTP request.
        content_type: The request's normalized content type, as
            "BaseGraphQLView.get_content_type" returns it.

    Returns:
        True when "REQUIRE_CSRF_HEADER" is on, the request is a POST of a
        CORS-simple content type, and the header is absent.
    """
    # PRESENCE, not truthiness: an empty value is still a non-safelisted header,
    # so carrying it cross-origin forces the same preflight a filled one does.
    # Refusing it would buy no security and would contradict the contract the
    # docs state -- that the value is never inspected.
    return (
        (request.method or "").upper() == "POST"
        and bool(graphql_api_settings.REQUIRE_CSRF_HEADER)
        and content_type in _CORS_SIMPLE_CONTENT_TYPES
        and _CSRF_GUARD_META_KEY not in request.META
    )


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

    Read per call (never memoized at import) so override_settings in tests —
    and a live settings reload — take effect immediately.

    None means "unbounded", the same as it does for every sibling limit in
    the namespace (MAX_BATCH_SIZE, MAX_REQUEST_BODY_SIZE,
    MAX_QUERY_DEPTH, MAX_PAGE_SIZE). It is reported as sys.maxsize so
    the callers stay plain integer comparisons: an LRU can never hold that many
    entries, so the eviction loop never runs.
    """
    configured = graphql_api_settings.DOCUMENT_CACHE_MAXSIZE
    return sys.maxsize if configured is None else int(configured)


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

    @classmethod
    def as_view(cls, *args: Any, **kwargs: Any) -> Any:
        """Build the view callable, fronted by the cross-site POST guard.

        The guard lives HERE, not in "dispatch", because "dispatch" is not the
        choke point: "GraphQLView.dispatch" overrides it and performs the whole
        response-cache interaction — the "cache.get", the version bump, the
        "cache.set" — reaching "BaseGraphQLView.dispatch" only through
        "super_call", at several different points. A guard behind that is
        bypassed by a warm cache entry, has its own 403 stored and replayed to
        legitimate callers, and still lets a rejected mutation flush the
        identity's cache namespace. Wrapping the view callable puts the check
        ahead of every dispatch on every subclass, and its response is built
        here so nothing can cache it.

        Args:
            *args: Positional arguments forwarded to Django's "View.as_view".
            **kwargs: Keyword arguments forwarded to Django's "View.as_view".

        Returns:
            The guarded view callable.
        """
        view = super().as_view(*args, **kwargs)

        @wraps(view)
        def guarded(request: Any, *inner: Any, **kw: Any) -> HttpResponse:
            refusal = cls.csrf_header_guard(request)
            return view(request, *inner, **kw) if refusal is None else refusal

        return guarded

    @classmethod
    def csrf_header_guard(cls, request: Any) -> HttpResponse | None:
        """Return the 403 for a forgeable header-less POST, or None to continue.

        The endpoint is "csrf_exempt", and a POST of one of the CORS-simple
        content types needs no preflight, so a cross-site form submit reaches it
        with the victim's session cookie attached. Demanding a header the CORS
        safelist does not cover forces that preflight back into existence — the
        attacker page cannot pass it. The header is only required where the
        preflight is missing, so "application/json" and "application/graphql"
        clients change nothing. The header VALUE is never inspected.

        The decision itself lives in "csrf_header_missing", which the SSE
        subscription transport shares; only the refusal shape differs.

        Args:
            request: The incoming HTTP request.

        Returns:
            The HTTP 403 response when the request must be refused, otherwise
            None.
        """
        if not csrf_header_missing(request, cls.get_content_type(request)):
            return None
        # Built here rather than raised as an HttpError: the refusal must reach
        # the client without passing through any dispatch that could store it.
        return HttpResponseForbidden(
            json.dumps({"errors": [{"message": CSRF_GUARD_MESSAGE}]}),
            content_type="application/json",
        )

    @method_decorator(ensure_csrf_cookie)
    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        """Handle a GraphQL GET/POST request (and GraphiQL/batch).

        The cross-site POST guard runs BEFORE this method, in "as_view" — see
        "csrf_header_guard" for why it cannot live here.

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
        2. Authoritative check: measure the body itself, regardless of the
           "Content-Length" header. This prevents a client from spoofing a low
           "Content-Length" to bypass the guard.

        Stage 2 measures the body two different ways, because the two request
        classes offer two different things:

        * Every content type EXCEPT "multipart/form-data" is measured by reading
          it, "len(request.body)". The body has to be in memory to be parsed
          anyway, so the read costs nothing extra.
        * "multipart/form-data" is measured WITHOUT reading it, by seeking
          "request._stream" to its end and straight back. Reading it would break
          the request (the CSRF check "@ensure_csrf_cookie" performs has already
          drained the stream through "request.POST" whenever the client holds a
          "csrftoken" cookie) and would drag a streamed upload under Django's
          "DATA_UPLOAD_MAX_MEMORY_SIZE". A seek does neither: nothing is
          allocated and the parser still receives a pristine stream. This is the
          same measurement Django's own "HttpRequest.body" performs on a seekable
          stream, done one level up so it can answer 413 instead of 400.

        A multipart stream that is not seekable is a WSGI "LimitedStream", which
        is already capped at "CONTENT_LENGTH": an under-declared length truncates
        the body it is lying about rather than smuggling it past stage 1. The one
        thing that cap cannot express is an ABSENT length, which "WSGIRequest"
        turns into a limit of zero, so such a request is refused with HTTP 411 —
        a clearer answer than the empty-payload 400 Django would otherwise give.

        None of this bounds RECEPTION under ASGI: the handler spools the whole
        body before this view exists, so the bytes are already on disk by the
        time the seek measures them. Bounding what arrives is the ASGI server's
        job, not this setting's.

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
            #   2. Authoritative check: measure the body itself and verify it
            #      is ≤ max_body.  This catches spoofed-low / absent / garbage
            #      Content-Length values.  Multipart is measured by seeking
            #      rather than by reading — see below.
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

                content_type = self.get_content_type(request)

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
                # Stage 1 compared the cap against a number the CLIENT chose, so
                # on its own it bounds nothing: a body declaring less than it
                # carries sails straight through it. Stage 2 is what makes the
                # cap mean something, and it must therefore run for every content
                # type — multipart included, which is where the bypass lived.
                if content_type == "multipart/form-data":
                    # Measure the stream instead of reading it. Reading
                    # request.body here would be WRONG: "dispatch" carries
                    # @ensure_csrf_cookie, whose process_view runs the full CSRF
                    # token check whenever a csrftoken cookie is present, and
                    # that check reads request.POST. For multipart that drains
                    # the stream before we get here, so request.body raises
                    # RawPostDataException (HTTP 500) — and this endpoint plants
                    # the cookie on every response, so only a client's FIRST
                    # multipart POST ever survived. Reading also drags multipart
                    # under DATA_UPLOAD_MAX_MEMORY_SIZE (2.5 MB by default),
                    # which streaming multipart otherwise escapes, and doubles
                    # peak memory for an upload that would have gone to disk.
                    #
                    # A seek costs none of that. Under ASGI "_stream" is the
                    # SpooledTemporaryFile "ASGIHandler.read_body" already
                    # filled, so its true size is one seek away: nothing is
                    # allocated, "_read_started" is never set, and the parser
                    # still sees a pristine stream. The position is saved and
                    # restored rather than assumed to be zero, because the CSRF
                    # check above may already have consumed it.
                    stream = getattr(request, "_stream", None)
                    measured_length = None
                    if stream is not None and stream.seekable():
                        position = stream.tell()
                        measured_length = stream.seek(0, os.SEEK_END)
                        stream.seek(position)

                    if measured_length is not None and measured_length > max_body:
                        raise HttpError(
                            _HR(status=413),
                            message=(
                                f"Request body ({measured_length} bytes) exceeds "
                                f"the MAX_REQUEST_BODY_SIZE limit of {max_body} "
                                "bytes. Split the request or increase the limit."
                            ),
                        )

                    # Not seekable means a WSGI LimitedStream, which Django has
                    # already capped at CONTENT_LENGTH — an under-declared length
                    # truncates the body it lies about instead of smuggling it,
                    # and stage 1 refused every declared length above the cap. So
                    # the only unbounded case left is an ABSENT length, which
                    # WSGIRequest turns into a limit of zero: the request was
                    # doomed anyway, but it died as an opaque "must provide query
                    # string" 400. 411 says what actually went wrong. It is not
                    # 413 because the size is unknown, not known-too-big.
                    if measured_length is None and declared_length is None:
                        raise HttpError(
                            _HR(status=411),
                            message=(
                                "A multipart/form-data request must declare a "
                                "Content-Length while MAX_REQUEST_BODY_SIZE is "
                                "set, because this server cannot measure its "
                                "body. Send a declared length instead of a "
                                "chunked body."
                            ),
                        )
                else:
                    # If reading the body raises Django's RequestDataTooBig /
                    # SuspiciousOperation, that propagates as Django's own
                    # response (we neither mask it nor 500 on it).
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
                request, {"errors": [self.format_error(e, request)]}
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
                    self.format_error(e, request) for e in execution_result.errors
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
        views) required to be a non-empty list of objects, form-encoded/multipart
        bodies return "request.POST", and any other type yields an empty dict.

        Args:
            request: The incoming HTTP request.

        Returns:
            The parsed request data (a mapping, or a list for batch requests).

        Raises:
            HttpError: When the body is not valid UTF-8, is not valid JSON (a
                body nested too deeply for the decoder counts), or when a batch
                view receives a non-list body, an empty list, or a list holding
                an entry that is not a JSON object.
        """
        content_type = self.get_content_type(request)

        if content_type == "application/graphql":
            # Same guard the "application/json" branch below already had: a body
            # that is not valid UTF-8 is bad client input, not a server fault,
            # and "UnicodeDecodeError" would escape the "except HttpError"
            # handler in "dispatch" as an unhandled 500.
            try:
                return {"query": request.body.decode("utf-8")}
            except UnicodeDecodeError as e:
                raise HttpError(HttpResponseBadRequest(str(e)))
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
                    # Check every ENTRY, not just the outer list: a non-mapping
                    # entry reaches "get_graphql_params", where "data.get(...)"
                    # raises an AttributeError that escapes the "except HttpError"
                    # handler in "dispatch" and turns a malformed body into a 500.
                    for entry in request_json:
                        if not isinstance(entry, dict):
                            raise HttpError(
                                HttpResponseBadRequest(),
                                message=(
                                    "Batch entries should be JSON objects, but "
                                    "received {}.".format(repr(entry))
                                ),
                            )
                else:
                    if not isinstance(request_json, dict):
                        raise HttpError(
                            HttpResponseBadRequest(),
                            message="The received data is not a valid JSON query.",
                        )
                return request_json
            except (TypeError, ValueError, RecursionError):
                # "RecursionError" is NOT a "ValueError": a body of deeply nested
                # arrays or objects (20 KB is enough) exhausts the JSON scanner's
                # stack, and without it here the request became an unhandled 500.
                # It is caught alongside the other two because the cause is the
                # same — a body this decoder cannot accept.
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
        validate and execute read the value it returns).

        Args:
            request: The incoming HTTP request.

        Returns:
            The schema to validate and execute against.
        """
        return self.schema.graphql_schema

    def _cache_key_signature(self, request: Any) -> str:
        """Return the per-request segment folded into the response-cache key.

        The base view returns the empty string, so its v2 cache key has no
        signature segment. Subclasses that serve a per-request
        schema (see _graphql_schema_for) override this to return a token
        that varies with the served schema — otherwise two callers who share an
        identity partition but see DIFFERENT schemas could read each other's
        cached response bodies.

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

            is_mutation = (
                operation_ast is not None
                and operation_ast.operation == OperationType.MUTATION
            )
            if is_mutation and (
                graphql_api_settings.ATOMIC_MUTATIONS is True
                or connection.settings_dict.get("ATOMIC_MUTATIONS", False) is True
            ):
                with transaction.atomic():
                    result = execute(schema, document, **execute_options)
                    rolled_back = getattr(request, MUTATION_ERRORS_FLAG, False) is True
                    if rolled_back:
                        transaction.set_rollback(True)
                if not rolled_back:
                    setattr(request, _CACHE_MUTATION_EXECUTED_FLAG, True)
                return result

            # Non-atomic execution may have committed work before a later
            # resolver reports an error, so mark it immediately before handing
            # control to graphql-core.  Atomic execution is marked only after
            # its transaction exits without an explicit rollback above.
            if is_mutation:
                setattr(request, _CACHE_MUTATION_EXECUTED_FLAG, True)
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

    def format_error(self, error: Any, request: Any = None) -> dict:
        """Format an error for the response "errors" list.

        Delegates to "security.format_graphql_error", the single formatter the
        HTTP view and both subscription transports share, so the "Did you
        mean ...?" schema oracle is closed on every surface at once.

        The chain comes from "get_middleware(request)" — the same hook
        execution asks — so a subclass that resolves its middleware per request
        gets a formatter whose introspection verdict matches the chain that
        actually ran.

        Args:
            error: The error (or exception) to format.
            request: The request being answered, used to resolve the middleware
                chain. None falls back to the view's configured chain.

        Returns:
            The error mapping suitable for the response "errors" list.
        """
        return format_graphql_error(error, self.get_middleware(request))

    @staticmethod
    def get_content_type(request: Any) -> str:
        """Return the request content type without parameters.

        Reads "CONTENT_TYPE" (falling back to "HTTP_CONTENT_TYPE"), drops any
        trailing parameters (e.g. "; charset=utf-8"), trims surrounding
        whitespace and lower-cases the result. The trim matters: the value is
        compared against a frozenset by the cross-site POST guard, where a
        padded content type would be a silent miss instead of a visible error.

        Args:
            request: The incoming HTTP request.

        Returns:
            The bare, lower-cased content type (empty string when absent).
        """
        meta = request.META
        content_type = meta.get("CONTENT_TYPE", meta.get("HTTP_CONTENT_TYPE", ""))
        return content_type.split(";", 1)[0].strip().lower()


#: Standard validation plus query-depth limiting ("Meta.max_depth" /
#: "MAX_QUERY_DEPTH") and cost analysis ("Meta.complexity" / "MAX_QUERY_COST").
#: Both are no-ops until configured, and both read their limits from
#: "graphql_api_settings" at validation time, so this tuple stays correct
#: whatever the settings say — which is why the subscription transports can
#: share the very same object instead of rebuilding it per transport. Anything
#: validating a document on behalf of this library MUST use it, or the depth and
#: cost guards silently do not apply to that surface.
DEFAULT_VALIDATION_RULES = (
    *specified_rules,
    DepthLimitValidationRule,
    CostLimitValidationRule,
)

#: Cache identity shared by every credential-free anonymous request. It is a
#: single fixed partition, so it is the one unauthenticated identity that is
#: already bounded and does not need the bucketing ``_cache_version_identity``
#: applies to the rest.
_ANON_CACHE_IDENTITY = "anon"

#: Shared counter namespace used by the default global invalidation policy.
_GLOBAL_CACHE_VERSION_IDENTITY = "global"


class GraphQLView(BaseGraphQLView):
    """Enhanced GraphQL view: response caching + depth/cost rules + cost payload.

    Extends the base view with per-request response caching (partitioned by
    caller identity), the depth-limit and cost-limit validation rules, and an
    optional "extensions.cost" payload. Each addition is inert until its
    corresponding "DJANGO_GRAPHEX" setting is configured.
    """

    validation_rules = DEFAULT_VALIDATION_RULES

    def get_operation_ast(self, request: HttpRequest) -> Any:
        """Get the AST of the GraphQL operation from the request.

        Returns None when there is no query, when the query cannot be parsed at
        all (a malformed document must not raise here; "dispatch" falls through
        to "super_call" which returns a 400), or when the document declares
        several operations and the request does not name one — the caller must
        then treat the operation as undeterminable.

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
            # location labels would differ, and a parse failure is swallowed here.
            document_ast = cached_parse(query)
        except Exception:
            # Every failure to turn the body's "query" into a document is
            # answered the same way: give up on classifying the operation and
            # let "super_call" produce the 400. "GraphQLSyntaxError" alone was
            # too narrow — a non-string "query" raises "TypeError" out of the
            # lexer and a deeply nested inline literal raises "RecursionError",
            # both of which became 500s. This mirrors the sibling call site in
            # "execute_graphql_request", which already catches "Exception" around
            # the very same "cached_parse" call and reports it as a GraphQL
            # error. Nothing is swallowed: the request still executes through
            # "super_call", which re-parses and surfaces the same failure.
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
        source (e.g. a session key or a tenant identifier). Whatever it returns
        for an UNAUTHENTICATED request is treated as caller-controlled: see
        "_cache_version_identity", which bounds how many permanent version
        counters such an identity can create.

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
        return _ANON_CACHE_IDENTITY

    def should_cache_query(self, request: HttpRequest) -> bool:
        """Return whether this query's context is safe for response caching.

        Cookies are contextual identity even when "request.user" is
        anonymous: sessions, carts, feature flags, locale and tenant routing
        can all change a resolver result.  Because neither the cookie jar nor a
        session key is part of the default cache key, cookie-bearing requests
        fail closed and execute normally.

        Subclasses may override this hook, but an override that returns "True"
        for contextual requests must also extend "cache_key_prefix" or
        "fetch_cache_key" with every value that can affect the response.

        Args:
            request: The incoming query request.

        Returns:
            "True" when the response may be read from and written to cache.
        """
        return not bool(request.COOKIES)

    #: Sentinel used by ``dispatch`` to distinguish a cache miss from a cached
    #: falsy value (e.g. an empty-body response).  Using ``cache.get(key)``
    #: with a default of ``None`` and then checking ``if not response:`` would
    #: treat a legitimately cached empty response as a miss.
    _CACHE_MISS = object()

    #: Template for a namespace version-counter key. ``{identity}`` receives
    #: the scope-selected version namespace: ``global`` by default, or the
    #: identity/bucket selected by the 3.0-compatible ``identity`` policy.
    #: Response entries carry the FULL identity under both policies.
    _CACHE_VERSION_KEY_TEMPLATE = "_graphql_cacheversion_{identity}"

    #: How many version namespaces an UNAUTHENTICATED caller can reach. The
    #: version counter is permanent by design (see ``_get_cache_version``), so
    #: an identity an anonymous caller can vary at will — ``cache_key_prefix``
    #: derives one from the caller-supplied ``Authorization`` header — would
    #: otherwise let it plant unbounded never-expiring cache entries. See
    #: ``_cache_version_identity`` for why collisions here are harmless.
    _CACHE_VERSION_BUCKETS = 64

    def _cache_version_identity(self, request: HttpRequest, identity: str) -> str:
        """Return the namespace whose version counter *identity* invalidates.

        The version counter is PERMANENT (see "_get_cache_version": it must
        outlive the response entries it namespaces, issue #60b). A permanent key
        whose name an unauthenticated caller chooses is a memory leak with a
        remote control: "cache_key_prefix" derives an identity from the
        caller-supplied "Authorization" header, which nothing has verified at
        this point, so an anonymous client sending a fresh token per request
        minted a fresh never-expiring counter per request.

        Bounding it costs one property and keeps the important one:

        * KEPT — isolation. Only the COUNTER namespace is bucketed. The response
          entry itself is still keyed by the FULL identity (see "dispatch"), so
          two callers who share a bucket never share a response slot and one
          caller's body is never handed to another.
        * SPENT — invalidation locality. Callers sharing a bucket share a
          counter, so one caller's mutation advances the other's namespace too.
          That can only turn a cache HIT into a MISS, which re-reads current data
          from the database; the counter only ever moves forward, so no entry is
          ever resurrected.

        Two identities keep their exact namespace because neither is mintable:
        an authenticated caller's is bounded by the real user table, and every
        credential-free request already shares the single "anon" partition. Any
        OTHER identity produced for an unauthenticated request is bucketed —
        including one a subclass override invents, which is the point: the rule
        is about what an unauthenticated caller can vary, not about the shape of
        the token this class happens to emit.

        STATED, NOT CLOSED — the spent property is reachable by an attacker. The
        bucket is a pure function of a header the caller chooses, so an
        unauthenticated client can hash candidate credentials offline until one
        lands in any bucket it likes, then bump that bucket's counter and send
        its members back to the database. Salting the digest would not help: the
        namespace is small by construction, so a caller that cannot AIM can
        still cover every bucket by volume. What bounds the damage is the shape
        of the property itself — the counter only moves forward, so the worst
        outcome is a miss, and the response entry is keyed by the FULL identity,
        so no body ever crosses callers. Anything stronger needs the counter key
        to be unguessable, which it cannot be while it is derived from the
        identity it namespaces. A latency-sensitive token client should
        authenticate: an authenticated identity is not bucketed at all.
        This method is used only when CACHE_INVALIDATION_SCOPE is identity;
        the default global scope does not expose caller-chosen counter names.
        tests/test_views_cache_bucket_invalidation.py pins both halves.

        Args:
            request: The incoming HTTP request, read for its authentication
                state only.
            identity: The per-request identity token from "cache_key_prefix".

        Returns:
            The identity itself when it is not attacker-mintable, else one of
            "_CACHE_VERSION_BUCKETS" bucket names derived from it.
        """
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            return identity
        if identity == _ANON_CACHE_IDENTITY:
            return identity
        digest = hashlib.sha256(identity.encode(), usedforsecurity=False).digest()
        bucket = int.from_bytes(digest[:4], "big") % self._CACHE_VERSION_BUCKETS
        # Prefixed with the anon partition name so a bucket can never collide
        # with an authenticated ``u{pk}`` namespace.
        return f"{_ANON_CACHE_IDENTITY}{bucket}"

    def _cache_version_namespace(
        self, request: HttpRequest, identity: str, scope: str
    ) -> str:
        """Return the version-counter namespace selected by invalidation scope.

        Args:
            request: The incoming request, used by identity bucketing.
            identity: The full response identity.
            scope: The validated CACHE_INVALIDATION_SCOPE value.

        Returns:
            The shared global namespace, or the 3.0 identity/bucket namespace.
        """
        if scope == "global":
            return _GLOBAL_CACHE_VERSION_IDENTITY
        return self._cache_version_identity(request, identity)

    def _get_cache_version(self, _cache: Any, identity: str) -> str:
        """Return the current namespace version token for *identity*.

        If no version exists yet, initialise it to 1 (integer) and persist
        it with timeout=None (never expires independently of its response
        entries).  Seeding with an integer — rather than a UUID hex string —
        ensures that cache.incr works atomically on all standard backends
        (Redis, Memcached, LocMemCache) without first deleting and re-setting
        the key.

        The initial value is 1 (not 0) so the first bump goes to 2,
        ensuring that version 0 is never used as a live cache key (closes the
        ambiguous zero-state described in issue #60c).

        The key is stored with timeout=None (permanent) to prevent the
        version counter from expiring before its associated response entries when
        CACHE_TIMEOUT exceeds the backend's own default TTL (issue #60b).

        Args:
            _cache: The Django cache backend instance.
            identity: The per-request identity token from cache_key_prefix.

        Returns:
            The current version as a string ("1", "2", …).  Integer
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
        """Invalidate a selected response namespace by advancing its version token.

        Callers MUST invoke this AFTER the mutation has been executed (see
        dispatch): scheduling it beforehand made the deferral below inert,
        because ATOMIC_MUTATIONS opens its atomic block inside
        execute_graphql_request — later than this call — so on_commit
        found no open transaction and ran the bump immediately.

        The bump is deferred via transaction.on_commit so it only fires once
        the mutation's database write is durable.  This eliminates the
        bump-before-commit TOCTOU window (issue #60a) where a concurrent query
        could cache pre-mutation data at the new version key.  If the surrounding
        transaction is rolled back, on_commit is never invoked, so a failed
        mutation does not advance the counter.  When there is no open transaction
        (ATOMIC_MUTATIONS is off) Django executes on_commit immediately
        after the current statement — behaviour is unchanged for that case.

        Residual microsecond window (audit rank 10 — ACCEPTABLE).  There is a
        tiny gap between the moment on_commit is SCHEDULED (here) and the
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

        Uses cache.incr for an atomic increment on Redis / Memcached /
        LocMemCache.  Because the key is seeded with integer 1 by
        _get_cache_version, incr always finds an integer value and
        succeeds on all standard backends.  Two recoverable failure modes are
        caught and healed by resetting the key to integer 1 (not 0) so
        the next bump never produces the ambiguous zero-state (issue #60c):

        * ValueError — the key has expired (Django's documented behaviour
          for a missing key on all standard backends).
        * TypeError — the key exists but holds a non-integer value (e.g. a
          uuid-hex string from an older deploy).  LocMemCache raises
          TypeError in this case; healing it to 1 lets the next incr
          succeed on every backend.

        The heal value is stored with timeout=None to match the seed policy
        in _get_cache_version (issue #60b).

        Truly unexpected backend errors (e.g. connection failure) are not
        suppressed and propagate normally.

        The caller selects either the shared global namespace or an identity
        namespace. No unrelated Django cache key is cleared in either mode.

        Args:
            _cache: The Django cache backend instance.
            identity: The per-request identity token from cache_key_prefix.
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

    def _execute_uncached_and_invalidate(
        self,
        request: HttpRequest,
        _cache: Any,
        version_identity: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute without response caching and invalidate after real mutation work.

        The execution marker is set inside execute_graphql_request only
        after validation and transport checks pass.  A finally is safe here:
        a non-atomic resolver may persist before raising, while an atomic
        rollback never sets the marker.  An outer request transaction still
        controls durability because _bump_cache_version uses on_commit.
        """
        try:
            return self.super_call(request, *args, **kwargs)
        finally:
            if getattr(request, _CACHE_MUTATION_EXECUTED_FLAG, False):
                self._bump_cache_version(_cache, version_identity)

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        """Fetch queried data from GraphQL and return the cached response.

        When "CACHE_ACTIVE" is True:

        * Cache keys are partitioned by user identity (see "cache_key_prefix") so
          one user's cached response is never served to another user. Their v2
          shape also records invalidation scope, counter namespace and version.
        * Mutations advance a namespace version counter instead of calling
          "cache.clear()", which would flush unrelated cache entries shared by
          other users or other cache clients. The counter is advanced AFTER the
          mutation has run, so a concurrent reader can never cache pre-mutation
          data under the new version (issue #60a). The default shared namespace
          invalidates every GraphQL identity; the opt-in identity policy buckets
          namespaces an unauthenticated caller can vary. Response entries keep
          the FULL identity either way, so isolation is unaffected.
        * A request that would render GraphiQL (the view serves it and the client
          prefers HTML) bypasses the cache entirely, so an HTML page and the JSON
          answer for the same query never share a cache slot.
        * A sentinel object detects cache misses so a legitimately cached falsy or
          empty body is not re-executed on every request.
        * A "query" that cannot be parsed during "get_operation_ast" — a syntax
          error, a non-string value, or a literal nested past the parser's
          recursion limit — falls through to "super_call", which returns the
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

        # RequestFactory-based callers may deliberately reuse a request object.
        # Never let execution state from a prior dispatch leak into this one.
        setattr(request, _CACHE_MUTATION_EXECUTED_FLAG, False)

        _cache = caches["default"]
        identity = self.cache_key_prefix(request)
        invalidation_scope = graphql_api_settings.CACHE_INVALIDATION_SCOPE
        # The response entry keeps the FULL identity. The default version
        # namespace is global; identity mode applies bounded bucketing because
        # its permanent counter name can otherwise be caller-controlled.
        version_identity = self._cache_version_namespace(
            request, identity, invalidation_scope
        )

        # Batch requests contain a list body — caching individual operations
        # inside a batch is not meaningful (each op may be different), and the
        # body-is-a-list would cause AttributeError in get_operation_ast /
        # fetch_cache_key which assume a dict body.  Bypass the cache entirely.
        if self.batch:
            return self._execute_uncached_and_invalidate(
                request, _cache, version_identity, *args, **kwargs
            )

        # Multipart/form-data requests bypass the cache to avoid
        # RawPostDataException: parse_body reads request.POST (consuming the
        # WSGI stream) so request.body is no longer accessible for cache-key
        # hashing.  Fall through to super_call uncached (issue #53a).
        content_type = self.get_content_type(request)
        if content_type == "multipart/form-data":
            return self._execute_uncached_and_invalidate(
                request, _cache, version_identity, *args, **kwargs
            )

        # A request that may render GraphiQL bypasses the cache entirely: the
        # cache key is content-negotiation blind, so an HTML render and the JSON
        # answer for the same query share one slot and whoever warms it decides
        # what everybody else receives.  A GraphiQL render is a static page —
        # caching it buys nothing.
        if self.graphiql and self.request_wants_html(request):
            return self._execute_uncached_and_invalidate(
                request, _cache, version_identity, *args, **kwargs
            )
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
            return self._execute_uncached_and_invalidate(
                request, _cache, version_identity, *args, **kwargs
            )
        if not self.should_cache_query(request):
            return self.super_call(request, *args, **kwargs)

        version = self._get_cache_version(_cache, version_identity)
        # ``_cache_key_signature`` is empty on the base view and, on
        # ``AuthenticatedGraphQLView`` with ``PERMISSION_SCOPED_
        # SCHEMA`` active, the caller's permission signature. Folding it in keeps
        # a low-permission caller from ever reading a high-permission caller's
        # cached body for the same query (their pruned schemas — and therefore
        # their responses — differ).
        signature = self._cache_key_signature(request)
        cache_key_parts = [
            "_graphql_v2",
            invalidation_scope,
            version_identity,
            version,
            identity,
        ]
        if signature:
            cache_key_parts.append(signature)
        cache_key_parts.append(self.fetch_cache_key(request))
        cache_key = "_".join(cache_key_parts)
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
        explicitly rather than relying on session-cookie CSRF protection. The
        cross-site POST guard the base "as_view" wraps around the view is what
        replaces the token for the content types a browser can post cross-site
        with no preflight.

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
    def _is_introspection_document(
        document: Any, operation_name: str | None = None
    ) -> bool:
        """Return True when the selected operation is an introspection query.

        Detects introspection by inspecting the AST rather than matching the raw
        query string. A document is treated as introspection when ALL of its
        top-level selections are "__schema" or "__type" fields (the two standard
        introspection entry-points). This correctly handles any formatting, named
        or anonymous operations, and mixed inline fragments.

        Args:
            document: A parsed graphql-core "DocumentNode".
            operation_name: The operation selected by the request, if named.

        Returns:
            True when every top-level selection is a meta-field ("__schema" /
            "__type"), False otherwise.
        """
        if document is None:
            return False
        from graphql.language.ast import FieldNode

        operation = get_operation_ast(document, operation_name)
        selections = getattr(
            getattr(operation, "selection_set", None), "selections", ()
        )
        if not selections:
            return False
        return all(
            isinstance(selection, FieldNode)
            and selection.name.value in ("__schema", "__type")
            for selection in selections
        )

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
                    self.format_error(e, request) for e in execution_result.errors
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
                and not self._is_introspection_document(parsed_document, operation_name)
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

        When PERMISSION_SCOPED_SCHEMA is False (default, read per-request) the
        FULL schema is served unchanged — byte-identical to the base view. When
        True, an ACTIVE superuser still gets the FULL schema (no signature); every
        other user gets the LRU-cached schema pruned to their permission
        signature. If that pruned schema has an EMPTY Query root (every root field
        was pruned) the request is denied with the endpoint's generic 403 —
        raised HERE, before validate/execute, so no field existence leaks.

        Args:
            request: The incoming HTTP request (its user drives pruning).

        Returns:
            The full or per-request-pruned schema.

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

        This mirrors the selection in _graphql_schema_for, so the cache key
        varies with the schema the caller actually validates/executes against:

        - PERMISSION_SCOPED_SCHEMA False (default): returns an empty string, so
          the key is byte-identical to the base view (feature inert).
        - An ACTIVE superuser: returns an empty string because they always get
          the FULL schema (no signature computed), so their key needs no
          signature segment.
        - Any other caller: returns the SHA-256 permission signature (the same
          projection the LRU keys on: perms ∩ schema label-set), so two
          callers who share a cache identity but hold DIFFERENT relevant perms
          never collide on one cached response body.

        Args:
            request: The incoming HTTP request (its user drives the signature).

        Returns:
            The permission signature, or an empty string when none applies.
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

        Every endpoint-level denial (permission_classes, API_ACCESS_GROUP,
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
        """Return whether request.user may access the group-gated endpoint.

        An active superuser always passes (hardcoded invariant). Otherwise the
        user must be authenticated and belong to group_name. A missing or
        anonymous user is denied (fail-closed).
        """
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        if user.is_active and user.is_superuser:
            return True
        return user.groups.filter(name=group_name).exists()
