"""Structural contracts for reproducible uv installation in CI."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github/workflows"
UV_VERSION = "0.12.9"


def _setup_uv_steps() -> list[tuple[Path, int, list[str]]]:
    steps: list[tuple[Path, int, list[str]]] = []
    setup_uv = re.compile(r"^(?P<indent> *)(?P<dash>-\s+)?uses:\s*astral-sh/setup-uv@")

    for path in sorted((*WORKFLOWS.glob("*.yaml"), *WORKFLOWS.glob("*.yml"))):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            match = setup_uv.match(line)
            if match is None:
                continue

            key_indent = len(match["indent"]) + (2 if match["dash"] else 0)
            step_indent = key_indent - 2
            start = index
            if match["dash"] is None:
                while start >= 0:
                    candidate = re.match(r"^( *)-\s+", lines[start])
                    if candidate and len(candidate[1]) == step_indent:
                        break
                    start -= 1
                assert start >= 0, f"{path}:{index + 1}: setup-uv is not in a step"

            end = index + 1
            while end < len(lines):
                candidate = lines[end]
                if candidate.strip() and not candidate.lstrip().startswith("#"):
                    indent = len(candidate) - len(candidate.lstrip())
                    if indent <= step_indent:
                        break
                end += 1
            steps.append((path, index + 1, lines[start:end]))

    return steps


def test_setup_uv_uses_one_exact_reproducible_version() -> None:
    """Require every setup-uv step to use the same exact uv release.

    The pin prevents CI from consulting the latest-version manifest at runtime.
    """
    steps = _setup_uv_steps()
    assert steps, "no astral-sh/setup-uv steps found in GitHub workflows"

    violations: list[str] = []
    versions: list[str] = []
    for path, line, step in steps:
        with_lines = [
            (index, len(value) - len(value.lstrip()))
            for index, value in enumerate(step)
            if value.strip() == "with:"
        ]
        if len(with_lines) != 1:
            violations.append(
                f"{path.relative_to(ROOT)}:{line}: expected one with mapping"
            )
            continue

        with_line, with_indent = with_lines[0]
        version_lines = []
        for value in step[with_line + 1 :]:
            if not value.strip() or value.lstrip().startswith("#"):
                continue
            indent = len(value) - len(value.lstrip())
            if indent <= with_indent:
                break
            if indent == with_indent + 2 and value.lstrip().startswith("version:"):
                version_lines.append(value)

        if len(version_lines) != 1:
            violations.append(
                f"{path.relative_to(ROOT)}:{line}: expected one with.version"
            )
            continue

        raw_version = version_lines[0].split(":", 1)[1].split("#", 1)[0].strip()
        version = raw_version.strip("'\"")
        versions.append(version)
        if version != UV_VERSION:
            violations.append(
                f"{path.relative_to(ROOT)}:{line}: expected uv {UV_VERSION}, got "
                f"{raw_version or '<empty>'}"
            )

    assert not violations, "\n".join(violations)
    assert set(versions) == {UV_VERSION}
