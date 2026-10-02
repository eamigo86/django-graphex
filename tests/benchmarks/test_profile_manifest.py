"""Validate the observed whole-stack comparison profile before bootstrap."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

BENCHMARKS = Path(__file__).resolve().parents[2] / "benchmarks"


def _profile() -> object:
    """Import the profile validator through the project package."""
    return importlib.import_module("benchmarks.profile_bootstrap")


def test_new_profile_pins_compatible_complete_stacks() -> None:
    """Require observed per-library freezes and distinct core generations."""
    profile = _profile()
    expected = {
        "graphex": ("3.3.0", "source"),
        "strawberry": ("3.3.0", "source-independent"),
        "graphene": ("3.2.13", "source-independent"),
        "ariadne": ("3.2.13", "source-independent"),
    }
    for library, (core, mode) in expected.items():
        spec = profile.load_profile("core33", library, BENCHMARKS)
        assert spec["python"] == "3.12.11"
        assert spec["mode"] == mode
        assert spec["packages"]["django"] == "6.0.8"
        assert spec["packages"]["graphql-core"] == core
        constraints = profile.load_constraints(spec["constraints"])
        assert constraints == spec["freeze"]
        assert constraints["graphql-core"] == core
    strawberry = profile.load_profile("core33", "strawberry", BENCHMARKS)
    assert strawberry["packages"]["strawberry-graphql"] == "0.328.0"
    assert strawberry["packages"]["strawberry-graphql-django"] == "0.90.0"


def test_mismatched_or_missing_freeze_fails_before_install(tmp_path: Path) -> None:
    """Refuse inconsistent manifest data without starting an install.

    Args:
        tmp_path: Disposable directory for modified profile inputs.
    """
    bench = tmp_path / "benchmarks"
    target = bench / "comparison_profiles" / "core33"
    target.mkdir(parents=True)
    manifest = json.loads(
        (BENCHMARKS / "comparison_profiles" / "core33" / "manifest.json").read_text()
    )
    manifest["libraries"]["strawberry"]["packages"]["graphql-core"] = "3.2.13"
    (target / "manifest.json").write_text(json.dumps(manifest))
    freezes = target / "constraints"
    freezes.mkdir()
    (freezes / "strawberry.txt").write_bytes(
        (
            BENCHMARKS / "comparison_profiles" / "core33" / "constraints" / "strawberry.txt"
        ).read_bytes()
    )
    with pytest.raises(ValueError, match="mismatch"):
        _profile().load_profile("core33", "strawberry", bench)
    (freezes / "strawberry.txt").unlink()
    with pytest.raises(FileNotFoundError):
        _profile().load_profile("core33", "strawberry", bench)
