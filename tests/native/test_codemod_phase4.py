"""TDD WU-5 RED — scripts/codemod_phase4.py: self→root codemod.

Tests:
- A ``def resolve_X(self, info, ...)`` inside a Mutation subclass is rewritten to ``(root, ...)``.
- A ``def mutate(self, ...)`` inside a Mutation subclass is rewritten to ``(root, ...)``.
- ``class Arguments`` inside a Mutation subclass is renamed to ``class args``.
- A ``class Arguments`` inside a NON-Mutation class is NOT renamed (false-positive guard).
- Import rewrite: ``from graphene import Mutation`` → ``from django_graphex import Mutation``.
- Import rewrite: ``graphene.Mutation`` as base class → ``Mutation``.
- Idempotency: running the codemod twice produces identical output.
- ``--dry-run`` flag makes no changes to the filesystem.

Run:
    .venv/bin/python -m pytest -q tests/native/test_codemod_phase4.py
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Absolute path to the script under test — resolved once so every test uses
# the same module instance.
_SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "codemod_phase4.py"
_SCRIPTS_DIR = str(_SCRIPT.parent)


def _load_codemod():
    """Import scripts/codemod_phase4.py via sys.path so coverage can trace it."""
    if _SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, _SCRIPTS_DIR)
    # Use importlib to get a fresh reference each call, but via normal import
    # machinery so coverage.py can instrument the bytecode.
    import importlib
    import codemod_phase4  # noqa: PLC0415
    importlib.reload(codemod_phase4)
    return codemod_phase4


def transform(src: str) -> str:
    """Run the codemod transform on *src* and return the result."""
    mod = _load_codemod()
    return mod.transform_source(src)


# ---------------------------------------------------------------------------
# 5.1  self-first resolver in Mutation subclass is rewritten to root
# ---------------------------------------------------------------------------


def test_resolve_self_rewritten_in_mutation_subclass():
    """def resolve_X(self, info, ...) inside a Mutation subclass becomes (root, ...)."""
    src = textwrap.dedent("""\
        import graphene

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


