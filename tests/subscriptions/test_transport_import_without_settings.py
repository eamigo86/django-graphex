# -*- coding: utf-8 -*-
"""Both subscription transports must import with Django settings unconfigured.

Sharing the HTTP view's validation-rule tuple (and, for SSE, its CSRF guard)
put a "from ...views import ..." at the top of each transport. "views" reaches
"core.permission_signature_cache", which reads the "DJANGO_GRAPHEX" setting
WHILE IT IS BEING IMPORTED -- so the module-level form made both transports
raise "ImproperlyConfigured" on import alone, a dependency neither had before.

That breaks an ASGI entrypoint that imports the consumer (or a routing module
that imports it) before it points the process at a settings module. The imports
are deferred into the request/operation path instead; this module is the check
that they stay there.

A subprocess is the only honest way to assert it: the pytest process configures
Django in "conftest.pytest_configure", so an in-process import proves nothing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("channels")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_PROBE = (
    "import django_graphex.subscriptions.transports.ws\n"
    "import django_graphex.subscriptions.transports.sse\n"
    "from django.conf import settings\n"
    "assert not settings.configured, 'settings got configured by the import'\n"
    "print('ok')\n"
)


def _run_probe() -> subprocess.CompletedProcess[str]:
    """Import both transports in a subprocess that has no settings module.

    Returns:
        The completed process, whose "returncode" and "stderr" carry the
        outcome of the import.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("DJANGO_SETTINGS_MODULE", "PYTHONSTARTUP")
    }
    env["PYTHONPATH"] = str(_REPO_ROOT)

    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_transports_import_without_configured_settings() -> None:
    """Importing either transport must not require a configured settings module.

    This test breaks the moment a "from ...views import ..." moves back to
    module level in either transport.
    """
    result = _run_probe()

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout, result.stdout
    assert "ImproperlyConfigured" not in result.stderr, result.stderr
