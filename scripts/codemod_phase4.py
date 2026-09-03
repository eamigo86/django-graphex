#!/usr/bin/env python
"""Migrate graphene.Mutation subclasses to django_graphex.

The idempotent Phase 4 codemod rewrites Mutation imports and replaces a
graphene.Mutation base with the django-graphex Mutation class. Within Mutation
subclasses, it renames the first self parameter of mutate and resolver methods
to root. The native Arguments container name remains unchanged.

Use --dry-run to preview changes, --show-diff to print a unified diff, or
--apply to update Python files in place. Directory targets process every Python
file below them.

The implementation uses the standard AST for analysis and a line-level rewrite
for text changes. Only targeted lines change, leaving formatting intact and
making repeated runs idempotent.
"""

from __future__ import annotations

import ast
import difflib
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Names that identify graphene.Mutation / django_graphex.Mutation
_MUTATION_NAMES: frozenset[str] = frozenset({"Mutation"})

# Attribute-access form that means graphene.Mutation
_GRAPHENE_MUTATION_ATTR = "graphene.Mutation"


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _is_mutation_base(node: ast.expr) -> bool:
    """Return whether a base-class expression refers to Mutation.

    Recognized forms are a bare Mutation name and graphene.Mutation attribute
    access.
    """
    if isinstance(node, ast.Name):
        return node.id in _MUTATION_NAMES
    if isinstance(node, ast.Attribute):
        return (
            isinstance(node.value, ast.Name)
            and node.value.id == "graphene"
            and node.attr == "Mutation"
        )
    return False


def _collect_mutation_class_ranges(tree: ast.Module) -> list[tuple[int, int]]:
    """Return [(start_line, end_line), ...] for every Mutation subclass.

    Lines are 1-based and inclusive.  Only top-level and module-level nested
    classes are scanned; deeply nested classes that happen to name Mutation
    as a base are intentionally out of scope for a first-pass codemod.
    """
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if any(_is_mutation_base(b) for b in node.bases):
            # end_lineno is available on Python 3.8+
            end = getattr(node, "end_lineno", node.lineno)
            ranges.append((node.lineno, end))
    return ranges


def _in_mutation_range(lineno: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= lineno <= end for start, end in ranges)


# ---------------------------------------------------------------------------
# Line-level transforms
# ---------------------------------------------------------------------------

# Regex for ``def mutate(self, …)`` or ``def resolve_*(self, …)``
# Captures: (indent)(def )(name)( \( )(self)(, …)
_RE_SELF_PARAM = re.compile(r"^(\s*def\s+(?:mutate|resolve_\w+)\s*\()\s*self\s*,\s*")

# Regex for ``from graphene import Mutation`` (exact; ignores multi-import lines)
_RE_FROM_GRAPHENE_MUTATION = re.compile(
    r"^(\s*)from\s+graphene\s+import\s+(.*\bMutation\b.*)"
)

# Regex for ``import graphene`` line (we may need to keep it)
_RE_IMPORT_GRAPHENE = re.compile(r"^\s*import\s+graphene\s*$")

# Regex for ``graphene.Mutation`` as a base class token (in class Foo(...):)
# We use a token-level replacement, not a whole-line match.
_RE_GRAPHENE_MUTATION_BASE = re.compile(r"\bgraphene\.Mutation\b")


def _has_import(lines: list[str], stmt: str) -> bool:
    """Return True if *stmt* already appears verbatim in *lines*."""
    needle = stmt.strip()
    return any(line.strip() == needle for line in lines)


def _transform_import_line(
    line: str,
    *,
    need_gdx_mutation: list[bool],
    already_has_gdx_mutation: bool,
) -> str | None:
    """Rewrite a graphene Mutation import line.

    Returns:
    - New line string if a replacement was made.
    - None if no change is needed.

    Side effect: marks the first need_gdx_mutation entry when graphene.Mutation
    is found in a base-class position (handled separately in caller).
    """
    m = _RE_FROM_GRAPHENE_MUTATION.match(line)
    if not m:
        return None
    indent = m.group(1)
    imports_str = m.group(2)

    # Parse the imported names from ``from graphene import X, Y, Mutation, Z``
    names = [n.strip() for n in imports_str.split(",")]

    graphene_names = [n for n in names if n != "Mutation" and n]
    has_mutation = "Mutation" in names

    if not has_mutation:
        return None

    if already_has_gdx_mutation:
        # Already imported from django_graphex — just remove Mutation from graphene import
        if graphene_names:
            return f"{indent}from graphene import {', '.join(graphene_names)}\n"
        else:
            # The entire line was ``from graphene import Mutation`` — remove it
            return ""  # empty string = delete the line
    else:
        # Replace ``from graphene import Mutation [, other]`` with two lines:
        # ``from django_graphex import Mutation`` and, if there were other names,
        # ``from graphene import other_names``
        new_line = f"{indent}from django_graphex import Mutation\n"
        if graphene_names:
            new_line += f"{indent}from graphene import {', '.join(graphene_names)}\n"
        return new_line


# ---------------------------------------------------------------------------
# Main transform
# ---------------------------------------------------------------------------


