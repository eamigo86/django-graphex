"""Every repository path a test reads ships in the sdist or is declared repo-only."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

from tests._repo_only import requires_repo_paths

ROOT = Path(__file__).resolve().parents[1]
# The leftmost operand of a root-anchored path: ROOT / "name", parents[1] / "name".
_ROOT_EXPR = re.compile(
    r"(?:ROOT|REPO_ROOT|_REPO_ROOT|project_root)|.*(?:parents\[\d\]|parent\.parent)"
)


def _included() -> set[str]:
    """Read the top-level names the sdist allowlist ships.

    Returns:
        The first path segment of every include entry.
    """
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    entries = config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    return {entry.lstrip("/").split("/")[0] for entry in entries}


def _first_segments(tree: ast.AST) -> set[str]:
    """Collect the first segment of each root-anchored path literal.

    Args:
        tree: The parsed test module.

    Returns:
        Names such as ".github" or "benchmarks" read below the repository root.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
            continue
        literals: list[str] = []
        left: ast.expr = node
        while isinstance(left, ast.BinOp) and isinstance(left.op, ast.Div):
            right = left.right
            literals.append(
                right.value
                if isinstance(right, ast.Constant) and isinstance(right.value, str)
                else ""
            )
            left = left.left
        first = literals[-1].strip("/").split("/")[0]
        if first and _ROOT_EXPR.fullmatch(ast.unparse(left)):
            names.add(first)
    return names


def _declared(tree: ast.AST) -> list[str]:
    """Collect the literal paths a module passes to requires_repo_paths.

    Args:
        tree: The parsed test module.

    Returns:
        Every string argument of every requires_repo_paths call.
    """
    paths: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and "requires_repo_paths" in ast.unparse(
            node.func
        ):
            paths += [
                arg.value
                for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            ]
    return paths


def _scan() -> tuple[dict[str, set[str]], dict[str, list[str]]]:
    """Scan every test module once.

    Returns:
        The root-anchored first segments and the declared repo-only paths, both
        keyed by module path relative to the repository root.
    """
    reads: dict[str, set[str]] = {}
    declared: dict[str, list[str]] = {}
    for module in sorted((ROOT / "tests").rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        key = module.relative_to(ROOT).as_posix()
        reads[key] = _first_segments(tree)
        declared[key] = _declared(tree)
    return reads, declared


def test_every_path_a_test_reads_is_shipped_or_declared_repo_only() -> None:
    """A published tarball must not lose the inputs of its own tests.

    Any root-anchored path, nested ones included, must sit under an sdist
    include entry or be declared with requires_repo_paths in the same module.
    """
    shipped = _included()
    reads, declared = _scan()
    assert {"CHANGELOG.md", "pyproject.toml"} <= set().union(*reads.values())
    assert any(".github" in names for names in reads.values())  # the scan sees nesting
    missing = sorted(
        f"{module}: {name}"
        for module, names in reads.items()
        for name in names
        if (ROOT / name).exists()
        and name not in shipped
        and name not in {path.split("/")[0] for path in declared[module]}
    )
    assert not missing, (
        "add to [tool.hatch.build.targets.sdist] include, or declare with "
        f"requires_repo_paths: {missing}"
    )


@requires_repo_paths(".github")  # an sdist has no repository to compare against
def test_declared_repo_only_paths_exist_in_the_checkout() -> None:
    """A typo in a declaration must not skip a test forever.

    The checkout has every input, so each declared path must exist here.
    """
    _, declared = _scan()
    absent = sorted(
        f"{module}: {path}"
        for module, paths in declared.items()
        for path in paths
        if not (ROOT / path).exists()
    )
    assert not absent, f"declared repo-only paths missing from the repo: {absent}"


def test_requires_repo_paths_skips_only_when_a_path_is_absent() -> None:
    """Skip on a missing input, never on a present one.

    The marker reads the repository root, so a present path must not skip.
    """
    present = requires_repo_paths("pyproject.toml").mark
    input_name = "no/such/" + "input"  # not a literal: the scan skips it
    absent = requires_repo_paths("pyproject.toml", input_name).mark
    assert present.args == (False,)
    assert absent.args == (True,)
    assert "no/such/input" in absent.kwargs["reason"]
