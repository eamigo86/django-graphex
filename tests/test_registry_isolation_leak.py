"""Library-level regression: a local-registry type must not leak into globals.

A DjangoObjectType / DjangoListObjectType that declares a non-global
Meta.registry is schema-scoped: its compiled output node belongs to its own
schema pair (populated by compile_outputs_into at fork-build time), not to the
process-global shared output registry. The class-def compile historically
stamped the global shared registry set_compiled(model, ...) unconditionally
(only skipping during a forked build), so a local-registry class defined before
any build deposited its node into the global slot. A later default-pair schema
over the same related model then resolved a relation (e.g. Post.category) to
that leaked node and, transitively, to the leaked "<Model>ListType" container --
producing graphql-core's "Schema must contain uniquely named types but contains
multiple types named 'PostListType'" at assembly time.

These tests pin the invariant at the library level (no cross-module ordering
luck): declaring a local-registry type must leave
get_shared_output_registry().get_compiled(model) untouched.
"""

from __future__ import annotations

from django.test import TestCase

from django_graphex.core.base import get_shared_output_registry
from django_graphex.registry import Registry
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from .models import IsoLeakCategory, IsoLeakPost


class LocalRegistryDoesNotStampGlobalTest(TestCase):
    """Local-registry types must not claim the global shared compiled slot.

    Each test declares a type bound to a fresh local registry and asserts the
    process-global shared output registry stays untouched for that model.
    """

    def test_local_registry_object_type_does_not_stamp_global_shared_registry(
        self,
    ) -> None:
        """Defining a local-registry DjangoObjectType leaves the global slot empty.

        The global shared registry get_compiled(model) must stay None for a model
        whose only declared type carries a non-global Meta.registry.
        """
        shared = get_shared_output_registry()
        self.assertIsNone(
            shared.get_compiled(IsoLeakCategory),
            "Global shared registry must not hold a compiled type for a model "
            "before any local-registry class is defined for it.",
        )

        local = Registry()

        class _IsoLeakCategoryType(DjangoObjectType):
            """Category node bound to a LOCAL registry."""

            class Meta:
                """Bind to IsoLeakCategory under the local registry."""

                model = IsoLeakCategory
                registry = local

        # THE INVARIANT: the local-registry class must NOT have stamped the
        # process-global shared registry — that is the leak.
        self.assertIsNone(
            shared.get_compiled(IsoLeakCategory),
            "Local-registry DjangoObjectType leaked its compiled node into the "
            "GLOBAL shared output registry (types.py class-def set_compiled).",
        )
        # It MUST, however, be resolvable through its own local graphene registry.
        self.assertIsNotNone(
            local.get_type_for_model(IsoLeakCategory),
            "Local-registry class must still register in its own graphene "
            "Registry so its schema fork resolves it.",
        )

    def test_local_registry_list_type_does_not_stamp_global_shared_registry(
        self,
    ) -> None:
        """A local-registry DjangoListObjectType also leaves the global slot alone.

        A list CONTAINER never claims the model slot anyway (the node does), but
        the node it would resolve must not be a globally-leaked one either.
        """
        shared = get_shared_output_registry()
        local = Registry()

        class _IsoLeakPostType(DjangoObjectType):
            """Post node bound to a LOCAL registry."""

            class Meta:
                """Bind to IsoLeakPost under the local registry."""

                model = IsoLeakPost
                registry = local

        class _IsoLeakPostListType(DjangoListObjectType):
            """Post list container bound to a LOCAL registry."""

            class Meta:
                """Bind the list container to IsoLeakPost under the local registry."""

                model = IsoLeakPost
                registry = local

        self.assertIsNone(
            shared.get_compiled(IsoLeakPost),
            "Local-registry DjangoObjectType/DjangoListObjectType leaked its "
            "compiled node into the GLOBAL shared output registry.",
        )
