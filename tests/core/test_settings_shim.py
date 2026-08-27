"""Unified DJANGO_GRAPHEX settings reader tests.

Tests the single "DJANGO_GRAPHEX" Django-setting namespace and its reader
("GraphQLAPISettings" / the "graphql_api_settings" singleton).

BREAKING CHANGE (2.0): django-graphex unified its two settings dicts into ONE
"DJANGO_GRAPHEX" namespace. The schema/middleware/subscription keys (SCHEMA,
MIDDLEWARE, SUBSCRIPTION_PATH, ATOMIC_MUTATIONS, MAX_VALIDATION_ERRORS,
SUBSCRIPTION_CONNECTION_INIT_TIMEOUT) now live in "DJANGO_GRAPHEX" alongside the
package's own settings. The legacy "GRAPHENE" namespace (and the former separate
schema-settings dict + its reader) are gone: "graphql_api_settings" is the
single reader for every key.

"CAMELCASE_ERRORS" is NOT one of them. It was dropped from DEFAULTS, so it is no
longer a recognised key: an operator who sets it gets the unknown-setting system
check warning from "check_unknown_settings" and the value is ignored.
"""

from __future__ import annotations

import warnings

from django.test import override_settings

# ---------------------------------------------------------------------------
# 1. GraphQLAPISettings — reads the DJANGO_GRAPHEX namespace (schema keys too)
# ---------------------------------------------------------------------------


class TestGraphQLAPISettingsSchemaKeys:
    """GraphQLAPISettings reads the schema/middleware keys from DJANGO_GRAPHEX.

    Covers user_settings precedence, package defaults, and reload() behavior.
    """

    def test_reads_subscription_path_from_user_settings(self) -> None:
        """Ships broken if GraphQLAPISettings.SUBSCRIPTION_PATH stops
        returning the value from user_settings.

        Uses SUBSCRIPTION_PATH (not an import string) to avoid the
        import-resolution step that would fail with a fake dotted-path string.
        """
        from django_graphex.settings import GraphQLAPISettings

        s = GraphQLAPISettings(user_settings={"SUBSCRIPTION_PATH": "/ws/graphql/"})
        assert s.SUBSCRIPTION_PATH == "/ws/graphql/"

    @override_settings(DJANGO_GRAPHEX={})
    def test_defaults_when_django_graphex_key_missing(self) -> None:
        """Ships broken if a missing schema key stops falling back to the
        package DEFAULTS.

        An empty "user_settings={}" is falsy, so the reader falls back to the
        Django "DJANGO_GRAPHEX" dict; "override_settings(DJANGO_GRAPHEX={})"
        empties it so every key resolves to its package default (independent of
        the harness's global DJANGO_GRAPHEX schema config).
        """
        from django_graphex.settings import GraphQLAPISettings

        s = GraphQLAPISettings(user_settings={})
        # SCHEMA default is None
        assert s.SCHEMA is None
        assert s.SUBSCRIPTION_PATH is None

    def test_reload_rereads_from_django_settings(self) -> None:
        """Ships broken if reload() stops dropping the cached value AND
        re-reading the namespace from Django.

        A GraphQLAPISettings with no explicit user_settings reads from
        "settings.DJANGO_GRAPHEX". After the value is cached, changing the
        Django setting and calling reload() must surface the NEW value on next
        access — proving reload() clears both the per-key cache and the cached
        "_user_settings" dict.
        """
        from django_graphex.settings import GraphQLAPISettings

        s = GraphQLAPISettings()  # no explicit user_settings -> reads from Django

        with override_settings(DJANGO_GRAPHEX={"SUBSCRIPTION_PATH": "/ws/first/"}):
            s.reload()  # ensure we read the overridden namespace
            assert s.SUBSCRIPTION_PATH == "/ws/first/"  # reads and caches

        with override_settings(DJANGO_GRAPHEX={"SUBSCRIPTION_PATH": "/ws/second/"}):
            # Without reload the cached "/ws/first/" would still be returned;
            # reload() must drop the cache and re-read from Django settings.
            s.reload()
            assert s.SUBSCRIPTION_PATH == "/ws/second/"

    @override_settings(DJANGO_GRAPHEX={"SUBSCRIPTION_PATH": "/ws/override/"})
    def test_reads_from_django_settings_when_no_user_settings(self) -> None:
        """Ships broken if, without explicit user_settings, the reader stops
        reading from Django settings.DJANGO_GRAPHEX.
        """
        from django_graphex.settings import GraphQLAPISettings

        s = GraphQLAPISettings()
        assert s.SUBSCRIPTION_PATH == "/ws/override/"


