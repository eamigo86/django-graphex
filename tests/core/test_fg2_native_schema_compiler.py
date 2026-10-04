"""Behavioral contracts for native schema field and resolver selection."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from graphql import GraphQLArgument, GraphQLField, GraphQLString


@pytest.fixture(autouse=True)
def _isolate_output_registry() -> Iterator[None]:
    """Restore shared output registrations after each native type fixture.

    Yields:
        Control while one test owns temporary model registrations.
    """
    from django_graphex.core.base import (
        _gdx_output_registry,
        get_shared_output_registry,
    )

    shared = get_shared_output_registry()
    entries = list(_gdx_output_registry)
    compiled = dict(shared._compiled)
    try:
        yield
    finally:
        _gdx_output_registry[:] = entries
        shared._compiled.clear()
        shared._compiled.update(compiled)


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        (("library.custom",), frozenset({"library.custom"})),
        ((), frozenset()),
    ],
)
def test_model_field_explicit_permissions_override_composite_default(
    override: tuple[str, ...], expected: frozenset[str]
) -> None:
    """Keep explicit permissions on a compiled field without dropping metadata.

    Args:
        override: Permissions chosen by the field declaration.
        expected: The immutable label GraphQL must retain.
    """
    from django_graphex.core.schema_compiler import _label_model_field
    from tests.models import Category

    field = GraphQLField(GraphQLString, extensions={"audit": "kept"})
    descriptor = SimpleNamespace(model=Category, required_perms=override)
    labeled = _label_model_field(field, descriptor, "retrieve")
    assert labeled is field
    assert labeled.extensions == {
        "audit": "kept",
        "gdx_required_perms": expected,
    }


def test_model_field_without_override_uses_composite_permissions() -> None:
    """Use the model/action permission policy when no override is declared.

    The field label must match the policy used by the schema pruner.
    """
    from django_graphex.core.perm_labels import required_perms_for
    from django_graphex.core.schema_compiler import _label_model_field
    from tests.models import Category

    field = GraphQLField(GraphQLString)
    descriptor = SimpleNamespace(model=Category, required_perms=None)
    labeled = _label_model_field(field, descriptor, "list")
    assert labeled.extensions["gdx_required_perms"] == required_perms_for(
        Category, "list"
    )


def test_unbound_resolver_is_unwrapped_for_graphql_core() -> None:
    """Hand the underlying callable to GraphQL when a method is unbound.

    GraphQL passes root and execution context to the unbound function.
    """
    from django_graphex.core.schema_compiler import _get_unbound_function

    def resolve(root: object, info: object) -> str:
        """Return a stable resolved value.

        Args:
            root: The parent value.
            info: GraphQL execution context.

        Returns:
            A fixed field value.
        """
        return "ready"

    unbound = SimpleNamespace(__self__=None, __func__=resolve)
    assert _get_unbound_function(unbound) is resolve
    assert _get_unbound_function(unbound)(None, None) == "ready"


def test_bound_resolver_keeps_its_owner() -> None:
    """Do not strip the owner from an already bound resolver method.

    The bound method remains callable with only the execution context.
    """
    from django_graphex.core.schema_compiler import _get_unbound_function

    class _Resolver:
        def resolve(self, info: object) -> str:
            """Return the owner's field value.

            Args:
                info: GraphQL execution context.

            Returns:
                A fixed field value.
            """
            return "bound"

    bound = _Resolver().resolve
    assert _get_unbound_function(bound) is bound
    assert _get_unbound_function(bound)(None) == "bound"


def test_plain_django_output_field_preserves_argument_and_resolver() -> None:
    """Compile a model output target with its argument and parent resolver.

    The field keeps its compiled node identity, argument, and description.
    """
    from django_graphex.core.schema_compiler import _build_django_output_field
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _CategoryNode(DjangoObjectType):
        class Meta:
            model = Category

    class _Root:
        @staticmethod
        def resolve_category(root: object, info: object, *, slug: str) -> str:
            """Resolve the requested category key.

            Args:
                root: The parent value.
                info: GraphQL execution context.
                slug: The requested category key.

            Returns:
                The requested key.
            """
            return slug

    class _Field:
        type = _CategoryNode
        args = {"slug": GraphQLArgument(GraphQLString)}
        description = "A selected category"

        @staticmethod
        def wrap_resolve(parent: Any) -> Any:
            """Use the root's resolver for this field.

            Args:
                parent: The root resolver callable.

            Returns:
                The same resolver callable.
            """
            return parent

    compiled = _build_django_output_field(
        _Field(), source_cls=_Root, field_name="category"
    )
    assert compiled.type is _CategoryNode._meta.graphql_output_type
    assert compiled.args["slug"].type is GraphQLString
    assert compiled.description == "A selected category"
    assert compiled.resolve(None, None, slug="books") == "books"


def test_forked_nonmutation_field_keeps_existing_type() -> None:
    """Do not refork an ordinary field that lacks mutation provenance.

    Forked registries only replace fields with a mutation source witness.
    """
    from django_graphex.core.schema_compiler import _maybe_refork_mutation_field
    from django_graphex.registry import Registry
    from tests._schema_isolation import isolated_pair

    field = GraphQLField(GraphQLString, extensions={"source": "ordinary"})
    assert _maybe_refork_mutation_field(field, isolated_pair(Registry())) is field
