"""Validate the observed whole-stack comparison profile before bootstrap."""

from __future__ import annotations

import importlib
import json
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

BENCHMARKS = Path(__file__).resolve().parents[2] / "benchmarks"


def _profile() -> object:
    """Import the profile validator through the project package."""
    return importlib.import_module("benchmarks.profile_bootstrap")


def test_new_profile_pins_compatible_complete_stacks() -> None:
    """Require observed per-library freezes and distinct core generations.

    The selected direct pins must agree with every recorded dependency freeze.
    """
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


def test_profile_includes_source_runtime_requirements() -> None:
    """Keep the Graphex freeze sufficient for its current source."""
    project = tomllib.loads((BENCHMARKS.parent / "pyproject.toml").read_text())
    graphex = _profile().load_profile("core33", "graphex", BENCHMARKS)
    for raw in project["project"]["dependencies"]:
        requirement = Requirement(raw)
        pinned = graphex["packages"].get(requirement.name)
        assert pinned is not None, f"missing Graphex runtime pin: {requirement.name}"
        assert requirement.specifier.contains(pinned)
        assert graphex["freeze"][requirement.name] == pinned


def test_profile_includes_graphene_adapter_filter() -> None:
    """Pin the filter package imported by the existing Graphene adapter."""
    adapter = (BENCHMARKS / "libs" / "graphene" / "bench_schema.py").read_text()
    assert "from graphene_django.filter import DjangoFilterConnectionField" in adapter
    graphene = _profile().load_profile("core33", "graphene", BENCHMARKS)
    assert graphene["packages"]["django-filter"] == "25.2"
    assert graphene["freeze"]["django-filter"] == "25.2"


@pytest.mark.parametrize(
    "library,required", [("graphex", "pydantic"), ("graphene", "django-filter")]
)
def test_required_source_package_cannot_be_omitted_from_both_inputs(
    tmp_path: Path, library: str, required: str
) -> None:
    """Reject a consistent but unrunnable manifest and freeze.

    Args:
        tmp_path: Disposable profile directory.
        library: Stack whose source import requires the package.
        required: Distribution omitted from both profile inputs.
    """
    bench = tmp_path / "benchmarks"
    directory = bench / "comparison_profiles" / "core33"
    freezes = directory / "constraints"
    freezes.mkdir(parents=True)
    manifest = json.loads(
        (BENCHMARKS / "comparison_profiles" / "core33" / "manifest.json").read_text()
    )
    manifest["libraries"][library]["packages"].pop(required, None)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    source = (
        BENCHMARKS / "comparison_profiles" / "core33" / "constraints" / f"{library}.txt"
    )
    (freezes / f"{library}.txt").write_text(
        "\n".join(
            row
            for row in source.read_text().splitlines()
            if not row.startswith(f"{required}==")
        )
        + "\n"
    )
    with pytest.raises(ValueError, match="required"):
        _profile().load_profile("core33", library, bench)


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
            BENCHMARKS
            / "comparison_profiles"
            / "core33"
            / "constraints"
            / "strawberry.txt"
        ).read_bytes()
    )
    with pytest.raises(ValueError, match="mismatch"):
        _profile().load_profile("core33", "strawberry", bench)
    (freezes / "strawberry.txt").unlink()
    with pytest.raises(FileNotFoundError):
        _profile().load_profile("core33", "strawberry", bench)
