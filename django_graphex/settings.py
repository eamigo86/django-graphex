"""Settings configuration for django-graphex.

This module provides configuration management for the django-graphex
package, including pagination, caching, schema/middleware and other global
settings. Everything is read from the SINGLE "DJANGO_GRAPHEX" Django-setting
namespace, exposed through the "graphql_api_settings" singleton.

Migration note (v1.x -> v2.0): the legacy graphene-django "GRAPHENE" namespace
is renamed to "DJANGO_GRAPHEX" (its schema/middleware/subscription keys are
merged into this package's own settings dict — there is no separate namespace).
"""

from __future__ import annotations

from difflib import get_close_matches
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.checks import Warning as CheckWarning
from django.test.signals import setting_changed
from django.utils.module_loading import import_string

if TYPE_CHECKING:
    from django.apps import AppConfig
    from django.core.checks import CheckMessage

DEFAULTS = {
    # Pagination
    # Dotted path (or class) of the default paginator applied to list fields
    # that don't set their own. None disables default pagination.
    "DEFAULT_PAGINATION_CLASS": "django_graphex.paginations.LimitOffsetGraphqlPagination",
    "DEFAULT_PAGE_SIZE": None,  # page size when the client omits one (None = unbounded)
    "MAX_PAGE_SIZE": None,  # hard ceiling on the effective page size (None = no cap)
    # Response shaping & cache
    "CLEAN_RESPONSE": False,  # strip null values from the response payload
    "CACHE_ACTIVE": False,  # enable per-request response caching in GraphQLView
    "CACHE_TIMEOUT": 300,  # response cache TTL in seconds (default 5 min)
    # In-process bound (per LRU) for the parse+validate document cache. graphql-
    # core re-parses and re-validates the identical document on every request; a
    # small replayed document set makes both memoizable. The parse cache maps
    # query text -> DocumentNode (immutable AST); the validation cache is keyed by
    # the schema OBJECT (a per-schema sub-cache) so a permission-pruned schema
    # never serves another schema's verdict. 0 disables both caches entirely.
    "DOCUMENT_CACHE_MAXSIZE": 128,
    # Queryset optimization (N+1)
    # Apply nested select_related / prefetch_related derived from the query.
    "OPTIMIZE_QUERYSET": True,
    # Also narrow columns with .only() across the select_related span.
    # Conservative (keeps pk/FK/ordering, skips computed-field models); set to
    # False if your models read non-selected columns in properties/resolvers.
    "OPTIMIZE_ONLY_FIELDS": True,
    # Enable DB-side ROW_NUMBER window slicing for reverse-FK nested paginated
    # lists (LimitOffset and Page paginators). Set to False to opt out globally
    # and fall back to the in-memory order+slice path (exact pre-Phase-C
    # behavior).
    "OPTIMIZE_NESTED_PAGINATION": True,
    # Subscriptions: "id_only" (default) makes change notifications carry only
    # {<pk field name>: <pk>} and skip serializing the instance; "full" serializes
    # the full instance with the subscription's backend. Can be overridden per subscription
    # with `Meta.payload_mode` ("full" | "id_only").
    "SUBSCRIPTION_PAYLOAD_MODE": "id_only",
    # HTTP/view hardening
    # Maximum number of operations permitted in a single batch request.
    # Batch requests exceeding this limit are rejected with HTTP 400.
    # Default 10 is a pragmatic safety cap against request-amplification DoS.
    # Set to None to allow batches of any length (current pre-v1.2.1 behavior,
    # not recommended for public APIs — use only when you control all clients
    # and have independent rate limiting at the gateway/proxy level).
    "MAX_BATCH_SIZE": 10,
    # Security middlewares
    # Allow __schema/__type introspection (DisableIntrospectionMiddleware).
    "ALLOW_INTROSPECTION": False,
    # Let superusers bypass the introspection block.
    "INTROSPECTION_ALLOW_SUPERUSER": True,
    # Extra top-level field names requiring auth (AuthenticatedFieldsMiddleware)
    # when not using DjangoGraphQLSchema.
    "PROTECTED_FIELDS": (),
    # Restrict the AUTHENTICATED endpoint (AuthenticatedGraphQLView) to members
    # of this Django auth Group (by name). "" (default) disables the gate (zero
    # impact). Non-members get HTTP 403 before any GraphQL parsing/execution; an
    # ACTIVE SUPERUSER always passes (hardcoded bypass). The public GraphQLView
    # is NOT affected. Not an import string.
    "API_ACCESS_GROUP": "",
    # Serve each AUTHENTICATED request (AuthenticatedGraphQLView) a permission-
    # scoped pruned schema: fields whose required perms the caller lacks are
    # ABSENT (a pruned field reads as "Cannot query field", not an authz error).
    # Read PER-REQUEST. Default False = byte-identical to today (feature inert).
    # An active superuser always gets the full schema; a non-superuser whose
    # pruned Query root is empty gets the endpoint's generic 403. The public
    # GraphQLView is NEVER pruned. Requires a labeled DjangoGraphQLSchema.
    "PERMISSION_SCOPED_SCHEMA": False,
    # In-process LRU bound (signature -> pruned schema) for PERMISSION_SCOPED_
    # SCHEMA. Entries are keyed by the caller's permission signature (perms ∩
    # schema label-set), never by user id, so distinct permission profiles share
    # one entry. Least-recently-used entries evict past this cap. Benchmark-
    # calibrated (64 holds a realistic ~50-signature working set at ~97% hit
    # rate for a few KiB each); raise it only if you have many distinct profiles.
    "PERMISSION_SCHEMA_CACHE_MAXSIZE": 64,
    # Global default maximum query depth (nested object levels) enforced by
    # DepthLimitValidationRule. None disables the global limit; per-type
    # `Meta.max_depth` still applies on top of (or instead of) it.
    "MAX_QUERY_DEPTH": None,
    # Query cost analysis (CostLimitValidationRule). Estimated cost of a query is
    # `own_cost + pagination_multiplier * sum(children)`; scalars cost 0, object/
    # list fields cost 1 unless a type declares `Meta.complexity`.
    "MAX_QUERY_COST": None,  # None disables the budget (queries are never blocked)
    "EXPOSE_QUERY_COST": False,  # True -> add `extensions.cost` to responses
    # Multiplier for a list field whose page size is unknown (no literal/variable
    # value and no MAX_PAGE_SIZE cap to fall back to).
    "DEFAULT_LIST_MULTIPLIER": 10,
    # Argument names treated as a list's page size when costing a field.
    "COST_PAGINATION_ARGS": ("limit", "page_size", "first", "last"),
    # Native filtering: the base lookup set every filterable field receives when
    # `Meta.filter_fields` declares a field in list form (text/ordered fields
    # also get type-specific lookups on top). See `filtering/lookups.py`.
    "COMMON_FILTER_LOOKUPS": ("exact", "in", "isnull"),
    # Optimizer safety net: when True, any exception raised inside the queryset
    # optimization block degrades to the un-optimized queryset and logs a WARNING
    # instead of surfacing a 500. Default False (fail loud).
    "OPTIMIZER_SAFE_MODE": False,
    # Inject DB annotations declared via AnnotatedField only when the field is
    # selected in the GraphQL query. This is the DEPENDABLE runtime kill-switch
    # for annotation injection — independent of OPTIMIZE_ONLY_FIELDS.
    # Child annotations inject even with .only() narrowing off (the prefetch-
    # narrow pass fires on EITHER setting — see utils §6).
    # NOTE: OPTIMIZER_SAFE_MODE does NOT cover errors from a malformed Expression
    # that raises FieldError at SQL-eval time (outside the build boundary). Set
    # this False to disable injection entirely without a code change.
    "OPTIMIZE_ANNOTATED_FIELDS": True,
    # ---------------------------------------------------------------------------
    # File uploads (Base64FileInput — opt-in, import from django_graphex.uploads)
    # ---------------------------------------------------------------------------
    # Maximum decoded size (bytes) of a single base64 upload. REQUIRED when
    # Base64FileInput is used; raises ImproperlyConfigured if unset and no
    # per-field override is given. A per-field max_size= kwarg on
    # to_uploaded_file() / decode_base64_file() overrides this global cap.
    # Example: 5 * 1024 * 1024  →  5 MB
    "MAX_UPLOAD_SIZE": None,
    # Maximum total HTTP request body length (bytes) enforced by
    # BaseGraphQLView.dispatch BEFORE the JSON body is parsed. This is the
    # primary memory-safety cap: the base64 string is already in RAM once the
    # JSON body is parsed, so this guard prevents it from ever loading beyond
    # the threshold. None disables the guard (not recommended for public APIs).
    # The per-field decoded-size pre-check in decode_base64_file() is a
    # secondary guard that saves the decode allocation. Both guards compose:
    # peak memory ≈ body_size + MAX_UPLOAD_SIZE (batch runs sequentially).
    # For batch requests, this cap applies to the total body of all operations.
    # Example: 20 * 1024 * 1024  →  20 MB total body
    "MAX_REQUEST_BODY_SIZE": None,
    # ---------------------------------------------------------------------------
    # Schema / middleware (formerly a separate schema namespace; the key names
    # are kept close to graphene-django's for familiarity).
    # ---------------------------------------------------------------------------
    # Dotted path (or object) of the schema GraphQLView serves when no schema=
    # is passed to .as_view(). None = you must pass schema= explicitly.
    "SCHEMA": None,
    "SCHEMA_OUTPUT": "schema.json",  # default output file for the graphql_schema command
    "SCHEMA_INDENT": 2,  # JSON indent for graphql_schema output
    # GraphQL execution middleware (dotted paths or objects); the view's default
    # when middleware= is not passed. Bundled security middlewares plug in here.
    "MIDDLEWARE": (),
    # WebSocket subscription endpoint path advertised to clients (None = default).
    "SUBSCRIPTION_PATH": None,
    # Wrap each mutation in transaction.atomic() so a failure rolls back its writes.
    "ATOMIC_MUTATIONS": False,
    # Cap the number of GraphQL validation errors returned (None = no cap).
    "MAX_VALIDATION_ERRORS": None,
    # camelCase the field/path keys in error objects to match the wire schema.
    "CAMELCASE_ERRORS": True,
    # graphql-transport-ws: seconds the server waits for the first
    # ``connection_init`` after the socket opens before closing with 4408
    # (``connectionInitWaitTimeout``). The transport factory may override it.
    "SUBSCRIPTION_CONNECTION_INIT_TIMEOUT": 3.0,
}


