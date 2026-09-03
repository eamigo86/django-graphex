#!/usr/bin/env python3
"""Docstring-convention checker for the django-graphex codebase.

This stdlib-only tool enforces the author-mandated docstring convention across
public modules, classes, functions and methods. It gates a repo-wide
remediation and is designed to later run unchanged in CI.

The convention has three parts:
    A. Complete Google-style docstrings on public API surface (module, class,
       function, method) with the appropriate Args/Returns/Raises sections.
    B. Mandatory type hints on parameters and returns, with the type NOT
       repeated inside the docstring section body.
    C. No backticks anywhere inside any docstring.

Run it as a CLI over paths, or import check_source for programmatic use.

Algorithm (two-pass):
    First the file is parsed once into an AST and every public definition is
    visited; then each definition's docstring text is scanned line-by-line so
    section-scoped checks (such as type-in-docstring) never bleed into prose.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

# --- Rule codes and their human-readable messages --------------------------

RULE_MESSAGES: dict[str, str] = {
    "DOC001": "missing docstring",
    "DOC002": "single-line docstring (needs multi-line Google style)",
    "DOC003": "missing Args: section",
    "DOC004": "missing Returns: section",
    "DOC005": "missing Raises: section",
    "DOC101": "missing type hint",
    "DOC102": "type repeated in docstring",
    "DOC201": "backtick in docstring",
    "DOC901": "source parse failure",
    "DOC902": "source read failure",
    "DOC903": "diff inspection failure",
}

# Default directory/file globs that are never scanned.
DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".venv*",
    "__pycache__",
    "migrations",
    "node_modules",
    ".git",
    "site",
    "benchmarks/.venv*",
)

# Section headers whose indented body may legitimately name a type.
_TYPED_SECTIONS: frozenset[str] = frozenset(
    {"Args", "Arguments", "Returns", "Yields", "Attributes"}
)

# A Google section header line, e.g. "Args:" or "Returns:" (optionally indented).
_SECTION_HEADER_RE = re.compile(r"^\s*([A-Z][A-Za-z]+):\s*$")

# A "name (type):" entry, used to flag a type repeated inside a typed section.
_TYPE_IN_DOC_RE = re.compile(r"^\s*\w+ \([^)]*\):")

# A Google Args entry, including the conventional *args/**kwargs spelling.
_ARG_ENTRY_RE = re.compile(r"^\s+(\*{0,2}[A-Za-z_]\w*)(?:\s+\((.+)\))?\s*:")

# A trailing noqa pragma naming DOC codes (comma-separated codes accepted).
_NOQA_RE = re.compile(r"#\s*noqa:\s*(DOC[0-9, ]+)", re.IGNORECASE)

_DIFF_HUNK_RE = re.compile(
    rb"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@",
    re.MULTILINE,
)


class _DiffError(RuntimeError):
    """Signal that Git could not produce a trustworthy source diff."""


class Violation(NamedTuple):
    """A single convention violation found in a source file.

    Attributes:
        code: The rule code, e.g. "DOC001".
        lineno: The 1-based line the violation anchors to.
        message: The human-readable description of the violation.
    """

    code: str
    lineno: int
    message: str


def _make(code: str, lineno: int) -> Violation:
    """Build a Violation for a rule code at a line, filling in the message.

    Args:
        code: The rule code, e.g. "DOC001".
        lineno: The 1-based line the violation anchors to.

    Returns:
        violation: The assembled violation record.
    """
    return Violation(code=code, lineno=lineno, message=RULE_MESSAGES[code])


def _noqa_codes(source_line: str) -> set[str]:
    """Extract suppressed rule codes from a trailing noqa pragma on a line.

    Args:
        source_line: The raw source line that may carry a noqa comment.

    Returns:
        codes: The upper-cased rule codes this line suppresses (may be empty).
    """
    match = _NOQA_RE.search(source_line)
    if not match:
        return set()
    raw = match.group(1)
    return {token.strip().upper() for token in raw.split(",") if token.strip()}


def _docstring_lines(node: ast.AST) -> list[str] | None:
    """Return the raw docstring split into lines, or None when absent.

    Args:
        node: A module, class, or function AST node.

    Returns:
        lines: The docstring split on newlines, or None if there is none.
    """
    doc = ast.get_docstring(node, clean=False)
    if doc is None:
        return None
    return doc.splitlines()


def _is_multiline_doc(lines: list[str]) -> bool:
    """Report whether a docstring has meaningful content beyond one line.

    Args:
        lines: The docstring already split into lines.

    Returns:
        multiline: True when at least two non-blank lines are present.
    """
    non_blank = [line for line in lines if line.strip()]
    return len(non_blank) >= 2


def _has_section(lines: list[str], names: frozenset[str] | set[str]) -> bool:
    """Report whether the docstring contains any of the named sections.

    Args:
        lines: The docstring already split into lines.
        names: The set of acceptable section header names.

    Returns:
        present: True when a matching section header line is found.
    """
    for line in lines:
        header = _SECTION_HEADER_RE.match(line)
        if header and header.group(1) in names:
            return True
    return False


def _typed_section_line_flags(lines: list[str]) -> list[bool]:
    """Mark which docstring lines fall inside a typed section body.

    A typed section is one whose header is in _TYPED_SECTIONS (Args, Returns,
    Yields, Attributes). Only lines inside such a section body may legitimately
    contain a "name (type):" entry, so type-in-docstring detection is confined
    to them and prose headings such as "Algorithm (two-pass):" never match.

    Args:
        lines: The docstring already split into lines.

    Returns:
        flags: One boolean per input line, True when the line is in a typed
            section body.
    """
    flags: list[bool] = []
    in_typed = False
    for line in lines:
        header = _SECTION_HEADER_RE.match(line)
        if header:
            in_typed = header.group(1) in _TYPED_SECTIONS
            flags.append(False)  # the header line itself is not a body line
            continue
        flags.append(in_typed)
    return flags


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Collect the simple names of a function's decorators.

    Args:
        node: The function definition whose decorators are inspected.

    Returns:
        names: The decorator names, e.g. {"property", "overload"} or
            {"x.setter"} for attribute-style decorators.
    """
    names: set[str] = set()
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name):
            names.add(dec.id)
        elif isinstance(dec, ast.Attribute):
            names.add(dec.attr)
        elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
            names.add(dec.func.id)
    return names


