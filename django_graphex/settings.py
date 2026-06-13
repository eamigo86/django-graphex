"""Settings configuration for django-graphex.

This module provides configuration management for the django-graphex
package, including pagination, caching, and other global settings. It reads
both the ``DJANGO_GRAPHEX`` namespace (this package's own settings) and the
``GRAPHENE`` namespace (the schema/middleware settings formerly read by
``graphene-django``), each exposed through its own singleton.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.test.signals import setting_changed
from django.utils.module_loading import import_string

DEFAULTS = {
    # Pagination
    "DEFAULT_PAGINATION_CLASS": "django_graphex.paginations.LimitOffsetGraphqlPagination",
    "DEFAULT_PAGE_SIZE": None,
    "MAX_PAGE_SIZE": None,
    "CLEAN_RESPONSE": False,
    "CACHE_ACTIVE": False,
    "CACHE_TIMEOUT": 300,  # seconds (default 5 min)
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
    # Subscriptions: when False (default), change notifications carry only
    # {"id": <pk>} and skip serializing the instance; set True to serialize the
    # full instance with the subscription's backend. Can be overridden
    # per subscription with `Meta.serialize_data`.
    "SUBSCRIPTION_SERIALIZE_DATA": False,
    # Channel ownership guard (v1.2.1+). When True (default), the subscribe
    # mutation verifies that the channel_id was registered by the same session
    # that is calling subscribe, using the Django cache as the backing store.
    # Multi-worker deployments must configure a SHARED cache backend (Redis /
    # Memcached) so the guard works across processes; with the default LocMemCache
    # (per-process), HTTP and WS requests must land on the same worker.
    # Set to False to bypass the guard entirely — do this only as a temporary
    # escape hatch when a shared cache cannot be provisioned; it disables the
    # channel-hijack protection.
    "SUBSCRIPTIONS_CHANNEL_GUARD": True,
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
    # Global default maximum query depth (nested object levels) enforced by
    # DepthLimitValidationRule. None disables the global limit; per-type
    # `Meta.max_deep` still applies on top of (or instead of) it.
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
}


# List of settings that may be in string import notation.
IMPORT_STRINGS = ("DEFAULT_PAGINATION_CLASS",)


#: Defaults for the keys this package reads from ``GRAPHENE`` (a superset is
#: harmless; kept close to graphene-django's for familiarity).
GRAPHENE_DEFAULTS: dict[str, Any] = {
    "SCHEMA": None,
    "MIDDLEWARE": (),
    "SUBSCRIPTION_PATH": None,
    "ATOMIC_MUTATIONS": False,
    "MAX_VALIDATION_ERRORS": None,
    "CAMELCASE_ERRORS": True,
}

#: ``GRAPHENE`` settings that may be given as dotted import-path strings.
GRAPHENE_IMPORT_STRINGS = ("MIDDLEWARE", "SCHEMA")


class _BaseAPISettings:
    """Read a namespaced Django setting with defaults and import strings.

    Self-contained (no DRF dependency): mirrors the small slice of DRF's
    ``APISettings`` the package used, so ``django-graphex`` imports
    without ``djangorestframework`` installed. A subclass/instance reads one
    Django setting namespace (e.g. ``DJANGO_GRAPHEX`` or ``GRAPHENE``),
    resolving missing keys from ``defaults`` and dotted import-path strings for
    keys listed in ``import_strings``.
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
    """Read the ``DJANGO_GRAPHEX`` settings namespace."""

    def __init__(
        self,
        user_settings: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        import_strings: tuple[str, ...] | None = None,
    ) -> None:
        """Initialize the reader bound to the ``DJANGO_GRAPHEX`` namespace.

        Args:
            user_settings: Explicit user settings (else read from Django).
            defaults: The default values mapping (defaults to ``DEFAULTS``).
            import_strings: Keys whose string values are import paths
                (defaults to ``IMPORT_STRINGS``).
        """
        super().__init__(
            user_settings,
            defaults or DEFAULTS,
            import_strings or IMPORT_STRINGS,
            "DJANGO_GRAPHEX",
        )


class GrapheneSettings(_BaseAPISettings):
    """Read the ``GRAPHENE`` settings namespace."""

    def __init__(
        self,
        user_settings: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        import_strings: tuple[str, ...] | None = None,
    ) -> None:
        """Initialize the reader bound to the ``GRAPHENE`` namespace.

        Args:
            user_settings: Explicit user settings (else read from Django).
            defaults: The default values mapping (defaults to
                ``GRAPHENE_DEFAULTS``).
            import_strings: Keys whose string values are import paths
                (defaults to ``GRAPHENE_IMPORT_STRINGS``).
        """
        super().__init__(
            user_settings,
            defaults or GRAPHENE_DEFAULTS,
            import_strings or GRAPHENE_IMPORT_STRINGS,
            "GRAPHENE",
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


graphql_api_settings = GraphQLAPISettings(None, DEFAULTS, IMPORT_STRINGS)
graphene_settings = GrapheneSettings(None, GRAPHENE_DEFAULTS, GRAPHENE_IMPORT_STRINGS)


def reload_api_settings(*args: Any, **kwargs: Any) -> None:
    """Clear the cached settings on the singleton when a watched Django setting changes.

    Keeps ``override_settings(...)`` working in tests for both the
    ``DJANGO_GRAPHEX`` and ``GRAPHENE`` namespaces by re-reading from Django.
    Uses ``singleton.reload()`` rather than replacing the object so that any
    ``from .settings import graphql_api_settings`` bindings in other modules
    continue to reference the correct (updated) singleton.

    Args:
        *args: positional arguments from the "setting_changed" signal.
        **kwargs: keyword arguments from the signal, including "setting".
    """
    setting = kwargs.get("setting")
    if setting == "DJANGO_GRAPHEX":
        graphql_api_settings.reload()
    elif setting == "GRAPHENE":
        graphene_settings.reload()


setting_changed.connect(reload_api_settings)
