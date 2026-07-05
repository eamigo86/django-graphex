"""Conftest for tests/core/.

Provides the "normalize_sdl()" utility for SDL structural comparison.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# normalize_sdl
# ---------------------------------------------------------------------------


def normalize_sdl(sdl: str) -> str:
    """Normalize a GraphQL SDL string for structural comparison.

    Strips descriptions, sorts type blocks and fields within blocks.

    Steps:
    1. Remove triple-quoted description strings (GraphQL SDL descriptions).
    2. Remove single-line "#" comments.
    3. Strip leading/trailing whitespace per line.
    4. Remove blank lines within type blocks.
    5. Split SDL into type blocks (each starting with a keyword + name).
    6. Within each block, sort field lines alphabetically.
    7. Sort type blocks alphabetically by type name.
    8. Rejoin with a single blank line between blocks.

    This function is idempotent: applying it twice yields the same result as
    applying it once.

    Args:
        sdl: The raw GraphQL SDL text to normalize.

    Returns:
        normalized: The SDL text with descriptions and comments stripped,
            and its type blocks and fields sorted for stable comparison.
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
