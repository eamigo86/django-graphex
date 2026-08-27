# -*- coding: utf-8 -*-
"""An "editable=False" relation must stay OUT of the mutation input.

"construct_fields" and "_resolve_native_choices_input_fields" both honour
"field.editable", so a non-editable SCALAR was already excluded from create /
update input. "_resolve_native_relation_input_fields" had no such guard, so a
server-managed foreign key or many-to-many ("created_by", "tenant", anything a
custom "save()" owns) advertised itself as writable and then silently dropped
whatever the client sent.

The guard applies to the CONCRETE forward branches only: Django sets
"editable = False" on every "ForeignObjectRel", so testing it on the reverse
branches would delete the reverse-relation injection wholesale.
"""

from __future__ import annotations

from graphql import print_type

from django_graphex.registry import Registry
from django_graphex.types import DjangoInputObjectType

from .models import NonEditableThing, Post

R = Registry()


class _ThingCreate(DjangoInputObjectType):
    """Create input over the model with server-managed relations."""

    class Meta:
        """Bind the input to "NonEditableThing" for create."""

        model = NonEditableThing
        registry = R
        input_for = "create"


class _ThingUpdate(DjangoInputObjectType):
    """Update input over the model with server-managed relations."""

    class Meta:
        """Bind the input to "NonEditableThing" for update."""

        model = NonEditableThing
        registry = R
        input_for = "update"


class _PostCreate(DjangoInputObjectType):
    """Create input over a model whose relations are all editable.

    The control that proves the guard only removes NON-editable relations.
    """

    class Meta:
        """Bind the input to "Post" for create."""

        model = Post
        registry = R
        input_for = "create"


def test_non_editable_forward_fk_is_absent_from_create_input() -> None:
    """A server-managed foreign key is not offered for write.

    This test breaks if the relation walk stops honouring "editable".
    """
    sdl = print_type(_ThingCreate._meta.graphql_input_type)

    assert "owner" not in sdl, sdl


def test_non_editable_fk_is_absent_from_update_input() -> None:
    """The same foreign key stays out of the update input too.

    Create and update share the relation walk, so both must stay clean.
    """
    sdl = print_type(_ThingUpdate._meta.graphql_input_type)

    assert "owner" not in sdl, sdl


def test_non_editable_m2m_is_no_longer_an_id_relation() -> None:
    """A server-managed many-to-many is no longer rendered as an "ID" list.

    The relation spec is what turned the raw pk list into "[ID!]"; dropping it
    is this module's half of the fix. The two tests below assert the stronger
    property the guard now delivers: the field is gone from the input entirely.
    """
    for sdl in (
        print_type(_ThingCreate._meta.graphql_input_type),
        print_type(_ThingUpdate._meta.graphql_input_type),
    ):
        assert "tags: [ID!]" not in sdl, sdl


def test_non_editable_m2m_is_absent_from_create_input() -> None:
    """A server-managed many-to-many is not offered for write.

    This test breaks if the concrete-field guard stops covering
    "ManyToManyField", which puts the raw pk list back into the create input.
    """
    sdl = print_type(_ThingCreate._meta.graphql_input_type)

    assert "tags" not in sdl, sdl


def test_non_editable_m2m_is_absent_from_update_input() -> None:
    """A server-managed many-to-many is not offered for write on update.

    Create and update share the relation walk, so both must stay clean.
    """
    sdl = print_type(_ThingUpdate._meta.graphql_input_type)

    assert "tags" not in sdl, sdl


def test_the_editable_scalar_still_survives() -> None:
    """The guard removes only the non-editable fields.

    "label" is editable and must stay; "auditNote" is the non-editable SCALAR
    control that the pydantic path already excluded.
    """
    sdl = print_type(_ThingCreate._meta.graphql_input_type)

    assert "label" in sdl, sdl
    assert "auditNote" not in sdl, sdl


def test_editable_relations_are_untouched() -> None:
    """A model with ordinary relations keeps its full relation input surface.

    Forward foreign keys, many-to-many fields AND the injected reverse
    relations all stay: "editable" is "False" on every reverse relation object,
    so a blanket guard would have wiped the reverse injections out.
    """
    sdl = print_type(_PostCreate._meta.graphql_input_type)

    assert "author" in sdl, sdl
    assert "tags" in sdl, sdl
    assert "comments" in sdl, sdl
