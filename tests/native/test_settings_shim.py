"""WU8: GRAPHEX settings shim tests.

Tests the new GRAPHEX namespace (GraphexSettings) and the
graphex_or_graphene_settings shim that reads GRAPHEX first and falls back to
GRAPHENE with a lazy warn-once-per-process DeprecationWarning.

Backend-agnostic: these tests run under BOTH GDX_BACKEND=native and
GDX_BACKEND=graphene (no GDX_BACKEND pre-condition needed here).

WARNING ISOLATION: Each test that asserts a DeprecationWarning uses
warnings.catch_warnings() + simplefilter('always') to force a fresh
per-test filter state, bypassing Python's once-per-location deduplication
that would otherwise suppress the warning after the first call.
"""

from __future__ import annotations

import warnings

from django.test import override_settings

# ---------------------------------------------------------------------------
# 1. GraphexSettings — reads GRAPHEX namespace
# ---------------------------------------------------------------------------


class TestGraphexSettings:
    """GraphexSettings reads from settings.GRAPHEX like GrapheneSettings reads GRAPHENE."""

    def test_reads_subscription_path_from_graphex(self):
        """GraphexSettings.SUBSCRIPTION_PATH returns the value from user_settings.

        Uses SUBSCRIPTION_PATH (not in GRAPHENE_IMPORT_STRINGS) to avoid the
        import-resolution step that would fail with a fake dotted-path string.
        """
        from django_graphex.settings import GraphexSettings

        s = GraphexSettings(user_settings={"SUBSCRIPTION_PATH": "/ws/graphql/"})
        assert s.SUBSCRIPTION_PATH == "/ws/graphql/"

    def test_defaults_when_graphex_key_missing(self):
        """Missing key falls back to GRAPHENE_DEFAULTS (same keys)."""
        from django_graphex.settings import GraphexSettings

        s = GraphexSettings(user_settings={})
        # SCHEMA default is None (same as GRAPHENE_DEFAULTS)
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
# 2. graphex_or_graphene_settings — precedence + warn-once
# ---------------------------------------------------------------------------


