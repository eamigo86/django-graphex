"""Assert the supported, isolated GraphQL runtime before selected audit tests."""

from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path

import graphql

import django_graphex

_ROOT = Path(__file__).resolve().parents[1]
_OVERLAY = Path(
    "/Users/eamigo/.codex/visualizations/2026/09/02/"
    "01a062ff-dccb-7123-a1e9-e7de825aafc2/graphex-resume-2026-10-02/"
    "native330-reconstruction/core330-overlay"
)

assert Path.cwd().resolve() == _ROOT
assert graphql.__version__ == "3.3.0"
assert importlib.metadata.version("graphql-core") == "3.3.0"
assert Path(graphql.__file__).resolve().is_relative_to(_OVERLAY.resolve())
assert Path(django_graphex.__file__).resolve() == _ROOT / "django_graphex/__init__.py"
print(
    "native330-guard: cwd={}, graphql={}, module={}, package={}".format(
        os.getcwd(),
        graphql.__version__,
        Path(graphql.__file__).resolve(),
        Path(django_graphex.__file__).resolve(),
    )
)
