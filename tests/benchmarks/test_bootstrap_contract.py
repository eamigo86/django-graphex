"""Benchmark environment bootstrap contract tests."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

from benchmarks import harness
from benchmarks.verify_freeze import render_verified_freeze

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = REPO_ROOT / "benchmarks"


def _env_values(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text().splitlines()
        if line and not line.startswith("#")
    )


def test_direct_versions_match_the_canonical_artifacts() -> None:
    """Verify direct versions match the canonical artifacts.

    This test protects the corresponding regression contract.
    """
    versions = _env_values(BENCHMARKS / "versions.env")
    assert versions == {
        "PYTHON_VERSION": "3.12.11",
        "DJANGO_VERSION": "6.0.6",
        "CHANNELS_VERSION": "4.3.2",
        "GRAPHENE_DJANGO_VERSION": "3.2.3",
        "DJANGO_FILTER_VERSION": "25.2",
        "STRAWBERRY_DJANGO_VERSION": "0.86.4",
        "STRAWBERRY_VERSION": "0.320.1",
        "ARIADNE_VERSION": "1.1.0",
        "ARIADNE_DJANGO_VERSION": "0.3.0",
    }


def test_constraints_pin_every_canonical_transitive_dependency() -> None:
    """Verify constraints pin every canonical transitive dependency.

    This test protects the corresponding regression contract.
    """
    constraints = {
        line.split("==", 1)[0].lower().replace("_", "-"): line.split("==", 1)[1]
        for line in (BENCHMARKS / "constraints.txt").read_text().splitlines()
        if line and not line.startswith("#")
    }
    assert constraints == {
        "annotated-types": "0.7.0",
        "anyio": "4.14.1",
        "ariadne": "1.1.0",
        "ariadne-django": "0.3.0",
        "asgiref": "3.11.1",
        "channels": "4.3.2",
        "cross-web": "0.7.0",
        "django": "6.0.6",
        "django-filter": "25.2",
        "graphene": "3.4.3",
        "graphene-django": "3.2.3",
        "graphql-core": "3.2.11",
        "graphql-relay": "3.2.0",
        "idna": "3.18",
        "packaging": "26.2",
        "promise": "2.3",
        "pydantic": "2.13.4",
        "pydantic-core": "2.46.4",
        "python-dateutil": "2.9.0.post0",
        "six": "1.17.0",
        "sqlparse": "0.5.5",
        "starlette": "1.3.1",
        "strawberry-graphql": "0.320.1",
        "strawberry-graphql-django": "0.86.4",
        "text-unidecode": "1.3",
        "typing-extensions": "4.16.0",
        "typing-inspection": "0.4.2",
    }


def test_two_recreations_write_identical_freezes() -> None:
    """Verify equivalent recreations produce byte-identical freezes.

    This test protects deterministic benchmark environment replay.
    """
    constraints = {"django": "6.0.6", "asgiref": "3.11.1"}
    installed = [
        SimpleNamespace(metadata={"Name": "Django"}, version="6.0.6"),
        SimpleNamespace(metadata={"Name": "asgiref"}, version="3.11.1"),
    ]

    first = render_verified_freeze(installed, constraints, "graphex")
    second = render_verified_freeze(reversed(installed), constraints, "graphex")

    assert first == second == "asgiref==3.11.1\ndjango==6.0.6\n"


def test_setup_has_required_ariadne_integration_and_offline_mode() -> None:
    """Verify setup requires Ariadne integration and supports offline mode.

    This test protects the corresponding regression contract.
    """
    setup = (BENCHMARKS / "setup_envs.sh").read_text()
    assert "BENCH_OFFLINE" in setup
    assert "--offline" in setup
    assert "UV_PYTHON_DOWNLOADS=never" in setup
    assert '"ariadne-django==$ARIADNE_DJANGO_VERSION"' in setup
    assert "ariadne-django not installed" not in setup
    assert "|| true" not in setup


def test_offline_replay_fails_clearly_without_a_cached_package(tmp_path: Path) -> None:
    """Verify offline bootstrap never falls back to downloads.

    Args:
        tmp_path: Isolated directory containing a fake uv executable.
    """
    benchmark_dir = tmp_path / "benchmarks"
    benchmark_dir.mkdir()
    for name in ("setup_envs.sh", "versions.env", "constraints.txt"):
        shutil.copy2(BENCHMARKS / name, benchmark_dir / name)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_log = tmp_path / "uv.log"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env bash
printf '%s|%s\n' "$*" "${UV_PYTHON_DOWNLOADS:-}" >> "$UV_LOG"
if [[ "$1" == "venv" ]]; then
  mkdir -p "${@: -1}/bin"
  exit 0
fi
exit 1
"""
    )
    fake_uv.chmod(0o755)
    env = {
        **os.environ,
        "BENCH_OFFLINE": "1",
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "UV_LOG": str(uv_log),
    }

    result = subprocess.run(
        ["bash", str(benchmark_dir / "setup_envs.sh"), "graphex"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "offline benchmark cache is incomplete" in result.stderr
    assert "venv -p 3.12.11" in uv_log.read_text()
    assert "pip install --offline" in uv_log.read_text()
    assert all(line.endswith("|never") for line in uv_log.read_text().splitlines())


def test_result_provenance_records_commit_and_constraints_hash() -> None:
    """Verify result provenance records commit and constraints hash.

    This test protects the corresponding regression contract.
    """
    provenance = harness._provenance()
    expected_hash = hashlib.sha256(
        (BENCHMARKS / "constraints.txt").read_bytes()
    ).hexdigest()
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()
    assert provenance == {"commit": commit, "constraints_sha256": expected_hash}
