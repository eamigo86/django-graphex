"""S-args-8 follow-up: the shipped playground example declares mutation args natively.

The playground (``examples/playground/blog/schema.py``) ships two hand-written
``Mutation`` subclasses — ``CreateCategory`` and ``UploadDocument`` — whose
``class args`` USED to be declared with the transitional ``graphene.Argument``
form. After the S-args-8 CLEAN BREAK (``_compile_args`` is native-only) that form
is no longer recognised, so the example must declare its args via the NATIVE arg
API (a graphql-core ``GraphQLArgument`` / lazy thunk).

This test BUILDS the playground schema in its OWN Django environment (a subprocess,
because the playground installs a different ``INSTALLED_APPS`` than the test suite)
and asserts the mutation args are PRESENT (not dropped) with the expected SDL:

    createCategory(data: CategoryInput!): CreateCategory
    uploadDocument(name: String!, file: Base64FileInput!): UploadDocument

Run:
    .venv/bin/python -m pytest -q tests/native/test_playground_example_args.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.native_only

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PLAYGROUND = _REPO_ROOT / "examples" / "playground"

# Inline build script: setup Django with the playground settings, build the schema,
# and emit the createCategory + uploadDocument SDL lines (sorted, deterministic).
_BUILD_SCRIPT = r"""
import django
django.setup()
from blog.schema import schema
from graphql.utilities import print_schema

sdl = print_schema(schema.graphql_schema)
for line in sdl.splitlines():
    s = line.strip()
    if s.startswith("createCategory") or s.startswith("uploadDocument"):
        print(s)
"""


def _build_playground_mutation_sdl() -> list[str]:
    """Run the playground schema build in a subprocess; return the arg SDL lines."""
    if not _PLAYGROUND.exists():
        pytest.skip("playground example not present")

    env = dict(os.environ)
    env["GDX_BACKEND"] = "native"
    env["DJANGO_SETTINGS_MODULE"] = "config.settings"

    proc = subprocess.run(
        [sys.executable, "-c", _BUILD_SCRIPT],
        cwd=str(_PLAYGROUND),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        "playground schema build failed:\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def test_playground_create_category_has_data_arg():
    """``createCategory`` exposes its ``data: CategoryInput!`` arg (NOT dropped)."""
    lines = _build_playground_mutation_sdl()
    create = [ln for ln in lines if ln.startswith("createCategory")]
    assert create, f"createCategory not found in playground SDL: {lines}"
    assert create[0] == "createCategory(data: CategoryInput!): CreateCategory", (
        "createCategory must expose its native input-object arg (was silently "
        f"dropped before FIX 2); got: {create[0]!r}"
    )


def test_playground_upload_document_has_both_args():
    """``uploadDocument`` exposes ``name: String!`` AND ``file: Base64FileInput!``."""
    lines = _build_playground_mutation_sdl()
    upload = [ln for ln in lines if ln.startswith("uploadDocument")]
    assert upload, f"uploadDocument not found in playground SDL: {lines}"
    assert upload[0] == (
        "uploadDocument(name: String!, file: Base64FileInput!): UploadDocument"
    ), (
        "uploadDocument must expose BOTH native args (were silently dropped "
        f"before FIX 2); got: {upload[0]!r}"
    )