# ---------------------------------------------------------------------------
# 2. graphql_api_settings singleton — single reader, legacy GRAPHENE ignored
# ---------------------------------------------------------------------------


class TestGraphQLAPISettingsSingleton:
    """graphql_api_settings reads ONLY the unified DJANGO_GRAPHEX namespace.

    BREAKING CHANGE (2.0): the legacy "GRAPHENE" namespace is no longer
    consulted, and there is no separate schema-settings dict or reader anymore.
    """

    @override_settings(DJANGO_GRAPHEX={"SUBSCRIPTION_PATH": "/ws/only-graphex/"})
    def test_reads_value_from_django_graphex(self) -> None:
        """Ships broken if a DJANGO_GRAPHEX value stops being returned with
        NO warning.
        """
        from django_graphex.settings import graphql_api_settings

        graphql_api_settings.reload()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            path = graphql_api_settings.SUBSCRIPTION_PATH
        assert path == "/ws/only-graphex/"
        deprecation_warnings = [
            x for x in w if issubclass(x.category, DeprecationWarning)
        ]
        assert len(deprecation_warnings) == 0

    @override_settings(DJANGO_GRAPHEX={"SUBSCRIPTION_PATH": "/ws/graphex/"})
    def test_django_graphex_value_wins_over_legacy_graphene(self) -> None:
        """Ships broken if, with both DJANGO_GRAPHEX and the legacy GRAPHENE
        set, GRAPHENE stops being ignored.

        Uses SUBSCRIPTION_PATH (not an import string) to avoid the
        import-resolution step that would fail with a fake dotted-path string.
        """
        with override_settings(GRAPHENE={"SUBSCRIPTION_PATH": "/ws/graphene/"}):
            from django_graphex.settings import graphql_api_settings

            graphql_api_settings.reload()
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                path = graphql_api_settings.SUBSCRIPTION_PATH
            assert path == "/ws/graphex/"
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 0, "DJANGO_GRAPHEX path must NOT warn"

    def test_legacy_graphene_namespace_is_ignored(self) -> None:
        """Ships broken if a value set ONLY in GRAPHENE stops being ignored
        (BREAKING CHANGE, 2.0).

        Pre-2.0 the shim fell back to GRAPHENE (with a DeprecationWarning).
        As of 2.0 the GRAPHENE namespace is not consulted at all: the reader
        returns the package DEFAULT (here "None") and emits NO warning.
        """
        with override_settings(
            GRAPHENE={"SUBSCRIPTION_PATH": "/ws/legacy/"}, DJANGO_GRAPHEX={}
        ):
            from django_graphex.settings import graphql_api_settings

            graphql_api_settings.reload()
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                path = graphql_api_settings.SUBSCRIPTION_PATH
            # GRAPHENE is ignored — the DJANGO_GRAPHEX default (None) is returned.
            assert path is None, "GRAPHENE value must NOT be read"
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 0, (
                "GRAPHENE namespace no longer triggers a DeprecationWarning"
            )

    def test_neither_set_returns_defaults(self) -> None:
        """Ships broken if, with neither DJANGO_GRAPHEX nor GRAPHENE set,
        defaults stop applying (no error).
        """
        with override_settings(GRAPHENE={}, DJANGO_GRAPHEX={}):
            from django_graphex.settings import graphql_api_settings

            graphql_api_settings.reload()
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                schema = graphql_api_settings.SCHEMA
            assert schema is None
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 0