def transform_source(src: str) -> str:  # noqa: C901 (complexity justified)
    """Return the codemod-transformed version of *src*.

    The transform is IDEMPOTENT: applying it to already-transformed source
    returns the source unchanged.

    Args:
        src: Python source to transform.

    Returns:
        The transformed source, or the original source when no rewrite applies.
    """
    # Parse with ast to find Mutation subclass line ranges
    try:
        tree = ast.parse(src)
    except SyntaxError:
        # If the file can't be parsed, return it unchanged
        return src

    mutation_ranges = _collect_mutation_class_ranges(tree)

    lines = src.splitlines(keepends=True)

    # Pre-scan: does ``from django_graphex import Mutation`` already exist?
    already_has_gdx_mutation = _has_import(lines, "from django_graphex import Mutation")

    # Pre-scan: is ``graphene.Mutation`` used as a base class anywhere?
    has_graphene_mutation_base = any(
        _RE_GRAPHENE_MUTATION_BASE.search(line) for line in lines
    )

    new_lines: list[str] = []
    gdx_mutation_injected = already_has_gdx_mutation
    # Track whether we need to inject the gdx import (deferred to after last
    # ``import graphene`` or ``from graphene …`` line)
    pending_injection = has_graphene_mutation_base and not already_has_gdx_mutation

    i = 0
    while i < len(lines):
        line = lines[i]
        lineno = i + 1  # 1-based

        # ------------------------------------------------------------------
        # Import rewrites
        # ------------------------------------------------------------------

        # Rewrite ``from graphene import Mutation [, ...]``
        rewritten_import = _transform_import_line(
            line,
            need_gdx_mutation=[pending_injection],
            already_has_gdx_mutation=already_has_gdx_mutation,
        )
        if rewritten_import is not None:
            if rewritten_import == "":
                # Line deleted
                i += 1
                continue
            new_lines.append(rewritten_import)
            gdx_mutation_injected = True
            i += 1
            continue

        # Rewrite ``graphene.Mutation`` base-class usage
        if _RE_GRAPHENE_MUTATION_BASE.search(line):
            line = _RE_GRAPHENE_MUTATION_BASE.sub("Mutation", line)
            # Inject ``from django_graphex import Mutation`` before the next
            # non-import, non-blank line if not yet present
            if not gdx_mutation_injected:
                new_lines.append("from django_graphex import Mutation\n")
                gdx_mutation_injected = True

        # ------------------------------------------------------------------
        # Class-body rewrites (scoped to Mutation subclasses)
        # ------------------------------------------------------------------

        in_mutation = _in_mutation_range(lineno, mutation_ranges)

        if in_mutation:
            # Rewrite ``def mutate(self, …)`` / ``def resolve_X(self, …)``
            m_self = _RE_SELF_PARAM.match(line)
            if m_self:
                # Replace ``self,`` → ``root,`` at the first parameter position
                # m_self.group(0) is everything up to (not including) the rest
                prefix = m_self.group(1)  # ``    def mutate(``
                rest = line[m_self.end() :]  # everything after ``self, ``
                line = prefix + "root, " + rest
                new_lines.append(line)
                i += 1
                continue

        new_lines.append(line)
        i += 1

    return "".join(new_lines)


# ---------------------------------------------------------------------------
# File-level interface
# ---------------------------------------------------------------------------


def process_file(
    path: Path,
    *,
    dry_run: bool = True,
    show_diff: bool = False,
) -> bool:
    """Transform *path* in-place (unless *dry_run* is True).

    Args:
        path: Python file to transform.
        dry_run: Whether to report changes without writing the file.
        show_diff: Whether to print a unified diff.

    Returns:
        True when a change was made or would be made.
    """
    src = path.read_text(encoding="utf-8")
    result = transform_source(src)

    changed = result != src
    if not changed:
        return False

    if show_diff or dry_run:
        diff = difflib.unified_diff(
            src.splitlines(keepends=True),
            result.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path) + " (transformed)",
        )
        sys.stdout.writelines(diff)

    if not dry_run:
        path.write_text(result, encoding="utf-8")

    return True


def process_path(
    target: Path,
    *,
    dry_run: bool = True,
    show_diff: bool = False,
) -> int:
    """Process *target* (file or directory tree).

    Args:
        target: Python file or directory tree to process.
        dry_run: Whether to report changes without writing files.
        show_diff: Whether to print unified diffs.

    Returns:
        The number of files changed or that would change.
    """
    if target.is_file():
        return 1 if process_file(target, dry_run=dry_run, show_diff=show_diff) else 0

    count = 0
    for py_file in sorted(target.rglob("*.py")):
        if process_file(py_file, dry_run=dry_run, show_diff=show_diff):
            count += 1
            if not show_diff:
                verb = "Would rewrite" if dry_run else "Rewrote"
                print(f"{verb}: {py_file}")
    return count


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run the Phase 4 codemod command.

    Args:
        argv: Optional command-line arguments, excluding the executable name.

    Returns:
        A successful process status.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="codemod_phase4",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="+",
        metavar="PATH",
        help="Python files or directories to process.",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="(Default) Print a diff; do not write files.",
    )
    mode_group.add_argument(
        "--show-diff",
        action="store_true",
        help="Print a unified diff without writing files.",
    )
    mode_group.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes in-place.",
    )
    args = parser.parse_args(argv)

    dry_run = not args.apply
    show_diff = args.show_diff or (dry_run and not args.apply)

    total = 0
    for raw in args.paths:
        total += process_path(Path(raw), dry_run=dry_run, show_diff=show_diff)

    verb = "would be changed" if dry_run else "changed"
    print(f"\n{total} file(s) {verb}.")
    return 0 if total == 0 else 0  # Always exit 0; non-zero reserved for errors


if __name__ == "__main__":
    sys.exit(main())
