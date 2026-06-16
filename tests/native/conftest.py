"""Conftest for tests/native/ — GDX_BACKEND harness.

Sets up:
- ``GDX_BACKEND`` env var at collection time (default: ``native`` for this
  native test directory).
- ``native_only`` pytest mark so these tests can be excluded from the graphene
  CI job.
- ``normalize_sdl()`` utility for SDL structural comparison.

Usage:
    # Native backend CI job (this directory only):
    GDX_BACKEND=native .venv/bin/python -m pytest tests/native/ -q

    # Graphene path additivity gate (excludes tests/native/):
    GDX_BACKEND=graphene .venv/bin/python -m pytest tests/ --ignore=tests/native/ -q
"""
from __future__ import annotations

import os
import re


# ---------------------------------------------------------------------------
# normalize_sdl
# ---------------------------------------------------------------------------


def normalize_sdl(sdl: str) -> str:
    """Normalize a GraphQL SDL string for structural comparison.

    Strips descriptions, sorts type blocks and fields within blocks.

    Steps:
    1. Remove triple-quoted description strings (``\"\"\"...\"\"\"``).
    2. Remove single-line ``#`` comments.
    3. Strip leading/trailing whitespace per line.
    4. Remove blank lines within type blocks.
    5. Split SDL into type blocks (each starting with a keyword + name).
    6. Within each block, sort field lines alphabetically.
    7. Sort type blocks alphabetically by type name.
    8. Rejoin with a single blank line between blocks.

    This function is idempotent: normalize_sdl(normalize_sdl(sdl)) == normalize_sdl(sdl).
    """
    # Step 1: Strip triple-quoted descriptions (multi-line and single-line)
    sdl = re.sub(r'""".*?"""', "", sdl, flags=re.DOTALL)

    # Step 2: Strip single-line # comments
    sdl = re.sub(r"#[^\n]*", "", sdl)

    # Step 3: Strip leading/trailing whitespace per line, drop empty lines
    lines = [line.strip() for line in sdl.splitlines()]
    lines = [line for line in lines if line]

    # Step 4-7: Parse into type blocks and sort them
    # A block starts at a keyword (type, input, enum, interface, union, scalar, schema)
    block_keywords = re.compile(
        r"^(type|input|enum|interface|union|scalar|schema|directive|extend)\s"
    )

    blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in lines:
        if block_keywords.match(line) and current_block:
            blocks.append(current_block)
            current_block = [line]
        else:
            current_block.append(line)

    if current_block:
        blocks.append(current_block)

    # Sort fields within each block (lines between { and })
    def sort_block_fields(block: list[str]) -> list[str]:
        if len(block) < 3:
            return block

        # Find the opening brace line
        header_lines = []
        body_lines = []
        footer_lines = []
        in_body = False
        closed = False

        for line in block:
            if not in_body and "{" in line:
                if line.strip() == "{":
                    header_lines.append(line)
                else:
                    # Header + opening brace on same line
                    header_lines.append(line)
                in_body = True
            elif in_body and "}" in line:
                footer_lines.append(line)
                closed = True
                in_body = False
            elif in_body:
                body_lines.append(line)
            else:
                header_lines.append(line)

        if body_lines:
            body_lines.sort()

        return header_lines + body_lines + footer_lines

    sorted_blocks = [sort_block_fields(b) for b in blocks]

    # Sort blocks by their first line (type name)
    def block_sort_key(block: list[str]) -> str:
        if not block:
            return ""
        # Extract name from "type Foo {" → "Foo"
        match = re.match(r"\w+\s+(\w+)", block[0])
        return match.group(1).lower() if match else block[0].lower()

    sorted_blocks.sort(key=block_sort_key)

    # Step 8: Rejoin
    result_lines: list[str] = []
    for i, block in enumerate(sorted_blocks):
        if i > 0:
            result_lines.append("")
        result_lines.extend(block)

    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# pytest configuration
# ---------------------------------------------------------------------------


def pytest_configure(config: object) -> None:
    """Register the ``native_only`` mark (retained for back-compat).

    S7 (graphene-removal): the native backend is now the suite DEFAULT (set in
    ``tests/conftest.py``), so ``native_only`` no longer gates collection — the
    mark stays registered only so existing ``@pytest.mark.native_only`` decorators
    remain valid markers. The auto-skip (which excluded these tests under the old
    ``GDX_BACKEND=graphene`` default) is gone: a bare ``pytest`` runs native and
    these tests always run.
    """
    import pytest as _pytest
    _pytest.ini_options = getattr(_pytest, "ini_options", {})
    config.addinivalue_line(  # type: ignore[attr-defined]
        "markers",
        "native_only: mark test as native-backend only (suite default since S7)",
    )
