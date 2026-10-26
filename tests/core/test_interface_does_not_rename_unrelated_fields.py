"""Adding an interface must not change the wire name of non-interface fields."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.core.base import _gdx_output_registry, get_shared_output_registry
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoInterfaceType, DjangoObjectType
from tests._schema_isolation import isolated_pair
from tests.models import Author


@pytest.fixture(autouse=True)
def _isolate_global_registries() -> Iterator[None]:
    """Restore the process-global output registries after each test.

    Yields:
        None, once, with the global registries restored afterwards.
    """
    shared = get_shared_output_registry()
    entries_before = list(_gdx_output_registry)
    compiled_before = dict(shared._compiled)
    try:
        yield
    finally:
        _gdx_output_registry[:] = entries_before
        shared._compiled.clear()
        shared._compiled.update(compiled_before)


def _author_field_names(*, with_interface: bool) -> set[str]:
    """Build the same Author type with or without an interface.

    Args:
        with_interface: Whether the type implements an interface that declares
            only the "shared" field.

    Returns:
        The wire field names of the compiled Author type.
    """
    reg = Registry()
    implemented: tuple[type, ...] = ()
    if with_interface:

        class Named(DjangoInterfaceType):
            shared = field(GraphQLString, name="Shared_Name")

            class Meta:
                registry = reg

        implemented = (Named,)

    class AuthorType(DjangoObjectType):
        shared = field(GraphQLString, name="Shared_Name", resolver=lambda r, i: "s")
        other = field(GraphQLString, name="Other_Name", resolver=lambda r, i: "o")
        plain = field(GraphQLString, resolver=lambda r, i: "p")

        class Meta:
            model = Author
            registry = reg
            only_fields = ("name",)
            interfaces = implemented

    class Query(ObjectType):
        author = field(AuthorType)

    schema = DjangoGraphQLSchema(
        query=Query, registries=isolated_pair(reg)
    ).graphql_schema
    return set(schema.type_map["AuthorType"].fields)


def test_interface_does_not_change_non_interface_field_names() -> None:
    """Keep non-interface names identical; only the interface field is explicit.

    Scenario: the same type with and without an interface.
    """
    without = _author_field_names(with_interface=False)
    with_iface = _author_field_names(with_interface=True)
    assert {"other", "plain"} <= without
    assert {"other", "plain"} <= with_iface
    assert "Other_Name" not in with_iface
    assert "Shared_Name" in with_iface
    assert with_iface - {"Shared_Name"} == without - {"shared"}
