"""Vendored ``GRAPHENE`` settings reader (formerly ``graphene_django.settings``).

Self-contained replacement so the package reads the project's ``GRAPHENE``
Django setting without depending on ``graphene-django``. It mirrors that
package's behavior: defaults, string import-path resolution for ``SCHEMA`` /
``MIDDLEWARE``, attribute access, and live reload on ``setting_changed`` (so
``override_settings`` works in tests). It intentionally does not use DRF's
``APISettings`` (we are also shedding the hard DRF dependency).
"""

from __future__ import annotations

import importlib
from typing import Any

from django.conf import settings
from django.test.signals import setting_changed

#: Defaults for the keys this package reads from ``GRAPHENE`` (a superset is
#: harmless; kept close to graphene-django's for familiarity).
DEFAULTS: dict[str, Any] = {
    "SCHEMA": None,
    "MIDDLEWARE": (),
    "SUBSCRIPTION_PATH": None,
    "ATOMIC_MUTATIONS": False,
    "MAX_VALIDATION_ERRORS": None,
    "CAMELCASE_ERRORS": True,
}

#: Settings that may be given as dotted import-path strings.
IMPORT_STRINGS = ("MIDDLEWARE", "SCHEMA")


def perform_import(val: Any, setting_name: str) -> Any:
    """Resolve dotted import-path strings in a setting value.

    Args:
        val: The raw setting value (string, list/tuple, or already-resolved).
        setting_name: The setting key (for error messages).

    Returns:
        The value with any import-path strings resolved to objects.
    """
    if val is None:
        return None
    if isinstance(val, str):
        return import_from_string(val, setting_name)
    if isinstance(val, (list, tuple)):
        return [import_from_string(item, setting_name) for item in val]
    return val


def import_from_string(val: str, setting_name: str) -> Any:
    """Import an object from its dotted path.

    Args:
        val: The dotted import path (``"pkg.module.Object"``).
        setting_name: The setting key (for error messages).

    Returns:
        The imported object.

    Raises:
        ImportError: If the path cannot be imported.
    """
    try:
        module_path, class_name = val.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError, ValueError) as exc:
        raise ImportError(
            "Could not import '{}' for GRAPHENE setting '{}'. {}: {}.".format(
                val, setting_name, exc.__class__.__name__, exc
            )
        )


class GrapheneSettings:
    """Access ``GRAPHENE`` settings as attributes, with defaults and imports."""

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
        """Return the project's ``GRAPHENE`` setting mapping (cached)."""
        if not hasattr(self, "_user_settings"):
            self._user_settings = getattr(settings, "GRAPHENE", {})
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
            raise AttributeError(f"Invalid GRAPHENE setting: '{attr}'")
        try:
            val = self.user_settings[attr]
        except KeyError:
            val = self.defaults[attr]
        if attr in self.import_strings:
            val = perform_import(val, attr)
        setattr(self, attr, val)
        return val


graphene_settings = GrapheneSettings(None, DEFAULTS, IMPORT_STRINGS)


def reload_graphene_settings(*args: Any, **kwargs: Any) -> None:
    """Rebuild ``graphene_settings`` when the ``GRAPHENE`` setting changes."""
    global graphene_settings
    if kwargs.get("setting") == "GRAPHENE":
        graphene_settings = GrapheneSettings(None, DEFAULTS, IMPORT_STRINGS)


setting_changed.connect(reload_graphene_settings)
