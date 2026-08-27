# -*- coding: utf-8 -*-
"""The interface permission label must come from the SCHEMA, not the REGISTRY.

"perm_labels._interface_perms" answers with the union (an AND) of the read
permissions of every implementor found in the declaring type's REGISTRY. A
registry is process-wide and populated at class-definition time; a schema mounts
whatever subset of it its roots and relations happen to reach. The two sets are
therefore not the same, and the registry one is strictly larger.

Over-requiring is the safe direction for a LEAK -- a caller can never be handed
a row it lacks the permission for. It is not safe for AVAILABILITY: a caller who
holds the read permission of every implementor the schema can actually return
lost the field anyway, because of a type the schema never mounts and no query
could ever reach. On 2.2.0 that field was public, so the registry-scoped label
turned a leak into an outage.

The label is now the union over the SCHEMA's own "get_possible_types", which is
exactly what the field can return. This module pins both halves of that: the
mounted implementors are enough, and one missing mounted implementor still
prunes.
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

from .models import Author, Track2Book, Track2Magazine

_ON = {"PERMISSION_SCOPED_SCHEMA": True}

# Isolated so the unmounted implementor below never lands in the global registry
# and starts gating other modules' interface fields.
_scope_registry = Registry()


class _ScopeInterface(DjangoInterfaceType):
    """Interface implemented by three registered types, two of them mounted."""

    name = field(GraphQLString)

    class Meta:
        """Bind the interface to the isolated registry."""

        registry = _scope_registry
        name = "ScopeProduct"


class _ScopeBookType(DjangoObjectType):
    """Mounted implementor for "Track2Book"."""

    class Meta:
        """Bind the implementor to "Track2Book" in the isolated registry."""

        model = Track2Book
        registry = _scope_registry
        interfaces = (_ScopeInterface,)
        name = "ScopeBook"


class _ScopeMagazineType(DjangoObjectType):
    """Mounted implementor for "Track2Magazine"."""

    class Meta:
        """Bind the implementor to "Track2Magazine" in the isolated registry."""

        model = Track2Magazine
        registry = _scope_registry
        interfaces = (_ScopeInterface,)
        name = "ScopeMagazine"


class _ScopeGhostType(DjangoObjectType):
    """Implementor the schema NEVER mounts.

    Declared and therefore REGISTERED, but not forwarded through "types=" and
    not reachable from any root or relation, so no query can make the interface
    field return one of its rows.
    """

    class Meta:
        """Bind the unmounted implementor to "Author" in the isolated registry."""

        model = Author
        registry = _scope_registry
        interfaces = (_ScopeInterface,)
        name = "ScopeGhost"


class _ScopeQuery(ObjectType):
    """Root mounting the interface plus a direct field to one implementor.

    The direct "book" field is the control: it is untagged too, so it shows what
    the pruner does when only ONE model's permission is at stake.
    """

    product = field(_ScopeInterface)
    book = field(_ScopeBookType)


# Only the two real implementors are forwarded; "_ScopeGhostType" is left out.
_scope_schema = DjangoGraphQLSchema(
    query=_ScopeQuery,
    types=[_ScopeBookType, _ScopeMagazineType],
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
class InterfaceLabelScopeTest(TestCase):
    """Pin whose implementors decide an interface field's permission label.

    The direct "book" field is the control in every case: it is untagged too, so
    whatever the pruner does to it is the baseline the interface field is judged
    against.
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
        return print_schema(psc.pruned_schema_for(user, _scope_schema.graphql_schema))

    def test_ghost_implementor_is_not_a_possible_type_of_the_schema(self) -> None:
        """Assert the unmounted implementor really is unreachable.

        If this fails the premise is gone -- the extra permission would be a
        genuine requirement rather than an accident of registry scope.
        """
        gql = _scope_schema.graphql_schema
        possible = {
            t.name for t in gql.get_possible_types(gql.type_map["ScopeProduct"])
        }
        assert possible == {"ScopeBook", "ScopeMagazine"}

    def test_every_mounted_implementor_perm_is_enough(self) -> None:
        """Assert the schema, not the registry, decides the label.

        A caller holding the read permission of BOTH types the interface can
        actually return keeps the field. A third implementor registered
        elsewhere in the process is unreachable through this schema, so it
        cannot be a requirement.
        """
        eve = self._user("scope_eve", Track2Book, Track2Magazine)
        sdl = self._sdl(eve)

        assert "product: ScopeProduct" in sdl
        # The control survives too, so the field is kept on its own merits
        # rather than by a blanket failure to prune.
        assert "book: ScopeBook" in sdl

    def test_a_missing_mounted_implementor_perm_still_prunes(self) -> None:
        """Assert narrowing the label did not reopen the interface bypass.

        The union over the mounted implementors is still an AND: a caller who
        cannot read every type the field can return loses the field rather than
        keeping one that could hand them a row they may not read.
        """
        adam = self._user("scope_adam", Track2Book)
        sdl = self._sdl(adam)

        assert "product:" not in sdl
        assert "book: ScopeBook" in sdl

    def test_the_unmounted_implementor_perm_is_not_required(self) -> None:
        """Assert the ghost's permission changes nothing either way.

        Holding a permission for a type no query can reach must neither grant
        nor withhold the field; this is the mirror of the availability test
        above and rules out the label merely having grown.
        """
        cain = self._user("scope_cain", Track2Book, Author)
        sdl = self._sdl(cain)

        assert "product:" not in sdl
