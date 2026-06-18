"""Installability + management-command discovery tests for django_graphex.

These tests prove the package is a drop-in Django app:

1. ``django_graphex`` can be listed in ``INSTALLED_APPS`` and ``django.setup()``
   completes without ``AppRegistryNotReady`` (the whole import chain must avoid
   touching the model registry at module-load time).
2. Once installed, Django auto-discovers the ``graphql_schema`` management
   command (``manage.py graphql_schema``) — the literal graphene-django drop-in.

The conftest harness already lists ``django_graphex`` in ``INSTALLED_APPS``, so
``apps.is_installed`` / ``get_commands`` exercise the real, fully-populated app
registry. The first test additionally builds a fresh, isolated registry in a
subprocess so the assertion does not depend on the suite's settings — it is the
literal installability probe a downstream user would run.
"""

from __future__ import annotations

import subprocess
import sys

from django.apps import apps
from django.core.management import get_commands

# The minimal probe a migrating user runs: configure settings with
# django_graphex in INSTALLED_APPS, call django.setup(), assert installed.
# Run in a SUBPROCESS so it uses a pristine app registry (the test process has
# already called django.setup()), giving a settings-independent proof.
_PROBE = """
import django
from django.conf import settings

settings.configure(
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "django_graphex",
    ],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
)
django.setup()

from django.apps import apps
from django.core.management import get_commands

assert apps.is_installed("django_graphex"), "django_graphex is not installed"
assert "graphql_schema" in get_commands(), "graphql_schema command not discovered"
print("INSTALLABLE:", apps.is_installed("django_graphex"))
"""


def test_package_is_installable_in_a_fresh_registry():
    """A fresh ``django.setup()`` with django_graphex installed must succeed.

    This is the settings-independent installability probe: a clean Python
    process configures a minimal project with ``django_graphex`` in
    ``INSTALLED_APPS`` and calls ``django.setup()``. Before the lazy-defer fix
    this raised ``AppRegistryNotReady`` (the import chain loaded the
    ``ContentType`` model at module top). It must now exit 0 and report the app
    as installed.
    """
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"installability probe failed:\n{result.stderr}"
    )
    assert "INSTALLABLE: True" in result.stdout


def test_app_is_installed_under_suite_settings():
    """The suite's settings list django_graphex; the registry must confirm it.

    Because the conftest harness adds ``django_graphex`` to ``INSTALLED_APPS``
    and the whole suite runs after ``django.setup()``, the app being installed
    here is itself a strong, always-on installability proof.
    """
    assert apps.is_installed("django_graphex")


def test_graphql_schema_command_is_discovered_when_app_installed():
    """``graphql_schema`` is auto-discovered as a management command.

    With ``django_graphex`` in ``INSTALLED_APPS`` Django scans its
    ``management/commands`` package, so ``manage.py graphql_schema`` resolves to
    the real command (not "Unknown command") — the literal graphene-django
    drop-in workflow for migrating users.
    """
    commands = get_commands()
    assert "graphql_schema" in commands
    # It is provided by django_graphex itself, not another installed app.
    assert commands["graphql_schema"] == "django_graphex"