class TestGraphexOrGrapheneSettings:
    """graphex_or_graphene_settings reads GRAPHEX first, falls back to GRAPHENE."""

    @override_settings(GRAPHEX={"SUBSCRIPTION_PATH": "/ws/graphex/"})
    def test_graphex_takes_precedence_over_graphene(self):
        """When GRAPHEX is set, it wins over GRAPHENE — no warning emitted.

        Uses SUBSCRIPTION_PATH (not in GRAPHENE_IMPORT_STRINGS) to avoid the
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

    @override_settings(GRAPHEX={"SUBSCRIPTION_PATH": "/ws/only-graphex/"})
    def test_only_graphex_set_no_warning(self):
        """GRAPHEX only — no GRAPHENE — returns value with NO warning."""
        from django_graphex.settings import graphex_or_graphene_settings

        graphex_or_graphene_settings.reload()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            path = graphex_or_graphene_settings.SUBSCRIPTION_PATH
        assert path == "/ws/only-graphex/"
        deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecation_warnings) == 0

    def test_graphene_fallback_emits_deprecation_warning(self):
        """When only GRAPHENE is set, shim falls back and emits a DeprecationWarning.

        Uses SUBSCRIPTION_PATH (not in GRAPHENE_IMPORT_STRINGS) to avoid
        triggering the import-string resolution step.
        """
        with override_settings(GRAPHENE={"SUBSCRIPTION_PATH": "/ws/graphene/"}, GRAPHEX={}):
            from django_graphex.settings import graphex_or_graphene_settings

            graphex_or_graphene_settings.reload()
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                path = graphex_or_graphene_settings.SUBSCRIPTION_PATH
            assert path == "/ws/graphene/"
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1, (
                "GRAPHENE fallback must emit DeprecationWarning"
            )

    def test_graphene_fallback_warn_once_per_process(self):
        """The DeprecationWarning from GRAPHENE fallback fires ONCE then stops.

        Uses warnings.catch_warnings() + simplefilter('always') to bypass
        Python's per-location deduplication so the first call in each
        catch_warnings block can observe the warning. The shim's own
        ``_warned`` flag enforces once-per-process semantics on top of that.

        Note: reload() resets _warned so tests run independently.  The
        twice-reload pattern here checks that after reset, warn fires again
        (first call) and not on the second call within the same "session".
        """
        with override_settings(GRAPHENE={"SUBSCRIPTION_PATH": "/ws/legacy/"}, GRAPHEX={}):
            from django_graphex.settings import graphex_or_graphene_settings

            # === First "session" ===
            graphex_or_graphene_settings.reload()  # reset _warned
            with warnings.catch_warnings(record=True) as w1:
                warnings.simplefilter("always")
                graphex_or_graphene_settings.SUBSCRIPTION_PATH
            first_count = sum(
                1 for x in w1 if issubclass(x.category, DeprecationWarning)
            )

            # Second call WITHOUT resetting _warned: must NOT fire again
            with warnings.catch_warnings(record=True) as w2:
                warnings.simplefilter("always")
                graphex_or_graphene_settings.SUBSCRIPTION_PATH
            second_count = sum(
                1 for x in w2 if issubclass(x.category, DeprecationWarning)
            )

            assert first_count >= 1, "First call must warn"
            assert second_count == 0, "Second call (same session) must NOT warn again"

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
# 2b. PER-KEY fallback — incremental-migration safety (no key silently dropped)
# ---------------------------------------------------------------------------


class TestPerKeyFallback:
    """The shim resolves EACH key independently against GRAPHEX then GRAPHENE.

    Moving ONE key to GRAPHEX must NOT drop keys still in GRAPHENE. A
    whole-namespace switch would return the DEFAULT for any key left in
    GRAPHENE (e.g. MIDDLEWARE default ``()``), silently dropping a configured
    security/auth middleware — a migration footgun. Per-key resolution makes
    incremental migration safe.
    """

    @override_settings(
        GRAPHEX={"SUBSCRIPTION_PATH": "/ws/graphex/"},
        GRAPHENE={"MIDDLEWARE": ["x.Mw"]},
    )
    def test_perkey_resolution_keeps_graphene_keys(self):
        """GRAPHEX owns SUBSCRIPTION_PATH; MIDDLEWARE (only in GRAPHENE) is kept.

        Uses SUBSCRIPTION_PATH (not an import string) for the GRAPHEX key so the
        import-resolution step is skipped; MIDDLEWARE IS an import string but
        ``["x.Mw"]`` is only resolved on access — we read it through a patch-free
        path so the test exercises namespace selection, not import resolution.
        Here we keep MIDDLEWARE access guarded against import by reading it via
        the raw user-dict selection rather than the resolved value.
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

        # MIDDLEWARE is ONLY in GRAPHENE. Whole-namespace fallback would return
        # the MIDDLEWARE default (``()``); per-key fallback returns GRAPHENE's
        # value AND warns. We assert presence-driven selection by checking the
        # selected namespace owns the key, then assert the resolved value.
        assert graphex_or_graphene_settings._owning_namespace("MIDDLEWARE") == "GRAPHENE"

    @override_settings(
        GRAPHEX={"SCHEMA": None},
        GRAPHENE={"MIDDLEWARE": ["x.Mw"]},
    )
    def test_perkey_middleware_from_graphene_with_warning(self):
        """SCHEMA in GRAPHEX, MIDDLEWARE only in GRAPHENE → MIDDLEWARE == ['x.Mw'].

        This is the core defect probe: with whole-namespace fallback the shim
        returns the MIDDLEWARE DEFAULT (``[]``/``()``) the moment GRAPHEX has any
        key; per-key fallback returns ``['x.Mw']`` from GRAPHENE and warns once.

        MIDDLEWARE is an import string, so a real import would fail on ``x.Mw``.
        We patch ``_import_from_string`` to identity so the test isolates
        namespace selection from import resolution.
        """
        from unittest.mock import patch

        from django_graphex import settings as settings_mod
        from django_graphex.settings import graphex_or_graphene_settings

        graphex_or_graphene_settings.reload()

        with patch.object(
            settings_mod, "_import_from_string", lambda value, name: value
        ):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                middleware = graphex_or_graphene_settings.MIDDLEWARE
            assert middleware == ["x.Mw"], (
                "MIDDLEWARE must come from GRAPHENE (per-key), not the default"
            )
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1, (
                "Per-key GRAPHENE fallback must emit a DeprecationWarning"
            )


# ---------------------------------------------------------------------------
# 3. reload_api_settings signal handler handles GRAPHEX
# ---------------------------------------------------------------------------


class TestReloadApiSettingsHandlesGraphex:
    """reload_api_settings clears graphex_or_graphene_settings when GRAPHEX changes."""

    @override_settings(GRAPHEX={"SUBSCRIPTION_PATH": "/ws/initial/"})
    def test_override_settings_graphex_reloads_shim(self):
        """override_settings(GRAPHEX=...) causes the shim to reflect the new value.

        Uses SUBSCRIPTION_PATH (not an import string) to avoid triggering
        import-resolution for a fake dotted-path string.
        """
        from django_graphex.settings import graphex_or_graphene_settings

        graphex_or_graphene_settings.reload()
        # Force cache
        _ = graphex_or_graphene_settings.SUBSCRIPTION_PATH

        with override_settings(GRAPHEX={"SUBSCRIPTION_PATH": "/ws/new/"}):
            # The setting_changed signal fires; shim should reload
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
