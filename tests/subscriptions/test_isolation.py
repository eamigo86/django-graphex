# -*- coding: utf-8 -*-
"""T-ISO / T-IMPORT: base install stays channels-free; no forbidden legacy deps."""

import os
import subprocess
import sys

import django_graphex
from django_graphex import subscriptions

PACKAGE_DIR = os.path.dirname(subscriptions.__file__)

# A subprocess that configures minimal Django settings and then imports the
# base package (to verify it never pulls in channels / graphene-django).
_BOOTSTRAP = """
import django
from django.conf import settings
settings.configure(
    DATABASES={{"default": {{"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}}},
    INSTALLED_APPS=["django.contrib.contenttypes", "django.contrib.auth"],
)
django.setup()
{body}
"""


def _run(body):
    code = _BOOTSTRAP.format(body=body)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )


def test_base_import_does_not_pull_in_channels():
    """AC1: ``import django_graphex`` must not import channels."""
    proc = _run(
        "import sys\n"
        "import django_graphex\n"
        "leaked = sorted(m for m in sys.modules if m == 'channels' or m.startswith('channels.'))\n"
        "assert not leaked, leaked\n"
        "print('OK')\n"
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_subscriptions_without_channels_raises_friendly_error():
    """AC1: importing the subpackage without the extra raises a friendly error."""
    proc = _run(
        "import sys\n"
        "class _Block:\n"
        "    def find_spec(self, name, path, target=None):\n"
        "        if name == 'channels' or name.startswith('channels.'):\n"
        "            raise ImportError('channels blocked for test')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Block())\n"
        "for m in list(sys.modules):\n"
        "    if m == 'channels' or m.startswith('channels.'):\n"
        "        del sys.modules[m]\n"
        "try:\n"
        "    import django_graphex.subscriptions  # noqa\n"
        "except ImportError as exc:\n"
        "    assert '[subscriptions]' in str(exc), str(exc)\n"
        "    print('OK')\n"
        "else:\n"
        "    raise SystemExit('expected ImportError')\n"
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_no_forbidden_legacy_imports():
    """T-IMPORT: no rx/six/promise/channels_api anywhere in the subpackage."""
    # Match actual imports of the legacy packages, not prose mentions.
    forbidden = (
        "import rx",
        "from rx",
        "import six",
        "from six",
        "import promise",
        "from promise",
        "channels_api",
        "channels.generic.websockets",  # Channels 1.x module
    )
    offenders = []
    for root, _dirs, files in os.walk(PACKAGE_DIR):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
            for token in forbidden:
                if token in source:
                    offenders.append((path, token))
    assert not offenders, offenders


def test_public_exports():
    """T-IMPORT: the post-cutover public surface (spec §Public API Contract).

    After the WU11 lockstep cutover the bespoke transport symbols are gone and
    subscriptions are native-only. The public ``__all__`` keeps the developer
    base (``Subscription``), the auto-gen mount (``SubscriptionField``), the
    signal binding, the action enum and the rewritten client view; it drops the
    bespoke transport symbols and never exports the internal engine.
    """
    # Present: the kept public surface.
    for name in (
        "Subscription",
        "SubscriptionField",
        "SubscriptionBinding",
        "SubscriptionClientView",
    ):
        assert name in subscriptions.__all__, f"{name} must stay public"
        assert hasattr(subscriptions, name)

    # Absent: bespoke transport symbols removed in the lockstep cutover, the
    # internal engine, AND the native transport factories — the transports are an
    # explicit deep import (``subscriptions.transports.sse`` /
    # ``subscriptions.transports.ws``), never part of the top-level surface.
    for name in (
        "GraphqlAPIDemultiplexer",
        "SubscriptionGraphQLView",
        "OperationSubscriptionEnum",
        "StreamingSubscription",
        "drive_subscription",
        "ChannelLayerSource",
        "SubscriptionSpec",
        "subscription_sse_view",
        "subscription_ws_consumer",
    ):
        assert name not in subscriptions.__all__, f"{name} must not be public"
        assert not hasattr(subscriptions, name), (
            f"{name} must not be a top-level subscriptions attribute"
        )

    # The exact public surface is the spec §Public API Contract set — no extras.
    # S-del-backend-11: ``ActionSubscriptionEnum`` (graphene ``Enum``) was dropped
    # from the public surface with the graphene backend.
    assert set(subscriptions.__all__) == {
        "Subscription",
        "SubscriptionField",
        "SubscriptionBinding",
        "SubscriptionClientView",
    }

    # The base package must NOT re-export the subscription symbols.
    assert "Subscription" not in django_graphex.__all__
