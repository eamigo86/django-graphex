"""Contracts for validating and auditing the prebuilt release wheel."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import ANY

import pytest

ROOT = Path(__file__).parents[1]


def _load_script(name: str) -> ModuleType:
    """Load a repository script without making ``scripts`` a package."""
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wheel_check_reads_expected_version_from_pyproject(tmp_path: Path) -> None:
    """Derive the expected wheel version from release source metadata.

    Args:
        tmp_path: Isolated source metadata directory.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "django-graphex"\nversion = "9.8.7"\n'
    )
    check = _load_script("check_wheel_install")
    assert check.expected_version(tmp_path) == "9.8.7"


def test_wheel_check_rejects_imports_from_checkout(tmp_path: Path) -> None:
    """Reject an editable import masquerading as the installed wheel.

    Args:
        tmp_path: Isolated fake checkout directory.
    """
    check = _load_script("check_wheel_install")
    package_file = tmp_path / "django_graphex" / "__init__.py"
    with pytest.raises(RuntimeError, match="checkout"):
        check.assert_outside_checkout(package_file, tmp_path)


def test_wheel_check_validates_metadata_typing_and_base_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Require matching metadata and py.typed without Channels.

    Args:
        tmp_path: Isolated installed-package directory.
        monkeypatch: Fixture used to replace installed metadata lookups.
    """
    check = _load_script("check_wheel_install")
    package = tmp_path / "site-packages" / "django_graphex"
    package.mkdir(parents=True)
    module_file = package / "__init__.py"
    module_file.touch()
    (package / "py.typed").touch()

    monkeypatch.setattr(check.metadata, "version", lambda name: "3.1.0")
    monkeypatch.setattr(check.util, "find_spec", lambda name: None)
    check.assert_distribution_contract(module_file, "3.1.0")

    (package / "py.typed").unlink()
    with pytest.raises(RuntimeError, match="py.typed"):
        check.assert_distribution_contract(module_file, "3.1.0")
    (package / "py.typed").touch()

    monkeypatch.setattr(check.util, "find_spec", lambda name: object())
    with pytest.raises(RuntimeError, match="Channels"):
        check.assert_distribution_contract(module_file, "3.1.0")


def test_wheel_check_executes_a_real_minimal_schema() -> None:
    """Reach Django setup, schema compilation, and query execution.

    This proves the smoke check exercises real installed behavior.
    """
    check = _load_script("check_wheel_install")
    check.assert_graphql_smoke()


def test_release_audit_consumes_prebuilt_wheel_without_building(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Install the supplied wheel for audit without rebuilding it.

    Args:
        tmp_path: Isolated wheel and installation directory.
        monkeypatch: Fixture used to record audit subprocesses.
    """
    audit = _load_script("release_audit")
    wheel = tmp_path / "django_graphex-3.1.0-py3-none-any.whl"
    wheel.touch()
    commands: list[list[str]] = []
    monkeypatch.setattr(audit, "_run", lambda command: commands.append(command))

    assert audit.main([str(wheel)]) == 0
    assert commands == [
        [
            audit.sys.executable,
            "-m",
            "pip",
            "install",
            "--target",
            ANY,
            str(wheel),
        ],
        [audit.sys.executable, "-m", "pip_audit", "--path", ANY],
    ]
    assert not any("build" in argument for command in commands for argument in command)


def test_release_audit_rejects_missing_or_non_wheel_input(tmp_path: Path) -> None:
    """Reject missing and non-wheel audit inputs.

    Args:
        tmp_path: Isolated invalid-artifact directory.
    """
    audit = _load_script("release_audit")
    assert audit.main([]) == 2
    archive = tmp_path / "django-graphex.tar.gz"
    archive.touch()
    assert audit.main([str(archive)]) == 2


def test_ci_smoke_installs_and_audits_one_external_wheel() -> None:
    """Run the hosted wheel contract outside the checkout.

    The same prebuilt wheel must reach both smoke and dependency audit scripts.
    """
    workflow = (ROOT / ".github/workflows/cicd.yaml").read_text(encoding="utf-8")
    assert 'DIST_DIR="$RUNNER_TEMP/django-graphex-wheel-dist"' in workflow
    assert 'SMOKE_CWD="$RUNNER_TEMP/django-graphex-wheel-cwd"' in workflow
    assert 'uv pip install --python "$SMOKE_ENV/bin/python" "$WHEEL"' in workflow
    assert 'cd "$SMOKE_CWD"' in workflow
    assert 'env -u PYTHONPATH "$SMOKE_ENV/bin/python"' in workflow
    assert 'check_wheel_install.py" "$GITHUB_WORKSPACE"' in workflow
    assert 'release_audit.py "$WHEEL"' in workflow


def test_release_docs_describe_external_no_rebuild_contract() -> None:
    """Document external imports and auditing without rebuilding.

    This keeps contributor guidance aligned with the hosted release gate.
    """
    docs = (ROOT / "docs/contributing.md").read_text(encoding="utf-8")
    assert "outside the repository checkout" in docs
    assert "does not rebuild" in docs
