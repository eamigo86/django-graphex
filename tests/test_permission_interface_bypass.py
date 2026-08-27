# -*- coding: utf-8 -*-
"""A hand-mounted interface field must obey its IMPLEMENTORS' view permissions.

The interface arm of the relation-traversal bypass that
"tests/test_permission_relation_bypass.py" closed for relations and for typed
GFK unions. "implicit_perms_for_type" derives a field's permission label from
"extensions[gdx]._meta.model"; an ABSTRACT type has no model of its own, so it
returned None and the pruner treats an untagged field as PUBLIC.

A "GraphQLUnionType" was taught to answer with the union of its members' labels.
A "GraphQLInterfaceType" was not — so "field(SomeDjangoInterfaceType)" mounted by
hand still hands a caller its implementors' rows while a DIRECT field to the
very same implementor type is pruned away.

Invariants asserted here:

- A caller holding NO implementor view permission cannot select the interface
  field at all.
- A caller holding EVERY implementor's view permission keeps it.
- Missing ONE implementor's permission takes the whole field — the same
  deliberate over-prune the union arm documents, because the field can return
  any implementor.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.test import TestCase, override_settings
from graphql import GraphQLString, print_schema

from django_graphex.core import ObjectType, field
from django_graphex.core import permission_signature_cache as psc
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoInterfaceType, DjangoObjectType

from .models import Track2Book, Track2Magazine

_ON = {"PERMISSION_SCOPED_SCHEMA": True}

# Declared against an ISOLATED registry so these types never land in the global
# one (the Track2 models already carry global types of their own).
_iface_registry = Registry()


class _ProductInterface(DjangoInterfaceType):
    """Interface shared by the two implementor model types."""

    name = field(GraphQLString)

    class Meta:
        """Bind the interface to the isolated registry."""

        registry = _iface_registry
        name = "PermIfaceProduct"


class _BookType(DjangoObjectType):
    """Implementor type for "Track2Book"."""

    class Meta:
        """Bind the implementor to "Track2Book" in the isolated registry."""

        model = Track2Book
        registry = _iface_registry
        interfaces = (_ProductInterface,)
        name = "PermIfaceBook"


class _MagazineType(DjangoObjectType):
    """Implementor type for "Track2Magazine"."""

    class Meta:
        """Bind the implementor to "Track2Magazine" in the isolated registry."""

        model = Track2Magazine
        registry = _iface_registry
        interfaces = (_ProductInterface,)
        name = "PermIfaceMagazine"


class _InterfaceQuery(ObjectType):
    """Root pairing the interface field with a DIRECT field to one implementor.

    The direct "book" field is the CONTROL: it is untagged too, so the pruner
    gates it through the implementor's implicit label. If it disappears for a
    caller lacking "view_track2book" while "product" survives, the interface arm
    is the hole.
    """

    product = field(_ProductInterface)
    book = field(_BookType)


_iface_schema = DjangoGraphQLSchema(
    query=_InterfaceQuery,
    types=[_BookType, _MagazineType],
)


def _view_perm(model: type[Model]) -> Permission:
    """Return the Django "view" permission object for a model.

    Args:
        model: The model whose view permission is wanted.

    Returns:
        The persisted permission row.
    """
    return Permission.objects.get(
        content_type=ContentType.objects.get_for_model(model),
        codename=f"view_{model._meta.model_name}",
    )


@override_settings(DJANGO_GRAPHEX=_ON)
class InterfacePermissionBypassTest(TestCase):
    """An interface field must be gated by every implementor it can return.

    The control in each case is the direct "book" field: it is untagged too, so
    whatever the pruner does to it is what the interface field must match.
    """

    def setUp(self) -> None:
        """Clear the process-wide pruned-schema LRU.

        A pruned schema built for one caller's signature would otherwise be
        served to the next test's caller.
        """
        psc._CACHE.clear()

    def _user(self, name: str, *models: type[Model]) -> Any:
        """Create a user granted the view permission of each given model.

        Args:
            name: The username to create.
            *models: The models whose view permission the user receives.

        Returns:
            The persisted user.
        """
        user = User.objects.create_user(username=name, password="x")
        for model in models:
            user.user_permissions.add(_view_perm(model))
        return user

    def _sdl(self, user: Any) -> str:
        """Return the pruned SDL the given caller would be served.

        Args:
            user: The caller whose live permissions drive the pruning.

        Returns:
            The printed SDL of the pruned schema.
        """
        return print_schema(psc.pruned_schema_for(user, _iface_schema.graphql_schema))

    def test_interface_field_pruned_without_implementor_perms(self) -> None:
        """Ships broken if a caller holding NO implementor view permission can
        still select the interface field.

        The direct implementor field is the control: it is already pruned for
        this caller, so the interface carrying the same rows must go too.

        The implementor TYPE definitions stay in the SDL because the schema
        force-includes them through "types="; that exposes their shape, never a
        row, since no surviving field returns one.
        """
        ana = self._user("iface_ana")
        sdl = self._sdl(ana)

        self.assertNotIn("book:", sdl)
        self.assertNotIn("product:", sdl)

    def test_interface_field_kept_with_every_implementor_perm(self) -> None:
        """Ships broken if pruning removes more than the caller lacks — holding
        every implementor's view permission must keep the interface field.
        """
        eve = self._user("iface_eve", Track2Book, Track2Magazine)
        sdl = self._sdl(eve)

        self.assertIn("product: PermIfaceProduct", sdl)
        self.assertIn("interface PermIfaceProduct", sdl)

    def test_interface_field_pruned_when_one_implementor_perm_is_missing(self) -> None:
        """Ships broken if a caller missing ONE implementor's view permission
        keeps a field that can still hand them that implementor's rows.

        Same deliberate over-prune as the union arm: the label is the UNION of
        the implementors' permissions, so it is an AND.
        """
        bob = self._user("iface_bob", Track2Book)
        sdl = self._sdl(bob)

        self.assertNotIn("product:", sdl)
        # The control still survives: Bob holds exactly the book permission, so
        # only the field that could ALSO return a magazine is taken from him.
        self.assertIn("book: PermIfaceBook", sdl)
