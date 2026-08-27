# -*- coding: utf-8 -*-
"""A container's projection must not be accepted and then discarded.

"DjangoListObjectType" builds its node type ONLY when the model has no
registered "DjangoObjectType" yet. In the ordinary documented arrangement -- a
node type declared beside its list container -- the container reuses the
registered type and its own "Meta.only_fields" / "Meta.exclude_fields" were
DROPPED without a word. Every column the operator meant to hide stayed
readable, orderable and filterable, and the schema built clean.

This is the exact defect 2.2.0 fixed for "DjangoModelType", where a projection
that would be silently dropped raises "ImproperlyConfigured" at class
definition. The same answer applies here, for the same reason: a warning is
filterable and would leave the leak live in production, and the only
configurations affected are the ones already leaking.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.core.exceptions import ImproperlyConfigured

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from django_graphex.utils import get_model_fields

from ._schema_isolation import isolated_pair
from .models import Author


class TestADiscardedContainerProjectionIsRefused:
    """Declaring a projection the container cannot honour fails the build.

    The container has exactly two states: it MINTS the node type (and the
    projection is honoured) or it REUSES a registered one (and the projection
    is a lie). Only the second is refused.
    """

    def test_exclude_fields_behind_a_registered_node_type_raises(self) -> None:
        """The documented way to hide a column must not be silently ignored.

        If this breaks, "exclude_fields = ("bio",)" on the container builds a
        schema that still serves, sorts and filters "bio".
        """
        reg = Registry()

        class _RegisteredAuthorType(DjangoObjectType):
            """Author node registered before the container is declared."""

            class Meta:
                """Bind to "Author" with no projection of its own."""

                model = Author
                registry = reg

        with pytest.raises(ImproperlyConfigured) as exc:

            class _DiscardedAuthorListType(DjangoListObjectType):
                """Container declaring a projection it cannot honour."""

                class Meta:
                    """Bind to "Author" and try to hide "bio"."""

                    model = Author
                    registry = reg
                    exclude_fields = ("bio",)

        message = str(exc.value)
        assert "_DiscardedAuthorListType" in message
        assert "_RegisteredAuthorType" in message
        assert "exclude_fields" in message

    def test_only_fields_behind_a_registered_node_type_raises(self) -> None:
        """The allowance axis is dropped just as silently, and refused too.

        If this breaks, the container advertises a narrow surface and serves
        the registered type's full one.
        """
        reg = Registry()

        class _OnlyRegisteredAuthorType(DjangoObjectType):
            """Author node registered before the container is declared."""

            class Meta:
                """Bind to "Author" with no projection of its own."""

                model = Author
                registry = reg

        assert _OnlyRegisteredAuthorType is not None
        with pytest.raises(ImproperlyConfigured) as exc:

            class _OnlyDiscardedAuthorListType(DjangoListObjectType):
                """Container declaring an allowance it cannot honour."""

                class Meta:
                    """Bind to "Author" and try to publish only the name."""

                    model = Author
                    registry = reg
                    only_fields = ("id", "name")

        assert "only_fields" in str(exc.value)

    def test_include_fields_behind_a_registered_node_type_raises(self) -> None:
        """The force-include axis is dropped the same way.

        If this breaks, a container asking for a column back gets a surface
        that never had it.
        """
        reg = Registry()

        class _IncludeRegisteredAuthorType(DjangoObjectType):
            """Author node registered before the container is declared."""

            class Meta:
                """Bind to "Author" publishing only the name."""

                model = Author
                registry = reg
                only_fields = ("id", "name")

        assert _IncludeRegisteredAuthorType is not None
        with pytest.raises(ImproperlyConfigured) as exc:

            class _IncludeDiscardedAuthorListType(DjangoListObjectType):
                """Container trying to force a projected-away column back."""

                class Meta:
                    """Bind to "Author" and try to force "bio" back in."""

                    model = Author
                    registry = reg
                    include_fields = ("bio",)

        assert "include_fields" in str(exc.value)

    def test_a_projection_mirroring_the_node_type_is_accepted(self) -> None:
        """Restating the node's own projection changes nothing, so it stands.

        The guard exists to stop a projection being accepted and discarded. A
        container repeating the projection the node already carries is not
        discarded -- honouring it would expose exactly what is exposed now --
        and refusing it breaks the documented side-by-side arrangement for a
        defensive restatement. If this breaks, the canonical
        "Configuration Options" sample in "docs/usage/types.md" fails to
        import.
        """
        reg = Registry()

        class _MirrorAuthorType(DjangoObjectType):
            """Author node hiding "bio" on its own Meta."""

            class Meta:
                """Bind to "Author" and hide "bio"."""

                model = Author
                registry = reg
                exclude_fields = ("bio",)

        class _MirrorAuthorListType(DjangoListObjectType):
            """Container restating the very projection the node carries."""

            class Meta:
                """Bind to "Author" and hide "bio", exactly as the node does."""

                model = Author
                registry = reg
                exclude_fields = ("bio",)

        assert _MirrorAuthorListType._meta.baseType is _MirrorAuthorType

    def test_a_projection_exposing_the_same_columns_differently_is_accepted(
        self,
    ) -> None:
        """Equivalence is measured on the columns, not on the spelling.

        "only_fields" naming everything the node's "exclude_fields" left
        standing selects the same set, so honouring it would change nothing.
        If this breaks, the guard refuses on a difference the schema cannot
        see.
        """
        reg = Registry()

        class _EquivalentAuthorType(DjangoObjectType):
            """Author node hiding "bio" on its own Meta."""

            class Meta:
                """Bind to "Author" and hide "bio"."""

                model = Author
                registry = reg
                exclude_fields = ("bio",)

        published = tuple(
            name
            for name, _field in get_model_fields(Author)
            if name != "bio" and not name.endswith("+")
        )

        class _EquivalentAuthorListType(DjangoListObjectType):
            """Container spelling the same selection as an allowance."""

            class Meta:
                """Bind to "Author" and allow exactly what the node keeps."""

                model = Author
                registry = reg
                only_fields = published

        assert _EquivalentAuthorListType._meta.baseType is _EquivalentAuthorType

    def test_the_container_that_mints_its_node_keeps_its_projection(self) -> None:
        """A container with no registered node type still honours the options.

        The contrast case: only the configuration that was already leaking is
        refused.
        """
        reg = Registry()

        class _MintingAuthorListType(DjangoListObjectType):
            """Container that builds its own node type from these options."""

            class Meta:
                """Bind to "Author" and hide "bio" on the minted node."""

                model = Author
                registry = reg
                exclude_fields = ("bio",)

        node = _MintingAuthorListType._meta.baseType._meta.graphql_output_type
        assert "name" in node.fields
        assert "bio" not in node.fields


class TestTheDocumentedConfigurationSampleBuilds:
    """The "every common option in one place" sample, in a realistic file.

    "docs/usage/types.md" presents a "DjangoListObjectType" carrying a
    paginator, filters, a queryset and a projection. Read it as documentation
    and you write it beside a node type for the same model -- the ordinary
    arrangement the page itself describes -- and the container then REUSES that
    node. The sample is only executable if restating the node's projection is
    accepted, so it is executed here rather than trusted.
    """

    def test_the_sample_builds_beside_a_node_type_for_the_model(self) -> None:
        """The container sample must import cleanly next to its node type.

        If this breaks, the page's canonical example raises
        "ImproperlyConfigured" in any file that also declares the node.
        """
        reg = Registry()

        class UserType(DjangoObjectType):
            """The node type the sample's container reuses."""

            class Meta:
                """Bind to "User" with the sample's own field restrictions."""

                model = User
                registry = reg
                only_fields = (
                    "id",
                    "username",
                    "email",
                    "first_name",
                    "last_name",
                    "date_joined",
                    "is_active",
                    "groups",
                )
                exclude_fields = ("password",)

        class GroupType(DjangoObjectType):
            """Registered so the sample's "groups" filter has a target type."""

            class Meta:
                """Bind to "Group" with no projection."""

                model = Group
                registry = reg

        class UserListType(DjangoListObjectType):
            """The sample, with two deviations and no others.

            The "registry" line isolates this build from the global registry,
            and the custom queryset drops the sample's
            "select_related('profile')" because "auth.User" has no such
            relation to follow.
            """

            class Meta:
                """Every common option in one place, as the page shows it."""

                model = User
                registry = reg
                description = "User list with advanced features"

                # Pagination
                pagination = LimitOffsetGraphqlPagination(
                    default_limit=20,
                    max_limit=100,
                    ordering=("-date_joined", "username"),
                )

                # Filtering
                filter_fields = {
                    "username": ("exact", "icontains", "istartswith"),
                    "email": ("exact", "icontains"),
                    "date_joined": ("exact", "gte", "lte"),
                    "is_active": ("exact",),
                    "groups": ("exact",),
                }

                # Custom queryset
                queryset = User.objects.all()

                # Field restrictions
                only_fields = (
                    "id",
                    "username",
                    "email",
                    "first_name",
                    "last_name",
                    "date_joined",
                    "is_active",
                    "groups",
                )
                exclude_fields = ("password",)

        class _SampleQuery(ObjectType):
            """Root mounting the sample's container."""

            users = DjangoListObjectField(UserListType)

        assert GroupType is not None
        schema = DjangoGraphQLSchema(query=_SampleQuery, registries=isolated_pair(reg))
        node = schema.graphql_schema.type_map["UserType"]

        assert "username" in node.fields
        assert "password" not in node.fields
