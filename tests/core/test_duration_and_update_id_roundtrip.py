"""Round-trip guards for "DurationField" output and the update-input "id" scalar.

Two type-mapping defects broke a plain read/write round-trip:

* B7 -- a populated "DurationField" resolved a raw "timedelta" into the
  "Float" output scalar, so every read returned null plus a
  "Float cannot represent non numeric value" field error, while the INPUT
  surface degraded to "String" with an "unsupported input field type" warning.
  Both ends now speak "Float" seconds.

* B8 -- the update input declared "id" from the model's pk Python type
  ("Int" for an "AutoField"), so echoing back the "ID!" string a query
  returned raised 'Int cannot represent non-integer value'. The update input
  now declares "ID", matching the sibling delete mutation.

Run: .venv/bin/python -m pytest \
    tests/core/test_duration_and_update_id_roundtrip.py -q --no-cov
"""

from __future__ import annotations

import datetime
import uuid
import warnings
from typing import Any

from django.db import models
from django.test import RequestFactory, TestCase
from graphql import GraphQLFloat, GraphQLID, GraphQLString, graphql_sync

from django_graphex.core import ObjectType, field
from django_graphex.fields import DjangoObjectField
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType

from .._schema_isolation import isolated_pair
from ..models import DummyModel


# --------------------------------------------------------------------------- #
# Models                                                                       #
# --------------------------------------------------------------------------- #
class DurTask(DummyModel):
    """A task with a nullable duration column and an integer primary key.

    Backs both the B7 duration round-trip and the B8 integer-pk update.
    """

    name = models.CharField(max_length=50)
    duration = models.DurationField(null=True, blank=True)


