# -*- coding: utf-8 -*-
"""Assert that a *base* install of django-graphex stays channels-free.

Run by the CI ``base-install`` job (no ``[subscriptions]`` extra installed). It
proves AC1: the base package imports without channels, and importing the
subscriptions subpackage without the extra raises a friendly error.
"""

import importlib.util
import sys

import django
from django.conf import settings

# Configure a minimal Django project so the package can be imported.
settings.configure(
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.auth",
    ],
)
django.setup()

assert importlib.util.find_spec("channels") is None, (
    "channels must be absent in a base install (without the [subscriptions] extra)"
)
assert importlib.util.find_spec("graphene_django") is None, (
    "graphene-django must be absent: the package no longer depends on it"
)

import django_graphex  # noqa: E402,F401

leaked = sorted(m for m in sys.modules if m == "channels" or m.startswith("channels."))
assert not leaked, "importing django_graphex pulled in channels: {}".format(
    leaked
)

try:
    import django_graphex.subscriptions  # noqa: E402,F401
except ImportError as exc:
    assert "[subscriptions]" in str(exc), "unexpected error message: {}".format(exc)
    print("OK: base install is channels-free and the subscriptions guard works")
else:
    raise SystemExit(
        "expected ImportError importing subscriptions without the [subscriptions] extra"
    )
