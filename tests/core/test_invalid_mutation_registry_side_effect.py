"""Public registry behavior when a mutation declaration is rejected."""

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured

from django_graphex.mutation import DjangoModelMutation
from django_graphex.permissions import IsAuthenticated
from django_graphex.registry import Registry


def test_rejected_permission_host_does_not_register_user_output() -> None:
    """Reject the host without reserving its public model output slot.

    Scenario: rejected permission host does not register user output.
    """
    local_registry = Registry()

    with pytest.raises(ImproperlyConfigured, match="permission_classes"):

        class RejectedPermissionHost(DjangoModelMutation):
            permission_classes = (IsAuthenticated,)

            class Meta:
                model = User
                registry = local_registry

    assert local_registry.get_type_for_model(User) is None


def test_unknown_operation_precedes_permission_error_without_output() -> None:
    """Keep declaration-error precedence without reserving an output slot.

    Scenario: unknown operation precedes permission error without output.
    """
    local_registry = Registry()

    with pytest.raises(ImproperlyConfigured, match="unknown operation"):

        class RejectedOperationHost(DjangoModelMutation):
            permission_classes = (IsAuthenticated,)

            class Meta:
                model = User
                registry = local_registry
                model_operations = ("archive",)

    assert local_registry.get_type_for_model(User) is None


def test_rejected_permission_host_preserves_existing_output() -> None:
    """Leave an already registered public output unchanged after rejection.

    Scenario: rejected permission host preserves existing output.
    """
    from django_graphex.types import DjangoObjectType

    local_registry = Registry()

    class ExistingUserOutput(DjangoObjectType):
        class Meta:
            model = User
            registry = local_registry

    with pytest.raises(ImproperlyConfigured, match="permission_classes"):

        class RejectedExistingOutputHost(DjangoModelMutation):
            permission_classes = (IsAuthenticated,)

            class Meta:
                model = User
                registry = local_registry

    assert local_registry.get_type_for_model(User) is ExistingUserOutput


def test_valid_mutation_still_uses_one_public_output() -> None:
    """Keep the valid host's output and three operation builders available.

    Scenario: valid mutation still uses one public output.
    """
    local_registry = Registry()

    class ValidUserHost(DjangoModelMutation):
        class Meta:
            model = User
            registry = local_registry

    output = local_registry.get_type_for_model(User)
    assert output is ValidUserHost._meta.output_type
    assert output.__name__ == "GenericType"
    assert ValidUserHost.CreateField() is not None
    assert ValidUserHost.UpdateField() is not None
    assert ValidUserHost.DeleteField() is not None
