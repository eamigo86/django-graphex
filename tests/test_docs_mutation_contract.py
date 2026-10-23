"""Executable contracts for the mutation guide and API reference."""

from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured

from django_graphex.mutation import DjangoModelMutation
from django_graphex.permissions import IsAuthenticated

ROOT = Path(__file__).resolve().parents[1]


def test_django_model_mutation_rejects_permission_classes() -> None:
    """Verify the documented permission option fails during class creation.

    This keeps the guide aligned with the runtime contract.
    """
    with pytest.raises(ImproperlyConfigured, match="permission_classes"):

        class InvalidMutation(DjangoModelMutation):
            permission_classes = (IsAuthenticated,)

            class Meta:
                model = User


def test_docs_describe_only_the_operations_the_host_generates() -> None:
    """Verify the guide names only create, update, and delete operations.

    DjangoModelMutation never generates a read operation.
    """
    usage = (ROOT / "docs/usage/mutations.md").read_text(encoding="utf-8")
    assert "Create, Read, Update" not in usage
    assert "Create/Read/Update/Delete" not in usage
    assert "create, update, and delete" in usage.lower()


def test_docs_say_forbidden_permission_classes_fail_loudly() -> None:
    """Verify the filtering guide describes the rejected option accurately.

    The forbidden option must never be documented as a silent no-op.
    """
    filtering = (ROOT / "docs/usage/filtering.md").read_text(encoding="utf-8")
    assert "declaring\n    `permission_classes` on one has no effect" not in filtering
    assert "ImproperlyConfigured" in filtering


def test_guide_documents_string_literal_enum_client_migration() -> None:
    """Keep the new wire enum contract distinct from unsupported fallbacks."""
    usage = (ROOT / "docs/usage/mutations.md").read_text(encoding="utf-8")
    upgrade = (ROOT / "docs/UPGRADE-4.0.md").read_text(encoding="utf-8")
    for text in (usage, upgrade):
        assert "ArticleInputStatusEnum" in text
        assert 'status: "draft"' in text
        assert "status: DRAFT" in text
        assert '"status": "DRAFT"' in text
        assert "raw string" in text or "original string" in text
    assert "Numeric or mixed" in usage
    assert "automatically validated as Pydantic" in usage


def test_guide_documents_typed_integer_map_json_migration() -> None:
    """Keep the strict typed-map wire change distinct from bare JSON."""
    usage = (ROOT / "docs/usage/mutations.md").read_text(encoding="utf-8")
    upgrade = (ROOT / "docs/UPGRADE-4.0.md").read_text(encoding="utf-8")
    for text in (usage, upgrade):
        assert "dict[str, int]" in text
        assert "typing.Dict[str, int]" in text
        assert "JSON" in text
        assert '"mapping": {"count": 3}' in text
        assert "plain integer" in text
        assert "Bare `dict`" in text or "bare `dict`" in text


def test_guide_documents_typed_string_map_json_migration() -> None:
    """Keep exact string-valued maps distinct from unsupported forms."""
    paths = ("docs/usage/mutations.md", "docs/api/types.md", "docs/UPGRADE-4.0.md")
    for relative in paths:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "dict[str, str]" in text
        assert "typing.Dict[str, str]" in text
        assert "JSON" in text
        assert "string keys" in text and "string values" in text
        assert "without conversion" in text or "without implicit" in text
    for relative in ("docs/usage/mutations.md", "docs/api/types.md"):
        normalized = " ".join((ROOT / relative).read_text(encoding="utf-8").split())
        assert "dict[str, int]" in normalized
        assert "typing.Dict[str, int]" in normalized
        assert "dict[str, str]" in normalized
        assert "typing.Dict[str, str]" in normalized
        assert (
            "parameterized dictionaries other than these two exact integer-map spellings"
            not in normalized
        )
        assert (
            "other parameterized dictionaries remain on the warning/`String` fallback"
            not in normalized
        )
        assert "Other parameterized dictionaries remain unsupported" in normalized


def test_guide_documents_recursive_supported_input_lists() -> None:
    """Keep recursive list migration distinct from unsupported leaves."""
    paths = (
        "docs/usage/mutations.md",
        "docs/api/types.md",
        "docs/UPGRADE-4.0.md",
    )
    for relative in paths:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "list[list[int]]" in text
        assert "[[Int!]!]!" in text
        assert "unsupported" in text.lower()


