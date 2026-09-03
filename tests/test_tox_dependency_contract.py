"""Contract that keeps tox tool ranges aligned with project development bounds."""

from __future__ import annotations

import configparser
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]
TOX_TOOL_NAMES = {
    "bandit",
    "build",
    "coverage",
    "factory-boy",
    "mypy",
    "pip-audit",
    "pytest",
    "pytest-asyncio",
    "pytest-cov",
    "pytest-django",
    "pytest-randomly",
    "ruff",
    "types-python-dateutil",
    "zensical",
}


def _requirement_name(requirement: str) -> str:
    """Return a normalized distribution name from a PEP 508-style string."""
    requirement = requirement.split(":", 1)[-1].strip()
    match = re.match(r"([A-Za-z0-9_.-]+)", requirement)
    assert match is not None, requirement
    return match.group(1).lower().replace("_", "-")


def _requirement_spec(requirement: str) -> str:
    """Return the comparison portion while ignoring extras and whitespace."""
    requirement = requirement.split(":", 1)[-1].strip().replace(" ", "")
    return re.sub(r"^[A-Za-z0-9_.-]+(?:\[[^]]+\])?", "", requirement)


def _tox_dependencies() -> list[str]:
    """Return every concrete dependency declared by tox environments."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ROOT / "tox.ini")
    dependencies: list[str] = []
    for section in parser.sections():
        if not section.startswith("testenv") or not parser.has_option(section, "deps"):
            continue
        dependencies.extend(
            line.strip()
            for line in parser.get(section, "deps").splitlines()
            if line.strip()
        )
    return dependencies


def test_tox_tool_ranges_match_declared_dev_compatibility() -> None:
    """Every tox tool uses the same deliberate range as "dependency-groups.dev".

    This test protects the corresponding regression contract.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dev = {
        _requirement_name(requirement): _requirement_spec(requirement)
        for requirement in pyproject["dependency-groups"]["dev"]
    }
    assert TOX_TOOL_NAMES <= dev.keys()

    seen: set[str] = set()
    for requirement in _tox_dependencies():
        name = _requirement_name(requirement)
        if name not in TOX_TOOL_NAMES:
            continue
        seen.add(name)
        spec = _requirement_spec(requirement)
        assert spec == dev[name], (
            f"tox {requirement!r} drifts from dev range {dev[name]!r}"
        )
        assert ">=" in spec and "<" in spec, f"unbounded tox dependency: {requirement}"
    assert TOX_TOOL_NAMES <= seen


def test_diff_cover_has_a_deliberate_dev_range() -> None:
    """The standalone patch-coverage tool must not resolve to an arbitrary major.

    This test protects the corresponding regression contract.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dev = {
        _requirement_name(requirement): _requirement_spec(requirement)
        for requirement in pyproject["dependency-groups"]["dev"]
    }
    assert dev["diff-cover"] == ">=10.5.1,<11"


def test_ruff_range_stays_with_formatter_compatible_minor() -> None:
    """Keep CI on the Ruff minor used to format the repository.

    This prevents a newer formatter minor from rejecting unchanged files.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dev = {
        _requirement_name(requirement): _requirement_spec(requirement)
        for requirement in pyproject["dependency-groups"]["dev"]
    }
    assert dev["ruff"] == ">=0.15.17,<0.16"
