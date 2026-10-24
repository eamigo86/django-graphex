"""The benchmark harness re-imports the schema module through the real path."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

BENCHMARKS = Path(__file__).resolve().parents[2] / "benchmarks"

_SCRIPT = textwrap.dedent(
    """
    import os, sys

    sys.path.insert(0, os.getcwd())
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
    os.environ["BENCH_LIB"] = "graphex"

    import django

    django.setup()
    import harness

    module, _cold, samples = harness._import_schema()
    from graphql import print_schema

    sdl = print_schema(module.schema.graphql_schema)
    assert len(samples) == harness.SCHEMA_BUILDS, samples
    assert "type CommentType" in sdl and "commentCreate" in sdl
    print("OK")
    """
)


def test_real_import_schema_survives_repeated_reimport() -> None:
    """Run the unmocked harness import path in a fresh benchmark interpreter.

    The benchmark app has its own models and settings, so it cannot share this
    process. Re-importing bench_schema five times used to fail on the first
    redefinition of CommentType.
    """
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        cwd=BENCHMARKS,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().endswith("OK")
