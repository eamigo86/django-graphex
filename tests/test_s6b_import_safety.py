"""S6b import-safety gate — core modules import cleanly under BOTH backends.

After re-parenting ``DjangoObjectType`` / ``DjangoListObjectType`` off graphene
(S6b), the package's eagerly-imported modules MUST still import under both
``GDX_BACKEND=native`` AND ``GDX_BACKEND=graphene``. A bare ``import`` of these
modules needs Django configured, so this runs inside the test harness (conftest
configures settings). The actual backend value is read from the environment at
import time; running this file under each ``GDX_BACKEND`` proves both paths.

Run BOTH:
    GDX_BACKEND=native   .venv/bin/python -m pytest tests/test_s6b_import_safety.py -q -o addopts="" -p no:cacheprovider --no-header --override-ini=addopts=""
    GDX_BACKEND=graphene .venv/bin/python -m pytest tests/test_s6b_import_safety.py -q -o addopts=""
"""
from __future__ import annotations

import importlib

import pytest

_CORE_MODULES = (
    "django_graphex",
    "django_graphex.types",
    "django_graphex.mutation",
    "django_graphex.schema",
    "django_graphex.native.base",
    "django_graphex.subscriptions",
)


@pytest.mark.parametrize("module_name", _CORE_MODULES)
def test_core_module_imports_clean(module_name: str) -> None:
    """Each core module imports without raising under the active backend."""
    mod = importlib.import_module(module_name)
    assert mod is not None


def test_reparented_types_importable_and_native_metaclass() -> None:
    """DjangoObjectType / DjangoListObjectType import and carry the native base."""
    from django_graphex.native.base import ObjectType as NativeObjectType
    from django_graphex.types import DjangoListObjectType, DjangoObjectType

    # S6b: both re-parented onto the native graphene-free base.
    assert issubclass(DjangoObjectType, NativeObjectType)
    assert issubclass(DjangoListObjectType, NativeObjectType)