# ---------------------------------------------------------------------------
# 2b. Legacy GRAPHENE namespace fully decoupled — keys live only in DJANGO_GRAPHEX
# ---------------------------------------------------------------------------


class TestGrapheneNamespaceDecoupled:
    """The reader ignores the legacy GRAPHENE namespace entirely.

    BREAKING CHANGE (2.0): pre-2.0 the shim resolved each key independently
    against the schema dict then GRAPHENE so incremental migration would not
    drop keys still in GRAPHENE. That dual-read is removed: a key configured
    only in GRAPHENE is silently dropped (returns the DJANGO_GRAPHEX default).
    Projects MUST move all keys to DJANGO_GRAPHEX (see UPGRADE-2.0).
    """

    @override_settings(
        DJANGO_GRAPHEX={"SUBSCRIPTION_PATH": "/ws/graphex/"},
        GRAPHENE={"MIDDLEWARE": ["x.Mw"]},
    )
    def test_graphene_only_key_is_not_read(self) -> None:
        """Ships broken if SUBSCRIPTION_PATH stops coming from DJANGO_GRAPHEX,
        or if MIDDLEWARE (only in GRAPHENE) stops being dropped.

        Uses SUBSCRIPTION_PATH (not an import string) for the DJANGO_GRAPHEX key
        so the import-resolution step is skipped. MIDDLEWARE is configured ONLY
        in GRAPHENE — with GRAPHENE ignored, MIDDLEWARE resolves to the
        DJANGO_GRAPHEX default ("()"), NOT "["x.Mw"]".
        """
        from django_graphex.settings import graphql_api_settings

        graphql_api_settings.reload()

        # DJANGO_GRAPHEX key — resolved from DJANGO_GRAPHEX, no warning.
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            sub_path = graphql_api_settings.SUBSCRIPTION_PATH
        assert sub_path == "/ws/graphex/"
        graphex_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(graphex_warnings) == 0, "DJANGO_GRAPHEX-owned key must NOT warn"

        # MIDDLEWARE is ONLY in GRAPHENE; GRAPHENE is no longer consulted, so the
        # DJANGO_GRAPHEX default is returned (a list copy of the () default).
        assert list(graphql_api_settings.MIDDLEWARE) == []


# ---------------------------------------------------------------------------
# 3. reload_api_settings signal handler handles DJANGO_GRAPHEX
# ---------------------------------------------------------------------------


class TestReloadApiSettingsHandlesDjangoGraphex:
    """reload_api_settings clears graphql_api_settings when DJANGO_GRAPHEX changes.

    Confirmed via the Django setting_changed signal and override_settings.
    """

    @override_settings(DJANGO_GRAPHEX={"SUBSCRIPTION_PATH": "/ws/initial/"})
    def test_override_settings_django_graphex_reloads_singleton(self) -> None:
        """Ships broken if "override_settings(DJANGO_GRAPHEX=...)" stops
        causing the reader to reflect the new value.

        Uses SUBSCRIPTION_PATH (not an import string) to avoid triggering
        import-resolution for a fake dotted-path string.
        """
        from django_graphex.settings import graphql_api_settings

        graphql_api_settings.reload()
        # Force cache
        _ = graphql_api_settings.SUBSCRIPTION_PATH

        with override_settings(DJANGO_GRAPHEX={"SUBSCRIPTION_PATH": "/ws/new/"}):
            # The setting_changed signal fires; reader should reload
            assert graphql_api_settings.SUBSCRIPTION_PATH == "/ws/new/"


# ---------------------------------------------------------------------------
# 4. views.py consumers read from the unified reader (behavioral test)
# ---------------------------------------------------------------------------