class DurTicket(DummyModel):
    """A ticket whose primary key is a "UUIDField" rather than an "AutoField".

    Backs the B8 non-integer-pk update, proving the "ID" input coerces back
    to the model's own pk type.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50)


# --------------------------------------------------------------------------- #
# Schema                                                                       #
# --------------------------------------------------------------------------- #
_R = Registry()


class DurTaskType(DjangoObjectType):
    """Output type for "DurTask", queried through "DjangoObjectField".

    Reads the duration column so the B7 output round-trip can be observed.
    """

    class Meta:
        """Meta options binding this type to "DurTask".

        Uses the module registry so the type never collides globally.
        """

        model = DurTask
        registry = _R
        filter_fields = {"id": ("exact",)}


class DurTaskMutation(DjangoModelMutation):
    """Create/update/delete mutation for "DurTask".

    Drives the duration write-back and the integer-pk update.
    """

    class Meta:
        """Meta options binding this mutation to "DurTask".

        Uses the module registry so the mutation never collides globally.
        """

        model = DurTask
        registry = _R


class DurTicketMutation(DjangoModelMutation):
    """Create/update/delete mutation for the uuid-pk "DurTicket".

    Drives the non-integer-pk update.
    """

    class Meta:
        """Meta options binding this mutation to "DurTicket".

        Uses the module registry so the mutation never collides globally.
        """

        model = DurTicket
        registry = _R


class _Query(ObjectType):
    """Root query exposing a single "DurTask" lookup plus a filler scalar.

    The filler keeps the root non-empty for schemas built without relations.
    """

    __test__ = False
    task = DjangoObjectField(DurTaskType)
    hello = field(GraphQLString)


class _Mutation(ObjectType):
    """Root mutation exposing the task and ticket create/update/delete fields.

    The delete field is present so the "ID!" sibling contract stays visible.
    """

    __test__ = False
    task_create = DurTaskMutation.CreateField()
    task_update = DurTaskMutation.UpdateField()
    task_delete = DurTaskMutation.DeleteField()
    ticket_create = DurTicketMutation.CreateField()
    ticket_update = DurTicketMutation.UpdateField()


_schema = DjangoGraphQLSchema(
    query=_Query, mutation=_Mutation, registries=isolated_pair(_R)
)


def _gql(query: str) -> Any:
    """Execute a query against the module schema with a real request context.

    Args:
        query: The GraphQL document to execute.

    Returns:
        The graphql-core execution result.
    """
    request = RequestFactory().post("/graphql/", content_type="application/json")
    return graphql_sync(_schema.graphql_schema, query, context_value=request)


def _input_field(type_name: str, field_name: str) -> Any:
    """Return one field of a compiled input type from the module schema.

    Args:
        type_name: The GraphQL input type name to look up.
        field_name: The wire (camelCase) field name inside that type.

    Returns:
        The graphql-core input field.
    """
    return _schema.graphql_schema.type_map[type_name].fields[field_name]


# =========================================================================== #
# B7 -- DurationField                                                          #
# =========================================================================== #
class DurationFieldOutputTest(TestCase):
    """A populated "DurationField" must read back as Float seconds, never null.

    Guards B7 on the output end.
    """

    def test_read_populated_duration_returns_seconds(self) -> None:
        """Reading a stored timedelta must yield its total seconds with no errors.

        If this breaks, every read of a populated duration column returns
        null plus a "Float cannot represent non numeric value" field error.
        """
        task = DurTask.objects.create(
            name="t", duration=datetime.timedelta(hours=1, minutes=30)
        )
        result = _gql("{ task(id: %d) { name duration } }" % task.pk)
        self.assertIsNone(result.errors)
        self.assertEqual(result.data["task"]["duration"], 5400.0)

    def test_read_null_duration_stays_null(self) -> None:
        """A NULL duration column must still read back as null without errors.

        If this breaks, the duration resolver mishandles the empty case.
        """
        task = DurTask.objects.create(name="t", duration=None)
        result = _gql("{ task(id: %d) { duration } }" % task.pk)
        self.assertIsNone(result.errors)
        self.assertIsNone(result.data["task"]["duration"])


class DurationFieldInputTest(TestCase):
    """The duration INPUT surface must mirror the Float output.

    Guards B7 on the input end, including the full read/write round-trip.
    """

    def test_input_field_is_float(self) -> None:
        """The create input must declare "duration" as Float, matching the output.

        If this breaks, the input degrades to the String fallback and the
        read value cannot be written back.
        """
        self.assertIs(
            _input_field("DurTaskCreateGenericType", "duration").type, GraphQLFloat
        )

    def test_building_the_input_emits_no_unsupported_type_warning(self) -> None:
        """Compiling a duration input must not warn about an unsupported field type.

        If this breaks, the loud degradation warning returns because the
        timedelta annotation has no scalar mapping.
        """
        from django_graphex.core.fields import build_model_schema
        from django_graphex.core.input_compiler import compile_input_type

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            # ``fields`` is a lazy thunk: touch it so the mapping actually runs.
            compile_input_type(
                build_model_schema(DurTask), name="DurTaskWarningProbeInput"
            ).fields
        messages = [str(w.message) for w in caught]
        self.assertEqual(
            [m for m in messages if "unsupported input field type" in m], []
        )

    def test_duration_round_trips_through_the_mutation(self) -> None:
        """A duration read from a query must write back unchanged through an update.

        If this breaks, the read/write round-trip on a duration column is
        broken at one of its two ends.
        """
        task = DurTask.objects.create(
            name="t", duration=datetime.timedelta(hours=1, minutes=30)
        )
        read = _gql("{ task(id: %d) { id duration } }" % task.pk)
        self.assertIsNone(read.errors)
        seconds = read.data["task"]["duration"]

        written = _gql(
            'mutation { taskUpdate(newDurtask: {id: "%s", duration: %r}) '
            "{ ok errors { field messages } } }" % (read.data["task"]["id"], seconds)
        )
        self.assertIsNone(written.errors)
        self.assertTrue(written.data["taskUpdate"]["ok"], written.data)
        task.refresh_from_db()
        self.assertEqual(task.duration, datetime.timedelta(hours=1, minutes=30))


# =========================================================================== #
# B8 -- update-input id                                                        #
# =========================================================================== #
class UpdateInputIdTest(TestCase):
    """The update input "id" must be the same "ID" surface the output emits.

    Guards B8 on both an integer and a non-integer primary key.
    """

    def test_update_input_id_is_id_scalar_on_integer_pk(self) -> None:
        """An integer-pk model's update input must declare "id" as ID, not Int.

        If this breaks, the "ID!" string a query returns cannot be echoed
        back into the update mutation.
        """
        self.assertIs(_input_field("DurTaskUpdateGenericType", "id").type, GraphQLID)

    def test_update_input_id_is_id_scalar_on_uuid_pk(self) -> None:
        """A uuid-pk model's update input must also declare "id" as ID.

        If this breaks, the update input surface diverges per pk type
        instead of matching the uniform "ID" output.
        """
        self.assertIs(_input_field("DurTicketUpdateGenericType", "id").type, GraphQLID)

    def test_update_with_queried_id_succeeds_on_integer_pk(self) -> None:
        """The string id returned by a query must drive an update on an integer pk.

        If this breaks, an update raises 'Int cannot represent
        non-integer value' for a perfectly valid id.
        """
        task = DurTask.objects.create(name="before")
        read = _gql("{ task(id: %d) { id } }" % task.pk)
        self.assertIsNone(read.errors)
        queried_id = read.data["task"]["id"]
        self.assertIsInstance(queried_id, str)

        written = _gql(
            'mutation { taskUpdate(newDurtask: {id: "%s", name: "after"}) '
            "{ ok errors { field messages } } }" % queried_id
        )
        self.assertIsNone(written.errors)
        self.assertTrue(written.data["taskUpdate"]["ok"], written.data)
        task.refresh_from_db()
        self.assertEqual(task.name, "after")

    def test_update_with_queried_id_succeeds_on_uuid_pk(self) -> None:
        """The string id of a uuid-pk row must drive an update to the right row.

        If this breaks, a non-integer pk is never located and the update
        silently reports "not found".
        """
        ticket = DurTicket.objects.create(name="before")
        written = _gql(
            'mutation { ticketUpdate(newDurticket: {id: "%s", name: "after"}) '
            "{ ok errors { field messages } } }" % ticket.pk
        )
        self.assertIsNone(written.errors)
        self.assertTrue(written.data["ticketUpdate"]["ok"], written.data)
        ticket.refresh_from_db()
        self.assertEqual(ticket.name, "after")
