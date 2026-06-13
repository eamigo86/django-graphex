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
        "The VERSION tuple in __init__.py must match pyproject.toml."
    )


def test_version_is_current_release():
    """For the v1.2.2 release, __version__ must equal '1.2.2'."""
    assert django_graphex.__version__ == "1.2.2", (
        f"Expected __version__ == '1.2.2', got {django_graphex.__version__!r}. "
        "Update VERSION tuple in django_graphex/__init__.py to (1, 2, 2, 'final', '')."
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
