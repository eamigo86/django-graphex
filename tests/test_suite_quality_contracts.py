"""Repository test-suite quality contract tests."""

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).parent
RETIRED_DOCSTRING_RATCHETS = frozenset(
    {
        Path("test_docstring_benchmark_ariadne.py"),
        Path("test_docstring_benchmark_graphene.py"),
    }
)


def _test_files() -> list[Path]:
    return sorted(
        path
        for path in TESTS_ROOT.rglob("test*.py")
        if "spike" not in path.parts and path != Path(__file__)
    )


def _is_pytest_call(node: ast.AST, method: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "pytest"
        and node.func.attr == method
    )


def test_retired_docstring_ratchets_stay_deleted() -> None:
    """Prevent one-off ratchet contracts from returning after global enforcement.

    Add each retired contract path to the shared set as cleanup progresses.
    """
    offenders = sorted(
        str(relative_path)
        for relative_path in RETIRED_DOCSTRING_RATCHETS
        if (TESTS_ROOT / relative_path).exists()
    )
    assert offenders == [], f"retired docstring ratchets still exist: {offenders}"


def test_core_modules_do_not_importorskip_during_collection() -> None:  # noqa: DOC001
    offenders: list[str] = []
    for path in sorted((TESTS_ROOT / "core").glob("test*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for statement in tree.body:
            value = (
                statement.value
                if isinstance(statement, (ast.Expr, ast.Assign))
                else None
            )
            if value is not None and _is_pytest_call(value, "importorskip"):
                offenders.append(f"{path.relative_to(TESTS_ROOT)}:{statement.lineno}")
    assert offenders == [], (
        f"module-level importorskip prevents collection: {offenders}"
    )


def test_pytest_raises_never_accepts_broad_exception() -> None:  # noqa: DOC001
    offenders: list[str] = []
    for path in _test_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not _is_pytest_call(node, "raises") or not node.args:
                continue
            if any(
                isinstance(item, ast.Name) and item.id == "Exception"
                for item in ast.walk(node.args[0])
            ):
                offenders.append(f"{path.relative_to(TESTS_ROOT)}:{node.lineno}")
    assert offenders == [], f"pytest.raises accepts Exception: {offenders}"


def test_focused_commands_disable_global_coverage_without_erasing_addopts() -> None:  # noqa: DOC001
    offenders: list[str] = []
    for path in _test_files():
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if "-o addopts" in line:
                offenders.append(
                    f"{path.relative_to(TESTS_ROOT)}:{lineno}: erases addopts"
                )
            if "pytest" in line and "tests/" in line and "--no-cov" not in line:
                offenders.append(
                    f"{path.relative_to(TESTS_ROOT)}:{lineno}: missing --no-cov"
                )
    assert offenders == [], f"unsafe focused pytest command: {offenders}"
