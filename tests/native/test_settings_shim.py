"""GRAPHEX settings reader tests.

Tests the GRAPHEX namespace (GraphexSettings) and the
``graphex_or_graphene_settings`` public name.

BREAKING CHANGE (2.0): as of S2 the settings layer reads ONLY the ``GRAPHEX``
Django-setting dict. The legacy ``GRAPHENE`` namespace is no longer consulted
and the per-key dual-read / warn-once fallback shim has been removed. The public
name ``graphex_or_graphene_settings`` is retained as a backwards-compatible
alias for the GRAPHEX-only reader so existing reader call-sites (views.py and
the subscription transports) need no edits.

Backend-agnostic: these tests run under BOTH GDX_BACKEND=native and
GDX_BACKEND=graphene (no GDX_BACKEND pre-condition needed here).
"""

from __future__ import annotations

import warnings

from django.test import override_settings

# ---------------------------------------------------------------------------
# 1. GraphexSettings — reads GRAPHEX namespace
# ---------------------------------------------------------------------------


class TestGraphexSettings:
    """GraphexSettings reads from settings.GRAPHEX."""

    def test_reads_subscription_path_from_graphex(self):
        """GraphexSettings.SUBSCRIPTION_PATH returns the value from user_settings.

        Uses SUBSCRIPTION_PATH (not in GRAPHEX_IMPORT_STRINGS) to avoid the
        import-resolution step that would fail with a fake dotted-path string.
        """
        from django_graphex.settings import GraphexSettings

        s = GraphexSettings(user_settings={"SUBSCRIPTION_PATH": "/ws/graphql/"})
        assert s.SUBSCRIPTION_PATH == "/ws/graphql/"

    @override_settings(GRAPHEX={})
    def test_defaults_when_graphex_key_missing(self):
        """Missing key falls back to GRAPHEX_DEFAULTS.

        An empty ``user_settings={}`` is falsy, so the reader falls back to the
        Django ``GRAPHEX`` dict; ``override_settings(GRAPHEX={})`` empties it so
        every key resolves to its package default (independent of the harness's
        global ``GRAPHEX`` schema config).
        """
        from django_graphex.settings import GraphexSettings

        s = GraphexSettings(user_settings={})
        # SCHEMA default is None
        assert s.SCHEMA is None
        assert s.SUBSCRIPTION_PATH is None

    def test_reload_rereads_from_django_settings(self):
        """reload() drops the cached value AND re-reads the namespace from Django.

        A GraphexSettings with no explicit user_settings reads from
        ``settings.GRAPHEX``. After the value is cached, changing the Django
        setting and calling reload() must surface the NEW value on next access —
        proving reload() clears both the per-key cache and the cached
        ``_user_settings`` dict.
        """
        from django_graphex.settings import GraphexSettings

        s = GraphexSettings()  # no explicit user_settings -> reads from Django

        with override_settings(GRAPHEX={"SUBSCRIPTION_PATH": "/ws/first/"}):
            s.reload()  # ensure we read the overridden namespace
            assert s.SUBSCRIPTION_PATH == "/ws/first/"  # reads and caches

        with override_settings(GRAPHEX={"SUBSCRIPTION_PATH": "/ws/second/"}):
            # Without reload the cached "/ws/first/" would still be returned;
            # reload() must drop the cache and re-read from Django settings.
            s.reload()
            assert s.SUBSCRIPTION_PATH == "/ws/second/"

    @override_settings(GRAPHEX={"SUBSCRIPTION_PATH": "/ws/override/"})
    def test_reads_from_django_settings_when_no_user_settings(self):
        """Without explicit user_settings, reads from Django settings.GRAPHEX."""
        from django_graphex.settings import GraphexSettings

        s = GraphexSettings()
        assert s.SUBSCRIPTION_PATH == "/ws/override/"


# ---------------------------------------------------------------------------
# 2. graphex_or_graphene_settings — GRAPHEX-only (legacy GRAPHENE ignored)
# ---------------------------------------------------------------------------


