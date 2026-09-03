"""Tests for the docstring-convention checker in scripts/check_docstrings.py.

The checker is a stdlib-only tool that gates a repo-wide docstring remediation
and later runs in CI. These tests feed it small source snippets through
temporary files and assert which rule codes fire (and, crucially, which do NOT
fire for the two known false-positive traps).

The checker is imported by loading scripts/check_docstrings.py directly, since
the scripts directory is not an importable package.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_docstrings.py"


def _load_checker() -> ModuleType:
    """Load the checker module directly from its file path.

    The scripts directory is not a package, so the module is imported by
    spec from its absolute path rather than by name.

    Returns:
        module: The imported check_docstrings module object.
    """
    spec = importlib.util.spec_from_file_location("check_docstrings", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a deterministic Git command in a temporary repository.

    Args:
        repo: Repository working directory.
        args: Git arguments after the executable name.

    Returns:
        result: The successful completed process.
    """
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def codes_for(
    source: str,
    filename: str = "sample.py",
    *,
    strict_content: bool = False,
    strict_public: bool = False,
) -> list[str]:
    """Run the checker on a source string and return the rule codes fired.

    This is the shared helper every rule test uses to assert presence or
    absence of a specific code.

    Args:
        source: Python source text to analyze.
        filename: Virtual filename used for module-name heuristics.
        strict_content: Whether content-only rules cover every docstring owner.
        strict_public: Whether the opt-in exact public contract is enforced.

    Returns:
        codes: The rule codes (e.g. "DOC001") in the order reported.
    """
    violations = checker.check_source(
        source,
        filename,
        strict_content=strict_content,
        strict_public=strict_public,
    )
    return [v.code for v in violations]


def test_module_missing_docstring_fires_doc001() -> None:
    """A non-empty module without a docstring reports DOC001.

    The module has a top-level statement and no docstring, so the
    module-docstring rule must fire.
    """
    source = "x = 1\n"
    assert "DOC001" in codes_for(source)


def test_empty_module_is_clean() -> None:
    """An empty or whitespace-only file reports no violations at all.

    Empty files are explicitly exempt from the module-docstring rule.
    """
    assert codes_for("") == []
    assert codes_for("\n\n") == []


def test_init_reexport_stub_is_clean() -> None:
    """A short __init__.py re-export stub needs no module docstring.

    Stubs with fewer than ten statements are exempt from DOC001.
    """
    source = "from .a import A\nfrom .b import B\n"
    assert "DOC001" not in codes_for(source, filename="__init__.py")


def test_function_missing_docstring_fires_doc001() -> None:
    """A public function without a docstring reports DOC001.

    The function is public and undocumented, so the docstring rule fires.
    """
    source = '"""Module."""\n\n\ndef foo() -> None:\n    return None\n'
    assert "DOC001" in codes_for(source)


def test_single_line_docstring_fires_doc002() -> None:
    """A single-line function docstring reports DOC002.

    The convention requires multi-line Google-style docstrings.
    """
    source = (
        '"""Module."""\n\n\n'
        "def foo() -> None:\n"
        '    """Do the thing."""\n'
        "    return None\n"
    )
    assert "DOC002" in codes_for(source)


def test_complete_function_docstring_is_clean() -> None:
    """A complete multi-line Google docstring produces no codes.

    The function documents its single parameter and non-None return, so no
    content rule should fire.
    """
    source = (
        '"""Module."""\n\n\n'
        "def foo(a: int) -> int:\n"
        '    """Return a doubled.\n'
        "\n"
        "    Args:\n"
        "        a: The number to double.\n"
        "\n"
        "    Returns:\n"
        "        result: Twice the input.\n"
        '    """\n'
        "    return a * 2\n"
    )
    assert codes_for(source) == []


def test_missing_args_section_fires_doc003() -> None:
    """A function with params but no Args section reports DOC003.

    The parameter is undocumented in the docstring body.
    """
    source = (
        '"""Module."""\n\n\n'
        "def foo(a: int) -> None:\n"
        '    """Do the thing.\n'
        "\n"
        "    More detail here.\n"
        '    """\n'
        "    return None\n"
    )
    assert "DOC003" in codes_for(source)


def test_missing_returns_section_fires_doc004() -> None:
    """A function returning non-None without Returns reports DOC004.

    The return annotation is int, so a Returns section is required.
    """
    source = (
        '"""Module."""\n\n\n'
        "def foo() -> int:\n"
        '    """Do the thing.\n'
        "\n"
        "    More detail here.\n"
        '    """\n'
        "    return 1\n"
    )
    assert "DOC004" in codes_for(source)