def test_guide_documents_exact_integer_set_migration() -> None:
    """Distinguish the two approved integer-set forms from other sets."""
    paths = (
        "docs/usage/mutations.md",
        "docs/api/types.md",
        "docs/UPGRADE-4.0.md",
    )
    for relative in paths:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "set[int]" in text
        assert "[Int!]!" in text
        assert "typing.Set[int]" in text
        assert "singleton" in text
        assert "resolver" in text
    usage = (ROOT / "docs/usage/mutations.md").read_text(encoding="utf-8")
    assert '"numbers": [2, 1, 2]' in usage
    assert "iteration order is not" in usage
    assert "Exact `set[int]` and `typing.Set[int]` input fields" in usage
    assert "Other set leaves and sets" in usage


def test_guide_documents_exact_string_set_migration() -> None:
    """Document both string-set spellings and whole-string singleton input."""
    for relative in (
        "docs/usage/mutations.md",
        "docs/api/types.md",
        "docs/UPGRADE-4.0.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "set[str]" in text
        assert "typing.Set[str]" in text
        assert "[String!]!" in text
        assert "singleton" in text
        assert "resolver" in text
    usage = (ROOT / "docs/usage/mutations.md").read_text(encoding="utf-8")
    assert '"colors": ["red", "red", "blue"]' in usage
    assert '"colors": "ab"' in usage
    assert "never the characters" in usage


def test_guide_documents_exact_float_set_migration() -> None:
    """Document both spellings and field-local overflow rejection."""
    for relative in (
        "docs/usage/mutations.md",
        "docs/api/types.md",
        "docs/UPGRADE-4.0.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "set[float]" in text
        assert "typing.Set[float]" in text
        assert "[Float!]!" in text
        assert "singleton" in text
        assert "resolver" in text
        assert "overflowing numeric literals" in " ".join(text.split())
    usage = (ROOT / "docs/usage/mutations.md").read_text(encoding="utf-8")
    assert '"amounts": [1.5, 1.5, 2.0]' in usage
    assert '"amounts": 2' in usage
    assert "{2.0}" in usage
    assert "rejects booleans, strings and null items" in usage
    for relative in ("CHANGELOG.md", "docs/changelog.md"):
        assert "rejects overflowing numeric literals" in (ROOT / relative).read_text(
            encoding="utf-8"
        )


def test_guide_documents_exact_boolean_set_migration() -> None:
    """Document both boolean-set spellings and native validation."""
    for relative in (
        "docs/usage/mutations.md",
        "docs/api/types.md",
        "docs/UPGRADE-4.0.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "set[bool]" in text
        assert "typing.Set[bool]" in text
        assert "[Boolean!]!" in text
        assert "singleton" in text
        assert "resolver" in text
    usage = (ROOT / "docs/usage/mutations.md").read_text(encoding="utf-8")
    assert '"flags": [true, false, true]' in usage
    assert '"flags": false' in usage
    assert "{False}" in usage
    assert "rejects 0, 1, strings" in usage


def test_docs_qualify_fixed_json_object_default_metadata() -> None:
    """Distinguish printable JSON defaults from ineligible object keys."""
    paths = (
        "docs/usage/mutations.md",
        "docs/api/types.md",
        "docs/UPGRADE-4.0.md",
    )
    for relative in paths:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "fixed JSON default" in text
        assert "print_schema" in text
        assert "introspection" in text
        assert "GraphQL Name" in text
        assert "list-wrapped" in text.lower() or "list of json" in text.lower()
        assert 'Field(default_factory=lambda: {"views": 0})' in text
        assert "omitted input" in text.lower()


@pytest.mark.parametrize(
    "relative", ["docs/usage/mutations.md", "docs/api/mutations.md"]
)
def test_generic_mutation_examples_use_an_ordinary_model(relative: str) -> None:
    """Verify generic mutation examples use an ordinary domain model.

    Args:
        relative: Documentation path containing generic mutation examples.
    """
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert "class UserMutation(DjangoModelMutation)" not in text
    assert "class CustomerMutation(DjangoModelMutation)" in text
