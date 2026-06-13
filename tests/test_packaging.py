"""Packaging integrity tests for django-graphex.

Covers:
- __version__ == importlib.metadata.version("django-graphex") (single source of truth)
- __version__ == "1.2.1" (matches pyproject.toml for this release)
- py.typed marker present in the installed package
"""

import importlib.metadata
import importlib.resources

import django_graphex


def test_version_matches_importlib_metadata():
    """__version__ must be derived from importlib.metadata (single source of truth)."""
    installed = importlib.metadata.version("django-graphex")
    assert django_graphex.__version__ == installed, (
        f"__version__ ({django_graphex.__version__!r}) "
        f"does not match importlib.metadata ({installed!r}). "
        "__version__ is derived from the installed package metadata "
        "(generated from pyproject.toml) — there is no hardcoded version."
    )


def test_version_is_current_release():
    """For the v1.3.0 release, __version__ must equal '1.3.0'."""
    assert django_graphex.__version__ == "1.3.0", (
        f"Expected __version__ == '1.3.0', got {django_graphex.__version__!r}. "
        "Bump `version` in pyproject.toml and reinstall the package."
    )


def test_py_typed_marker_present():
    """py.typed must be present in the django_graphex package (PEP 561 compliance)."""
    import os

    package_dir = os.path.dirname(django_graphex.__file__)
    py_typed = os.path.join(package_dir, "py.typed")
    assert os.path.isfile(py_typed), (
        f"py.typed not found at {py_typed}. "
        "Run: touch django_graphex/py.typed and ensure it is included in the wheel."
    )
