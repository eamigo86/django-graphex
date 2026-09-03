# -*- coding: utf-8 -*-
"""Audit the dependency closure of a prebuilt release wheel."""

import subprocess
import sys
import tempfile
from pathlib import Path


def _run(command: list[str]) -> None:
    """Run a subprocess and propagate a failing exit status."""
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main(argv: list[str] | None = None) -> int:
    """Install and audit one existing wheel without rebuilding source."""
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print("usage: release_audit.py WHEEL", file=sys.stderr)
        return 2

    wheel = Path(arguments[0]).resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        print(f"error: expected an existing wheel, got {wheel}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="gdx-release-audit-") as workdir:
        target = str(Path(workdir) / "site")
        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--target",
                target,
                str(wheel),
            ]
        )
        _run([sys.executable, "-m", "pip_audit", "--path", target])

    print("OK: prebuilt wheel dependency closure audited clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
