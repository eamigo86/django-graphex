"""The sdist ships every repository-root file that the tests read."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# A root-anchored path literal: ROOT / "name", parents[1] / "name", and so on.
_ROOT_LITERAL = re.compile(
    r"(?:ROOT|REPO_ROOT|project_root|parents\[\d\]|parent\.parent)"
    r"\s*/\s*\(?\s*[\"']([^\"'/]+)[\"']"
)


def _included() -> list[str]:
    """Read the sdist include allowlist from pyproject.toml.

    Returns:
        The include entries without their leading slash.
    """
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    entries = config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    return [entry.lstrip("/") for entry in entries]


def _root_files_read_by_tests() -> set[str]:
    """Collect the root-level files that test modules reference by literal.

    Directories are out of scope: some (benchmarks, examples) are too large to
    ship, so only plain files at the repository root are checked.

    Returns:
        The file names found next to pyproject.toml.
    """
    names: set[str] = set()
    for module in (ROOT / "tests").rglob("*.py"):
        names.update(_ROOT_LITERAL.findall(module.read_text(encoding="utf-8")))
    return {name for name in names if (ROOT / name).is_file()}


def test_every_root_file_read_by_a_test_is_in_the_sdist_allowlist() -> None:
    """A published tarball must not lose the inputs of its own tests.

    Directories such as benchmarks and examples are not checked; see the scan.
    """
    included = _included()
    files = _root_files_read_by_tests()
    assert {"CHANGELOG.md", "pyproject.toml"} <= files  # the scan finds something
    missing = sorted(
        name
        for name in files
        if not any(name == entry or name.startswith(f"{entry}/") for entry in included)
    )
    assert not missing, f"add to [tool.hatch.build.targets.sdist] include: {missing}"