# List of settings that may be in string import notation.
IMPORT_STRINGS = ("DEFAULT_PAGINATION_CLASS", "MIDDLEWARE", "SCHEMA")


class _BaseAPISettings:
    """Read a namespaced Django setting with defaults and import strings.

    Self-contained (no DRF dependency): mirrors the small slice of DRF's
    ``APISettings`` the package used, so ``django-graphex`` imports
    without ``djangorestframework`` installed. A subclass/instance reads one
    Django setting namespace (``DJANGO_GRAPHEX``), resolving missing keys from
    ``defaults`` and dotted import-path strings for keys listed in
    ``import_strings``.
    """

    def __init__(
        self,
        user_settings: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        import_strings: tuple[str, ...] | None = None,
        setting_name: str = "",
    ) -> None:
        """Initialize the settings reader.

        Args:
            user_settings: Explicit user settings (else read from Django).
            defaults: The default values mapping.
            import_strings: Keys whose string values are import paths.
            setting_name: The Django setting namespace to read (e.g.
                ``"DJANGO_GRAPHEX"``); also used in error messages.
        """
        if user_settings:
            self._user_settings = user_settings
        self.defaults = defaults or {}
        self.import_strings = import_strings or ()
        self.setting_name = setting_name

    @property
    def user_settings(self) -> dict[str, Any]:
        """Return the namespaced Django setting mapping (cached)."""
        if not hasattr(self, "_user_settings"):
            self._user_settings = getattr(settings, self.setting_name, {})
        return self._user_settings

    def __getattr__(self, attr: str) -> Any:
        """Resolve a setting from user settings, falling back to defaults.

        Args:
            attr: The setting name.

        Returns:
            The (possibly import-resolved) setting value.

        Raises:
            AttributeError: If ``attr`` is not a known setting.
        """
        if attr not in self.defaults:
            raise AttributeError(f"Invalid {self.setting_name} setting: '{attr}'")
        try:
            value = self.user_settings[attr]
        except KeyError:
            value = self.defaults[attr]
        if attr in self.import_strings:
            value = _perform_import(value, attr)
        setattr(self, attr, value)
        return value

    def reload(self) -> None:
        """Clear all cached setting values and re-read from Django on next access.

        Called by ``reload_api_settings`` when ``setting_changed`` fires so that
        ``override_settings(...)`` works correctly in tests without replacing the
        singleton object (which would break any ``from .settings import
        graphql_api_settings`` bindings held in other modules).
        """
        # Remove the cached _user_settings dict so the property re-reads from Django.
        self.__dict__.pop("_user_settings", None)
        # Remove any individually cached setting attributes (set via setattr in __getattr__).
        for key in list(self.defaults):
            self.__dict__.pop(key, None)


