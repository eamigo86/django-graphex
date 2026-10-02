"""Contract checks for the separately named benchmark dependency profile."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / "benchmarks"


def _isolated_benchmarks(tmp_path: Path) -> Path:
    """Copy only bootstrap inputs into a disposable benchmark directory.

    Args:
        tmp_path: Temporary directory supplied by pytest.

    Returns:
        Directory containing the isolated bootstrap inputs.
    """
    target = tmp_path / "benchmarks"
    shutil.copytree(BENCHMARKS / "comparison_profiles", target / "comparison_profiles")
    for name in (
        "setup_envs.sh",
        "setup_profile_envs.sh",
        "profile_bootstrap.py",
        "verify_freeze.py",
    ):
        shutil.copy2(BENCHMARKS / name, target / name)
    return target


@pytest.mark.parametrize(
    "profile_name,library", [("unknown", "graphex"), ("core33", "unknown")]
)
def test_invalid_profile_or_library_is_rejected_before_env_changes(
    tmp_path: Path, profile_name: str, library: str
) -> None:
    """Reject unrecognized inputs before any package-manager invocation.

    Args:
        tmp_path: Disposable workspace.
        profile_name: Profile name under test.
        library: Library name under test.
    """
    bench = _isolated_benchmarks(tmp_path)
    marker = bench / f".venv-{profile_name}-{library}" / "keep"
    marker.parent.mkdir()
    marker.write_text("unchanged")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text('#!/bin/sh\necho invoked >>"$UV_LOG"\nexit 1\n')
    uv.chmod(0o755)
    log = tmp_path / "uv.log"
    result = subprocess.run(
        ["bash", str(bench / "setup_envs.sh"), "--profile", profile_name, library],
        cwd=bench,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "UV_LOG": str(log),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "unknown" in result.stderr.lower()
    assert marker.read_text() == "unchanged"
    assert not log.exists()


def test_legacy_bootstrap_uses_published_historical_distribution() -> None:
    """Keep the old no-argument profile tied to published version 3.1.0.

    The current source must not masquerade as the canonical 3.1.0 artifact.
    """
    setup = (BENCHMARKS / "setup_envs.sh").read_text()
    assert '"django-graphex==3.1.0"' in setup
    assert '-e "$REPO_ROOT"' not in setup


def test_missing_second_freeze_rejects_all_requested_libraries(tmp_path: Path) -> None:
    """Validate the entire request before touching any selected environment.

    Args:
        tmp_path: Disposable bootstrap inputs and fake package-manager log.
    """
    bench = _isolated_benchmarks(tmp_path)
    (
        bench / "comparison_profiles" / "core33" / "constraints" / "strawberry.txt"
    ).unlink()
    marker = bench / ".venv-core33-graphex" / "keep"
    marker.parent.mkdir()
    marker.write_text("unchanged")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text('#!/bin/sh\necho invoked >>"$UV_LOG"\nexit 1\n')
    uv.chmod(0o755)
    log = tmp_path / "uv.log"
    result = subprocess.run(
        [
            "bash",
            str(bench / "setup_envs.sh"),
            "--profile",
            "core33",
            "graphex",
            "strawberry",
        ],
        cwd=bench,
        env={
            **os.environ,
            "BENCH_PYTHON": sys.executable,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "UV_LOG": str(log),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "strawberry.txt" in result.stderr
    assert marker.read_text() == "unchanged"
    assert not log.exists()


def test_offline_cache_miss_leaves_no_profile_environment(tmp_path: Path) -> None:
    """Clean up staging without promoting an incomplete offline install.

    Args:
        tmp_path: Disposable bootstrap inputs and fake package-manager log.
    """
    bench = _isolated_benchmarks(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    log = tmp_path / "uv.log"
    uv.write_text(
        '#!/bin/bash\necho "$*|${UV_EXTRA_INDEX_URL-unset}|${UV_INDEX_USERNAME-unset}" '
        f'>>"{log}"\n'
        'for arg in "$@"; do\n'
        '  if [[ "$arg" == venv ]]; then mkdir -p "${@: -1}/bin"; exit 0; fi\n'
        "done\nexit 1\n"
    )
    uv.chmod(0o755)
    root = tmp_path / "venvs"
    result = subprocess.run(
        ["bash", str(bench / "setup_envs.sh"), "--profile", "core33", "graphex"],
        cwd=bench,
        env={
            **os.environ,
            "BENCH_PYTHON": sys.executable,
            "BENCH_UV_CACHE_DIR": str(tmp_path / "cache"),
            "BENCH_PROFILE_VENV_ROOT": str(root),
            "BENCH_OFFLINE": "1",
            "UV_EXTRA_INDEX_URL": "https://private.invalid/simple",
            "UV_INDEX_USERNAME": "private-user",
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "destination remains untouched" in result.stderr
    assert "--offline" in log.read_text()
    assert all(line.endswith("|unset|unset") for line in log.read_text().splitlines())
    assert not (root / ".venv-core33-graphex").exists()
    assert not list(root.glob("*.staging.*"))


def test_profile_venv_is_created_at_its_final_path(tmp_path: Path) -> None:
    """Avoid moving a venv after its activation scripts are generated.

    Args:
        tmp_path: Disposable bootstrap inputs and fake package manager.
    """
    bench = _isolated_benchmarks(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "uv.log"
    uv = fake_bin / "uv"
    uv.write_text(f'#!/bin/sh\necho "$*" >>"{log}"\nexit 1\n')
    uv.chmod(0o755)
    root = tmp_path / "venvs"
    result = subprocess.run(
        ["bash", str(bench / "setup_envs.sh"), "--profile", "core33", "graphex"],
        cwd=bench,
        env={
            **os.environ,
            "BENCH_PYTHON": sys.executable,
            "BENCH_UV_CACHE_DIR": str(tmp_path / "cache"),
            "BENCH_PROFILE_VENV_ROOT": str(root),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    target = root / ".venv-core33-graphex"
    assert result.returncode != 0
    assert log.read_text().splitlines()[0].endswith(str(target))
    assert not target.exists()
    assert not list(root.glob("*.staging.*"))