class TestViewsUsesUnifiedReader:
    """BaseGraphQLView reads SCHEMA/MIDDLEWARE/SUBSCRIPTION_PATH from graphql_api_settings.

    Covers the schema and subscription-path read paths.
    """

    def test_view_reads_schema_from_django_graphex(self) -> None:
        """Ships broken if, when DJANGO_GRAPHEX.SCHEMA is set,
        BaseGraphQLView.__init__ stops picking it up.
        """
        from unittest.mock import patch

        from graphql import GraphQLString

        from django_graphex.core import ObjectType, field
        from django_graphex.schema import DjangoGraphQLSchema
        from django_graphex.settings import graphql_api_settings

        class _Q(ObjectType):
            ping = field(GraphQLString)

        schema = DjangoGraphQLSchema(query=_Q)

        graphql_api_settings.reload()

        with patch.object(graphql_api_settings, "SCHEMA", schema):
            from django_graphex.views import BaseGraphQLView

            view = BaseGraphQLView()
            assert view.schema is schema

    def test_view_reads_subscription_path_from_django_graphex(self) -> None:
        """Ships broken if subscription_path stops being read from
        graphql_api_settings (DJANGO_GRAPHEX.SUBSCRIPTION_PATH).
        """
        from graphql import GraphQLString

        from django_graphex.core import ObjectType, field
        from django_graphex.schema import DjangoGraphQLSchema

        class _Q(ObjectType):
            ping = field(GraphQLString)

        schema = DjangoGraphQLSchema(query=_Q)

        from unittest.mock import patch

        from django_graphex.settings import graphql_api_settings

        graphql_api_settings.reload()

        with (
            patch.object(graphql_api_settings, "SCHEMA", schema),
            patch.object(graphql_api_settings, "SUBSCRIPTION_PATH", "/ws/graphql/"),
            patch.object(graphql_api_settings, "MIDDLEWARE", []),
        ):
            from django_graphex.views import BaseGraphQLView

            view = BaseGraphQLView()
            assert view.subscription_path == "/ws/graphql/"


# ---------------------------------------------------------------------------
# 5. _auth_middleware_configured honors DJANGO_GRAPHEX
# ---------------------------------------------------------------------------


class TestAuthMiddlewareConfiguredHonorsDjangoGraphex:
    """_auth_middleware_configured checks DJANGO_GRAPHEX['MIDDLEWARE'].

    Covers the present, absent, and legacy-namespace-only middleware cases.
    """

    @override_settings(
        DJANGO_GRAPHEX={
            "MIDDLEWARE": ["django_graphex.middleware.AuthenticatedFieldsMiddleware"]
        }
    )
    def test_returns_true_when_middleware_in_django_graphex(self) -> None:
        """Ships broken if _auth_middleware_configured stops returning True
        when DJANGO_GRAPHEX has the middleware.
        """
        from django_graphex.schema import _auth_middleware_configured

        assert _auth_middleware_configured() is True

    @override_settings(DJANGO_GRAPHEX={}, GRAPHENE={})
    def test_returns_false_when_middleware_absent(self) -> None:
        """Ships broken if _auth_middleware_configured stops returning False
        when middleware is not in either namespace.
        """
        from django_graphex.schema import _auth_middleware_configured

        assert _auth_middleware_configured() is False

    @override_settings(
        DJANGO_GRAPHEX={},
        GRAPHENE={
            "MIDDLEWARE": ["django_graphex.middleware.AuthenticatedFieldsMiddleware"]
        },
    )
    def test_ignores_legacy_graphene_namespace(self) -> None:
        """Ships broken if the legacy GRAPHENE namespace stops being ignored
        (BREAKING CHANGE, 2.0).

        Pre-2.0 "_auth_middleware_configured" unioned the schema dict +
        GRAPHENE "MIDDLEWARE". As of 2.0 the GRAPHENE namespace is retired
        everywhere: a middleware configured ONLY under GRAPHENE must be ignored,
        so the check returns False even though the middleware is present under
        the legacy key.
        """
        from django_graphex.schema import _auth_middleware_configured

        assert _auth_middleware_configured() is False
