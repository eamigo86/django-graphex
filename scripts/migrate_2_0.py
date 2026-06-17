#!/usr/bin/env python
"""django-graphex v1.x -> v2.0 migration codemod.

v2.0 removed the legacy **graphene** backend ENTIRELY (decision: full excision).
``graphene`` is no longer a dependency and is never imported, even on a full
build + mutations + subscriptions + pagination. The native graphql-core +
Pydantic path is the only path.

This codemod helps you move a project off graphene. It has two modes of
operation per construct:

1. MECHANICAL REWRITE (safe, automated with ``--apply``)
   - The schema/middleware settings namespace ``GRAPHENE = {...}`` is folded into
     the SINGLE ``DJANGO_GRAPHEX = {...}`` namespace (django-graphex unified its
     two settings dicts in v2.0):
       * if the module has no ``DJANGO_GRAPHEX`` dict yet, ``GRAPHENE`` is simply
         renamed to ``DJANGO_GRAPHEX``;
       * if a ``DJANGO_GRAPHEX`` dict already exists, the ``GRAPHENE`` keys are
         MERGED into it (DJANGO_GRAPHEX wins on the rare key collision) and the
         old ``GRAPHENE`` assignment is dropped.

2. REPORT-AND-FLAG (always; never auto-rewritten because the native shape is not
   a 1:1 token swap)
   - ``graphene.Argument(...)`` inside a ``Mutation`` ``class args`` → native
     ``graphql.GraphQLArgument(...)`` (v2.0 raises ``TypeError`` for non-native
     args — CLEAN BREAK).
   - ``graphene.ObjectType`` schema roots → ``from django_graphex import ObjectType``.
   - ``graphene.Schema(...)`` → ``django_graphex.DjangoGraphQLSchema(...)``.
   - graphene field descriptors (``graphene.String()`` / ``graphene.Field(...)``
     on a type body) → ``field(GraphQLString)`` / native ``field(...)``.

See ``docs/UPGRADE-2.0.md`` for the full before/after migration guide.

Usage::

    # Report only (default; no files written) — recommended first pass:
    python scripts/migrate_2_0.py path/to/project/

    # Show what the mechanical settings rewrite WOULD change (unified diff):
    python scripts/migrate_2_0.py --show-diff path/to/settings.py

    # Apply the mechanical GRAPHENE -> DJANGO_GRAPHEX settings rewrite in place
    # (graphene constructs are still reported, never auto-rewritten):
    python scripts/migrate_2_0.py --apply path/to/project/

Implementation note
-------------------
``libcst`` is not assumed present, and — critically — ``graphene`` is uninstalled
in v2.0, so this script NEVER imports graphene. It operates purely on source
text: ``ast`` for *analysis* (locating graphene constructs and their line
numbers, and the ``GRAPHENE`` / ``DJANGO_GRAPHEX`` settings dicts). The
mechanical transform folds ``GRAPHENE = {...}`` into ``DJANGO_GRAPHEX = {...}``:
a plain rename when no target dict exists, or a key merge when it does. All other
formatting is preserved and the rewrite is idempotent (a module with no
``GRAPHENE`` dict is returned unchanged).
"""
from __future__ import annotations

import argparse
import ast
import difflib
import re
import sys
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path

# --------------------------------------------------------------------------- #
# The legacy schema/middleware settings namespace that v2.0 folded away.       #
# ``GRAPHENE`` (read by graphene-django / the old backend) -> ``DJANGO_GRAPHEX``#
# (the SINGLE django-graphex settings namespace; the two v1.x dicts were        #
# unified). If a ``DJANGO_GRAPHEX`` dict already exists the keys are MERGED in. #
# --------------------------------------------------------------------------- #
_LEGACY_SETTINGS_NAMESPACE = "GRAPHENE"
_CANONICAL_SETTINGS_NAMESPACE = "DJANGO_GRAPHEX"

# A top-level assignment target ``GRAPHENE = ...`` (not ``DJANGO_GRAPHEX``, which
# is a different identifier and never matches this anchored pattern).
_SETTINGS_ASSIGN_RE = re.compile(
    r"^(?P<indent>\s*)" + _LEGACY_SETTINGS_NAMESPACE + r"(?P<rest>\s*=\s*)"
)


# --------------------------------------------------------------------------- #
# Findings — a flagged graphene construct that the user must port by hand.     #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Finding:
    """A graphene construct v2.0 no longer accepts, with porting guidance."""

    kind: str
    line: int
    path: str
    snippet: str
    guidance: str


