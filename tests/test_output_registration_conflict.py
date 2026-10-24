"""Public model output registration must not silently change relation surfaces."""

from __future__ import annotations

from typing import Iterator

import pytest
from django.core.exceptions import ImproperlyConfigured
from graphql import graphql_sync, print_schema

from django_graphex.core import ObjectType
from django_graphex.core.base import _gdx_output_registry, get_shared_output_registry
from django_graphex.fields import DjangoListObjectField, DjangoObjectField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import (
    DjangoInputObjectType,
    DjangoListObjectType,
    DjangoObjectType,
)
from tests._schema_isolation import isolated_default_pair, isolated_pair
from tests.models import Author, Post, Track2Account, Track2AccountProxy


@pytest.fixture(autouse=True)
def isolate_output_registries() -> Iterator[None]:
    """Restore global native entries after temporary public declarations.

    Yields:
        Control once, with the shared output registries restored afterward.
    """
    shared = get_shared_output_registry()
    entries = list(_gdx_output_registry)
    compiled = dict(shared._compiled)
    try:
        yield
    finally:
        _gdx_output_registry[:] = entries
        shared._compiled.clear()
        shared._compiled.update(compiled)


@pytest.mark.django_db
def test_second_public_author_type_fails_without_shadowing_nested_author() -> None:
    """Reject a second public type before its fields reach relation lookups.

    A distinct AdminAuthor exposing the private bio field must not replace
    PublicAuthor as the canonical target of Post.author in this registry.

    Raises:
        ImproperlyConfigured: Asserted for the conflicting public declaration.
    """
    local_registry = Registry()

    class PublicAuthor(DjangoObjectType):
        class Meta:
            model = Author
            registry = local_registry
            only_fields = ("id", "name")

    class PostType(DjangoObjectType):
        class Meta:
            model = Post
            registry = local_registry
            only_fields = ("id", "title", "author")

    original = local_registry.output_registry().get_compiled(Author)
    original_entries = len(_gdx_output_registry)

    with pytest.raises(ImproperlyConfigured, match="Author.*PublicAuthor.*AdminAuthor"):

        class AdminAuthor(DjangoObjectType):
            class Meta:
                model = Author
                registry = local_registry
                only_fields = ("id", "name", "bio")

    assert local_registry.get_type_for_model(Author) is PublicAuthor
    assert local_registry.output_registry().get_compiled(Author) is original
    assert len(_gdx_output_registry) == original_entries

    class Query(ObjectType):
        post = DjangoObjectField(PostType)

    schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(local_registry))
    sdl = print_schema(schema.graphql_schema)
    assert "author: PublicAuthor" in sdl
    assert "bio:" not in sdl

    author = Author.objects.create(name="Public", bio="hidden")
    post = Post.objects.create(title="Visible", author=author)
    result = graphql_sync(
        schema.graphql_schema, f"{{ post(id: {post.pk}) {{ author {{ name }} }} }}"
    )
    assert result.errors is None
    assert result.data == {"post": {"author": {"name": "Public"}}}


def test_identical_class_reregistration_is_idempotent() -> None:
    """Registering an existing class again preserves its output identity.

    Duplicate calls for one class are not a second public schema surface.
    """
    local_registry = Registry()

    class PublicAuthor(DjangoObjectType):
        class Meta:
            model = Author
            registry = local_registry
            only_fields = ("id", "name")

    compiled = local_registry.output_registry().get_compiled(Author)
    local_registry.register(PublicAuthor)
    assert local_registry.get_type_for_model(Author) is PublicAuthor
    assert local_registry.output_registry().get_compiled(Author) is compiled


def test_distinct_registries_may_publish_distinct_author_views() -> None:
    """A public/admin split is legal when each schema owns its registry.

    The one-output rule is scoped to the exact Registry instance.
    """
    public_registry = Registry()
    admin_registry = Registry()

    class PublicAuthor(DjangoObjectType):
        class Meta:
            model = Author
            registry = public_registry
            only_fields = ("id", "name")

    class AdminAuthor(DjangoObjectType):
        class Meta:
            model = Author
            registry = admin_registry
            only_fields = ("id", "name", "bio")

    assert public_registry.get_type_for_model(Author) is PublicAuthor
    assert admin_registry.get_type_for_model(Author) is AdminAuthor
    assert public_registry.output_registry().get_compiled(Author) is not (
        admin_registry.output_registry().get_compiled(Author)
    )


