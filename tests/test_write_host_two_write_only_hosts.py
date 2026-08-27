# -*- coding: utf-8 -*-
"""Two write-only hosts over one model: the FIRST one declared keeps the slot.

"tests.test_write_host_list_container_slot" pins the case the container-slot fix
was written for -- a write-only "DjangoModelType" must not displace a
hand-written "DjangoListObjectType". It leaves one case open: TWO write-only
hosts over the same model with nothing else registered for it.

There the fix reverses the old outcome. The first host finds an EMPTY slot and
fills it, so the second finds a non-empty one and yields it back -- where
last-write-wins used to hand the slot to the second. Neither declaration claims
"list", so nothing in either ranks them; first-wins is what the code does and
what the comment beside it now says, and this module is what keeps the two from
drifting apart again.
"""

from __future__ import annotations

import pytest
from django.db import models

from django_graphex.registry import get_global_registry
from django_graphex.types import DjangoListObjectType, DjangoModelType


class TwoWriteHostNote(models.Model):
    """A model nothing else in the suite registers a container for.

    A dedicated model is what makes the assertions below deterministic: the
    container slot is process-global, so any other declaration over the same
    model would decide the outcome instead of the two hosts here.
    """

    body = models.CharField(max_length=32)

    class Meta:
        """Register the throwaway model under the "tests" app label.

        No table is ever created for it -- only its "_meta" is read.
        """

        app_label = "tests"


class FirstWriteOnlyHost(DjangoModelType):
    """The write-only host declared FIRST, which finds the slot empty.

    It carries a create-only surface, the shape a project reaches for when a
    write-path concern (a permission, a hook) has to live somewhere.
    """

    class Meta:
        """Bind the host to "TwoWriteHostNote" and serve "create" only.

        Leaving "list" out of "model_operations" is what makes it write-only.
        """

        model = TwoWriteHostNote
        model_operations = ("create",)


class SecondWriteOnlyHost(DjangoModelType):
    """The write-only host declared SECOND, which finds the slot taken.

    Declaration order is the whole point: this is the host that used to win the
    slot under last-write-wins and now yields it.
    """

    class Meta:
        """Bind the host to "TwoWriteHostNote" and serve "update" only.

        A different operation from the first host, so neither is a duplicate of
        the other, and still no "list".
        """

        model = TwoWriteHostNote
        model_operations = ("update",)


def test_first_declared_write_only_host_keeps_the_container_slot() -> None:
    """The model's canonical container is the FIRST host's generated one.

    This test breaks if the slot goes back to last-write-wins, which is what
    deleting the incumbent hand-back would do.
    """
    claimed = get_global_registry().get_list_type_for_model(TwoWriteHostNote)

    assert claimed is FirstWriteOnlyHost._meta.output_list_type


def test_second_declared_write_only_host_yields_the_slot() -> None:
    """The second host's container exists but is not the registered one.

    Minting stays unconditional so "_meta.output_list_type" is never None; only
    the registration is given up.
    """
    generated = SecondWriteOnlyHost._meta.output_list_type

    assert generated is not None
    assert issubclass(generated, DjangoListObjectType)
    assert generated is not FirstWriteOnlyHost._meta.output_list_type
    assert get_global_registry().get_list_type_for_model(TwoWriteHostNote) is not (
        generated
    )


def test_the_losing_container_cannot_reach_a_schema() -> None:
    """A write-only host's "ListField()" raises, so its container stays unmounted.

    This is what makes first-wins lossless rather than a silent drop: the two
    generated containers carry the SAME GraphQL type name, and a schema holding
    both would fail to build. Only the registered one is ever reachable.
    """
    with pytest.raises(AttributeError) as excinfo:
        SecondWriteOnlyHost.ListField()

    message = str(excinfo.value)

    assert "list" in message, message
    assert "SecondWriteOnlyHost" in message, message