def test_returns_none_needs_no_returns_section() -> None:
    """A function annotated to return None needs no Returns section.

    A None return annotation exempts the callable from DOC004.
    """
    source = (
        '"""Module."""\n\n\n'
        "def foo() -> None:\n"
        '    """Do the thing.\n'
        "\n"
        "    More detail here.\n"
        '    """\n'
        "    return None\n"
    )
    assert "DOC004" not in codes_for(source)


def test_body_raises_without_raises_section_fires_doc005() -> None:
    """A function that raises without a Raises section reports DOC005.

    The body raises ValueError but documents no Raises section.
    """
    source = (
        '"""Module."""\n\n\n'
        "def foo() -> None:\n"
        '    """Do the thing.\n'
        "\n"
        "    More detail here.\n"
        '    """\n'
        "    raise ValueError('bad')\n"
    )
    assert "DOC005" in codes_for(source)


def test_raise_notimplemented_only_stub_is_clean_for_doc005() -> None:
    """An abstract stub raising only NotImplementedError is clean for DOC005.

    This is a known trap: a body whose only statement is raise
    NotImplementedError is an abstract stub and must not trigger DOC005.
    """
    source = (
        '"""Module."""\n\n\n'
        "def foo() -> None:\n"
        '    """Do the thing.\n'
        "\n"
        "    More detail here.\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    assert "DOC005" not in codes_for(source)


def test_missing_type_hints_fires_doc101() -> None:
    """A parameter without a type annotation reports DOC101.

    The parameter a has no annotation.
    """
    source = (
        '"""Module."""\n\n\n'
        "def foo(a) -> None:\n"
        '    """Do the thing.\n'
        "\n"
        "    Args:\n"
        "        a: The value.\n"
        '    """\n'
        "    return None\n"
    )
    assert "DOC101" in codes_for(source)


def test_missing_return_hint_fires_doc101() -> None:
    """A function without a return annotation reports DOC101.

    The return type hint is absent entirely.
    """
    source = (
        '"""Module."""\n\n\n'
        "def foo():\n"
        '    """Do the thing.\n'
        "\n"
        "    More detail here.\n"
        '    """\n'
        "    return None\n"
    )
    assert "DOC101" in codes_for(source)


def test_unannotated_args_kwargs_fires_doc101() -> None:
    """Unannotated star-args and star-kwargs report DOC101.

    Both variadic parameters must carry annotations.
    """
    source = (
        '"""Module."""\n\n\n'
        "def foo(*args, **kwargs) -> None:\n"
        '    """Do the thing.\n'
        "\n"
        "    Args:\n"
        "        args: Positional.\n"
        "        kwargs: Keyword.\n"
        '    """\n'
        "    return None\n"
    )
    assert "DOC101" in codes_for(source)


def test_type_in_docstring_fires_doc102() -> None:
    """Repeating a type in an Args block reports DOC102.

    The entry "a (int):" duplicates the type already in the signature.
    """
    source = (
        '"""Module."""\n\n\n'
        "def foo(a: int) -> None:\n"
        '    """Do the thing.\n'
        "\n"
        "    Args:\n"
        "        a (int): The value.\n"
        '    """\n'
        "    return None\n"
    )
    assert "DOC102" in codes_for(source)


def test_prose_heading_paren_colon_is_not_doc102() -> None:
    """A prose heading like 'Algorithm (two-pass):' must not report DOC102.

    This is a known trap: the type-in-docstring regex must only match inside
    typed sections, never in free-form prose headings.
    """
    source = (
        '"""Module."""\n\n\n'
        "def foo(a: int) -> int:\n"
        '    """Return a doubled.\n'
        "\n"
        "    Algorithm (two-pass):\n"
        "        First we read, then we write.\n"
        "\n"
        "    Args:\n"
        "        a: The number to double.\n"
        "\n"
        "    Returns:\n"
        "        result: Twice the input.\n"
        '    """\n'
        "    return a * 2\n"
    )
    assert "DOC102" not in codes_for(source)


def test_backticks_in_docstring_fires_doc201() -> None:
    """Any backtick inside a docstring reports DOC201.

    The module docstring here contains a backtick-quoted token.
    """
    source = (
        '"""Module with `code` marker."""\n\n\n'
        "def foo() -> None:\n"
        '    """Do the thing.\n'
        "\n"
        "    More detail here.\n"
        '    """\n'
        "    return None\n"
    )
    assert "DOC201" in codes_for(source)


def test_private_function_is_exempt() -> None:
    """A private (underscore-prefixed) function is not checked at all.

    Non-public names fall outside the convention entirely.
    """
    source = '"""Module."""\n\n\ndef _foo(a):\n    return a\n'
    assert codes_for(source) == []


def test_strict_content_checks_private_nested_and_dunder_docstrings() -> None:
    """Strict content mode reports backticks for every docstring owner.

    Private functions, nested functions, and dunder methods are outside the
    legacy public-surface rules, but DOC201 must cover them during migration.
    """
    source = (
        '"""Module."""\n\n\n'
        "def _private() -> None:\n"
        '    """Use `private`.\n\n    Internal detail.\n    """\n'
        "    return None\n\n\n"
        "def outer() -> None:\n"
        '    """Run outer.\n\n    Public detail.\n    """\n'
        "    def nested() -> None:\n"
        '        """Use `nested`.\n\n        Internal detail.\n        """\n'
        "        return None\n"
        "    return None\n\n\n"
        "class Public:\n"
        '    """Represent a value.\n\n    Public detail.\n    """\n'
        "    def __str__(self) -> str:\n"
        '        """Return `text`.\n\n        Internal detail.\n        """\n'
        '        return "value"\n'
    )

    assert codes_for(source) == []
    assert codes_for(source, strict_content=True).count("DOC201") == 3


def test_nested_def_is_exempt() -> None:
    """A def nested inside a function is exempt from all rules.

    Only module-, class-, and method-level definitions are examined.
    """
    source = (
        '"""Module."""\n\n\n'
        "def outer() -> None:\n"
        '    """Outer function.\n'
        "\n"
        "    More detail here.\n"
        '    """\n'
        "    def inner(a):\n"
        "        return a\n"
        "    return None\n"
    )
    assert codes_for(source) == []


def test_init_without_extra_params_is_exempt_from_doc001() -> None:
    """An __init__ taking only self needs no docstring.

    Parameterless constructors are exempt from DOC001.
    """
    source = (
        '"""Module."""\n\n\n'
        "class C:\n"
        '    """A class.\n'
        "\n"
        "    More detail here.\n"
        '    """\n'
        "    def __init__(self) -> None:\n"
        "        self.x = 1\n"
    )
    assert "DOC001" not in codes_for(source)


def test_init_with_extra_params_requires_docstring() -> None:
    """An __init__ with params beyond self reports DOC001 when undocumented.

    The constructor takes a real parameter, so a docstring is required.
    """
    source = (
        '"""Module."""\n\n\n'
        "class C:\n"
        '    """A class.\n'
        "\n"
        "    More detail here.\n"
        '    """\n'
        "    def __init__(self, a: int) -> None:\n"
        "        self.a = a\n"
    )
    assert "DOC001" in codes_for(source)


def test_property_getter_requires_returns() -> None:
    """A property getter with a non-None return requires a Returns section.

    Property getters are held to the Returns rule like ordinary methods.
    """
    source = (
        '"""Module."""\n\n\n'
        "class C:\n"
        '    """A class.\n'
        "\n"
        "    More detail here.\n"
        '    """\n'
        "    @property\n"
        "    def x(self) -> int:\n"
        '        """The x value.\n'
        "\n"
        "        More detail here.\n"
        '        """\n'
        "        return 1\n"
    )
    assert "DOC004" in codes_for(source)


def test_property_setter_strict_public_requires_args_not_returns() -> None:
    """A setter requires Args only when the strict public mode is enabled.

    Its None return remains exempt from DOC004 in both modes.
    """
    source = (
        '"""Module."""\n\n\n'
        "class C:\n"
        '    """A class.\n'
        "\n"
        "    More detail here.\n"
        '    """\n'
        "    @property\n"
        "    def x(self) -> int:\n"
        '        """The x value.\n'
        "\n"
        "        Returns:\n"
        "            value: the x value.\n"
        '        """\n'
        "        return self._x\n"
        "    @x.setter\n"
        "    def x(self, value: int) -> None:\n"
        '        """Set x.\n'
        "\n"
        "        More detail here.\n"
        '        """\n'
        "        self._x = value\n"
    )
    codes = codes_for(source)
    assert "DOC003" not in codes
    assert "DOC004" not in codes
    strict = codes_for(source, strict_public=True)
    assert "DOC003" in strict
    assert {"DOC004", "DOC101"}.isdisjoint(strict)


def test_strict_public_checks_private_symbol_exported_in_all() -> None:
    """Strict mode checks private top-level names exported in __all__.

    Explicit exports define public surface regardless of naming."""
    source = (
        '"""Module."""\n\n'
        '__all__ = ["_exported"]\n\n\n'
        "def _exported(value):\n"
        "    return value\n"
    )

    assert codes_for(source) == []
    assert {"DOC001", "DOC101"}.issubset(codes_for(source, strict_public=True))


def test_strict_public_module_function_self_is_not_a_receiver() -> None:
    """A module-level self parameter requires a hint and Args entry.

    Only methods can own receivers."""
    source = (
        '"""Module."""\n\n\n'
        "def render(self) -> None:\n"
        '    """Render the value.\n\n    More detail.\n    """\n'
        "    return None\n"
    )

    assert codes_for(source) == []
    strict = codes_for(source, strict_public=True)
    assert "DOC003" in strict
    assert "DOC101" in strict


def test_strict_public_staticmethod_self_is_not_a_receiver() -> None:
    """A staticmethod self parameter requires a hint and Args entry.

    Static methods have no implicit receiver."""
    source = (
        '"""Module."""\n\n\n'
        "class Parser:\n"
        '    """Parse values.\n\n    More detail.\n    """\n'
        "    @staticmethod\n"
        "    def parse(self) -> None:\n"
        '        """Parse one value.\n\n        More detail.\n        """\n'
        "        return None\n"
    )

    assert codes_for(source) == []
    strict = codes_for(source, strict_public=True)
    assert "DOC003" in strict
    assert "DOC101" in strict


@pytest.mark.parametrize(
    "args_section",
    [
        "    Args:\n        first: The first value.",
        "    Arguments:\n        first: First.\n        second: Second.",
        "    Args:\n",
        "    Args:\n        first: First.\n        second: Second.\n        extra: Extra.",
    ],
    ids=["incomplete", "arguments-alias", "empty", "extra"],
)
def test_strict_public_rejects_inexact_args_sections(args_section: str) -> None:
    """Reject an Args section that does not match the signature exactly.

    Args:
        args_section: Candidate Args section body."""
    source = (
        '"""Module."""\n\n\n'
        "def combine(first: int, second: int) -> None:\n"
        f'    """Combine values.\n\n{args_section}\n    """\n'
        "    return None\n"
    )

    assert "DOC003" not in codes_for(source)
    assert "DOC003" in codes_for(source, strict_public=True)


def test_strict_public_args_include_variadic_parameter_names() -> None:
    """Exact Args validation includes both variadic parameter spellings.

    Star prefixes remain part of the documented names."""
    source = (
        '"""Module."""\n\n\n'
        "def collect(*args: object, **kwargs: object) -> None:\n"
        '    """Collect values.\n\n    Args:\n'
        "        *args: Positional values.\n"
        '        **kwargs: Keyword values.\n    """\n'
        "    return None\n"
    )

    assert "DOC003" not in codes_for(source, strict_public=True)


def test_strict_public_distinguishes_real_reexport_stub() -> None:
    """Strict mode identifies stubs by syntax, never statement count.

    Executable assignments make an initializer a real module."""
    imports = "".join(f"from .mod{i} import Name{i}\n" for i in range(12))
    false_stub = "from .mod import Name\nvalue = 1\n"

    assert "DOC001" not in codes_for(
        imports,
        filename="__init__.py",
        strict_public=True,
    )
    assert "DOC001" in codes_for(
        false_stub,
        filename="__init__.py",
        strict_public=True,
    )


def test_overload_is_exempt_from_args_returns() -> None:
    """An @overload signature is exempt from Args and Returns requirements.

    Overload stubs describe types only and carry no body worth documenting.
    """
    source = (
        '"""Module."""\n\n\n'
        "from typing import overload\n\n\n"
        "@overload\n"
        "def foo(a: int) -> int:\n"
        '    """Do the thing.\n'
        "\n"
        "    More detail here.\n"
        '    """\n'
        "    ...\n"
    )
    codes = codes_for(source)
    assert "DOC003" not in codes
    assert "DOC004" not in codes


def test_noqa_suppresses_specific_rule() -> None:
    """A trailing noqa pragma suppresses only its named rule for that def.

    The pragma names DOC003, so the missing-Args rule is silenced.
    """
    source = (
        '"""Module."""\n\n\n'
        "def foo(a: int) -> None:  # noqa: DOC003\n"
        '    """Do the thing.\n'
        "\n"
        "    More detail here.\n"
        '    """\n'
        "    return None\n"
    )
    codes = codes_for(source)
    assert "DOC003" not in codes


def test_noqa_does_not_suppress_other_rules() -> None:
    """A noqa for one code leaves other codes on the same def firing.

    DOC003 is suppressed but the missing-Returns rule still applies.
    """
    source = (
        '"""Module."""\n\n\n'
        "def foo(a: int) -> int:  # noqa: DOC003\n"
        '    """Do the thing.\n'
        "\n"
        "    More detail here.\n"
        '    """\n'
        "    return 1\n"
    )
    codes = codes_for(source)
    assert "DOC003" not in codes
    assert "DOC004" in codes


def test_test_function_gets_same_rules() -> None:
    """A test_* function is held to the same convention with no special case.

    Test functions still need a docstring and a return annotation.
    """
    source = '"""Module."""\n\n\ndef test_thing():\n    assert True\n'
    codes = codes_for(source)
    assert "DOC001" in codes
    assert "DOC101" in codes


def test_class_missing_docstring_fires_doc001() -> None:
    """A public class without a docstring reports DOC001.

    The class is public and undocumented.
    """
    source = '"""Module."""\n\n\nclass C:\n    x = 1\n'
    assert "DOC001" in codes_for(source)


# --- CLI-level tests -------------------------------------------------------


def test_cli_self_check_is_clean() -> None:
    """Running the checker on itself exits zero.

    The tool must obey its own convention with no violations.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(SCRIPT_PATH), "--strict-public"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_reports_violation_line_format(tmp_path: Path) -> None:
    """The CLI prints one 'path:lineno: CODE message' line per violation.

    A single-statement module is written and the DOC001 line is asserted.

    Args:
        tmp_path: pytest temporary directory fixture.
    """
    bad = tmp_path / "bad.py"
    bad.write_text("x = 1\n")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(bad)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert f"{bad}:1: DOC001" in result.stdout


def test_cli_exit_zero_on_clean(tmp_path: Path) -> None:
    """The CLI exits zero when the target has no violations.

    A file with only a module docstring is written and checked.

    Args:
        tmp_path: pytest temporary directory fixture.
    """
    good = tmp_path / "good.py"
    good.write_text('"""A clean module docstring."""\n')
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(good)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout


def test_cli_stats_only_prints_summary(tmp_path: Path) -> None:
    """The --stats flag prints only the per-rule summary table.

    The per-violation line must be absent while the summary is present.

    Args:
        tmp_path: pytest temporary directory fixture.
    """
    bad = tmp_path / "bad.py"
    bad.write_text("x = 1\n")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(bad), "--stats"],
        capture_output=True,
        text=True,
    )
    assert f"{bad}:1: DOC001" not in result.stdout
    assert "DOC001" in result.stdout


def test_cli_exclude_glob(tmp_path: Path) -> None:
    """A user-supplied --exclude glob skips matching files.

    The only file present matches the glob, so the run is clean.

    Args:
        tmp_path: pytest temporary directory fixture.
    """
    skip = tmp_path / "skip_me.py"
    skip.write_text("x = 1\n")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(tmp_path), "--exclude", "*skip_me*"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout


def test_cli_default_excludes_pycache(tmp_path: Path) -> None:
    """Files under __pycache__ are excluded by default.

    A cached module is written under __pycache__ and must be skipped.

    Args:
        tmp_path: pytest temporary directory fixture.
    """
    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "mod.py").write_text("x = 1\n")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout


def test_cli_strict_content_routes_to_all_docstring_owners(tmp_path: Path) -> None:
    """The CLI opt-in enables DOC201 for a private docstring owner.

    Args:
        tmp_path: pytest temporary directory fixture.
    """
    private = tmp_path / "private.py"
    private.write_text(
        '"""Module."""\n\n\ndef _private() -> None:\n'
        '    """Use `private`.\n\n    Internal detail.\n    """\n'
        "    return None\n"
    )

    legacy = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(private)],
        capture_output=True,
        text=True,
    )
    strict = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(private), "--strict-content"],
        capture_output=True,
        text=True,
    )

    assert legacy.returncode == 0, legacy.stdout + legacy.stderr
    assert strict.returncode == 1
    assert f"{private}:4: DOC201" in strict.stdout


def test_cli_syntax_error_is_fail_closed(tmp_path: Path) -> None:
    """Invalid Python produces a parse diagnostic and non-zero CLI exit.

    Args:
        tmp_path: pytest temporary directory fixture.
    """
    invalid = tmp_path / "invalid.py"
    invalid.write_text("def broken(:\n")

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(invalid)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert f"{invalid}:1: DOC901" in result.stdout
    assert "source parse failure" in result.stdout


def test_check_file_read_failure_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable file returns an explicit diagnostic through the API.

    Args:
        tmp_path: pytest temporary directory fixture.
        monkeypatch: pytest attribute replacement fixture.
    """
    unreadable = tmp_path / "unreadable.py"
    unreadable.write_text('"""Module."""\n')

    monkeypatch.setattr(Path, "read_text", Mock(side_effect=OSError("blocked")))

    violations = checker.check_file(unreadable)

    assert [violation.code for violation in violations] == ["DOC902"]
    assert "source read failure" in violations[0].message


def test_ratchet_module_owner_requires_a_docstring_line_change() -> None:
    """Select module debt only when its own docstring range changes.

    A change to an ordinary top-level statement must not select the module.
    """
    source = '"""Module with `legacy` debt."""\n\nvalue = 1\n'

    assert checker.check_content_source(source, changed_lines={3}) == []
    violations = checker.check_content_source(source, changed_lines={1})
    assert [(item.code, item.lineno) for item in violations] == [("DOC201", 1)]


def test_cli_diff_ratchet_covers_touched_and_new_owners(tmp_path: Path) -> None:
    """The Git ratchet checks exact owners and fails closed on new bad files.

    Args:
        tmp_path: pytest temporary directory fixture.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Docstring Tests")
    _git(repo, "config", "user.email", "tests@example.invalid")

    original = (
        '"""Module with `untouched` debt."""\n\n\n'
        "def _untouched() -> int:\n"
        '    """Return `untouched` debt."""\n'
        "    return 0\n\n\n"
        "def _private() -> int:\n"
        '    """Return `private` debt."""\n'
        "    return 1\n\n\n"
        "def outer() -> int:\n"
        '    """Return `outer` debt."""\n'
        "    def nested() -> int:\n"
        '        """Return `nested` debt."""\n'
        "        return 2\n"
        "    return 3\n\n\n"
        "class Container:\n"
        '    """Hold `class` debt."""\n'
        "    value = 4\n\n"
        "    def __str__(self) -> str:\n"
        '        """Return `dunder` debt."""\n'
        '        return "5"\n'
    )
    legacy = repo / "legacy.py"
    legacy.write_text(original)
    deleted = repo / "deleted.py"
    deleted.write_text('"""Deleted `legacy` debt."""\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "test: add legacy debt")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()

    updated = (
        original.replace("return 1", "return 10")
        .replace("return 2", "return 20")
        .replace("return 3", "return 30")
        .replace("value = 4", "value = 40")
        .replace('return "5"', 'return "50"')
    )
    legacy.write_text(updated)
    deleted.unlink()
    new_file = repo / "new.py"
    new_file.write_text(
        '"""New module."""\n\n\ndef _new() -> None:\n'
        '    """Contain `new` debt."""\n'
        "    return None\n"
    )
    invalid = repo / "invalid.py"
    invalid.write_text("def broken(:\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "test: change selected owners")

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), ".", "--diff-base", base],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    expected_lines = [
        lineno
        for lineno, line in enumerate(updated.splitlines(), start=1)
        if line.lstrip().startswith(
            (
                "def _private",
                "def outer",
                "def nested",
                "class Container",
                "def __str__",
            )
        )
    ]
    assert result.returncode == 1
    assert result.stdout.count(": DOC201 ") == 6
    for lineno in expected_lines:
        assert f"legacy.py:{lineno}: DOC201" in result.stdout
    assert "new.py:4: DOC201" in result.stdout
    assert "invalid.py:1: DOC901 source parse failure" in result.stdout
    assert "legacy.py:1: DOC201" not in result.stdout
    assert "legacy.py:4: DOC201" not in result.stdout
    assert "deleted.py" not in result.stdout


def test_cli_diff_failure_is_fail_closed() -> None:
    """An invalid diff base produces DOC903 and a non-zero CLI exit.

    The ratchet cannot silently pass when Git cannot resolve its comparison.
    """
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            ".",
            "--diff-base",
            "definitely-not-a-ref",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "<diff>:1: DOC903 diff inspection failure" in result.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
