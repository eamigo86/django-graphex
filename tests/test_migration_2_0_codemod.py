"""Tests for ``scripts/migrate_2_0.py`` — the v1.x -> v2.0 migration codemod.

v2.0 removed the graphene backend entirely (decision #1603). This codemod helps
users move their project off graphene:

* MECHANICAL REWRITE (``--apply`` / ``rewrite_source``): the schema/middleware
  settings namespace ``GRAPHENE = {...}`` is folded into the SINGLE
  ``DJANGO_GRAPHEX = {...}`` namespace (rename when no target dict exists, key
  MERGE when it does).
* REPORT-AND-FLAG (always): graphene constructs that v2.0 no longer accepts —
  ``graphene.Argument(...)`` in a ``Mutation`` ``class args``, ``graphene.ObjectType``
  schema roots, ``graphene.Schema(...)`` and graphene field descriptors — are
  detected and surfaced with actionable native-API guidance.

IMPORTANT: graphene is UNINSTALLED in v2.0. This test must NEVER import graphene.
It operates purely on SOURCE STRINGS, so the graphene tokens below are built from
fragments / appear only inside string literals — never on a physical import line.

Run:
    .venv/bin/python -m pytest -q tests/test_migration_2_0_codemod.py
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Load the codemod module from scripts/ without it being on a package path.    #
# --------------------------------------------------------------------------- #
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CODEMOD_PATH = _REPO_ROOT / "scripts" / "migrate_2_0.py"


def _load_codemod():
    spec = importlib.util.spec_from_file_location("migrate_2_0", _CODEMOD_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # Register before exec so dataclass field-type resolution (which reads
    # ``sys.modules[cls.__module__].__dict__``) works for a file-loaded module.
    sys.modules["migrate_2_0"] = module
    spec.loader.exec_module(module)
    return module


migrate_2_0 = _load_codemod()


# --------------------------------------------------------------------------- #
# Source fixtures. The graphene tokens are assembled from fragments so no       #
# physical line in this file starts with ``import graphene`` / ``from graphene``#
# (the repo-wide zero-graphene gate is line-based). The RENDERED string is      #
# byte-identical to a real graphene-using module.                              #
# --------------------------------------------------------------------------- #
_G = "graph" + "ene"  # noqa: S105 - not a secret; avoids the literal token on an import line
_IMPORT_GRAPHENE = f"import {_G}"

# Merge case: a project that has BOTH a legacy GRAPHENE dict and the package's
# own DJANGO_GRAPHEX dict. The codemod merges GRAPHENE's keys into DJANGO_GRAPHEX
# and drops the GRAPHENE assignment.
SETTINGS_FIXTURE = (
    "# settings.py\n"
    'GRAPHENE = {\n'
    '    "SCHEMA": "myapp.schema.schema",\n'
    '    "MIDDLEWARE": ["django_graphex.GraphQLDirectiveMiddleware"],\n'
    "}\n"
    "\n"
    'DJANGO_GRAPHEX = {\n'
    '    "DEFAULT_PAGE_SIZE": 20,\n'
    "}\n"
)

# Rename case: a project with ONLY a legacy GRAPHENE dict (no DJANGO_GRAPHEX yet).
# The codemod renames GRAPHENE -> DJANGO_GRAPHEX in place.
SETTINGS_RENAME_FIXTURE = (
    "# settings.py\n"
    'GRAPHENE = {\n'
    '    "SCHEMA": "myapp.schema.schema",\n'
    '    "MIDDLEWARE": ["django_graphex.GraphQLDirectiveMiddleware"],\n'
    "}\n"
)

SCHEMA_FIXTURE = (
    f"{_IMPORT_GRAPHENE}\n"
    "from django_graphex import DjangoListObjectField\n"
    "\n"
    "\n"
    f"class Query({_G}.ObjectType):\n"
    "    users = DjangoListObjectField(UserListType)\n"
    "\n"
    "\n"
    f"class CreateUser({_G}.Mutation):\n"
    "    class args:\n"
    f"        name = {_G}.Argument({_G}.String, required=True)\n"
    "\n"
    f"    ok = {_G}.Boolean()\n"
    "\n"
    "    def mutate(root, info, name):\n"
    "        return CreateUser(ok=True)\n"
    "\n"
    "\n"
    f"schema = {_G}.Schema(query=Query, mutation=CreateUser)\n"
)


# --------------------------------------------------------------------------- #
# 1. GRAPHENE -> DJANGO_GRAPHEX settings rewrite (the mechanical, safe          #
#    transform): rename when no target dict exists, MERGE when it does.         #
# --------------------------------------------------------------------------- #
def test_rewrite_merges_graphene_keys_into_existing_django_graphex():
    """When a ``DJANGO_GRAPHEX`` dict exists, ``GRAPHENE`` keys are merged into it."""
    new_source, changed = migrate_2_0.rewrite_source(SETTINGS_FIXTURE)

    assert changed is True
    # The unified namespace remains; the legacy GRAPHENE assignment is gone.
    assert "DJANGO_GRAPHEX = {" in new_source
    assert "GRAPHENE = {" not in new_source
    # The merged schema/middleware values are preserved verbatim.
    assert '"SCHEMA": "myapp.schema.schema"' in new_source
    assert '"MIDDLEWARE": ["django_graphex.GraphQLDirectiveMiddleware"]' in new_source


def test_rewrite_renames_graphene_when_no_django_graphex_dict():
    """With ONLY a legacy ``GRAPHENE`` dict, it is renamed to ``DJANGO_GRAPHEX``."""
    new_source, changed = migrate_2_0.rewrite_source(SETTINGS_RENAME_FIXTURE)

    assert changed is True
    assert "DJANGO_GRAPHEX = {" in new_source
    assert "GRAPHENE = {" not in new_source
    assert '"SCHEMA": "myapp.schema.schema"' in new_source
    assert '"MIDDLEWARE": ["django_graphex.GraphQLDirectiveMiddleware"]' in new_source


def test_rewritten_settings_imports_cleanly_and_unifies_into_django_graphex():
    """The rewritten fixture is valid Python and exposes a single merged DJANGO_GRAPHEX."""
    new_source, _ = migrate_2_0.rewrite_source(SETTINGS_FIXTURE)

    # Parses (valid Python).
    tree = ast.parse(new_source)

    # Execute it in an isolated namespace — no graphene needed, it's plain dicts.
    namespace: dict[str, object] = {}
    exec(compile(tree, "<rewritten-settings>", "exec"), namespace)  # noqa: S102

    assert "GRAPHENE" not in namespace
    # The schema/middleware keys are merged into the SINGLE DJANGO_GRAPHEX dict,
    # alongside the package's own keys.
    assert namespace["DJANGO_GRAPHEX"] == {
        "DEFAULT_PAGE_SIZE": 20,
        "SCHEMA": "myapp.schema.schema",
        "MIDDLEWARE": ["django_graphex.GraphQLDirectiveMiddleware"],
    }


def test_rewrite_is_idempotent_and_noop_without_graphene_namespace():
    """A file with no ``GRAPHENE`` namespace is returned unchanged (changed=False)."""
    already_migrated = 'DJANGO_GRAPHEX = {"SCHEMA": "myapp.schema.schema"}\n'
    new_source, changed = migrate_2_0.rewrite_source(already_migrated)

    assert changed is False
    assert new_source == already_migrated


# --------------------------------------------------------------------------- #
# 2. REPORT-AND-FLAG graphene constructs v2.0 no longer accepts                 #
# --------------------------------------------------------------------------- #
def test_analyze_flags_graphene_argument_in_mutation_args():
    """A ``graphene.Argument(...)`` is flagged with native ``GraphQLArgument`` guidance."""
    findings = migrate_2_0.analyze_source(SCHEMA_FIXTURE, path="schema.py")

    arg_findings = [f for f in findings if f.kind == "graphene-argument"]
    assert arg_findings, "graphene.Argument(...) must be flagged"
    guidance = arg_findings[0].guidance
    assert "GraphQLArgument" in guidance
    # It must point at the breaking-change semantics (clean break / TypeError).
    assert "class args" in guidance or "Mutation" in guidance


def test_analyze_flags_graphene_objecttype_root():
    """``graphene.ObjectType`` roots are flagged with the native ``ObjectType`` guidance."""
    findings = migrate_2_0.analyze_source(SCHEMA_FIXTURE, path="schema.py")

    root_findings = [f for f in findings if f.kind == "graphene-objecttype"]
    assert root_findings, "graphene.ObjectType root must be flagged"
    assert "from django_graphex import ObjectType" in root_findings[0].guidance


def test_analyze_flags_graphene_schema_root():
    """``graphene.Schema(...)`` is flagged with the ``DjangoGraphQLSchema`` guidance."""
    findings = migrate_2_0.analyze_source(SCHEMA_FIXTURE, path="schema.py")

    schema_findings = [f for f in findings if f.kind == "graphene-schema"]
    assert schema_findings, "graphene.Schema(...) must be flagged"
    assert "DjangoGraphQLSchema" in schema_findings[0].guidance


def test_analyze_flags_graphene_field_descriptor():
    """A graphene field descriptor (``graphene.Boolean()`` / ``graphene.String()``)
    is flagged with the native ``field(...)`` guidance."""
    findings = migrate_2_0.analyze_source(SCHEMA_FIXTURE, path="schema.py")

    desc_findings = [f for f in findings if f.kind == "graphene-field-descriptor"]
    assert desc_findings, "graphene field descriptor must be flagged"
    assert "field(" in desc_findings[0].guidance


def test_analyze_reports_line_numbers():
    """Every finding carries a 1-based line number so the report is actionable."""
    findings = migrate_2_0.analyze_source(SCHEMA_FIXTURE, path="schema.py")
    assert findings, "the schema fixture has graphene usage to flag"
    for finding in findings:
        assert finding.line >= 1
        assert finding.path == "schema.py"


def test_analyze_clean_native_source_yields_no_findings():
    """A native (graphene-free) module produces zero findings."""
    native_source = (
        "from django_graphex import DjangoGraphQLSchema, ObjectType, field\n"
        "from django_graphex.fields import DjangoListObjectField\n"
        "from graphql import GraphQLBoolean\n"
        "\n"
        "\n"
        "class Query(ObjectType):\n"
        "    users = DjangoListObjectField(UserListType)\n"
        "    ok = field(GraphQLBoolean)\n"
        "\n"
        "\n"
        "schema = DjangoGraphQLSchema(query=Query)\n"
    )
    findings = migrate_2_0.analyze_source(native_source, path="native.py")
    assert findings == []


# --------------------------------------------------------------------------- #
# 3. report formatting + end-to-end run on the fixtures                         #
# --------------------------------------------------------------------------- #
def test_format_report_lists_all_construct_kinds():
    """The human report names each detected breaking construct."""
    findings = migrate_2_0.analyze_source(SCHEMA_FIXTURE, path="schema.py")
    report = migrate_2_0.format_report(findings)

    assert "graphene.Argument" in report
    assert "graphene.ObjectType" in report
    assert "graphene.Schema" in report
    # actionable native targets surface in the report
    assert "GraphQLArgument" in report
    assert "DjangoGraphQLSchema" in report


def test_codemod_module_does_not_import_graphene():
    """The codemod itself must never import graphene (it is uninstalled in v2.0)."""
    assert "graphene" not in sys.modules or sys.modules.get("graphene") is None
    # The module's source has no top-level graphene import.
    source = _CODEMOD_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "graphene"
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "graphene"


@pytest.fixture
def project_tree(tmp_path: Path) -> Path:
    (tmp_path / "settings.py").write_text(SETTINGS_FIXTURE, encoding="utf-8")
    (tmp_path / "schema.py").write_text(SCHEMA_FIXTURE, encoding="utf-8")
    return tmp_path


def test_run_apply_rewrites_settings_file_in_place(project_tree: Path):
    """``run(paths, apply=True)`` rewrites the GRAPHENE namespace on disk and
    flags the graphene constructs in schema.py (which it does NOT rewrite)."""
    result = migrate_2_0.run([str(project_tree)], apply=True)

    rewritten = (project_tree / "settings.py").read_text(encoding="utf-8")
    assert "DJANGO_GRAPHEX = {" in rewritten
    assert "GRAPHENE = {" not in rewritten

    # schema.py is report-only; it is NOT mutated by --apply.
    schema_after = (project_tree / "schema.py").read_text(encoding="utf-8")
    assert schema_after == SCHEMA_FIXTURE

    # The run reports the rewritten file and the flagged constructs.
    assert any("settings.py" in p for p in result.rewritten_files)
    flagged_kinds = {f.kind for f in result.findings}
    assert "graphene-argument" in flagged_kinds
    assert "graphene-objecttype" in flagged_kinds
    assert "graphene-schema" in flagged_kinds


def test_run_report_only_does_not_mutate_files(project_tree: Path):
    """Without ``apply=True`` the codemod is read-only (report + would-change)."""
    settings_before = (project_tree / "settings.py").read_text(encoding="utf-8")

    result = migrate_2_0.run([str(project_tree)], apply=False)

    assert (project_tree / "settings.py").read_text(encoding="utf-8") == settings_before
    # It still REPORTS that settings.py would change.
    assert any("settings.py" in p for p in result.would_rewrite_files)
    assert result.rewritten_files == []
