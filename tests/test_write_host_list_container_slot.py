# -*- coding: utf-8 -*-
"""A write-only "DjangoModelType" must not seize the model's list container.

"DjangoModelType.__init_subclass_with_meta__" mints a "DjangoListObjectType"
subclass for every host, and every "DjangoListObjectType" registers itself as
the model's canonical container on a last-write-wins basis (types.py, at the
end of "DjangoListObjectType.__init_subclass_with_meta__"). A host that
declared "Meta.model_operations" WITHOUT "list" therefore still displaced the
container a hand-written "DjangoListObjectType" had registered, and every
nested to-many relation pointing at that model silently changed shape: the
converter resolves a reverse relation through "get_or_create_list_object_type",
which reads that same registry slot.

The practical fallout was that attaching "permission_classes" to a model's
write path -- which only a "DjangoModelType" can carry -- rewrote the model's
READ container as a side effect, so a query selecting the hand-written
container's "pageInfo" stopped validating.

The generated container now claims the slot only when the host actually serves
"list", or when nothing else has claimed it.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from graphql import parse, validate

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.paginations.pagination import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
)
from django_graphex.registry import get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import (
    DjangoListObjectType,
    DjangoModelType,
    DjangoObjectType,
)

from .models import WriteHostAudit, WriteHostReply, WriteHostThread


class WriteHostReplyType(DjangoObjectType):
    """Node type for "WriteHostReply", the element of the nested list.

    Registered first so the containers below reuse it as their node.
    """

    class Meta:
        """Bind the node to "WriteHostReply".

        No other option matters here: only its registration does.
        """

        model = WriteHostReply


class WriteHostThreadType(DjangoObjectType):
    """Node type for "WriteHostThread", the parent carrying "replies".

    Its reverse accessor is converted through the container registry slot,
    which is the slot this module is about.
    """

    class Meta:
        """Bind the node to "WriteHostThread".

        The reverse relation is picked up automatically from the model.
        """

        model = WriteHostThread


class WriteHostReplyListType(DjangoListObjectType):
    """The hand-written container the project registered for the child.

    Cursor pagination is what gives it a "pageInfo" field, so the shape it
    contributes to the nested relation is observable in the schema.
    """

    class Meta:
        """Bind the container to "WriteHostReply" with cursor pagination.

        Cursor pagination is the only option that matters: it is what adds
        "pageInfo".
        """

        model = WriteHostReply
        pagination = CursorGraphqlPagination(ordering="-id")


class WriteHostReplyWriteType(DjangoModelType):
    """A write-only host over the child, declared AFTER the container.

    This is the class that used to displace the container: it exists only to
    carry a write-path concern (a permission, a hook), and says so by leaving
    "list" out of "Meta.model_operations".
    """

    class Meta:
        """Bind the host to "WriteHostReply" and serve the writes only.

        Leaving "list" out of "model_operations" is the declaration the fix
        makes binding.
        """

        model = WriteHostReply
        model_operations = ("create", "update", "delete")


class WriteHostThreadListType(DjangoListObjectType):
    """Container for the parent, mounted so the reverse list is reachable.

    A root field has to return a container for the nested list below it to be
    part of the schema at all.
    """

    class Meta:
        """Bind the container to "WriteHostThread".

        The default paginator is fine: nothing here asserts on the parent.
        """

        model = WriteHostThread


class _WriteHostQuery(ObjectType):
    """Root query mounting the parent so its reverse list is reachable.

    Nothing mounts the child directly: the whole point is that the child's
    shape arrives through the parent.
    """

    threads = DjangoListObjectField(WriteHostThreadListType)


def test_write_only_host_leaves_the_registered_container_in_place() -> None:
    """The model's canonical container is still the hand-written one.

    Reverting the fix puts the generated
    "WriteHostReplyListGenericType" back into the slot.
    """
    claimed = get_global_registry().get_list_type_for_model(WriteHostReply)

    assert claimed is WriteHostReplyListType


def test_write_only_host_still_has_its_own_container_on_meta() -> None:
    """The host's "output_list_type" stays populated even when unregistered.

    Not minting the container at all was the other candidate fix; it was
    rejected because "list_object_type()" and "ListField()" read this attribute
    and would have started handing out None.
    """
    generated = WriteHostReplyWriteType._meta.output_list_type

    assert generated is not None
    assert issubclass(generated, DjangoListObjectType)
    assert generated is not WriteHostReplyListType


def test_nested_relation_keeps_the_declared_container_shape() -> None:
    """The reverse "replies" list still validates a "pageInfo" selection.

    This is the end-to-end symptom: the displacing container is not cursor
    paginated, so it has no "pageInfo" and the query stopped validating.
    """
    schema = DjangoGraphQLSchema(query=_WriteHostQuery)
    query = (
        "{ threads { results { id replies { results { id }"
        " pageInfo { hasNextPage } } } } }"
    )

    errors = validate(schema.graphql_schema, parse(query))

    assert errors == [], [str(error) for error in errors]


# --------------------------------------------------------------------------- #
# A host that DOES serve "list" must keep displacing, exactly as before.       #
# --------------------------------------------------------------------------- #

_AUDIT_HOST_PAGINATION = LimitOffsetGraphqlPagination(default_limit=7)


class WriteHostAuditType(DjangoObjectType):
    """Node type for "WriteHostAudit", the list-serving host's element.

    Registered first so both containers below reuse it as their node.
    """

    class Meta:
        """Bind the node to "WriteHostAudit".

        No other option matters here: only its registration does.
        """

        model = WriteHostAudit


class WriteHostAuditListType(DjangoListObjectType):
    """A hand-written container declared BEFORE the list-serving host.

    Declaration order is the point: this one occupies the slot the host is
    still expected to take over.
    """

    class Meta:
        """Bind the container to "WriteHostAudit" with cursor pagination.

        Its paginator only has to differ from the host's to be recognizable.
        """

        model = WriteHostAudit
        pagination = CursorGraphqlPagination(ordering="-id")


class WriteHostAuditModelType(DjangoModelType):
    """A host over "WriteHostAudit" that keeps the default operations.

    Serving "list" is what still entitles it to the container slot.
    """

    class Meta:
        """Bind the host to "WriteHostAudit" with its own paginator.

        "model_operations" is left at its default, which includes "list".
        """

        model = WriteHostAudit
        pagination = _AUDIT_HOST_PAGINATION


def test_write_only_host_still_cannot_smuggle_a_dropped_projection() -> None:
    """The 2.2.0 reused-output-type guard fires for a write-only host too.

    Yielding the container slot must not read as "this host is harmless": its
    output type is still the one already registered for the model, so a
    projection declared here would still be dropped and the column it means to
    hide would stay queryable.
    """
    with pytest.raises(ImproperlyConfigured) as excinfo:

        class _LeakyWriteHost(DjangoModelType):
            """A write-only host trying to hide a column it does not own."""

            class Meta:
                """Bind the host to "WriteHostReply" and hide "body"."""

                model = WriteHostReply
                model_operations = ("create", "update", "delete")
                exclude_fields = ("body",)

    message = str(excinfo.value)

    assert "exclude_fields" in message, message
    assert "WriteHostReply" in message, message


def test_list_serving_host_still_claims_the_container_slot() -> None:
    """A host that serves "list" keeps winning the slot, as it does today.

    Making the generated container defer to an existing registration
    unconditionally would break this: the host's own pagination would stop
    reaching the model's nested relations.
    """
    claimed = get_global_registry().get_list_type_for_model(WriteHostAudit)

    assert claimed is WriteHostAuditModelType._meta.output_list_type
    assert claimed is not WriteHostAuditListType
    assert claimed._meta.pagination is _AUDIT_HOST_PAGINATION
