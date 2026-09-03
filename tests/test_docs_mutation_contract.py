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
