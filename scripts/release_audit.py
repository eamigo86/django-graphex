# -*- coding: utf-8 -*-
"""Audit the BUILT release artifact instead of the editable local install.

``pip-audit`` skips an editable checkout of django-graphex ("Dependency not
found on PyPI and could not be audited"), so the security job only ever audits
the dev environment. The published wheel, however, carries its own declared
dependency closure (django, graphql-core, pydantic, python-dateutil,
text-unidecode and their transitives). This script audits exactly that closure:

1. Build the wheel + sdist of the current source into a temp directory.
2. ``pip install --target`` the built wheel (with its dependencies) into a clean
   isolated directory, resolving the full declared transitive set as it would be
   for a downstream ``pip install django-graphex``.
3. Run ``pip-audit --path <dir>`` against that directory. The local package
   itself is reported as "not found on PyPI" (expected for an unpublished build)
   and is harmless; every transitive dependency that WOULD ship is audited.

A non-empty vulnerability set makes pip-audit exit non-zero, which propagates
here so CI fails. ``--target`` is used instead of a throwaway virtualenv on
purpose: it reuses the current interpreter's pip and avoids ``ensurepip``, which
is stripped from some standalone (e.g. uv-managed) Python builds. Shell-free on
purpose: tox/CI run commands without a shell, so wheel globbing is resolved in
Python rather than by the shell.
"""

import glob
import os
import subprocess
import sys
import tempfile


def _run(cmd: list[str]) -> None:
    """Run a subprocess, echoing the command, and raise on failure."""
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> int:
    """Build the artifact, install it in isolation, and audit the closure."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    with tempfile.TemporaryDirectory(prefix="ga-release-audit-") as workdir:
        dist_dir = os.path.join(workdir, "dist")
        target_dir = os.path.join(workdir, "site")

        # 1) Build the wheel + sdist of the current source tree.
        _run([sys.executable, "-m", "build", "--outdir", dist_dir, project_root])

        wheels = glob.glob(os.path.join(dist_dir, "*.whl"))
        if not wheels:
            print("error: no wheel produced by `python -m build`", file=sys.stderr)
            return 1
        wheel = wheels[0]

        # 2) Install the built wheel WITH its dependencies into an isolated dir
        #    so the published closure resolves without touching the dev env.
        _run([sys.executable, "-m", "pip", "install", "--target", target_dir, wheel])

        # 3) Audit the resolved closure. The unpublished local package is the
        #    only skip; its transitive dependencies are all audited.
        _run([sys.executable, "-m", "pip_audit", "--path", target_dir])

    print("OK: built release artifact transitive dependencies audited clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