def test_non_registering_internal_view_does_not_replace_public_type() -> None:
    """An explicitly non-registering type leaves the canonical output intact.

    Permission-specific internal forks are not public registration attempts.
    """
    local_registry = Registry()

    class PublicAuthor(DjangoObjectType):
        class Meta:
            model = Author
            registry = local_registry
            only_fields = ("id", "name")

    canonical = local_registry.output_registry().get_compiled(Author)

    class InternalAuthor(DjangoObjectType):
        class Meta:
            model = Author
            registry = local_registry
            skip_registry = True
            only_fields = ("id", "name", "bio")

    assert InternalAuthor is not PublicAuthor
    assert local_registry.get_type_for_model(Author) is PublicAuthor
    assert local_registry.output_registry().get_compiled(Author) is canonical


@pytest.mark.django_db
def test_registered_node_remains_list_and_filter_target() -> None:
    """A list and its filter retain the registered node without minting another.

    The container's result row and filter input stay bound to one public node.
    """
    local_registry = Registry()

    class PublicAuthor(DjangoObjectType):
        class Meta:
            model = Author
            registry = local_registry
            only_fields = ("id", "name")

    class AuthorList(DjangoListObjectType):
        class Meta:
            model = Author
            registry = local_registry
            filter_fields = {"name": ("exact",)}

    assert AuthorList._meta.baseType is PublicAuthor
    assert local_registry.get_type_for_model(Author) is PublicAuthor

    class Query(ObjectType):
        authors = DjangoListObjectField(AuthorList)

    schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(local_registry))
    Author.objects.create(name="Visible")
    Author.objects.create(name="Other")
    result = graphql_sync(
        schema.graphql_schema,
        '{ authors(filter: { name: { exact: "Visible" } }) { results { name } } }',
    )
    assert result.errors is None
    assert result.data == {"authors": {"results": [{"name": "Visible"}]}}


def test_input_registration_and_proxy_model_keys_remain_distinct() -> None:
    """The output guard leaves input action slots and exact proxy keys alone.

    A proxy model is a different model class, while input slots use action keys.
    """
    local_registry = Registry()

    class Account(DjangoObjectType):
        class Meta:
            model = Track2Account
            registry = local_registry

    class AccountProxy(DjangoObjectType):
        class Meta:
            model = Track2AccountProxy
            registry = local_registry

    class AccountCreateInput(DjangoInputObjectType):
        class Meta:
            model = Track2Account
            registry = local_registry
            input_for = "create"

    assert local_registry.get_type_for_model(Track2Account) is Account
    assert local_registry.get_type_for_model(Track2AccountProxy) is AccountProxy
    assert (
        local_registry.get_type_for_model(Track2Account, for_input="create")
        is AccountCreateInput
    )


def test_model_mutation_reuses_registered_public_output() -> None:
    """A generated model mutation does not replace its public result node.

    DjangoModelType follows its established output-node reuse contract.
    """
    from django_graphex.registry import get_global_registry
    from django_graphex.types import DjangoModelType

    with isolated_default_pair():

        class PublicAuthor(DjangoObjectType):
            class Meta:
                model = Author
                only_fields = ("id", "name")

        canonical = get_global_registry().output_registry().get_compiled(Author)

        class AuthorMutation(DjangoModelType):
            class Meta:
                model = Author

        assert AuthorMutation._meta.model is Author
        assert get_global_registry().get_type_for_model(Author) is PublicAuthor
        assert get_global_registry().output_registry().get_compiled(Author) is canonical


@pytest.mark.django_db(transaction=True)
def test_public_and_admin_user_schemas_bind_post_user_independently() -> None:
    """Separate schemas resolve Post.user to their own registered user view.

    Both schemas execute on one disposable row, but their SDL differs.
    """
    from django.contrib.auth import get_user_model
    from django.db import connection, models
    from django.test.utils import isolate_apps

    User = get_user_model()

    with isolate_apps("tests"):

        class PostWithUser(models.Model):
            user = models.ForeignKey(User, on_delete=models.CASCADE)

            class Meta:
                app_label = "tests"
                db_table = "tests_a4_post_with_user"

        public_registry = Registry()
        admin_registry = Registry()

        class PublicUser(DjangoObjectType):
            class Meta:
                model = User
                registry = public_registry
                only_fields = ("id", "username")

        class PublicPost(DjangoObjectType):
            class Meta:
                model = PostWithUser
                registry = public_registry
                only_fields = ("id", "user")

        class AdminUser(DjangoObjectType):
            class Meta:
                model = User
                registry = admin_registry
                only_fields = ("id", "username", "is_staff")

        class AdminPost(DjangoObjectType):
            class Meta:
                model = PostWithUser
                registry = admin_registry
                only_fields = ("id", "user")

        class PublicQuery(ObjectType):
            post = DjangoObjectField(PublicPost)

        class AdminQuery(ObjectType):
            post = DjangoObjectField(AdminPost)

        public_schema = DjangoGraphQLSchema(
            query=PublicQuery, registries=isolated_pair(public_registry)
        )
        admin_schema = DjangoGraphQLSchema(
            query=AdminQuery, registries=isolated_pair(admin_registry)
        )
        public_sdl = print_schema(public_schema.graphql_schema)
        admin_sdl = print_schema(admin_schema.graphql_schema)
        assert "user: PublicUser" in public_sdl
        assert "user: AdminUser" in admin_sdl
        assert "isStaff:" not in public_sdl
        assert "isStaff:" in admin_sdl

        with connection.schema_editor() as editor:
            editor.create_model(PostWithUser)
        try:
            user = User.objects.create_user(username="reader", is_staff=True)
            post = PostWithUser.objects.create(user=user)
            public_result = graphql_sync(
                public_schema.graphql_schema,
                f"{{ post(id: {post.pk}) {{ user {{ username }} }} }}",
            )
            admin_result = graphql_sync(
                admin_schema.graphql_schema,
                f"{{ post(id: {post.pk}) {{ user {{ username isStaff }} }} }}",
            )
            assert public_result.errors is None
            assert admin_result.errors is None
            assert public_result.data == {"post": {"user": {"username": "reader"}}}
            assert admin_result.data == {
                "post": {"user": {"username": "reader", "isStaff": True}}
            }
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(PostWithUser)


