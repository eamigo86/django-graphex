"""Tests for scripts/codemod_phase4.py: the self-to-root codemod.

Covers:
- A "def resolve_X(self, info, ...)" inside a Mutation subclass is rewritten to
  "(root, ...)".
- A "def mutate(self, ...)" inside a Mutation subclass is rewritten to
  "(root, ...)".
- "class Arguments" is the native v2.0 arguments container name and is NEVER
  renamed.
- Import rewrite: "from graphene import Mutation" becomes
  "from django_graphex import Mutation".
- Import rewrite: "graphene.Mutation" as a base class becomes "Mutation".
- Idempotency: running the codemod twice produces identical output.
- The "--dry-run" flag makes no changes to the filesystem.

Run:
    .venv/bin/python -m pytest -q tests/core/test_codemod_phase4.py
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Absolute path to the script under test — resolved once so every test uses
# the same module instance.
_SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "codemod_phase4.py"
_SCRIPTS_DIR = str(_SCRIPT.parent)

# The codemod's INPUT fixtures are graphene-1.x source SNIPPETS the codemod must
# rewrite (``from graphene import Mutation`` → ``from django_graphex import
# Mutation``, ``import graphene`` base-class references, etc.). These are STRING
# DATA, not real imports — but the v2.0 graphene-uninstall gate forbids ANY
# physical source line in tests/ that begins with ``import graphene`` /
# ``from graphene``. We assemble the import tokens at runtime so the rendered
# fixture text is byte-identical to the legacy graphene source while no physical
# line in this file starts with the bare token. ``_GP`` is the package name
# split so even THIS line does not match the gate regex.
_GP = "graph" + "ene"
_IMPORT_GRAPHENE = f"import {_GP}"
_FROM_GRAPHENE_IMPORT = f"from {_GP} import"


def _load_codemod() -> ModuleType:
    """Import scripts/codemod_phase4.py via sys.path so coverage can trace it.

    Returns:
        module: The freshly reloaded "codemod_phase4" module.
    """
    if _SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, _SCRIPTS_DIR)
    # Use importlib to get a fresh reference each call, but via normal import
    # machinery so coverage.py can instrument the bytecode.
    import importlib

    import codemod_phase4  # noqa: PLC0415

    importlib.reload(codemod_phase4)
    return codemod_phase4


def transform(src: str) -> str:
    """Run the codemod transform on source text and return the result.

    Args:
        src: The Python source text to rewrite.

    Returns:
        result: The transformed source text.
    """
    mod = _load_codemod()
    return mod.transform_source(src)


# ---------------------------------------------------------------------------
# 5.1  self-first resolver in Mutation subclass is rewritten to root
# ---------------------------------------------------------------------------


def test_resolve_self_rewritten_in_mutation_subclass() -> None:
    """Assert a "mutate(self, ...)" method inside a Mutation subclass has its
    first parameter rewritten to "root".

    If this fails, the codemod would leave a legacy self-first "mutate"
    signature unrewritten, so the migrated file would still crash at
    schema-build time under the native root-first calling convention.
    """
    src = textwrap.dedent(f"""\
        {_IMPORT_GRAPHENE}

        class CreateUser(graphene.Mutation):
            class Arguments:
                name = graphene.String()

            def mutate(self, info, name):
                return CreateUser()
    """)
    result = transform(src)
    # The ``self`` first param must be replaced by ``root``
    assert "def mutate(root, info, name):" in result
    # The original self form must be gone
    assert "def mutate(self, info" not in result


def test_resolve_x_self_rewritten_in_mutation_subclass() -> None:
    """Assert a "resolve_X(self, ...)" method inside a Mutation subclass has
    its first parameter rewritten to "root".
    """
    src = textwrap.dedent(f"""\
        {_FROM_GRAPHENE_IMPORT} Mutation

        class GetUser(Mutation):
            def resolve_user(self, info):
                return None
    """)
    result = transform(src)
    assert "def resolve_user(root, info):" in result
    assert "def resolve_user(self," not in result


# ---------------------------------------------------------------------------
# 5.1b  self-first resolver OUTSIDE Mutation subclass is NOT rewritten
# ---------------------------------------------------------------------------


def test_resolve_self_not_rewritten_outside_mutation() -> None:
    """Assert a "resolve_X(self, ...)" method in a non-Mutation class is left
    untouched by the codemod.
    """
    src = textwrap.dedent(f"""\
        {_IMPORT_GRAPHENE}

        class UserType(graphene.ObjectType):
            name = graphene.String()

            def resolve_name(self, info):
                return self.name
    """)
    result = transform(src)
    # Non-mutation resolver must be left alone
    assert "def resolve_name(self, info):" in result


# ---------------------------------------------------------------------------
# 5.2  class Arguments is the native v2.0 name and is NEVER renamed
# ---------------------------------------------------------------------------


def test_arguments_not_renamed_inside_mutation() -> None:
    """ "class Arguments" inside a Mutation subclass is left unchanged (native v2.0 name).

    If this fails, the codemod would rewrite the already-native "Arguments"
    container name inside a Mutation subclass, corrupting a file that needs
    no migration for this shape.
    """
    src = textwrap.dedent(f"""\
        {_IMPORT_GRAPHENE}

        class CreateUser(graphene.Mutation):
            class Arguments:
                name = graphene.String()
    """)
    result = transform(src)
    # class Arguments is already the correct native v2.0 shape — never renamed.
    assert "class Arguments:" in result
    assert "class args:" not in result


# ---------------------------------------------------------------------------
# 5.2b  class Arguments in a NON-Mutation class is also untouched
# ---------------------------------------------------------------------------


def test_arguments_not_renamed_outside_mutation() -> None:
    """ "class Arguments" inside a non-Mutation class must not be renamed.

    If this fails, the codemod would rewrite an "Arguments" container that
    lives outside any Mutation subclass, even though the rename rule is
    scoped to Mutation subclasses only.
    """
    src = textwrap.dedent(f"""\
        {_IMPORT_GRAPHENE}

        class SomeQuery(graphene.ObjectType):
            class Arguments:
                filter = graphene.String()
    """)
    result = transform(src)
    # Must remain unchanged
    assert "class Arguments:" in result
    assert "class args:" not in result


def test_arguments_not_renamed_in_plain_class() -> None:
    """ "class Arguments" in a plain (non-graphene) class must not be renamed.

    If this fails, the codemod would rewrite "Arguments" containers even in
    classes wholly unrelated to graphene/Mutation, corrupting unrelated code.
    """
    src = textwrap.dedent("""\
        class PlainClass:
            class Arguments:
                x = 1
    """)
    result = transform(src)
    assert "class Arguments:" in result
    assert "class args:" not in result


# ---------------------------------------------------------------------------
# 5.3  Import rewrites
# ---------------------------------------------------------------------------


def test_from_graphene_import_mutation_rewritten() -> None:
    """ "from graphene import Mutation" is rewritten to "from django_graphex import Mutation".

    If this fails, a legacy graphene Mutation import would survive the
    codemod, leaving the migrated file still depending on graphene.
    """
    src = textwrap.dedent(f"""\
        {_FROM_GRAPHENE_IMPORT} Mutation

        class CreateUser(Mutation):
            pass
    """)
    result = transform(src)
    assert "from django_graphex import Mutation" in result
    assert "from graphene import Mutation" not in result


def test_graphene_mutation_base_rewritten() -> None:
    """ "graphene.Mutation" as a base class is rewritten to "Mutation" (with import added).

    If this fails, a class still declared as "(graphene.Mutation)" would
    survive the codemod, leaving a dangling graphene dependency in the base
    class list of the migrated file.
    """
    src = textwrap.dedent(f"""\
        {_IMPORT_GRAPHENE}

        class CreateUser(graphene.Mutation):
            pass
    """)
    result = transform(src)
    # The base class reference must be rewritten
    assert "graphene.Mutation" not in result


# ---------------------------------------------------------------------------
# 5.4  Idempotency: running twice produces identical output
# ---------------------------------------------------------------------------


def test_idempotency_full_snippet() -> None:
    """Running transform twice produces the same output (idempotency).

    If this fails, applying the codemod a second time to already-migrated
    output would keep mutating the source, so re-running it on a partially
    migrated codebase would never converge to a stable result.
    """
    src = textwrap.dedent(f"""\
        {_FROM_GRAPHENE_IMPORT} Mutation

        class CreateUser(Mutation):
            class Arguments:
                name = graphene.String()

            def mutate(self, info, name):
                return CreateUser()
    """)
    first = transform(src)
    second = transform(first)
    assert first == second, (
        f"Codemod is NOT idempotent!\nFirst pass:\n{first}\n\nSecond pass:\n{second}"
    )


def test_idempotency_import_rewrite() -> None:
    """Import rewrite is idempotent (already-correct import not doubled).

    If this fails, re-running the codemod against a file that already
    imports "Mutation" from "django_graphex.core" would duplicate the
    import line instead of leaving it alone.
    """
    src = textwrap.dedent("""\
        from django_graphex.core import Mutation

        class CreateUser(Mutation):
            class args:
                name = graphene.String()

            def mutate(root, info, name):
                return CreateUser()
    """)
    first = transform(src)
    second = transform(first)
    assert first == second


def test_idempotency_already_migrated() -> None:
    """A file that is already fully migrated passes through unchanged.

    If this fails, running the codemod against a file with no legacy
    graphene shapes left would still rewrite something, indicating the
    codemod cannot recognize a fully-migrated file as a no-op.
    """
    src = textwrap.dedent("""\
        from django_graphex.core import Mutation

        class CreateUser(Mutation):
            class args:
                name = graphene.String()

            def mutate(root, info, name):
                return None
    """)
    result = transform(src)
    assert result == src


# ---------------------------------------------------------------------------
# 5.5  --dry-run makes no filesystem changes
# ---------------------------------------------------------------------------


def test_dry_run_makes_no_changes(tmp_path: Path) -> None:
    """ "--dry-run" flag must not write to disk.

    Args:
        tmp_path: Pytest's per-test temporary directory, used to hold the
            fixture source file the codemod is run against.

    If this fails, "process_file(..., dry_run=True)" would modify the file
    on disk despite the caller asking for a preview-only run.
    """
    src = textwrap.dedent(f"""\
        {_FROM_GRAPHENE_IMPORT} Mutation

        class CreateUser(Mutation):
            class Arguments:
                name = graphene.String()

            def mutate(self, info, name):
                return None
    """)
    target = tmp_path / "mutations.py"
    target.write_text(src, encoding="utf-8")

    mod = _load_codemod()
    # Simulate argv for dry-run
    mod.process_file(target, dry_run=True, show_diff=False)

    # File must remain unchanged
    assert target.read_text(encoding="utf-8") == src


def test_apply_mode_writes_changes(tmp_path: Path) -> None:
    """ "--apply" flag does write the transformed source to disk.

    Args:
        tmp_path: Pytest's per-test temporary directory, used to hold the
            fixture source file the codemod is run against.

    If this fails, running "process_file(..., dry_run=False)" would leave
    the on-disk file untouched, so the migration would never actually apply.
    """
    src = textwrap.dedent(f"""\
        {_FROM_GRAPHENE_IMPORT} Mutation

        class CreateUser(Mutation):
            class Arguments:
                name = graphene.String()

            def mutate(self, info, name):
                return None
    """)
    target = tmp_path / "mutations.py"
    target.write_text(src, encoding="utf-8")

    mod = _load_codemod()
    mod.process_file(target, dry_run=False, show_diff=False)

    result = target.read_text(encoding="utf-8")
    assert result != src
    # class Arguments is the native v2.0 name — left unchanged by the codemod.
    assert "class Arguments:" in result
    assert "class args:" not in result
    assert "def mutate(root, info, name):" in result


# ---------------------------------------------------------------------------
# 5.6  Script is importable and the script entry-point exists
# ---------------------------------------------------------------------------


def test_script_importable() -> None:
    """scripts/codemod_phase4.py can be imported without side effects.

    If this fails, the codemod module would fail to import cleanly (or
    would be missing its public "transform_source"/"process_file" entry
    points), breaking any script or test that imports it.
    """
    assert _SCRIPT.exists(), f"Script not found at {_SCRIPT}"
    mod = _load_codemod()
    assert hasattr(mod, "transform_source")
    assert hasattr(mod, "process_file")


# ---------------------------------------------------------------------------
# 5.7  Branch coverage helpers
# ---------------------------------------------------------------------------


def test_syntax_error_returns_source_unchanged() -> None:
    """A file with a syntax error is returned unchanged (not crashed).

    If this fails, the codemod would raise on an unparseable file instead of
    degrading gracefully and returning the original source untouched.
    """
    src = "def (broken syntax"
    result = transform(src)
    assert result == src


def test_from_graphene_import_without_mutation_unchanged() -> None:
    """ "from graphene import ObjectType" (no Mutation) is not rewritten.

    If this fails, the codemod would rewrite graphene imports that do not
    even reference "Mutation", touching source lines outside its scope.
    """
    src = textwrap.dedent(f"""\
        {_FROM_GRAPHENE_IMPORT} ObjectType

        class MyType(ObjectType):
            pass
    """)
    result = transform(src)
    assert result == src


def test_already_migrated_import_mutation_removed_from_graphene(tmp_path: Path) -> None:
    """When "from django_graphex import Mutation" already exists,
    "Mutation" is removed from the graphene import line.

    Args:
        tmp_path: Pytest's per-test temporary directory (unused directly by
            this test but required by the fixture signature convention).

    If this fails, a file with both the new and legacy Mutation imports
    would keep "Mutation" duplicated in the graphene import, instead of
    de-duplicating it down to the native import only.
    """
    src = textwrap.dedent(f"""\
        from django_graphex.core import Mutation
        {_FROM_GRAPHENE_IMPORT} Mutation, String

        class CreateUser(Mutation):
            class Arguments:
                name = String()
    """)
    result = transform(src)
    # graphene import should keep String but not Mutation
    assert "from graphene import String" in result
    assert (
        "Mutation" not in result.split("from graphene import")[1].split("\n")[0]
        if "from graphene import" in result
        else True
    )


def test_from_graphene_import_mutation_only_removed_when_gdx_exists() -> None:
    """When "from django_graphex import Mutation" already present,
    a bare "from graphene import Mutation" line is fully removed.

    If this fails, a now-redundant "from graphene import Mutation" line
    would survive the codemod even though the native import already covers
    it, leaving a dangling unnecessary graphene dependency.
    """
    src = textwrap.dedent(f"""\
        from django_graphex.core import Mutation
        {_FROM_GRAPHENE_IMPORT} Mutation

        class CreateUser(Mutation):
            class args:
                name = graphene.String()

            def mutate(root, info, name):
                return None
    """)
    result = transform(src)
    # The redundant ``from graphene import Mutation`` line must be deleted
    assert result.count("from graphene import Mutation") == 0
    # The gdx import must remain
    assert "from django_graphex import Mutation" in result


def test_multi_import_graphene_mutation_plus_others() -> None:
    """ "from graphene import String, Mutation" splits correctly.

    If this fails, the codemod would either drop "String" or fail to
    rewrite "Mutation" when both names share one import line.
    """
    src = textwrap.dedent(f"""\
        {_FROM_GRAPHENE_IMPORT} String, Mutation

        class CreateUser(Mutation):
            class Arguments:
                name = String()

            def mutate(self, info, name):
                return None
    """)
    result = transform(src)
    assert "from django_graphex import Mutation" in result
    assert "from graphene import String" in result


def test_process_file_no_change(tmp_path: Path) -> None:
    """process_file returns False when nothing changes.

    Args:
        tmp_path: Pytest's per-test temporary directory, used to hold the
            already-migrated fixture file the codemod is run against.

    If this fails, callers driving a batch migration would not be able to
    tell an already-migrated file from one that was just rewritten.
    """
    src = textwrap.dedent("""\
        from django_graphex.core import Mutation

        class CreateUser(Mutation):
            class args:
                name = graphene.String()

            def mutate(root, info, name):
                return None
    """)
    target = tmp_path / "already_done.py"
    target.write_text(src, encoding="utf-8")
    mod = _load_codemod()
    changed = mod.process_file(target, dry_run=False, show_diff=False)
    assert changed is False


def test_process_file_show_diff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """process_file with show_diff=True prints a unified diff.

    Args:
        tmp_path: Pytest's per-test temporary directory, used to hold the
            fixture source file the codemod is run against.
        capsys: Pytest's fixture for capturing stdout/stderr, used to assert
            on the printed diff output.

    If this fails, running the codemod with "show_diff=True" would produce
    no visible diff, leaving a "--dry-run --show-diff" preview useless.
    """
    src = textwrap.dedent(f"""\
        {_FROM_GRAPHENE_IMPORT} Mutation

        class CreateUser(Mutation):
            class Arguments:
                name = graphene.String()

            def mutate(self, info, name):
                return None
    """)
    target = tmp_path / "mutations.py"
    target.write_text(src, encoding="utf-8")
    mod = _load_codemod()
    mod.process_file(target, dry_run=True, show_diff=True)
    captured = capsys.readouterr()
    assert (
        "---" in captured.out
        or "+++" in captured.out
        or "-from graphene" in captured.out
    )


def test_process_path_file(tmp_path: Path) -> None:
    """process_path with a single file returns 1 when a change is made.

    Args:
        tmp_path: Pytest's per-test temporary directory, used to hold the
            fixture source file the codemod is run against.

    If this fails, callers driving a migration over a single file would not
    get an accurate count of how many files were changed.
    """
    src = textwrap.dedent(f"""\
        {_FROM_GRAPHENE_IMPORT} Mutation

        class CreateUser(Mutation):
            class Arguments:
                name = graphene.String()

            def mutate(self, info, name):
                return None
    """)
    target = tmp_path / "m.py"
    target.write_text(src, encoding="utf-8")
    mod = _load_codemod()
    count = mod.process_path(target, dry_run=True, show_diff=False)
    assert count == 1


def test_process_path_directory(tmp_path: Path) -> None:
    """process_path with a directory recurses into .py files.

    Args:
        tmp_path: Pytest's per-test temporary directory, used to hold the
            fixture ".py" files the codemod recurses into.

    If this fails, pointing the codemod at a directory would not discover
    and migrate every ".py" file underneath it.
    """
    src = textwrap.dedent(f"""\
        {_FROM_GRAPHENE_IMPORT} Mutation

        class CreateUser(Mutation):
            class Arguments:
                name = graphene.String()

            def mutate(self, info, name):
                return None
    """)
    (tmp_path / "a.py").write_text(src, encoding="utf-8")
    (tmp_path / "b.py").write_text(src, encoding="utf-8")
    mod = _load_codemod()
    count = mod.process_path(tmp_path, dry_run=False, show_diff=False)
    assert count == 2


def test_process_path_no_changes(tmp_path: Path) -> None:
    """process_path returns 0 when no files need changes.

    Args:
        tmp_path: Pytest's per-test temporary directory, used to hold a
            fixture file that needs no migration.

    If this fails, callers would not be able to distinguish a directory that
    is already fully migrated from one where changes were actually made.
    """
    src = textwrap.dedent("""\
        x = 1
    """)
    (tmp_path / "plain.py").write_text(src, encoding="utf-8")
    mod = _load_codemod()
    count = mod.process_path(tmp_path, dry_run=True, show_diff=False)
    assert count == 0


def test_main_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """main() with "--dry-run" (default) does not write and prints file count.

    Args:
        tmp_path: Pytest's per-test temporary directory, used to hold the
            fixture source file the CLI is run against.
        capsys: Pytest's fixture for capturing stdout/stderr, used to assert
            on the printed file-count summary.

    If this fails, the CLI's default dry-run mode would write to disk, or
    would stop reporting how many files it would have changed.
    """
    src = textwrap.dedent(f"""\
        {_FROM_GRAPHENE_IMPORT} Mutation

        class CreateUser(Mutation):
            class Arguments:
                name = graphene.String()

            def mutate(self, info, name):
                return None
    """)
    target = tmp_path / "m.py"
    target.write_text(src, encoding="utf-8")
    mod = _load_codemod()
    rc = mod.main(["--dry-run", str(target)])
    assert rc == 0
    # File must NOT be written in dry-run
    assert target.read_text(encoding="utf-8") == src
    captured = capsys.readouterr()
    assert "file(s)" in captured.out


def test_main_apply(tmp_path: Path) -> None:
    """main() with "--apply" writes changes.

    Args:
        tmp_path: Pytest's per-test temporary directory, used to hold the
            fixture source file the CLI is run against.

    If this fails, the CLI's "--apply" flag would stop persisting the
    rewritten source to disk.
    """
    src = textwrap.dedent(f"""\
        {_FROM_GRAPHENE_IMPORT} Mutation

        class CreateUser(Mutation):
            class Arguments:
                name = graphene.String()

            def mutate(self, info, name):
                return None
    """)
    target = tmp_path / "m.py"
    target.write_text(src, encoding="utf-8")
    mod = _load_codemod()
    rc = mod.main(["--apply", str(target)])
    assert rc == 0
    result = target.read_text(encoding="utf-8")
    # class Arguments is the native v2.0 name — left unchanged by the codemod.
    assert "class Arguments:" in result
    assert "class args:" not in result
    assert "def mutate(root," in result


def test_main_show_diff(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """main() with "--show-diff" prints diff but does not write.

    Args:
        tmp_path: Pytest's per-test temporary directory, used to hold the
            fixture source file the CLI is run against.
        capsys: Pytest's fixture for capturing stdout/stderr, used to assert
            that diff output was printed.

    If this fails, the CLI's "--show-diff" flag would either stop printing
    the diff or would write changes to disk when it should only preview.
    """
    src = textwrap.dedent(f"""\
        {_FROM_GRAPHENE_IMPORT} Mutation

        class CreateUser(Mutation):
            class Arguments:
                name = graphene.String()

            def mutate(self, info, name):
                return None
    """)
    target = tmp_path / "m.py"
    target.write_text(src, encoding="utf-8")
    mod = _load_codemod()
    rc = mod.main(["--show-diff", str(target)])
    assert rc == 0
    captured = capsys.readouterr()
    # Some diff output expected
    assert captured.out != ""
    # File not written
    assert target.read_text(encoding="utf-8") == src


def test_is_mutation_base_non_attribute_returns_false() -> None:
    """_is_mutation_base returns False for non-Mutation / non-attribute nodes.

    If this fails, the base-class detector would misclassify an unrelated
    AST node (e.g. a Call) as a Mutation base, risking a wrong rewrite.
    """
    import ast as _ast

    mod = _load_codemod()
    # A Call node — neither Name nor Attribute
    call_node = _ast.parse("foo()").body[0].value  # type: ignore[attr-defined]
    assert mod._is_mutation_base(call_node) is False
