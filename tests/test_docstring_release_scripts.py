"""Focused contract for release-script docstrings."""

from pathlib import Path

import pytest

from scripts.check_docstrings import check_file

ROOT = Path(__file__).resolve().parents[1]
RELEASE_SCRIPTS = (
    ROOT / "scripts" / "check_wheel_install.py",
    ROOT / "scripts" / "release_audit.py",
)


@pytest.mark.parametrize("script", RELEASE_SCRIPTS, ids=lambda path: path.name)
def test_release_scripts_satisfy_strict_docstring_contract(script: Path) -> None:
    """Require each release script to satisfy both strict modes.

    Args:
        script: Exact release-script path under contract.
    """
    violations = check_file(
        script,
        strict_public=True,
        strict_content=True,
    )

    details = "\n".join(
        f"{script}:{item.lineno}: {item.code} {item.message}" for item in violations
    )
    assert not violations, details
