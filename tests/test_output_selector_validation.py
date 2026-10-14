"""Output field selector configuration must fail closed before registration."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from graphql import GraphQLString

from django_graphex.core import CharField
from django_graphex.core.descriptors import field
from django_graphex.registry import Registry
from django_graphex.types import DjangoObjectType

from .models import Author, CustomPKProduct, Track2GfkComment


@pytest.mark.parametrize("option", ("only_fields", "exclude_fields"))
def test_unknown_output_selector_fails_before_registration(option: str) -> None:
    """Reject typo selectors without replacing the registered public model type.

    Args:
        option: Projection option containing the invalid field name.
    """
    reg = Registry()

    class Incumbent(DjangoObjectType):
        """A valid public type for the sensitive user model."""

        class Meta:
            """Publish a narrow view of the user model."""

            model = User
            registry = reg
            only_fields = ("id", "username")

    native_before = reg.output_registry().get_compiled(User)

    class InvalidConfig:
        """Configure an invalid selector without changing other options."""

        model = User
        registry = reg

    setattr(InvalidConfig, option, ("passwrod",))

    with pytest.raises(ImproperlyConfigured, match="passwrod"):

        class InvalidUserType(DjangoObjectType):
            """A typo must not replace the valid public type."""

            class Meta(InvalidConfig):
                """Inherit the invalid selector configuration."""

    assert reg.get_type_for_model(User) is Incumbent
    assert reg.output_registry().get_compiled(User) is native_before
    assert "password" not in Incumbent._meta.graphql_output_type.fields
    assert "password" not in native_before.fields


@pytest.mark.parametrize("option", ("only_fields", "exclude_fields"))
def test_bare_string_output_selector_is_rejected(option: str) -> None:
    """A scalar string is not a container of complete field names.

    Args:
        option: Projection option containing the bare string.
    """
    reg = Registry()

    class InvalidConfig:
        """Configure a bare string selector for the dynamic option."""

        model = User
        registry = reg

    setattr(InvalidConfig, option, "password")

    with pytest.raises(ImproperlyConfigured, match=option):

        class StringSelectorType(DjangoObjectType):
            """A bare string must never be read as field-name substrings."""

            class Meta(InvalidConfig):
                """Inherit the invalid selector configuration."""

    assert reg.get_type_for_model(User) is None


def test_valid_model_and_declared_selectors_remain_supported() -> None:
    """Keep model relations and declared custom fields valid selector names.

    Declared fields compile independently even when listed as exclusions.
    """
    reg = Registry()

    class AuthorType(DjangoObjectType):
        """Use a reverse relation and a declared custom field in projection."""

        display = CharField()
        explicit = field(GraphQLString, name="wireAlias")

        class Meta:
            """Publish a selected model field and declared fields."""

            model = Author
            registry = reg
            only_fields = (
                "id",
                "author_profile",
                "coauthored_posts",
                "display",
                "explicit",
                "wireAlias",
            )
            exclude_fields = ("bio", "display")

    assert reg.get_type_for_model(Author) is AuthorType
    assert "display" in AuthorType._meta.fields
    assert "explicit" in AuthorType._meta.fields
    assert "display" in AuthorType._meta.graphql_output_type.fields
    assert "explicit" in AuthorType._meta.graphql_output_type.fields


def test_generic_foreign_key_and_set_selectors_remain_supported() -> None:
    """Keep private model names and legacy set containers valid.

    A GenericForeignKey is private model metadata but selectable in output.
    """
    reg = Registry()

    class GfkType(DjangoObjectType):
        """Expose a selected GFK owner model."""

        class Meta:
            """Keep a private GFK selector accepted."""

            model = Track2GfkComment
            registry = reg
            only_fields = {"id", "body", "target"}

    assert reg.get_type_for_model(Track2GfkComment) is GfkType


def test_declared_custom_only_output_remains_valid() -> None:
    """Allow a custom-only output declaration without a selected model field.

    Model projection filters auto-derived fields, not declared descriptors.
    """
    reg = Registry()

    class CustomOnlyType(DjangoObjectType):
        """Expose only a declared read-only label."""

        label = CharField()

        class Meta:
            """Select the declared field without a model column."""

            model = Author
            registry = reg
            only_fields = ("label",)

    assert "label" in CustomOnlyType._meta.graphql_output_type.fields
    assert "bio" not in CustomOnlyType._meta.graphql_output_type.fields


def test_corrected_exclusion_hides_sensitive_user_field() -> None:
    """A valid complete selector must keep the password out of native SDL.

    This is the safe replacement for a misspelled or bare-string exclusion.
    """
    reg = Registry()

    class SafeUserType(DjangoObjectType):
        """Expose the user model without its password column."""

        class Meta:
            """Exclude a complete model field name."""

            model = User
            registry = reg
            exclude_fields = ("password",)

    assert "password" not in SafeUserType._meta.graphql_output_type.fields


def test_one_shot_selector_is_reused_for_projection() -> None:
    """Reuse valid one-shot names for the actual output projection.

    Exhausting an iterator during validation must not publish every field.
    """
    reg = Registry()

    class IteratorType(DjangoObjectType):
        """Publish only an iterator-selected model field."""

        class Meta:
            """Use the existing iterable selector form."""

            model = Author
            registry = reg
            only_fields = iter(("id", "name"))

    assert {"id", "name"} <= set(IteratorType._meta.graphql_output_type.fields)
    assert "bio" not in IteratorType._meta.graphql_output_type.fields


def test_custom_slug_key_and_empty_selector_are_valid() -> None:
    """Keep a nonstandard model primary key and empty exclusion valid.

    A slug key is an ordinary selectable Django model field.
    """
    reg = Registry()

    class SlugType(DjangoObjectType):
        """Publish a model with a nonstandard primary key."""

        class Meta:
            """Select the slug and keep the exclusion empty."""

            model = CustomPKProduct
            registry = reg
            only_fields = ("slug",)
            exclude_fields = []

    assert "slug" in SlugType._meta.graphql_output_type.fields


@pytest.mark.parametrize("selector", (42, ("id", 42)))
def test_non_name_selectors_fail_in_configuration(selector: object) -> None:
    """Non-iterables and non-string entries cannot select model fields.

    Args:
        selector: Invalid projection declaration to reject.
    """
    reg = Registry()

    class InvalidConfig:
        """Configure a malformed output projection."""

        model = Author
        registry = reg
        only_fields = selector

    with pytest.raises(ImproperlyConfigured, match="only_fields"):

        class InvalidType(DjangoObjectType):
            """Invalid model projection should fail class definition."""

            class Meta(InvalidConfig):
                """Use the malformed inherited projection."""

    assert reg.get_type_for_model(Author) is None