class TestGraphexOrGrapheneSettings:
    """graphex_or_graphene_settings reads ONLY the GRAPHEX namespace.

    BREAKING CHANGE (2.0): the GRAPHENE-fallback / dual-read / warn-once
    behavior has been removed. The public name is retained as an alias to the
    GRAPHEX-only reader for call-site compatibility.
    """

    @override_settings(GRAPHEX={"SUBSCRIPTION_PATH": "/ws/only-graphex/"})
    def test_reads_value_from_graphex(self):
        """GRAPHEX value is returned with NO warning."""
        from django_graphex.settings import graphex_or_graphene_settings

        graphex_or_graphene_settings.reload()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            path = graphex_or_graphene_settings.SUBSCRIPTION_PATH
        assert path == "/ws/only-graphex/"
        deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecation_warnings) == 0

    @override_settings(GRAPHEX={"SUBSCRIPTION_PATH": "/ws/graphex/"})
    def test_graphex_wins_when_both_set(self):
        """When both GRAPHEX and GRAPHENE are set, GRAPHEX wins — GRAPHENE ignored.

        Uses SUBSCRIPTION_PATH (not in GRAPHEX_IMPORT_STRINGS) to avoid the
        import-resolution step that would fail with a fake dotted-path string.
        """
        with override_settings(GRAPHENE={"SUBSCRIPTION_PATH": "/ws/graphene/"}):
            from django_graphex.settings import graphex_or_graphene_settings

            graphex_or_graphene_settings.reload()
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                path = graphex_or_graphene_settings.SUBSCRIPTION_PATH
            assert path == "/ws/graphex/"
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) == 0, "GRAPHEX path must NOT warn"

    def test_legacy_graphene_namespace_is_ignored(self):
        """BREAKING CHANGE: a value set ONLY in GRAPHENE is no longer read.

        Pre-2.0 the shim fell back to GRAPHENE (with a DeprecationWarning).
        As of S2 the GRAPHENE namespace is not consulted at all: the reader
        returns the package DEFAULT (here ``None``) and emits NO warning.
        """
        with override_settings(GRAPHENE={"SUBSCRIPTION_PATH": "/ws/legacy/"}, GRAPHEX={}):
            from django_graphex.settings import graphex_or_graphene_settings

            graphex_or_graphene_settings.reload()
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                path = graphex_or_graphene_settings.SUBSCRIPTION_PATH
            # GRAPHENE is ignored — the GRAPHEX default (None) is returned.
            assert path is None, "GRAPHENE value must NOT be read"
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 0, (
                "GRAPHENE namespace no longer triggers a DeprecationWarning"
            )

    def test_neither_set_returns_defaults(self):
        """When neither GRAPHEX nor GRAPHENE is set, defaults apply (no error)."""
        with override_settings(GRAPHENE={}, GRAPHEX={}):
            from django_graphex.settings import graphex_or_graphene_settings

            graphex_or_graphene_settings.reload()
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                schema = graphex_or_graphene_settings.SCHEMA
            assert schema is None
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) == 0


# ---------------------------------------------------------------------------
# 2b. GRAPHENE namespace fully decoupled — keys live only in GRAPHEX
# ---------------------------------------------------------------------------


class TestGrapheneNamespaceDecoupled:
    """The reader ignores the legacy GRAPHENE namespace entirely.

    BREAKING CHANGE (2.0): pre-2.0 the shim resolved each key independently
    against GRAPHEX then GRAPHENE so incremental migration would not drop keys
    still in GRAPHENE. That dual-read is removed: a key configured only in
    GRAPHENE is silently dropped (returns the GRAPHEX default). Projects MUST
    move all keys to GRAPHEX. This is documented for UPGRADE-2.0 (S8).
    """

    @override_settings(
        GRAPHEX={"SUBSCRIPTION_PATH": "/ws/graphex/"},
        GRAPHENE={"MIDDLEWARE": ["x.Mw"]},
    )
    def test_graphene_only_key_is_not_read(self):
        """SUBSCRIPTION_PATH comes from GRAPHEX; MIDDLEWARE (only in GRAPHENE) is dropped.

        Uses SUBSCRIPTION_PATH (not an import string) for the GRAPHEX key so the
        import-resolution step is skipped. MIDDLEWARE is configured ONLY in
        GRAPHENE — with GRAPHENE ignored, MIDDLEWARE resolves to the GRAPHEX
        default (``()``), NOT ``["x.Mw"]``.
        """
        from django_graphex.settings import graphex_or_graphene_settings

        graphex_or_graphene_settings.reload()

        # GRAPHEX key — resolved from GRAPHEX, no warning.
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            sub_path = graphex_or_graphene_settings.SUBSCRIPTION_PATH
        assert sub_path == "/ws/graphex/"
        graphex_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(graphex_warnings) == 0, "GRAPHEX-owned key must NOT warn"

        # MIDDLEWARE is ONLY in GRAPHENE; GRAPHENE is no longer consulted, so the
        # GRAPHEX default is returned (a list copy of the () default).
        assert list(graphex_or_graphene_settings.MIDDLEWARE) == []


# ---------------------------------------------------------------------------
# 3. reload_api_settings signal handler handles GRAPHEX
# ---------------------------------------------------------------------------