def test_resolve_x_self_rewritten_in_mutation_subclass():
    """def resolve_X(self, ...) inside a Mutation subclass becomes (root, ...)."""
    src = textwrap.dedent("""\
        from graphene import Mutation

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


def test_resolve_self_not_rewritten_outside_mutation():
    """def resolve_X(self, ...) in a non-Mutation class must not be touched."""
    src = textwrap.dedent("""\
        import graphene

        class UserType(graphene.ObjectType):
            name = graphene.String()

            def resolve_name(self, info):
                return self.name
    """)
    result = transform(src)
    # Non-mutation resolver must be left alone
    assert "def resolve_name(self, info):" in result


# ---------------------------------------------------------------------------
# 5.2  class Arguments renamed to class args inside Mutation subclass
# ---------------------------------------------------------------------------


def test_arguments_renamed_in_mutation_subclass():
    """class Arguments inside a Mutation subclass is renamed to class args."""
    src = textwrap.dedent("""\
        import graphene

        class CreateUser(graphene.Mutation):
            class Arguments:
                name = graphene.String()
    """)
    result = transform(src)
    assert "class args:" in result
    assert "class Arguments:" not in result


# ---------------------------------------------------------------------------
# 5.2b  False-positive guard: class Arguments in NON-Mutation class untouched
# ---------------------------------------------------------------------------


def test_arguments_not_renamed_outside_mutation():
    """class Arguments inside a non-Mutation class must NOT be renamed."""
    src = textwrap.dedent("""\
        import graphene

        class SomeQuery(graphene.ObjectType):
            class Arguments:
                filter = graphene.String()
    """)
    result = transform(src)
    # Must remain unchanged
    assert "class Arguments:" in result
    assert "class args:" not in result


def test_arguments_not_renamed_in_plain_class():
    """class Arguments in a plain (non-graphene) class must NOT be renamed."""
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


def test_from_graphene_import_mutation_rewritten():
    """``from graphene import Mutation`` → ``from django_graphex import Mutation``."""
    src = textwrap.dedent("""\
        from graphene import Mutation

        class CreateUser(Mutation):
            pass
    """)
    result = transform(src)
    assert "from django_graphex import Mutation" in result
    assert "from graphene import Mutation" not in result


def test_graphene_mutation_base_rewritten():
    """``graphene.Mutation`` as a base class → ``Mutation`` (with import added)."""
    src = textwrap.dedent("""\
        import graphene

        class CreateUser(graphene.Mutation):
            pass
    """)
    result = transform(src)
    # The base class reference must be rewritten
    assert "graphene.Mutation" not in result


# ---------------------------------------------------------------------------
# 5.4  Idempotency: running twice produces identical output
# ---------------------------------------------------------------------------


def test_idempotency_full_snippet():
    """Running transform twice produces the same output (idempotency)."""
    src = textwrap.dedent("""\
        from graphene import Mutation

        class CreateUser(Mutation):
            class Arguments:
                name = graphene.String()

            def mutate(self, info, name):
                return CreateUser()
    """)
    first = transform(src)
    second = transform(first)
    assert first == second, (
        "Codemod is NOT idempotent!\n"
        f"First pass:\n{first}\n\nSecond pass:\n{second}"
    )


def test_idempotency_import_rewrite():
    """Import rewrite is idempotent (already-correct import not doubled)."""
    src = textwrap.dedent("""\
        from django_graphex import Mutation

        class CreateUser(Mutation):
            class args:
                name = graphene.String()

            def mutate(root, info, name):
                return CreateUser()
    """)
    first = transform(src)
    second = transform(first)
    assert first == second


def test_idempotency_already_migrated():
    """A file that is already fully migrated passes through unchanged."""
    src = textwrap.dedent("""\
        from django_graphex import Mutation

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
    """--dry-run flag must NOT write to disk."""
    src = textwrap.dedent("""\
        from graphene import Mutation

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
    """--apply flag DOES write the transformed source to disk."""
    src = textwrap.dedent("""\
        from graphene import Mutation

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
    assert "class args:" in result
    assert "def mutate(root, info, name):" in result


# ---------------------------------------------------------------------------
# 5.6  Script is importable and the script entry-point exists
# ---------------------------------------------------------------------------


def test_script_importable() -> None:
    """scripts/codemod_phase4.py can be imported without side effects."""
    assert _SCRIPT.exists(), f"Script not found at {_SCRIPT}"
    mod = _load_codemod()
    assert hasattr(mod, "transform_source")
    assert hasattr(mod, "process_file")


# ---------------------------------------------------------------------------
# 5.7  Branch coverage helpers
# ---------------------------------------------------------------------------


def test_syntax_error_returns_source_unchanged():
    """A file with a syntax error is returned unchanged (not crashed)."""
    src = "def (broken syntax"
    result = transform(src)
    assert result == src


def test_from_graphene_import_without_mutation_unchanged():
    """``from graphene import ObjectType`` (no Mutation) is not rewritten."""
    src = textwrap.dedent("""\
        from graphene import ObjectType

        class MyType(ObjectType):
            pass
    """)
    result = transform(src)
    assert result == src


def test_already_migrated_import_mutation_removed_from_graphene(tmp_path: Path) -> None:
    """When ``from django_graphex import Mutation`` already exists,
    Mutation is removed from the graphene import line."""
    src = textwrap.dedent("""\
        from django_graphex import Mutation
        from graphene import Mutation, String

        class CreateUser(Mutation):
            class Arguments:
                name = String()
    """)
    result = transform(src)
    # graphene import should keep String but not Mutation
    assert "from graphene import String" in result
    assert "Mutation" not in result.split("from graphene import")[1].split("\n")[0] if "from graphene import" in result else True


def test_from_graphene_import_mutation_only_removed_when_gdx_exists():
    """When ``from django_graphex import Mutation`` already present,
    a bare ``from graphene import Mutation`` line is fully removed."""
    src = textwrap.dedent("""\
        from django_graphex import Mutation
        from graphene import Mutation

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


def test_multi_import_graphene_mutation_plus_others():
    """``from graphene import String, Mutation`` splits correctly."""
    src = textwrap.dedent("""\
        from graphene import String, Mutation

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
    """process_file returns False when nothing changes."""
    src = textwrap.dedent("""\
        from django_graphex import Mutation

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


def test_process_file_show_diff(tmp_path: Path, capsys) -> None:
    """process_file with show_diff=True prints a unified diff."""
    src = textwrap.dedent("""\
        from graphene import Mutation

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
    assert "---" in captured.out or "+++" in captured.out or "-from graphene" in captured.out


def test_process_path_file(tmp_path: Path) -> None:
    """process_path with a single file returns 1 when a change is made."""
    src = textwrap.dedent("""\
        from graphene import Mutation

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
    """process_path with a directory recurses into .py files."""
    src = textwrap.dedent("""\
        from graphene import Mutation

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
    """process_path returns 0 when no files need changes."""
    src = textwrap.dedent("""\
        x = 1
    """)
    (tmp_path / "plain.py").write_text(src, encoding="utf-8")
    mod = _load_codemod()
    count = mod.process_path(tmp_path, dry_run=True, show_diff=False)
    assert count == 0


def test_main_dry_run(tmp_path: Path, capsys) -> None:
    """main() with --dry-run (default) does not write and prints file count."""
    src = textwrap.dedent("""\
        from graphene import Mutation

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
    """main() with --apply writes changes."""
    src = textwrap.dedent("""\
        from graphene import Mutation

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
    assert "class args:" in result
    assert "def mutate(root," in result


def test_main_show_diff(tmp_path: Path, capsys) -> None:
    """main() with --show-diff prints diff but does not write."""
    src = textwrap.dedent("""\
        from graphene import Mutation

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
    """_is_mutation_base returns False for non-Mutation / non-attribute nodes."""
    import ast as _ast
    mod = _load_codemod()
    # A Call node — neither Name nor Attribute
    call_node = _ast.parse("foo()").body[0].value  # type: ignore[attr-defined]
    assert mod._is_mutation_base(call_node) is False
