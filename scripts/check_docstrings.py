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

# A trailing noqa pragma naming DOC codes (comma-separated codes accepted).
_NOQA_RE = re.compile(r"#\s*noqa:\s*(DOC[0-9, ]+)", re.IGNORECASE)


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


def _body_raises_nontrivially(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the body raises, excluding raise-NotImplementedError stubs.

    A body whose only statement is a bare raise NotImplementedError (or with an
    explicit expression list) is an abstract stub and must not require a
    Raises: section.

    Args:
        node: The function definition to inspect.

    Returns:
        raises: True when a non-stub raise appears anywhere in the body.
    """
    body = node.body
    real_body = body[1:] if _has_docstring_stmt(body) else body
    if len(real_body) == 1 and _is_notimplemented_raise(real_body[0]):
        return False
    for child in ast.walk(node):
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


def _check_docstring_content(lines: list[str], suppressed: set[str]) -> list[str]:
    """Run the docstring-body checks (backticks and type-in-docstring).

    Args:
        lines: The docstring already split into lines.
        suppressed: Rule codes suppressed by a noqa pragma on the def line.

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
    return codes


def _module_is_reexport_stub(tree: ast.Module, filename: str) -> bool:
    """Report whether a module is a short __init__.py re-export stub.

    Such stubs (fewer than 10 statements) are exempt from the module-docstring
    requirement.

    Args:
        tree: The parsed module AST.
        filename: The file name, used to detect __init__.py.

    Returns:
        stub: True when the module is an exempt re-export stub.
    """
    if Path(filename).name != "__init__.py":
        return False
    statements = [stmt for stmt in tree.body if not _is_expr_docstring(stmt)]
    return len(statements) < 10


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
) -> list[Violation]:
    """Check one public function or method against the convention.

    Args:
        node: The function or method definition to check.
        source_lines: The file's source lines, for reading the def-line noqa.

    Returns:
        violations: The violations found for this callable.
    """
    violations: list[Violation] = []
    name = node.name
    is_init = name == "__init__"
    params = _params_beyond_self(node)

    if not _is_public_name(name) and not is_init:
        return violations
    if is_init and not params:
        # __init__ with only self is exempt from the docstring requirement.
        if _docstring_lines(node) is None:
            return violations

    suppressed = _noqa_codes(source_lines[node.lineno - 1])
    decorators = _decorator_names(node)
    is_overload = "overload" in decorators
    is_setter = "setter" in decorators
    exempt_args_returns = is_overload or is_setter

    lines = _docstring_lines(node)
    if lines is None:
        if "DOC001" not in suppressed:
            violations.append(_make("DOC001", node.lineno))
        # Still report missing hints even without a docstring.
        if "DOC101" not in suppressed and _missing_hints(node):
            violations.append(_make("DOC101", node.lineno))
        return violations

    if not _is_multiline_doc(lines) and "DOC002" not in suppressed:
        violations.append(_make("DOC002", node.lineno))

    if not exempt_args_returns:
        if (
            params
            and not _has_section(lines, {"Args", "Arguments"})
            and "DOC003" not in suppressed
        ):
            violations.append(_make("DOC003", node.lineno))
        if (
            _return_is_nonnone(node)
            and not _has_section(lines, {"Returns", "Yields"})
            and "DOC004" not in suppressed
        ):
            violations.append(_make("DOC004", node.lineno))

    if (
        _body_raises_nontrivially(node)
        and not _has_section(lines, {"Raises"})
        and "DOC005" not in suppressed
    ):
        violations.append(_make("DOC005", node.lineno))

    if "DOC101" not in suppressed and _missing_hints(node):
        violations.append(_make("DOC101", node.lineno))

    for code in _check_docstring_content(lines, suppressed):
        violations.append(_make(code, node.lineno))

    return violations


def _missing_hints(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the callable is missing any required type hint.

    Args:
        node: The function or method definition to check.

    Returns:
        missing: True when a param or the return annotation is absent.
    """
    if _unannotated_params(node):
        return True
    if node.returns is None:
        return True
    return False


def _check_class(node: ast.ClassDef, source_lines: list[str]) -> list[Violation]:
    """Check a public class node and its direct method members.

    Args:
        node: The class definition to check.
        source_lines: The file's source lines, for reading def-line noqa.

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
            violations.extend(_check_callable(member, source_lines))
        elif isinstance(member, ast.ClassDef) and _is_public_name(member.name):
            violations.extend(_check_class(member, source_lines))
    return violations


def check_source(source: str, filename: str = "<string>") -> list[Violation]:
    """Check Python source text against the docstring convention.

    This is the programmatic entry point. Nested definitions inside functions
    are exempt; only module-, class-, and top-level/method-level public
    definitions are examined.

    Args:
        source: The Python source text to analyze.
        filename: The file name, used for module-name heuristics.

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
        and not _module_is_reexport_stub(tree, filename)
    ):
        violations.append(_make("DOC001", 1))
    elif module_doc is not None:
        doc_lines = module_doc.splitlines()
        for code in _check_docstring_content(doc_lines, set()):
            violations.append(_make(code, 1))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            violations.extend(_check_callable(node, source_lines))
        elif isinstance(node, ast.ClassDef) and _is_public_name(node.name):
            violations.extend(_check_class(node, source_lines))

    violations.sort(key=lambda v: (v.lineno, v.code))
    return violations


def check_file(path: Path) -> list[Violation]:
    """Check a single file on disk against the convention.

    Args:
        path: The path to the Python file to check.

    Returns:
        violations: All violations found in the file (empty on parse error).
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        return check_source(source, str(path))
    except SyntaxError:
        return []


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
    patterns = list(DEFAULT_EXCLUDES) + list(args.exclude)

    files: list[Path] = []
    for raw in args.paths:
        files.extend(_iter_python_files(Path(raw), patterns))

    counts: Counter[str] = Counter()
    output_lines: list[str] = []
    for path in files:
        if args.list_files:
            output_lines.append(f"# {path}")
        for violation in check_file(path):
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
