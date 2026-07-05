"""Packaging integrity tests for django-graphex.

Covers:
- __version__ == importlib.metadata.version("django-graphex") (single source of truth)
- __version__ == "2.0.0" (matches pyproject.toml for this release)
- py.typed marker present in the installed package
"""

import importlib.metadata
import importlib.resources

import django_graphex


def test_version_matches_importlib_metadata() -> None:
    """ "__version__" must be derived from importlib.metadata (single source of truth).

    This test breaks if the package ever hardcodes a version string instead
    of reading it from the installed distribution metadata.
    """
    installed = importlib.metadata.version("django-graphex")
    assert django_graphex.__version__ == installed, (
        f"__version__ ({django_graphex.__version__!r}) "
        f"does not match importlib.metadata ({installed!r}). "
        "__version__ is derived from the installed package metadata "
        "(generated from pyproject.toml) — there is no hardcoded version."
    )


def test_version_is_current_release() -> None:
    """For the v2.0.0 release (graphene-free), "__version__" must equal "2.0.0".

    This test breaks if pyproject.toml's version is bumped without
    reinstalling the package, or vice versa.
    """
    assert django_graphex.__version__ == "2.0.0", (
        f"Expected __version__ == '2.0.0', got {django_graphex.__version__!r}. "
        "Bump `version` in pyproject.toml and reinstall the package."
    )


def test_py_typed_marker_present() -> None:
    """ "py.typed" must be present in the django_graphex package (PEP 561 compliance).

    This test breaks if the marker file is missing from the installed
    package or excluded from the wheel, which would make type checkers
    ignore the package's type hints entirely.
    """
    import os

    package_dir = os.path.dirname(django_graphex.__file__)
    py_typed = os.path.join(package_dir, "py.typed")
    assert os.path.isfile(py_typed), (
        f"py.typed not found at {py_typed}. "
        "Run: touch django_graphex/py.typed and ensure it is included in the wheel."
    )


def test_root_namespace_exports_only_version() -> None:
    """v2.0 public-API contract: the package root exports ONLY "__version__".

    Every class/function/middleware is imported from its own submodule
    (DRF-style). This is the authoritative guard for the submodule-only
    surface — if a re-export creeps back into django_graphex/__init__.py, it
    breaks here.
    """
    assert django_graphex.__all__ == ("__version__",), (
        f"Expected the package root to export only __version__, got "
        f"{django_graphex.__all__!r}. Do not re-add re-exports to "
        "django_graphex/__init__.py — import from the submodule instead."
    )


def test_flat_symbol_import_is_gone() -> None:
    """A representative former flat re-export must no longer import from the root.

    This test breaks if "IsAdmin" (or another legacy flat symbol) is
    re-added to the package root, silently reviving the v1.x flat-import
    surface.
    """
    import pytest

    with pytest.raises(ImportError):
        from django_graphex import IsAdmin  # noqa: F401 — must raise
