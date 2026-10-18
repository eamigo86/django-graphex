"""A forked schema build must not govern another thread's output declarations."""

from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest
from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.core.base import _forking_build, _gdx_output_registry, is_forking
from django_graphex.fields import DjangoListObjectField, DjangoObjectField
from django_graphex.registry import Registry, get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from tests._schema_isolation import isolated_default_pair, isolated_pair
from tests.models import Author, BasicModel, Category


@pytest.fixture(autouse=True)
def _isolated_global_pair() -> Iterator[None]:
    """Restore the default schema-pair singleton after each temporary registry."""
    import django_graphex.core.base as base

    previous_pair = base._default_schema_registries
    base._default_schema_registries = None
    try:
        with isolated_default_pair():
            yield
    finally:
        base._default_schema_registries = previous_pair


@pytest.mark.parametrize("local_b_pair", [False, True])
def test_concurrent_fork_preserves_sibling_output_projections(
    monkeypatch: pytest.MonkeyPatch, local_b_pair: bool
) -> None:
    """Register projected node/list types while another public fork is active.

    The two events force B's real class definitions between A's entry into
    DjangoGraphQLSchema's fork context and its exit. B's subsequent public
    schema must retain both only/exclude selectors on actual GraphQL types.

    Args:
        monkeypatch: Replaces the compiler hook to pause A's schema build.
        local_b_pair: Whether B's projected types use a separate registry pair.
    """
    import django_graphex.core.registry_compiler as compiler

    fork_entered = threading.Event()
    declarations_finished = threading.Event()
    release_fork = threading.Event()
    errors: list[BaseException] = []
    declarations: dict[str, object] = {}

    class IdleQuery(ObjectType):
        status = field(GraphQLString)

    a_registry = Registry()
    b_registry = Registry() if local_b_pair else get_global_registry()
    real_compile = compiler.compile_outputs_into

    def pause_inside_fork(registries: object) -> object:
        if threading.current_thread() is builder:

            class ForkOwnedNode(DjangoObjectType):
                class Meta:
                    name = "MT1ForkOwnedNode"
                    model = BasicModel
                    registry = a_registry
                    only_fields = ("id",)

            class ForkOwnedList(DjangoListObjectType):
                class Meta:
                    name = "MT1ForkOwnedList"
                    model = BasicModel
                    registry = a_registry

            declarations.update(fork_node=ForkOwnedNode, fork_list=ForkOwnedList)
            fork_entered.set()
            if not release_fork.wait(timeout=5):
                raise AssertionError("owned fork thread was not released")
        return real_compile(registries)

    monkeypatch.setattr(compiler, "compile_outputs_into", pause_inside_fork)

    def build_a() -> None:
        try:
            DjangoGraphQLSchema(query=IdleQuery, registries=isolated_pair(a_registry))
        except BaseException as exc:
            errors.append(exc)

    def declare_b() -> None:
        try:
            if not fork_entered.wait(timeout=5):
                raise AssertionError("owned fork did not enter")

            declarations["marker_during_b"] = is_forking()

            class AuthorOnly(DjangoObjectType):
                class Meta:
                    name = "MT1AuthorOnly"
                    model = Author
                    registry = b_registry
                    only_fields = ("id", "name")

            class CategoryWithoutTitle(DjangoObjectType):
                class Meta:
                    name = "MT1CategoryWithoutTitle"
                    model = Category
                    registry = b_registry
                    exclude_fields = ("title",)

            class AuthorList(DjangoListObjectType):
                class Meta:
                    name = "MT1AuthorList"
                    model = Author
                    registry = b_registry

            declarations.update(
                author=AuthorOnly,
                category=CategoryWithoutTitle,
                authors=AuthorList,
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            declarations_finished.set()

    builder = threading.Thread(target=build_a, name="mt1-fork-builder")
    registrar = threading.Thread(target=declare_b, name="mt1-projected-registrar")
    try:
        builder.start()
        registrar.start()
        assert fork_entered.wait(timeout=5), "owned fork did not enter"
        assert declarations_finished.wait(timeout=5), "registration did not finish"
    finally:
        release_fork.set()
        builder.join(timeout=5)
        registrar.join(timeout=5)
    assert not builder.is_alive() and not registrar.is_alive()
    assert not errors, errors

    author_type = declarations["author"]
    category_type = declarations["category"]
    authors_type = declarations["authors"]

    class Query(ObjectType):
        author = DjangoObjectField(author_type)
        category = DjangoObjectField(category_type)
        authors = DjangoListObjectField(authors_type)

    schema = DjangoGraphQLSchema(
        query=Query,
        registries=isolated_pair(b_registry) if local_b_pair else None,
    )
    types = schema.graphql_schema.type_map
    assert set(types["MT1AuthorOnly"].fields) == {"id", "name"}
    assert set(types["MT1CategoryWithoutTitle"].fields) == {"id"}
    assert str(types["MT1AuthorList"].fields["results"].type) == "[MT1AuthorOnly]"
    assert all(
        any(entry.cls is declarations[name] for entry in _gdx_output_registry)
        for name in ("author", "category", "authors")
    )
    assert all(
        all(entry.cls is not declarations[name] for entry in _gdx_output_registry)
        for name in ("fork_node", "fork_list")
    )
    assert declarations["marker_during_b"] is False


def test_serial_projected_list_keeps_its_node_type() -> None:
    """Confirm the projected list retains its node type without overlap.

    This serial case separates ordinary schema construction from a fork race.
    """
    reg = get_global_registry()

    class SerialAuthor(DjangoObjectType):
        class Meta:
            name = "MT1SerialAuthor"
            model = Author
            registry = reg
            only_fields = ("id", "name")

    class SerialAuthors(DjangoListObjectType):
        class Meta:
            name = "MT1SerialAuthors"
            model = Author
            registry = reg

    class Query(ObjectType):
        authors = DjangoListObjectField(SerialAuthors)

    schema = DjangoGraphQLSchema(query=Query)
    types = schema.graphql_schema.type_map
    assert set(types["MT1SerialAuthor"].fields) == {"id", "name"}
    assert str(types["MT1SerialAuthors"].fields["results"].type) == (
        "[MT1SerialAuthor]"
    )


def test_fork_marker_is_nested_and_restored_after_error() -> None:
    """Restore the fork marker after nested same-thread scopes unwind.

    The inner failure must not leave either scope marked as active.

    Raises:
        RuntimeError: Raised intentionally inside the captured nested scope.
    """
    assert not is_forking()
    with pytest.raises(RuntimeError, match="owned failure"):
        with _forking_build():
            assert is_forking()
            with _forking_build():
                assert is_forking()
                raise RuntimeError("owned failure")
    assert not is_forking()
