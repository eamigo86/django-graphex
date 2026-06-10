"""Settings configuration for django-graphex.

This module provides configuration management for the django-graphex
package, including pagination, caching, and other global settings.
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
    # Subscriptions: when False (default), change notifications carry only
    # {"id": <pk>} and skip serializing the instance; set True to serialize the
    # full instance with the subscription's backend. Can be overridden
    # per subscription with `Meta.serialize_data`.
    "SUBSCRIPTION_SERIALIZE_DATA": False,
    # Security middlewares
    # Allow __schema/__type introspection (DisableIntrospectionMiddleware).
    "ALLOW_INTROSPECTION": False,
    # Let superusers bypass the introspection block.
    "INTROSPECTION_ALLOW_SUPERUSER": True,
    # Extra top-level field names requiring auth (AuthenticatedFieldsMiddleware)
    # when not using ExtraGraphQLSchema.
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
}


# List of settings that may be in string import notation.
IMPORT_STRINGS = ("DEFAULT_PAGINATION_CLASS",)


def _perform_import(value: Any, setting_name: str) -> Any:
    """Resolve dotted import-path strings in a setting value."""
    if value is None:
        return None
    if isinstance(value, str):
        return import_string(value)
    if isinstance(value, (list, tuple)):
        return [
            import_string(item) if isinstance(item, str) else item for item in value
        ]
    return value


class GraphQLAPISettings:
    """Read ``DJANGO_GRAPHEX`` settings with defaults and import strings.

    Self-contained (no DRF dependency): mirrors the small slice of DRF's
    ``APISettings`` the package used, so ``django-graphex`` imports
    without ``djangorestframework`` installed.
    """

    def __init__(
        self,
        user_settings: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        import_strings: tuple[str, ...] | None = None,
    ) -> None:
        """Initialize the settings reader.

        Args:
            user_settings: Explicit user settings (else read from Django).
            defaults: The default values mapping.
            import_strings: Keys whose string values are import paths.
        """
        if user_settings:
            self._user_settings = user_settings
        self.defaults = defaults or DEFAULTS
        self.import_strings = import_strings or IMPORT_STRINGS

    @property
    def user_settings(self) -> dict[str, Any]:
        """Return the ``DJANGO_GRAPHEX`` mapping (cached)."""
        if not hasattr(self, "_user_settings"):
            self._user_settings = getattr(settings, "DJANGO_GRAPHEX", {})
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
            raise AttributeError(f"Invalid DJANGO_GRAPHEX setting: '{attr}'")
        try:
            value = self.user_settings[attr]
        except KeyError:
            value = self.defaults[attr]
        if attr in self.import_strings:
            value = _perform_import(value, attr)
        setattr(self, attr, value)
        return value


graphql_api_settings = GraphQLAPISettings(None, DEFAULTS, IMPORT_STRINGS)


def reload_graphql_api_settings(*args: Any, **kwargs: Any) -> None:
    """Reload GraphQL API settings when Django settings change.

    Args:
        *args: positional arguments from the "setting_changed" signal.
        **kwargs: keyword arguments from the signal, including "setting" and
            "value".
    """
    global graphql_api_settings
    setting, value = kwargs["setting"], kwargs["value"]
    if setting == "DJANGO_GRAPHEX":
        graphql_api_settings = GraphQLAPISettings(value, DEFAULTS, IMPORT_STRINGS)


setting_changed.connect(reload_graphql_api_settings)