def _params_beyond_self(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """List parameter names excluding a leading self/cls.

    Args:
        node: The function definition to inspect.

    Returns:
        names: Parameter names that count toward Args requirements.
    """
    args = node.args
    positional = args.posonlyargs + args.args
    names = [a.arg for a in positional]
    if names and names[0] in {"self", "cls"}:
        names = names[1:]
    names.extend(a.arg for a in args.kwonlyargs)
    if args.vararg is not None:
        names.append(args.vararg.arg)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return names


def _strict_params(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    receiver: str | None,
) -> list[str]:
    """List exact Args entry names after removing a real method receiver."""
    args = node.args
    positional = args.posonlyargs + args.args
    names = [item.arg for item in positional]
    if receiver is not None and names and names[0] == receiver:
        names = names[1:]
    names.extend(item.arg for item in args.kwonlyargs)
    if args.vararg is not None:
        names.append(f"*{args.vararg.arg}")
    if args.kwarg is not None:
        names.append(f"**{args.kwarg.arg}")
    return names


def _strict_receiver(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str | None:
    """Return self or cls only when it is the callable's real receiver."""
    decorators = _decorator_names(node)
    if "staticmethod" in decorators:
        return None
    positional = node.args.posonlyargs + node.args.args
    expected = "cls" if "classmethod" in decorators else "self"
    if positional and positional[0].arg == expected:
        return expected
    return None


def _unannotated_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether any checkable parameter lacks a type annotation.

    self/cls are exempt; *args and **kwargs must be annotated when present.

    Args:
        node: The function definition to inspect.

    Returns:
        missing: True when at least one parameter lacks an annotation.
    """
    args = node.args
    positional = args.posonlyargs + args.args
    checkable = list(positional)
    if checkable and checkable[0].arg in {"self", "cls"}:
        checkable = checkable[1:]
    checkable.extend(args.kwonlyargs)
    for arg in checkable:
        if arg.annotation is None:
            return True
    if args.vararg is not None and args.vararg.annotation is None:
        return True
    if args.kwarg is not None and args.kwarg.annotation is None:
        return True
    return False


def _args_entries(lines: list[str]) -> list[str] | None:
    """Return entries from the exact Args section, or None when absent."""
    in_args = False
    entries: list[str] = []
    for line in lines:
        header = _SECTION_HEADER_RE.match(line)
        if header:
            if in_args:
                break
            in_args = header.group(1) == "Args"
            continue
        if in_args:
            match = _ARG_ENTRY_RE.match(line)
            if match:
                entries.append(match.group(1))
    return entries if in_args else None


def _has_exact_args(lines: list[str], params: list[str]) -> bool:
    """Report whether Args is non-empty and matches the signature exactly."""
    entries = _args_entries(lines)
    if entries is None:
        return not params and not _has_section(lines, {"Arguments"})
    return bool(entries) and Counter(entries) == Counter(params)


def _section_body(lines: list[str], name: str) -> list[str] | None:
    """Return one exact Google section body, or None when absent."""
    active = False
    body: list[str] = []
    for line in lines:
        header = _SECTION_HEADER_RE.match(line)
        if header:
            if active:
                break
            active = header.group(1) == name
        elif active:
            body.append(line)
    return body if active else None


def _has_nonempty_section(lines: list[str], name: str) -> bool:
    """Report whether an exact section contains meaningful body text."""
    body = _section_body(lines, name)
    return body is not None and any(line.strip() for line in body)


def _owner_nodes(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.AST]:
    """Collect descendants owned by a callable, excluding nested scopes."""
    owned: list[ast.AST] = []
    pending: list[ast.AST] = list(node.body)
    while pending:
        child = pending.pop()
        owned.append(child)
        if isinstance(
            child,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
        ):
            continue
        pending.extend(ast.iter_child_nodes(child))
    return owned


def _annotation_expr(annotation: ast.expr | None) -> ast.expr | None:
    """Resolve a string annotation to its expression when possible."""
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            return ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return annotation
    return annotation


def _annotation_name(annotation: ast.expr | None) -> str | None:
    """Return the terminal name of a simple or qualified annotation."""
    annotation = _annotation_expr(annotation)
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    return None


def _required_result_section(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str | None:
    """Select Returns, Yields, or no result section from callable structure."""
    if _annotation_name(node.returns) in {"NoReturn", "Never"}:
        return None
    if any(
        isinstance(child, (ast.Yield, ast.YieldFrom)) for child in _owner_nodes(node)
    ):
        return "Yields"
    annotation = _annotation_expr(node.returns)
    if annotation is None or (
        isinstance(annotation, ast.Constant) and annotation.value is None
    ):
        return None
    return "Returns"


def _return_is_nonnone(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the return annotation is present and not None.

    Args:
        node: The function definition to inspect.

    Returns:
        nonnone: True when the annotation exists and is not the None literal.
    """
    ann = node.returns
    if ann is None:
        return False
    if isinstance(ann, ast.Constant) and ann.value is None:
        return False
    return True


def _body_raises_nontrivially(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    strict_public: bool = False,
) -> bool:
    """Report whether the body raises, excluding raise-NotImplementedError stubs.

    A body whose only statement is a bare raise NotImplementedError (or with an
    explicit expression list) is an abstract stub and must not require a
    Raises: section.

    Args:
        node: The function definition to inspect.
        strict_public: Whether nested scopes are excluded from the owner.

    Returns:
        raises: True when a non-stub raise appears anywhere in the body.
    """
    body = node.body
    real_body = body[1:] if _has_docstring_stmt(body) else body
    if len(real_body) == 1 and _is_notimplemented_raise(real_body[0]):
        return False
    descendants = _owner_nodes(node) if strict_public else ast.walk(node)
    for child in descendants:
        if isinstance(child, ast.Raise):
            if _is_notimplemented_raise_stmt(child):
                continue
            return True
    return False


def _has_docstring_stmt(body: list[ast.stmt]) -> bool:
    """Report whether the first body statement is a string-literal docstring.

    Args:
        body: The statement list of a definition body.

    Returns:
        present: True when the first statement is a bare string constant.
    """
    if not body:
        return False
    first = body[0]
    return (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    )


def _is_notimplemented_raise(stmt: ast.stmt) -> bool:
    """Report whether a statement is a raise of NotImplementedError.

    Args:
        stmt: The statement to inspect.

    Returns:
        matched: True when the statement raises NotImplementedError.
    """
    return isinstance(stmt, ast.Raise) and _is_notimplemented_raise_stmt(stmt)


def _is_notimplemented_raise_stmt(node: ast.Raise) -> bool:
    """Report whether a raise node targets NotImplementedError.

    Handles both bare "raise NotImplementedError" and the call form
    "raise NotImplementedError(...)".

    Args:
        node: The raise statement to inspect.

    Returns:
        matched: True when the raised exception is NotImplementedError.
    """
    exc = node.exc
    if exc is None:
        return False
    if isinstance(exc, ast.Name):
        return exc.id == "NotImplementedError"
    if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
        return exc.func.id == "NotImplementedError"
    return False


def _is_public_name(name: str) -> bool:
    """Report whether a name is public per the convention.

    Public means not starting with an underscore, with __init__ as the single
    dunder exception (handled specially by callers).

    Args:
        name: The definition name to classify.

    Returns:
        public: True when the name is considered public.
    """
    return not name.startswith("_")


def _documented_result_type(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    section: str,
) -> ast.expr | None:
    """Return the annotated type that a result section must not repeat."""
    annotation = _annotation_expr(node.returns)
    if section != "Yields" or not isinstance(annotation, ast.Subscript):
        return annotation
    containers = {
        "AsyncGenerator",
        "AsyncIterable",
        "AsyncIterator",
        "Generator",
        "Iterable",
        "Iterator",
    }
    if _annotation_name(annotation.value) not in containers:
        return annotation
    item = annotation.slice
    if isinstance(item, ast.Tuple):
        return item.elts[0] if item.elts else None
    return item


def _repeats_result_type(
    lines: list[str],
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """Report a leading Returns or Yields type matching the annotation."""
    section = _required_result_section(node)
    if section is None:
        return False
    expected = _documented_result_type(node, section)
    if expected is None:
        return False
    expected_shape = ast.dump(expected, include_attributes=False)
    for line in _section_body(lines, section) or []:
        candidate, separator, _description = line.strip().partition(":")
        if not separator:
            continue
        try:
            expression = ast.parse(candidate.strip(), mode="eval").body
        except SyntaxError:
            continue
        if ast.dump(expression, include_attributes=False) == expected_shape:
            return True
    return False


def _strict_repeats_type(
    lines: list[str],
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """Report typed entries in strict Args, Returns, or Yields sections."""
    for section in ("Args", "Returns", "Yields"):
        for line in _section_body(lines, section) or []:
            entry = _ARG_ENTRY_RE.match(line)
            if entry is not None and entry.group(2) is not None:
                return True
    return _repeats_result_type(lines, node)


def _check_docstring_content(
    lines: list[str],
    suppressed: set[str],
    *,
    node: ast.FunctionDef | ast.AsyncFunctionDef | None = None,
    strict_public: bool = False,
) -> list[str]:
    """Run the docstring-body checks (backticks and type-in-docstring).

    Args:
        lines: The docstring already split into lines.
        suppressed: Rule codes suppressed by a noqa pragma on the def line.
        node: Callable whose result annotation may be repeated.
        strict_public: Whether structural result-type checks are active.

    Returns:
        codes: The rule codes fired by the docstring body content.
    """
    codes: list[str] = []
    if "DOC201" not in suppressed and any("`" in line for line in lines):
        codes.append("DOC201")
    if "DOC102" not in suppressed:
        typed_flags = _typed_section_line_flags(lines)
        for line, is_typed in zip(lines, typed_flags):
            if is_typed and _TYPE_IN_DOC_RE.match(line):
                codes.append("DOC102")
                break
        else:
            if strict_public and node is not None and _strict_repeats_type(lines, node):
                codes.append("DOC102")
    return codes


def _check_strict_content(
    tree: ast.Module,
    source_lines: list[str],
    changed_lines: set[int] | None = None,
) -> list[Violation]:
    """Check DOC201 on every docstring owner in the syntax tree.

    Unlike the legacy public-surface traversal, this covers private, nested,
    and dunder definitions while leaving all other convention rules unchanged.

    Args:
        tree: The parsed module syntax tree.
        source_lines: The file's source lines, for reading definition pragmas.
        changed_lines: Current-file lines changed by Git, or None for all.

    Returns:
        violations: DOC201 violations from every documented owner.
    """
    owner_types = (
        ast.Module,
        ast.ClassDef,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
    )
    owners = [owner for owner in ast.walk(tree) if isinstance(owner, owner_types)]
    if changed_lines is not None:
        definitions = [owner for owner in owners if not isinstance(owner, ast.Module)]
        bounds: dict[ast.AST, tuple[int, int]] = {}
        for owner in definitions:
            decorators = getattr(owner, "decorator_list", [])
            starts = [owner.lineno, *(item.lineno for item in decorators)]
            bounds[owner] = (min(starts), owner.end_lineno or owner.lineno)

        touched: set[ast.AST] = set()
        module_doc = tree.body[0] if ast.get_docstring(tree, clean=False) else None
        module_bounds = (
            (module_doc.lineno, module_doc.end_lineno or module_doc.lineno)
            if module_doc is not None
            else None
        )
        for lineno in changed_lines:
            candidates = [
                owner
                for owner in definitions
                if bounds[owner][0] <= lineno <= bounds[owner][1]
            ]
            if candidates:
                touched.add(
                    min(
                        candidates,
                        key=lambda owner: bounds[owner][1] - bounds[owner][0],
                    )
                )
            elif module_bounds and module_bounds[0] <= lineno <= module_bounds[1]:
                touched.add(tree)
        owners = [owner for owner in owners if owner in touched]

    violations: list[Violation] = []
    for owner in owners:
        lineno = getattr(owner, "lineno", 1)
        suppressed = (
            set()
            if isinstance(owner, ast.Module)
            else _noqa_codes(source_lines[lineno - 1])
        )
        lines = _docstring_lines(owner)
        if (
            lines is not None
            and "DOC201" not in suppressed
            and any("`" in line for line in lines)
        ):
            violations.append(_make("DOC201", lineno))
    return violations


def check_content_source(
    source: str,
    *,
    changed_lines: set[int] | None = None,
) -> list[Violation]:
    """Check DOC201 for all or only diff-selected docstring owners.

    Args:
        source: Python source text to analyze.
        changed_lines: Current-file lines changed by Git, or None for all.

    Returns:
        violations: DOC201 violations sorted by owner line.

    Raises:
        SyntaxError: When the source cannot be parsed.
    """
    tree = ast.parse(source)
    violations = _check_strict_content(tree, source.splitlines(), changed_lines)
    violations.sort(key=lambda item: (item.lineno, item.code))
    return violations


def _module_is_reexport_stub(
    tree: ast.Module,
    filename: str,
    *,
    strict_public: bool = False,
) -> bool:
    """Report whether a module is a short __init__.py re-export stub.

    Legacy mode uses the original size heuristic. Strict public mode instead
    requires every statement to be an import or a static __all__ declaration.

    Args:
        tree: The parsed module AST.
        filename: The file name, used to detect __init__.py.
        strict_public: Whether to classify by syntax rather than statement count.

    Returns:
        stub: True when the module is an exempt re-export stub.
    """
    if Path(filename).name != "__init__.py":
        return False
    statements = [stmt for stmt in tree.body if not _is_expr_docstring(stmt)]
    if strict_public:
        return bool(statements) and all(
            isinstance(stmt, (ast.Import, ast.ImportFrom)) or _is_all_declaration(stmt)
            for stmt in statements
        )
    return len(statements) < 10


def _all_value(stmt: ast.stmt) -> ast.expr | None:
    """Return the value assigned to __all__, when statically visible."""
    if isinstance(stmt, ast.Assign):
        assigned = any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in stmt.targets
        )
        return stmt.value if assigned else None
    if isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
        if isinstance(stmt.target, ast.Name) and stmt.target.id == "__all__":
            return stmt.value
    return None


def _is_all_declaration(stmt: ast.stmt) -> bool:
    """Report whether a statement declares a static __all__ collection."""
    value = _all_value(stmt)
    return isinstance(value, (ast.List, ast.Tuple, ast.Set)) and all(
        isinstance(item, ast.Constant) and isinstance(item.value, str)
        for item in value.elts
    )


def _explicit_exports(tree: ast.Module) -> set[str]:
    """Collect statically declared string names from module __all__."""
    exports: set[str] = set()
    for stmt in tree.body:
        value = _all_value(stmt)
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            exports.update(
                item.value
                for item in value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
    return exports


def _is_expr_docstring(stmt: ast.stmt) -> bool:
    """Report whether a top-level statement is a bare string-literal expression.

    Args:
        stmt: The statement to inspect.

    Returns:
        matched: True when the statement is a bare string constant.
    """
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _check_callable(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    source_lines: list[str],
    *,
    strict_public: bool = False,
    is_method: bool = False,
    force_public: bool = False,
) -> list[Violation]:
    """Check one public function or method against the convention.

    Args:
        node: The function or method definition to check.
        source_lines: The file's source lines, for reading the def-line noqa.
        strict_public: Whether to enforce the exact public contract.
        is_method: Whether the callable is a direct class member.
        force_public: Whether __all__ explicitly exports a private name.

    Returns:
        violations: The violations found for this callable.
    """
    violations: list[Violation] = []
    name = node.name
    is_init = name == "__init__"
    receiver = _strict_receiver(node) if strict_public and is_method else None
    params = (
        _strict_params(node, receiver) if strict_public else _params_beyond_self(node)
    )

    if not _is_public_name(name) and not is_init and not force_public:
        return violations
    if is_init and not params:
        # __init__ with only self is exempt from the docstring requirement.
        if _docstring_lines(node) is None:
            return violations

    suppressed = _noqa_codes(source_lines[node.lineno - 1])
    decorators = _decorator_names(node)
    is_overload = "overload" in decorators
    is_setter = "setter" in decorators
    exempt_args = is_overload or (is_setter and not strict_public)
    exempt_returns = is_overload or (is_setter and not strict_public)
    missing_hints = _missing_hints(node, strict_public=strict_public, receiver=receiver)

    lines = _docstring_lines(node)
    if lines is None:
        if "DOC001" not in suppressed:
            violations.append(_make("DOC001", node.lineno))
        # Still report missing hints even without a docstring.
        if "DOC101" not in suppressed and missing_hints:
            violations.append(_make("DOC101", node.lineno))
        return violations

    if not _is_multiline_doc(lines) and "DOC002" not in suppressed:
        violations.append(_make("DOC002", node.lineno))

    if not exempt_args:
        if (
            not _has_exact_args(lines, params)
            if strict_public
            else params and not _has_section(lines, {"Args", "Arguments"})
        ) and "DOC003" not in suppressed:
            violations.append(_make("DOC003", node.lineno))
    if not exempt_returns:
        if strict_public:
            result_section = _required_result_section(node)
            if result_section is None:
                invalid_result = _has_section(lines, {"Returns", "Yields"})
            else:
                other_section = "Returns" if result_section == "Yields" else "Yields"
                invalid_result = not _has_nonempty_section(
                    lines, result_section
                ) or _has_section(lines, {other_section})
        else:
            invalid_result = _return_is_nonnone(node) and not _has_section(
                lines, {"Returns", "Yields"}
            )
        if invalid_result and "DOC004" not in suppressed:
            violations.append(_make("DOC004", node.lineno))

    if (
        _body_raises_nontrivially(node, strict_public=strict_public)
        and (
            not _has_nonempty_section(lines, "Raises")
            if strict_public
            else not _has_section(lines, {"Raises"})
        )
        and "DOC005" not in suppressed
    ):
        violations.append(_make("DOC005", node.lineno))

    if "DOC101" not in suppressed and missing_hints:
        violations.append(_make("DOC101", node.lineno))

    for code in _check_docstring_content(
        lines,
        suppressed,
        node=node,
        strict_public=strict_public,
    ):
        violations.append(_make(code, node.lineno))

    return violations


def _missing_hints(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    strict_public: bool = False,
    receiver: str | None = None,
) -> bool:
    """Report whether the callable is missing any required type hint.

    Args:
        node: The function or method definition to check.
        strict_public: Whether only a real receiver is exempt.
        receiver: The validated strict-mode receiver name, if any.

    Returns:
        missing: True when a param or the return annotation is absent.
    """
    if strict_public:
        args = node.args
        checkable = list(args.posonlyargs + args.args)
        if receiver is not None and checkable and checkable[0].arg == receiver:
            checkable = checkable[1:]
        checkable.extend(args.kwonlyargs)
        checkable.extend(item for item in (args.vararg, args.kwarg) if item is not None)
        if any(item.annotation is None for item in checkable):
            return True
    elif _unannotated_params(node):
        return True
    if node.returns is None:
        return True
    return False


def _check_class(
    node: ast.ClassDef,
    source_lines: list[str],
    *,
    strict_public: bool = False,
) -> list[Violation]:
    """Check a public class node and its direct method members.

    Args:
        node: The class definition to check.
        source_lines: The file's source lines, for reading def-line noqa.
        strict_public: Whether to enforce the exact public contract on members.

    Returns:
        violations: The violations found for the class and its methods.
    """
    violations: list[Violation] = []
    suppressed = _noqa_codes(source_lines[node.lineno - 1])
    lines = _docstring_lines(node)
    if lines is None:
        if "DOC001" not in suppressed:
            violations.append(_make("DOC001", node.lineno))
    else:
        if not _is_multiline_doc(lines) and "DOC002" not in suppressed:
            violations.append(_make("DOC002", node.lineno))
        for code in _check_docstring_content(lines, suppressed):
            violations.append(_make(code, node.lineno))

    for member in node.body:
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
            violations.extend(
                _check_callable(
                    member, source_lines, strict_public=strict_public, is_method=True
                )
            )
        elif isinstance(member, ast.ClassDef) and _is_public_name(member.name):
            violations.extend(
                _check_class(member, source_lines, strict_public=strict_public)
            )
    return violations


def check_source(
    source: str,
    filename: str = "<string>",
    *,
    strict_content: bool = False,
    strict_public: bool = False,
) -> list[Violation]:
    """Check Python source text against the docstring convention.

    This is the programmatic entry point. Nested definitions inside functions
    are exempt; only module-, class-, and top-level/method-level public
    definitions are examined.

    Args:
        source: The Python source text to analyze.
        filename: The file name, used for module-name heuristics.
        strict_content: Whether DOC201 covers every docstring owner.
        strict_public: Whether the exact public API contract is enforced.

    Returns:
        violations: All violations found, sorted by line then code.

    Raises:
        SyntaxError: When the source cannot be parsed.
    """
    tree = ast.parse(source)
    source_lines = source.splitlines()
    violations: list[Violation] = []

    non_doc_stmts = [s for s in tree.body if not _is_expr_docstring(s)]
    module_doc = ast.get_docstring(tree, clean=False)
    if (
        non_doc_stmts
        and module_doc is None
        and not _module_is_reexport_stub(
            tree,
            filename,
            strict_public=strict_public,
        )
    ):
        violations.append(_make("DOC001", 1))
    elif module_doc is not None:
        doc_lines = module_doc.splitlines()
        for code in _check_docstring_content(doc_lines, set()):
            violations.append(_make(code, 1))

    exports = _explicit_exports(tree) if strict_public else set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            violations.extend(
                _check_callable(
                    node,
                    source_lines,
                    strict_public=strict_public,
                    force_public=node.name in exports,
                )
            )
        elif isinstance(node, ast.ClassDef) and (
            _is_public_name(node.name) or node.name in exports
        ):
            violations.extend(
                _check_class(node, source_lines, strict_public=strict_public)
            )

    if strict_content:
        for violation in _check_strict_content(tree, source_lines):
            if violation not in violations:
                violations.append(violation)

    violations.sort(key=lambda v: (v.lineno, v.code))
    return violations


def check_file(
    path: Path,
    *,
    strict_content: bool = False,
    strict_public: bool = False,
    content_only: bool = False,
    changed_lines: set[int] | None = None,
) -> list[Violation]:
    """Check a single file on disk against the convention.

    Args:
        path: The path to the Python file to check.
        strict_content: Whether DOC201 covers every docstring owner.
        strict_public: Whether the exact public API contract is enforced.
        content_only: Whether to run only the strict content engine.
        changed_lines: Current-file lines changed by Git, or None for all.

    Returns:
        violations: All violations found, including inspection failures.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        detail = str(exc) or type(exc).__name__
        return [
            Violation(
                code="DOC902",
                lineno=1,
                message=f"{RULE_MESSAGES['DOC902']}: {detail}",
            )
        ]
    try:
        if content_only:
            return check_content_source(source, changed_lines=changed_lines)
        return check_source(
            source,
            str(path),
            strict_content=strict_content,
            strict_public=strict_public,
        )
    except SyntaxError as exc:
        return [
            Violation(
                code="DOC901",
                lineno=exc.lineno or 1,
                message=f"{RULE_MESSAGES['DOC901']}: {exc.msg}",
            )
        ]


def _is_excluded(path: Path, patterns: list[str]) -> bool:
    """Report whether a path matches any exclude glob.

    Both the full path and each path part are tested so directory-name globs
    such as "__pycache__" exclude everything beneath them.

    Args:
        path: The candidate file path.
        patterns: The active exclude globs.

    Returns:
        excluded: True when the path should be skipped.
    """
    parts = path.parts
    text = str(path)
    for pattern in patterns:
        if fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(text, f"*{pattern}*"):
            return True
        if any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
    return False


def _iter_python_files(root: Path, patterns: list[str]) -> list[Path]:
    """Collect Python files under a root, honoring exclude globs.

    Args:
        root: A file or directory path to scan.
        patterns: The active exclude globs.

    Returns:
        files: The sorted list of .py files to check.
    """
    if root.is_file():
        return [root] if not _is_excluded(root, patterns) else []
    found: list[Path] = []
    for candidate in sorted(root.rglob("*.py")):
        if not _is_excluded(candidate, patterns):
            found.append(candidate)
    return found


def _git_diff(args: list[str]) -> bytes:
    """Run Git for ratchet discovery or raise a fail-closed error."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise _DiffError(detail or "git diff failed")
    return result.stdout


def _changed_python_lines(base: str) -> dict[Path, set[int] | None]:
    """Return added files and changed current-file lines since a Git base."""
    revision = f"{base}...HEAD"

    def paths_for(diff_filter: str) -> list[Path]:
        raw = _git_diff(
            [
                "diff",
                "--name-only",
                "-z",
                "--no-renames",
                f"--diff-filter={diff_filter}",
                revision,
                "--",
                "*.py",
            ]
        )
        return [
            Path(item.decode("utf-8", errors="surrogateescape"))
            for item in raw.split(b"\0")
            if item
        ]

    changes: dict[Path, set[int] | None] = {path: None for path in paths_for("A")}
    for path in paths_for("M"):
        patch = _git_diff(
            ["diff", "--unified=0", "--no-renames", revision, "--", str(path)]
        )
        lines: set[int] = set()
        for match in _DIFF_HUNK_RE.finditer(patch):
            start = int(match.group(1))
            count = int(match.group(2) or b"1")
            lines.update(range(start, start + count))
            if count == 0 and start > 0:
                lines.add(start)
        changes[path] = lines
    return changes


def _path_in_roots(path: Path, roots: list[Path]) -> bool:
    """Report whether a repository-relative path is under a requested root."""
    candidate = path.resolve()
    return any(
        candidate == root.resolve() or root.resolve() in candidate.parents
        for root in roots
    )


def _format_summary(counts: Counter[str]) -> list[str]:
    """Build the per-rule summary table lines.

    Args:
        counts: A mapping of rule code to its violation count.

    Returns:
        rows: The formatted summary lines including a total.
    """
    rows: list[str] = ["", "Summary:"]
    total = 0
    for code in sorted(RULE_MESSAGES):
        count = counts.get(code, 0)
        total += count
        rows.append(f"  {code}  {count:>5}  {RULE_MESSAGES[code]}")
    rows.append(f"  TOTAL {total:>5}")
    return rows


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: The argument vector excluding the program name.

    Returns:
        namespace: The parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Check Python docstrings against the project convention.",
    )
    parser.add_argument("paths", nargs="+", help="Files or directories to check.")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PAT",
        help="Extra glob pattern to exclude (repeatable).",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print only the per-rule summary table.",
    )
    parser.add_argument(
        "--list-files",
        action="store_true",
        help="List each scanned file before checking it.",
    )
    parser.add_argument(
        "--strict-content",
        action="store_true",
        help="Apply DOC201 to every docstring owner during migration.",
    )
    parser.add_argument(
        "--strict-public",
        action="store_true",
        help="Apply the exact public API contract during migration.",
    )
    parser.add_argument(
        "--diff-base",
        metavar="REF",
        help="Apply DOC201 only to owners changed since a Git merge base.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the checker as a command-line tool.

    Args:
        argv: The argument vector excluding the program name; defaults to
            sys.argv[1:] when None.

    Returns:
        exit_code: 0 when no violations were found, 1 otherwise.
    """
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    changes: dict[Path, set[int] | None] | None = None
    if args.diff_base:
        try:
            changes = _changed_python_lines(args.diff_base)
        except _DiffError as exc:
            diff_counts = Counter({"DOC903": 1})
            if not args.stats:
                print(f"<diff>:1: DOC903 {RULE_MESSAGES['DOC903']}: {exc}")
            for line in _format_summary(diff_counts):
                print(line)
            return 1
        roots = [Path(raw) for raw in args.paths]
        files = [
            path
            for path in sorted(changes)
            if _path_in_roots(path, roots) and not _is_excluded(path, args.exclude)
        ]
    else:
        patterns = list(DEFAULT_EXCLUDES) + list(args.exclude)
        files = []
        for raw in args.paths:
            files.extend(_iter_python_files(Path(raw), patterns))

    counts: Counter[str] = Counter()
    output_lines: list[str] = []
    for path in files:
        if args.list_files:
            output_lines.append(f"# {path}")
        for violation in check_file(
            path,
            strict_content=args.strict_content,
            strict_public=args.strict_public,
            content_only=changes is not None,
            changed_lines=changes[path] if changes is not None else None,
        ):
            counts[violation.code] += 1
            output_lines.append(
                f"{path}:{violation.lineno}: {violation.code} {violation.message}"
            )

    if not args.stats:
        for line in output_lines:
            print(line)
    for line in _format_summary(counts):
        print(line)

    return 1 if sum(counts.values()) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