class GraphQLAPISettings(_BaseAPISettings):
    """Read the "DJANGO_GRAPHEX" settings namespace.

    Binds the base reader to the "DJANGO_GRAPHEX" namespace with this package's
    "DEFAULTS" and "IMPORT_STRINGS", so callers get a ready-to-use singleton.
    """

    def __init__(
        self,
        user_settings: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        import_strings: tuple[str, ...] | None = None,
    ) -> None:
        """Initialize the reader bound to the "DJANGO_GRAPHEX" namespace.

        Args:
            user_settings: Explicit user settings (else read from Django).
            defaults: The default values mapping (defaults to "DEFAULTS").
            import_strings: Keys whose string values are import paths
                (defaults to "IMPORT_STRINGS").
        """
        super().__init__(
            user_settings,
            defaults or DEFAULTS,
            import_strings or IMPORT_STRINGS,
            "DJANGO_GRAPHEX",
        )


def _perform_import(value: Any, setting_name: str) -> Any:
    """Resolve dotted import-path strings in a setting value.

    Args:
        value: The raw setting value (string, list/tuple, or already resolved).
        setting_name: The setting key (for error messages).

    Returns:
        The value with any import-path strings resolved to objects.

    Raises:
        ImportError: If an import-path string cannot be imported.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return _import_from_string(value, setting_name)
    if isinstance(value, (list, tuple)):
        return [
            _import_from_string(item, setting_name) if isinstance(item, str) else item
            for item in value
        ]
    return value


def _import_from_string(value: str, setting_name: str) -> Any:
    """Import an object from its dotted path.

    Args:
        value: The dotted import path (``"pkg.module.Object"``).
        setting_name: The setting key (for error messages).

    Returns:
        The imported object.

    Raises:
        ImportError: If the path cannot be imported.
    """
    try:
        return import_string(value)
    except ImportError as exc:
        raise ImportError(
            "Could not import '{}' for setting '{}'. {}: {}.".format(
                value, setting_name, exc.__class__.__name__, exc
            )
        )


#: The single reader for every django-graphex setting (the ``DJANGO_GRAPHEX``
#: namespace), including the schema/middleware/subscription keys that used to
#: live in a separate schema-settings dict.
graphql_api_settings = GraphQLAPISettings(None, DEFAULTS, IMPORT_STRINGS)


def reload_api_settings(*args: Any, **kwargs: Any) -> None:
    """Clear the cached settings on the singleton when "DJANGO_GRAPHEX" changes.

    Keeps "override_settings(DJANGO_GRAPHEX=...)" working in tests. Uses
    "singleton.reload()" rather than replacing the object so that any
    "from .settings import graphql_api_settings" bindings in other modules
    continue to reference the correct (updated) singleton.

    Args:
        *args: positional arguments from the "setting_changed" signal.
        **kwargs: keyword arguments from the signal, including "setting".
    """
    setting = kwargs.get("setting")
    if setting == "DJANGO_GRAPHEX":
        graphql_api_settings.reload()


setting_changed.connect(reload_api_settings)


def check_unknown_settings(
    app_configs: list[AppConfig] | None = None, **kwargs: Any
) -> list[CheckMessage]:
    """Report keys of the "DJANGO_GRAPHEX" dict that are not real settings.

    An unknown key is silently dropped by the reader, so the setting it was
    meant to configure keeps its library default: a misspelled cap
    ("MAX_PAGE_SIZ") or security flag ("CACHE_ACTIV") does nothing at all.
    This is a WARNING and never an exception, so an app that starts today
    keeps starting. Registered from "DjangoGraphexConfig.ready" under
    "Tags.compatibility", so "manage.py check" surfaces it.

    Args:
        app_configs: The app configs Django is checking, or None for all
            (unused: the setting is global).
        **kwargs: Extra arguments passed by the checks framework.

    Returns:
        A single-element list carrying the warning when unknown keys exist,
        otherwise an empty list.
    """
    unknown = sorted(set(graphql_api_settings.user_settings) - set(DEFAULTS))
    if not unknown:
        return []
    hints = []
    for key in unknown:
        closest = get_close_matches(key, DEFAULTS, n=1)
        hints.append(
            "'{}' -> did you mean '{}'?".format(key, closest[0])
            if closest
            else "'{}' has no close match — remove it.".format(key)
        )
    return [
        CheckWarning(
            "Unknown DJANGO_GRAPHEX setting(s) {!r}. They are IGNORED, so the "
            "setting they were meant to configure keeps its default.".format(unknown),
            hint=" ".join(hints),
            id="django_graphex.W001",
        )
    ]