@dataclass
class RunResult:
    """Aggregate outcome of a :func:`run` invocation."""

    findings: list[Finding] = dataclass_field(default_factory=list)
    rewritten_files: list[str] = dataclass_field(default_factory=list)
    would_rewrite_files: list[str] = dataclass_field(default_factory=list)


# --------------------------------------------------------------------------- #
# Guidance text (kept in one place so the report and the docs stay in sync).   #
# --------------------------------------------------------------------------- #
_GUIDANCE = {
    "graphene-argument": (
        "graphene.Argument(...) in a Mutation `class args` is no longer accepted "
        "(CLEAN BREAK: v2.0 raises TypeError). Use the native graphql-core arg API:\n"
        "    from graphql import GraphQLArgument, GraphQLNonNull, GraphQLString\n"
        "    class args:\n"
        "        name = GraphQLArgument(GraphQLNonNull(GraphQLString))\n"
        "(a bare graphql-core type is also accepted and auto-wrapped in a "
        "GraphQLArgument)."
    ),
    "graphene-objecttype": (
        "graphene.ObjectType schema roots are gone. Use the native root base:\n"
        "    from django_graphex import ObjectType\n"
        "    class Query(ObjectType):\n"
        "        ..."
    ),
    "graphene-schema": (
        "graphene.Schema(...) is gone. Build the schema with "
        "django_graphex.DjangoGraphQLSchema:\n"
        "    from django_graphex import DjangoGraphQLSchema\n"
        "    schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)"
    ),
    "graphene-field-descriptor": (
        "graphene field descriptors (graphene.String() / graphene.Field(...)) on a "
        "type/root body are gone. Use the native field() helper with a graphql-core "
        "type:\n"
        "    from django_graphex import field\n"
        "    from graphql import GraphQLString\n"
        "    server_time = field(GraphQLString, description='ISO timestamp')"
    ),
}

# graphene descriptor callables that map to native ``field(GraphQL<Scalar>)``.
_GRAPHENE_FIELD_DESCRIPTORS = frozenset(
    {
        "String",
        "Int",
        "Float",
        "Boolean",
        "ID",
        "DateTime",
        "Date",
        "Time",
        "Decimal",
        "UUID",
        "JSONString",
        "Field",
        "List",
        "NonNull",
        "Dynamic",
    }
)


# --------------------------------------------------------------------------- #
# AST helpers                                                                  #
# --------------------------------------------------------------------------- #
def _is_graphene_attr(node: ast.AST, attr: str | None = None) -> bool:
    """True if ``node`` is ``graphene.<attr>`` (or any ``graphene.X`` if attr is None)."""
    if not isinstance(node, ast.Attribute):
        return False
    if not (isinstance(node.value, ast.Name) and node.value.id == "graphene"):
        return False
    return attr is None or node.attr == attr


def _base_is_graphene(base: ast.AST, name: str, native_names: frozenset[str]) -> bool:
    """True if a class base is the GRAPHENE ``<name>`` (qualified or bare).

    A bare ``<name>`` base counts as graphene only when it was imported from
    graphene (``from graphene import ObjectType``) — NOT when it is the NATIVE
    ``django_graphex`` symbol of the same name (``from django_graphex import
    ObjectType``), which is the v2.0 replacement.
    """
    if _is_graphene_attr(base, name):
        return True
    # ``from graphene import ObjectType`` then ``class Query(ObjectType)``.
    return (
        isinstance(base, ast.Name)
        and base.id == name
        and name not in native_names
    )


def _module_imports_graphene(tree: ast.Module) -> bool:
    """True if the module imports graphene (so bare ``ObjectType`` bases count)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] == "graphene" for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "graphene":
                return True
    return False


def _native_imported_names(tree: ast.Module) -> frozenset[str]:
    """Names imported from ``django_graphex`` (the native API, NOT graphene).

    Used to disambiguate a bare ``ObjectType`` / ``Mutation`` base: if it came
    from ``django_graphex`` it is already the v2.0 form and must NOT be flagged.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "django_graphex"
        ):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return frozenset(names)


def _snippet(source_lines: list[str], lineno: int) -> str:
    idx = lineno - 1
    if 0 <= idx < len(source_lines):
        return source_lines[idx].strip()
    return ""


