"""Top-level pytest configuration: Django settings bootstrap and shared fixtures.

Configures Django once for the whole suite (in "pytest_configure"), adds the
distribution-smoke CLI options ("--no-pkgroot", "--staticfiles"), and defines
the autouse fixture that clears the view-layer document caches between tests.
"""

import os
import sys
from typing import TYPE_CHECKING, Iterator

import django
import pytest as _pytest
from django.core import management

if TYPE_CHECKING:
    import pytest


def pytest_addoption(parser: "pytest.Parser") -> None:
    """Register the distribution-smoke CLI options for this suite.

    Args:
        parser: The pytest option parser to add options to.
    """
    parser.addoption(
        "--no-pkgroot",
        action="store_true",
        default=False,
        help="Remove package root directory from sys.path, ensuring that "
        "django_graphex is imported from the installed site-packages. "
        "Used for testing the distribution.",
    )
    parser.addoption(
        "--staticfiles",
        action="store_true",
        default=False,
        help="Run tests with static files collection, using manifest "
        "staticfiles storage. Used for testing the distribution.",
    )


try:
    import channels  # noqa: F401

    HAS_CHANNELS = True
except ImportError:
    HAS_CHANNELS = False


def pytest_configure(config: "pytest.Config") -> None:
    """Configure Django settings for the suite and apply distribution-smoke options.

    Builds the full "settings.configure(...)" call (installed apps, database,
    templates, middleware, DJANGO_GRAPHEX schema/middleware), then honors
    "--no-pkgroot" and "--staticfiles" before calling "django.setup()".

    Args:
        config: The pytest configuration, used to read the registered options.
    """
    from django.conf import settings

    # Subscriptions are an optional extra: only wire channels when it is present
    # so the base-install CI job (no extra) can still configure and run.
    channels_apps = ("channels",) if HAS_CHANNELS else ()
    channel_layers = (
        {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
        if HAS_CHANNELS
        else {}
    )

    settings.configure(
        CHANNEL_LAYERS=channel_layers,
        ALLOWED_HOSTS=["*"],
        DEBUG_PROPAGATE_EXCEPTIONS=True,
        DATABASES={
            "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
        },
        SITE_ID=1,
        SECRET_KEY="not very secret in tests",
        USE_I18N=True,
        STATIC_URL="/static/",
        ROOT_URLCONF="tests.urls",
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
                "OPTIONS": {"debug": True},  # We want template errors to raise
            }
        ],
        MIDDLEWARE=(
            "django.middleware.common.CommonMiddleware",
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            "django.contrib.messages.middleware.MessageMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
        ),
        INSTALLED_APPS=(
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.sites",
            "django.contrib.staticfiles",
            *channels_apps,
            # django_graphex installs as a regular Django app: listing it here
            # exercises the real app registry every suite run, so the whole suite
            # is itself a strong, always-on installability proof (the package
            # import chain must never touch the model registry at module load).
            "django_graphex",
            "tests",
        ),
        PASSWORD_HASHERS=("django.contrib.auth.hashers.MD5PasswordHasher",),
        # S2 (2.0 breaking change): settings are read from the SINGLE
        # DJANGO_GRAPHEX namespace; the legacy GRAPHENE fallback has been
        # removed. The harness uses DJANGO_GRAPHEX so the global SCHEMA/MIDDLEWARE
        # resolve through graphql_api_settings (the one and only reader).
        DJANGO_GRAPHEX={
            "SCHEMA": "tests.schema.schema",
            "MIDDLEWARE": ["django_graphex.middleware.GraphQLDirectiveMiddleware"],
        },
        AUTHENTICATION_BACKENDS=(
            "django.contrib.auth.backends.ModelBackend",
            # django-guardian is NOT a dependency of this library. The
            # ObjectPermissionBackend entry was a leftover from an earlier
            # development snapshot. Object-permission support is not part of
            # django-graphex's public API or test surface.
        ),
    )

    # --no-pkgroot: strips the project root from sys.path so that pytest imports
    # django_graphex from the *installed* site-packages rather than the source
    # tree. This verifies the built distribution is self-contained and does not
    # silently depend on editable-install artefacts. The option is intentionally
    # not wired into tox or CI (it requires a prior `pip install dist/...` step),
    # so it serves as a manual distribution-smoke hook only.
    if config.getoption("--no-pkgroot"):
        sys.path.pop(0)

        # import the package before pytest re-adds the package root directory.
        import django_graphex

        package_dir = os.path.join(os.getcwd(), "django_graphex")
        assert not django_graphex.__file__.startswith(package_dir)

    # Manifest storage will raise an exception if static files are not present (ie, a packaging failure).
    if config.getoption("--staticfiles"):
        import django_graphex

        settings.STATIC_ROOT = os.path.join(
            os.path.dirname(django_graphex.__file__), "static-root"
        )
        settings.STATICFILES_STORAGE = (
            "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
        )

    django.setup()

    if config.getoption("--staticfiles"):
        management.call_command("collectstatic", verbosity=0, interactive=False)


# ---------------------------------------------------------------------------
# Global registry isolation strategy
#
# django_graphex.registry.get_global_registry() returns a process-wide
# singleton that is populated at *import time* when DjangoObjectType subclasses
# are defined (the metaclass registers each type on class creation).
#
# The suite relies on this populated singleton: many tests call
# get_global_registry() and expect to find the types registered by the
# test models defined in tests/models.py, tests/schema.py, and elsewhere.
#
# reset_global_registry() was a dead helper (zero call sites) that would have
# cleared the singleton and broken those tests.  It has been removed (see issue
# #73).
#
# Test-order independence is therefore provided by:
#   1. DjangoObjectType metaclass registration happens once at import time;
#      it is idempotent (re-importing does not duplicate registrations).
#   2. Tests that need a clean registry use a *local* Registry() instance
#      rather than the global one (see test_registry.py).
#   3. Cache and view tests call cache.clear() in setUp / override_settings,
#      which is the correct per-test isolation scope for the cache layer.
#
# Follow-up: add pytest-randomly to CI to validate shuffle-order independence
# as a separate issue.  Do NOT add it as part of #73.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Document-cache isolation (P3 perf batch).
#
# django_graphex.views keeps process-global parse/validation caches
# (_PARSE_CACHE / _VALIDATE_CACHE).  Left uncleared, a document parsed by one
# test is served from cache in the next, breaking any test that counts
# parse()/validate() calls (e.g. test_http_hardening's single-parse guard) and
# making the suite order-dependent.  Clearing per test keeps every test's
# cache observations self-contained; tests that exercise the cache itself
# build their state within the test body.
# ---------------------------------------------------------------------------


@_pytest.fixture(autouse=True)
def _clear_document_caches() -> Iterator[None]:
    """Clear the view-layer parse/validation caches before each test.

    Runs automatically for every test in the suite so a document parsed by
    one test is never served from cache in the next, keeping cache-observing
    tests (e.g. the "test_http_hardening" single-parse guard) order-independent.

    Yields:
        None. Control returns to the test after clearing the caches.
    """
    from django_graphex.views import clear_document_caches

    clear_document_caches()
    yield
