"""B7: CI lint — ban eager instantiation in resolver-path modules.

Verifies that model_validate, model_dump, and from_attributes=True are absent
from resolver-path modules without the escape comment.

Resolver-path modules: types.py, fields.py, utils.py, converter.py, views.py
Escape comment: # gdx: output-path-exception

All tests run under GDX_BACKEND=native via the native_only mark.
"""
from __future__ import annotations

import os
import re
import pytest

pytestmark = pytest.mark.native_only

# Resolver-path modules to lint
_RESOLVER_PATH_MODULES = [
    "django_graphex/types.py",
    "django_graphex/fields.py",
    "django_graphex/utils.py",
    "django_graphex/converter.py",
    "django_graphex/views.py",
]

# Patterns to ban (without escape)
_BANNED_PATTERNS = [
    r"\bmodel_validate\s*\(",
    r"\bmodel_dump\s*\(",
    r"from_attributes\s*=\s*True",
]

_ESCAPE_COMMENT = "# gdx: output-path-exception"


def _check_file_for_violations(filepath: str) -> list[tuple[int, str]]:
    """Return a list of (line_number, line) tuples for violations."""
    violations = []

    # Find project root (parent of django_graphex/)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    full_path = os.path.join(project_root, filepath)

    if not os.path.exists(full_path):
        return []

    with open(full_path) as f:
        lines = f.readlines()

    for lineno, line in enumerate(lines, 1):
        # Skip lines with the escape comment
        if _ESCAPE_COMMENT in line:
            continue

        for pattern in _BANNED_PATTERNS:
            if re.search(pattern, line):
                violations.append((lineno, line.rstrip()))

    return violations


def test_types_py_no_banned_patterns():
    """types.py must not contain model_validate/model_dump/from_attributes=True
    without the escape comment."""
    violations = _check_file_for_violations("django_graphex/types.py")
    assert not violations, (
        "types.py contains banned eager-instantiation patterns:\n"
        + "\n".join(f"  Line {lineno}: {line}" for lineno, line in violations)
    )


def test_fields_py_no_banned_patterns():
    """fields.py must not contain banned patterns without escape."""
    violations = _check_file_for_violations("django_graphex/fields.py")
    assert not violations, (
        "fields.py contains banned eager-instantiation patterns:\n"
        + "\n".join(f"  Line {lineno}: {line}" for lineno, line in violations)
    )


def test_utils_py_no_banned_patterns():
    """utils.py must not contain banned patterns without escape."""
    violations = _check_file_for_violations("django_graphex/utils.py")
    assert not violations, (
        "utils.py contains banned eager-instantiation patterns:\n"
        + "\n".join(f"  Line {lineno}: {line}" for lineno, line in violations)
    )


def test_converter_py_no_banned_patterns():
    """converter.py must not contain banned patterns without escape."""
    violations = _check_file_for_violations("django_graphex/converter.py")
    assert not violations, (
        "converter.py contains banned eager-instantiation patterns:\n"
        + "\n".join(f"  Line {lineno}: {line}" for lineno, line in violations)
    )


def test_views_py_no_banned_patterns():
    """views.py must not contain banned patterns without escape."""
    violations = _check_file_for_violations("django_graphex/views.py")
    assert not violations, (
        "views.py contains banned eager-instantiation patterns:\n"
        + "\n".join(f"  Line {lineno}: {line}" for lineno, line in violations)
    )


def test_escape_comment_allows_violation():
    """A banned pattern WITH the escape comment must NOT be flagged as a violation.

    This is a meta-test that verifies our lint checker correctly honors escapes.
    """
    import tempfile
    import os

    # Write a temp file with an escaped violation
    content = "# This file tests the escape mechanism\n"
    content += "result = obj.model_validate(data)  # gdx: output-path-exception\n"
    content += "print('hello')\n"

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(content)
        tmp_path = f.name

    try:
        # Manually call our checker logic
        violations = []
        with open(tmp_path) as fh:
            for lineno, line in enumerate(fh, 1):
                if _ESCAPE_COMMENT in line:
                    continue
                for pattern in _BANNED_PATTERNS:
                    if re.search(pattern, line):
                        violations.append((lineno, line.rstrip()))

        assert not violations, (
            f"Escape comment was not honored; violations: {violations}"
        )
    finally:
        os.unlink(tmp_path)