def test_user_type_replaces_mutation_generated_placeholder() -> None:
    """A user type declared after a mutation takes over the model slot.

    The mutation auto-registers a placeholder output; the payload must then
    resolve to the user type, so no hidden column leaks through the placeholder.
    """
    from django_graphex.mutation import DjangoModelMutation

    local_registry = Registry()

    class CreateAuthor(DjangoModelMutation):
        class Meta:
            model = Author
            registry = local_registry
            model_operations = ("create",)

    placeholder = local_registry.get_type_for_model(Author)
    assert placeholder is not None

    class AuthorType(DjangoObjectType):
        class Meta:
            model = Author
            registry = local_registry
            only_fields = ("id", "name")

    assert local_registry.get_type_for_model(Author) is AuthorType
    assert all(e.cls is not placeholder for e in _gdx_output_registry)

    class Query(ObjectType):
        author = DjangoObjectField(AuthorType)

    class Mutation(ObjectType):
        create_author = CreateAuthor.CreateField()

    schema = DjangoGraphQLSchema(
        query=Query, mutation=Mutation, registries=isolated_pair(local_registry)
    )
    sdl = print_schema(schema.graphql_schema)
    assert "author: AuthorType" in sdl
    assert "AuthorGenericType" not in sdl
    assert "bio" not in sdl.split("input AuthorCreateGenericType")[0]


def test_redefining_the_same_declaration_replaces_the_stale_type() -> None:
    """Re-executing a declaration (reload, re-import) is not a second type.

    The stale class is replaced and its compile entry dropped, so entries do not
    accumulate across reloads.
    """
    local_registry = Registry()

    def declare() -> type:
        class ReloadedAuthor(DjangoObjectType):
            class Meta:
                model = Author
                registry = local_registry
                only_fields = ("id", "name")

        return ReloadedAuthor

    first = declare()
    count = len(_gdx_output_registry)
    second = declare()
    assert second is not first
    assert local_registry.get_type_for_model(Author) is second
    assert len(_gdx_output_registry) == count
    assert all(e.cls is not first for e in _gdx_output_registry)


def test_subclass_with_own_model_is_still_rejected_with_a_remedy() -> None:
    """A subclass is a distinct public type, so it keeps being rejected.

    The message names the supported escapes: skip_registry or a new Registry.

    Raises:
        ImproperlyConfigured: Asserted for the conflicting subclass.
    """
    local_registry = Registry()

    class BaseAuthor(DjangoObjectType):
        class Meta:
            model = Author
            registry = local_registry
            only_fields = ("id", "name")

    with pytest.raises(ImproperlyConfigured, match="skip_registry = True"):

        class WiderAuthor(BaseAuthor):
            class Meta:
                model = Author
                registry = local_registry

    assert local_registry.get_type_for_model(Author) is BaseAuthor


def test_redefining_a_model_free_input_keeps_one_registry_entry() -> None:
    """A re-executed InputType declaration replaces its stale registry entry.

    Otherwise the next input compile would report a duplicate GraphQL name.
    """
    from django_graphex.core import InputType
    from django_graphex.core.base import _gdx_input_registry

    before = list(_gdx_input_registry)

    def declare() -> type:
        class ReloadedSearch(InputType):
            query: str

        return ReloadedSearch

    try:
        first = declare()
        second = declare()
        assert first not in _gdx_input_registry
        assert _gdx_input_registry.count(second) == 1
    finally:
        _gdx_input_registry[:] = before
