"""Validate an observed benchmark profile before creating any environment."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

LIBRARIES = ("graphex", "graphene", "strawberry", "ariadne")
PROFILES = ("core33",)
_PIN = re.compile(r"([a-z0-9][a-z0-9-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)")


def load_constraints(path: Path) -> dict[str, str]:
    """Read a complete exact-pin file without accepting ambiguous rows.

    Args:
        path: File containing one exact distribution pin per line.

    Returns:
        Distribution names mapped to exact versions.

    Raises:
        ValueError: If a row is malformed or names a distribution twice.
    """
    pins: dict[str, str] = {}
    for row in path.read_text().splitlines():
        if not row or row.startswith("#"):
            continue
        match = _PIN.fullmatch(row)
        if match is None or match[1] in pins:
            raise ValueError(f"invalid or duplicate freeze row: {row}")
        pins[match[1]] = match[2]
    if not pins:
        raise ValueError(f"empty freeze: {path}")
    return pins


def load_profile(profile: str, library: str, benchmarks: Path) -> dict[str, Any]:
    """Validate a named profile and its selected library before installation.

    Args:
        profile: Explicit profile identifier.
        library: One of the four benchmark adapters.
        benchmarks: Directory containing the profile manifest and freezes.

    Returns:
        Validated direct pins, complete freeze, interpreter and source mode.

    Raises:
        ValueError: If the profile, library, or its direct pins are inconsistent.
        FileNotFoundError: If the manifest or selected freeze is absent.
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown profile: {profile}")
    if library not in LIBRARIES:
        raise ValueError(f"unknown library: {library}")
    directory = benchmarks / "comparison_profiles" / profile
    manifest = json.loads((directory / "manifest.json").read_text())
    spec = manifest["libraries"][library]
    path = directory / "constraints" / f"{library}.txt"
    freeze = load_constraints(path)
    for name, version in spec["packages"].items():
        if freeze.get(name) != version:
            raise ValueError(f"manifest/freeze mismatch for {library}: {name}")
    return {
        "python": manifest["python"],
        "mode": spec["mode"],
        "packages": spec["packages"],
        "constraints": path,
        "freeze": freeze,
    }


def main(argv: list[str] | None = None) -> int:
    """Print a validated constraint path for the shell bootstrap.

    Args:
        argv: Profile, library, and benchmark directory; defaults to sys.argv.

    Returns:
        Zero after validation, or one for invalid profile input.
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        print("usage: profile_bootstrap.py PROFILE LIBRARY BENCHMARKS", file=sys.stderr)
        return 1
    try:
        spec = load_profile(args[0], args[1], Path(args[2]))
    except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"invalid benchmark profile: {exc}", file=sys.stderr)
        return 1
    print(spec["constraints"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