class TestReloadApiSettingsHandlesGraphex:
    """reload_api_settings clears graphex_or_graphene_settings when GRAPHEX changes."""

    @override_settings(GRAPHEX={"SUBSCRIPTION_PATH": "/ws/initial/"})
    def test_override_settings_graphex_reloads_shim(self):
        """override_settings(GRAPHEX=...) causes the reader to reflect the new value.

        Uses SUBSCRIPTION_PATH (not an import string) to avoid triggering
        import-resolution for a fake dotted-path string.
        """
        from django_graphex.settings import graphex_or_graphene_settings

        graphex_or_graphene_settings.reload()
        # Force cache
        _ = graphex_or_graphene_settings.SUBSCRIPTION_PATH

        with override_settings(GRAPHEX={"SUBSCRIPTION_PATH": "/ws/new/"}):
            # The setting_changed signal fires; reader should reload
            assert graphex_or_graphene_settings.SUBSCRIPTION_PATH == "/ws/new/"


# ---------------------------------------------------------------------------
# 4. views.py consumers use the shim (behavioral test)
# ---------------------------------------------------------------------------


class TestViewsUsesShim:
    """BaseGraphQLView reads SCHEMA/MIDDLEWARE/SUBSCRIPTION_PATH from the shim."""

    def test_view_reads_schema_from_graphex(self):
        """When GRAPHEX.SCHEMA is set, BaseGraphQLView.__init__ picks it up."""
        from unittest.mock import patch

        import graphene

        from django_graphex.settings import graphex_or_graphene_settings

        class _Q(graphene.ObjectType):
            ping = graphene.String()

        schema = graphene.Schema(query=_Q)

        graphex_or_graphene_settings.reload()

        with patch.object(graphex_or_graphene_settings, "SCHEMA", schema):
            from django_graphex.views import BaseGraphQLView

            view = BaseGraphQLView()
            assert view.schema is schema

    def test_view_reads_subscription_path_from_graphex(self):
        """subscription_path is read from the shim (GRAPHEX.SUBSCRIPTION_PATH)."""
        import graphene

        class _Q(graphene.ObjectType):
            ping = graphene.String()

        schema = graphene.Schema(query=_Q)

        from unittest.mock import patch

        from django_graphex.settings import graphex_or_graphene_settings

        graphex_or_graphene_settings.reload()

        with (
            patch.object(graphex_or_graphene_settings, "SCHEMA", schema),
            patch.object(graphex_or_graphene_settings, "SUBSCRIPTION_PATH", "/ws/graphql/"),
            patch.object(graphex_or_graphene_settings, "MIDDLEWARE", []),
        ):
            from django_graphex.views import BaseGraphQLView

            view = BaseGraphQLView()
            assert view.subscription_path == "/ws/graphql/"


# ---------------------------------------------------------------------------
# 5. _auth_middleware_configured honors GRAPHEX
# ---------------------------------------------------------------------------


class TestAuthMiddlewareConfiguredHonorsGraphex:
    """_auth_middleware_configured checks GRAPHEX['MIDDLEWARE'] too."""

    @override_settings(
        GRAPHEX={
            "MIDDLEWARE": [
                "django_graphex.middleware.AuthenticatedFieldsMiddleware"
            ]
        }
    )
    def test_returns_true_when_middleware_in_graphex(self):
        """_auth_middleware_configured returns True when GRAPHEX has the middleware."""
        from django_graphex.schema import _auth_middleware_configured

        assert _auth_middleware_configured() is True

    @override_settings(GRAPHEX={}, GRAPHENE={})
    def test_returns_false_when_middleware_absent(self):
        """_auth_middleware_configured returns False when middleware not in either."""
        from django_graphex.schema import _auth_middleware_configured

        assert _auth_middleware_configured() is False

    @override_settings(
        GRAPHEX={},
        GRAPHENE={
            "MIDDLEWARE": [
                "django_graphex.middleware.AuthenticatedFieldsMiddleware"
            ]
        },
    )
    def test_ignores_legacy_graphene_namespace(self):
        """BREAKING CHANGE (S2): the legacy GRAPHENE namespace is NOT consulted.

        Pre-2.0 ``_auth_middleware_configured`` unioned GRAPHEX + GRAPHENE
        ``MIDDLEWARE``. As of S2 the GRAPHENE namespace is retired everywhere:
        a middleware configured ONLY under GRAPHENE must be ignored, so the
        check returns False even though the middleware is present under the
        legacy key.
        """
        from django_graphex.schema import _auth_middleware_configured

        assert _auth_middleware_configured() is False
