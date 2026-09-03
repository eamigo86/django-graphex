"""Validate and render a deterministic benchmark environment freeze."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Mapping
from importlib.metadata import Distribution, distributions
from pathlib import Path


def _normalize(value: str) -> str:
    """Return the normalized package name used by Python packaging tools."""
    return re.sub(r"[-_.]+", "-", value).lower()


def _load_constraints(path: Path) -> dict[str, str]:
    """Read exact package versions from a constraints file."""
    return {
        _normalize(name): version
        for line in path.read_text().splitlines()
        if line and not line.startswith("#")
        for name, version in (line.split("==", 1),)
    }


def render_verified_freeze(
    installed: Iterable[Distribution], constraints: Mapping[str, str], lib: str
) -> str:
    """Return a stable freeze, rejecting packages outside the canonical lock."""
    rows = []
    for dist in installed:
        name = _normalize(dist.metadata["Name"])
        version = dist.version
        if name != "django-graphex" and constraints.get(name) != version:
            raise SystemExit(f"unfrozen dependency in {lib}: {name}=={version}")
        rows.append(f"{name}=={version}")
    return "\n".join(sorted(rows)) + "\n"


def main() -> None:
    """Validate the active environment and print its deterministic freeze."""
    constraints_path = Path(sys.argv[1])
    sys.stdout.write(
        render_verified_freeze(
            distributions(), _load_constraints(constraints_path), sys.argv[2]
        )
    )


if __name__ == "__main__":
    main()