# --------------------------------------------------------------------------- #
# Analysis (report-and-flag) — pure source string in, findings out.            #
# --------------------------------------------------------------------------- #
def analyze_source(source: str, *, path: str = "<source>") -> list[Finding]:
    """Find graphene constructs v2.0 rejects. Returns findings sorted by line.

    Never imports graphene — works entirely on the parsed AST of ``source``.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    graphene_imported = _module_imports_graphene(tree)
    native_names = _native_imported_names(tree)
    source_lines = source.splitlines()
    findings: list[Finding] = []

    def add(kind: str, node: ast.AST) -> None:
        lineno = getattr(node, "lineno", 1)
        findings.append(
            Finding(
                kind=kind,
                line=lineno,
                path=path,
                snippet=_snippet(source_lines, lineno),
                guidance=_GUIDANCE[kind],
            )
        )

    # Track which classes are graphene.Mutation subclasses so we only flag
    # graphene.Argument inside a real Mutation `class args` body.
    for node in ast.walk(tree):
        # graphene.ObjectType root.
        if isinstance(node, ast.ClassDef):
            if any(_base_is_graphene(b, "ObjectType", native_names) for b in node.bases):
                add("graphene-objecttype", node)
            is_mutation = any(
                _base_is_graphene(b, "Mutation", native_names) for b in node.bases
            )
            if is_mutation:
                _flag_mutation_args(node, add)

        # graphene.Schema(...) call.
        if isinstance(node, ast.Call) and _is_graphene_attr(node.func, "Schema"):
            add("graphene-schema", node)

    # graphene field descriptors anywhere at a class body's statement level
    # (e.g. ``ok = graphene.Boolean()`` / ``me = graphene.Field(UserType)``).
    # Skip those nested inside a `class args` (already covered as args).
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "args":
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                _is_graphene_attr(node.func)
                and node.func.attr in _GRAPHENE_FIELD_DESCRIPTORS
            ):
                # Don't double-report graphene.Argument (its own kind) or Schema.
                add("graphene-field-descriptor", node)

    # Suppress field-descriptor noise if graphene isn't even imported (the
    # attribute access could be an unrelated `graphene` local). Conservative.
    if not graphene_imported:
        findings = [f for f in findings if f.kind != "graphene-field-descriptor"]

    return sorted(findings, key=lambda f: (f.line, f.kind))


def _flag_mutation_args(mutation: ast.ClassDef, add) -> None:
    """Flag every ``graphene.Argument(...)`` declared in a Mutation `class args`."""
    for stmt in mutation.body:
        if isinstance(stmt, ast.ClassDef) and stmt.name == "args":
            for arg_stmt in ast.walk(stmt):
                if isinstance(arg_stmt, ast.Call) and _is_graphene_attr(
                    arg_stmt.func, "Argument"
                ):
                    add("graphene-argument", arg_stmt)


# --------------------------------------------------------------------------- #
# Mechanical rewrite — GRAPHENE settings namespace -> DJANGO_GRAPHEX.           #
# --------------------------------------------------------------------------- #
def _module_assignment(tree: ast.Module, name: str) -> ast.Assign | ast.AnnAssign | None:
    """Return the LAST module-level assignment to ``name`` (a dict target), if any."""
    found: ast.Assign | ast.AnnAssign | None = None
    for node in tree.body:  # module level only
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    found = node
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                found = node
    return found


def _dict_value(node: ast.Assign | ast.AnnAssign) -> ast.Dict | None:
    """Return the assigned value when it is a dict literal, else None."""
    value = node.value if isinstance(node, ast.AnnAssign) else node.value
    return value if isinstance(value, ast.Dict) else None


def _rename_only(source: str, target_lines: set[int]) -> tuple[str, bool]:
    """Rename the ``GRAPHENE =`` assignment target line(s) to ``DJANGO_GRAPHEX``."""
    out_lines: list[str] = []
    changed = False
    for i, line in enumerate(source.splitlines(keepends=True), start=1):
        if i in target_lines:
            new_line, n = _SETTINGS_ASSIGN_RE.subn(
                r"\g<indent>" + _CANONICAL_SETTINGS_NAMESPACE + r"\g<rest>",
                line,
                count=1,
            )
            if n:
                changed = True
                out_lines.append(new_line)
                continue
        out_lines.append(line)
    return "".join(out_lines), changed


def _dict_entries(
    source: str, dict_node: ast.Dict
) -> list[tuple[str | None, str, str]]:
    """Extract ``(key_literal, key_source, value_source)`` for each dict entry.

    ``key_literal`` is the literal string key when the key is a constant string
    (used for collision detection), else ``None``. ``key_source`` /
    ``value_source`` preserve the exact source text so non-literal values
    (import expressions, tuples, …) survive the merge verbatim.
    """
    entries: list[tuple[str | None, str, str]] = []
    for key, value in zip(dict_node.keys, dict_node.values):
        if key is None:  # ``**spread`` — keep source, no literal key
            value_src = ast.get_source_segment(source, value) or ""
            entries.append((None, f"**{value_src}", ""))
            continue
        key_src = ast.get_source_segment(source, key) or ""
        value_src = ast.get_source_segment(source, value) or ""
        key_literal = key.value if isinstance(key, ast.Constant) and isinstance(
            key.value, str
        ) else None
        entries.append((key_literal, key_src, value_src))
    return entries


def rewrite_source(source: str) -> tuple[str, bool]:
    """Fold the legacy ``GRAPHENE = {...}`` settings dict into ``DJANGO_GRAPHEX``.

    Two cases (django-graphex unified its two settings namespaces in v2.0):

    * No ``DJANGO_GRAPHEX`` dict in the module → the ``GRAPHENE =`` assignment
      target is renamed to ``DJANGO_GRAPHEX`` (a conservative, line-anchored
      rename; values are preserved verbatim).
    * A ``DJANGO_GRAPHEX`` dict already exists → the ``GRAPHENE`` keys are MERGED
      into it (the existing ``DJANGO_GRAPHEX`` value wins on a key collision) and
      the old ``GRAPHENE`` assignment block is removed.

    ``DJANGO_GRAPHEX`` is never matched as a legacy target. Returns
    ``(new_source, changed)``; a module with no ``GRAPHENE`` dict is unchanged.
    """
    # AST gate: only rewrite when there is a real module-level ``GRAPHENE``
    # assignment target (avoids touching the token inside strings/comments).
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, False

    graphene_assign = _module_assignment(tree, _LEGACY_SETTINGS_NAMESPACE)
    if graphene_assign is None:
        return source, False

    graphene_dict = _dict_value(graphene_assign)
    target_assign = _module_assignment(tree, _CANONICAL_SETTINGS_NAMESPACE)
    target_dict = _dict_value(target_assign) if target_assign is not None else None

    # --- Case 1: no existing DJANGO_GRAPHEX dict (or non-dict values) -> rename.
    if target_dict is None or graphene_dict is None:
        target_lines: set[int] = set()
        if isinstance(graphene_assign, ast.Assign):
            for tgt in graphene_assign.targets:
                if isinstance(tgt, ast.Name) and tgt.id == _LEGACY_SETTINGS_NAMESPACE:
                    target_lines.add(tgt.lineno)
        elif isinstance(graphene_assign.target, ast.Name):
            target_lines.add(graphene_assign.target.lineno)
        return _rename_only(source, target_lines)

    # --- Case 2: merge GRAPHENE keys into the existing DJANGO_GRAPHEX dict. -----
    existing_keys = {
        key_literal
        for key_literal, _key_src, _val_src in _dict_entries(source, target_dict)
        if key_literal is not None
    }
    graphene_entries = _dict_entries(source, graphene_dict)
    # DJANGO_GRAPHEX wins on a collision: skip GRAPHENE keys already present.
    new_entries = [
        (key_src, val_src)
        for key_literal, key_src, val_src in graphene_entries
        if key_literal is None or key_literal not in existing_keys
    ]

    lines = source.splitlines(keepends=True)
    # 1-based, inclusive end line of each construct.
    g_start = graphene_assign.lineno
    g_end = graphene_assign.end_lineno or g_start
    t_dict_end = target_dict.end_lineno or target_assign.lineno

    # Indentation of the target dict's entries (match the first entry, else 4 sp).
    if target_dict.values:
        first_val = target_dict.values[0]
        entry_indent = " " * ((first_val.col_offset or 4))
        # col_offset of the value is past the key; recover from the key instead.
        first_key = target_dict.keys[0]
        if first_key is not None:
            entry_indent = " " * (first_key.col_offset or 4)
    else:
        entry_indent = "    "

    injected = "".join(
        f"{entry_indent}{key_src}: {val_src},\n" if key_src and not key_src.startswith("**")
        else f"{entry_indent}{key_src},\n"
        for key_src, val_src in new_entries
    )

    out: list[str] = []
    for i, line in enumerate(lines, start=1):
        # Drop the entire GRAPHENE assignment block.
        if g_start <= i <= g_end:
            continue
        # Inject merged entries just before the DJANGO_GRAPHEX dict's closing brace.
        if i == t_dict_end and injected:
            close_idx = line.rfind("}")
            if close_idx != -1:
                out.append(line[:close_idx])
                out.append(injected)
                out.append(line[close_idx:])
                continue
        out.append(line)

    # Collapse a blank line left where the GRAPHENE block used to be (cosmetic).
    merged = "".join(out)
    merged = re.sub(r"\n\n\n+", "\n\n", merged)
    return merged, True


# --------------------------------------------------------------------------- #
# Reporting                                                                    #
# --------------------------------------------------------------------------- #
def format_report(findings: list[Finding]) -> str:
    """Render findings as an actionable human report."""
    if not findings:
        return "No graphene constructs detected. Source is v2.0-ready.\n"

    by_kind: dict[str, list[Finding]] = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)

    label = {
        "graphene-argument": "graphene.Argument(...) in Mutation `class args`",
        "graphene-objecttype": "graphene.ObjectType schema root",
        "graphene-schema": "graphene.Schema(...)",
        "graphene-field-descriptor": "graphene field descriptor",
    }

    parts: list[str] = ["graphene constructs that must be ported to native v2.0:\n"]
    for kind, items in by_kind.items():
        parts.append(f"\n## {label.get(kind, kind)} ({len(items)})")
        for it in items:
            parts.append(f"  {it.path}:{it.line}: {it.snippet}")
        parts.append("  -> " + _GUIDANCE[kind].replace("\n", "\n     "))
    return "\n".join(parts) + "\n"


# --------------------------------------------------------------------------- #
# Driver                                                                       #
# --------------------------------------------------------------------------- #
def _iter_python_files(paths: list[str]):
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            yield from sorted(p.rglob("*.py"))
        elif p.suffix == ".py":
            yield p


def run(paths: list[str], *, apply: bool = False) -> RunResult:
    """Analyze (and optionally rewrite) the given files / directories.

    - Always: analyze every ``.py`` file and collect graphene-construct findings.
    - With ``apply=True``: rewrite the mechanical ``GRAPHENE -> DJANGO_GRAPHEX``
      settings namespace in place. graphene constructs are NEVER auto-rewritten.
    """
    result = RunResult()
    for file_path in _iter_python_files(paths):
        try:
            source = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        result.findings.extend(analyze_source(source, path=str(file_path)))

        new_source, changed = rewrite_source(source)
        if changed:
            if apply:
                file_path.write_text(new_source, encoding="utf-8")
                result.rewritten_files.append(str(file_path))
            else:
                result.would_rewrite_files.append(str(file_path))

    return result


def _show_diff(paths: list[str]) -> None:
    for file_path in _iter_python_files(paths):
        source = file_path.read_text(encoding="utf-8")
        new_source, changed = rewrite_source(source)
        if changed:
            diff = difflib.unified_diff(
                source.splitlines(keepends=True),
                new_source.splitlines(keepends=True),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
            )
            sys.stdout.writelines(diff)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns 1 when manual porting is still required."""
    parser = argparse.ArgumentParser(
        description="django-graphex v1.x -> v2.0 migration codemod.",
    )
    parser.add_argument("paths", nargs="+", help="Files or directories to process.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--apply",
        action="store_true",
        help="Apply the mechanical GRAPHENE -> DJANGO_GRAPHEX settings rewrite in place.",
    )
    group.add_argument(
        "--show-diff",
        action="store_true",
        help="Print a unified diff of the settings rewrite without writing.",
    )
    args = parser.parse_args(argv)

    if args.show_diff:
        _show_diff(args.paths)
        return 0

    result = run(args.paths, apply=args.apply)

    print(format_report(result.findings))
    if args.apply and result.rewritten_files:
        print("Rewrote (GRAPHENE -> DJANGO_GRAPHEX settings namespace):")
        for path in result.rewritten_files:
            print(f"  {path}")
    elif not args.apply and result.would_rewrite_files:
        print("Would rewrite (run with --apply): GRAPHENE -> DJANGO_GRAPHEX settings in:")
        for path in result.would_rewrite_files:
            print(f"  {path}")

    # Non-zero exit when manual porting is still required (CI-friendly).
    return 1 if result.findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
