"""Existing native input and date-format boundaries with observable outputs."""

from __future__ import annotations

from datetime import datetime

import pytest
from dateutil.relativedelta import relativedelta
from django.db import models
from django.test.utils import isolate_apps
from graphql import GraphQLField, GraphQLObjectType, GraphQLString

from django_graphex.core.schema_compiler import _maybe_refork_mutation_field
from django_graphex.directives.date import (
    _format_dt,
    _format_relativedelta,
    _parse,
)
from django_graphex.registry import Registry
from django_graphex.types import (
    _resolve_native_choices_input_fields,
    _resolve_native_relation_input_fields,
)
from tests._schema_isolation import isolated_pair
from tests.models import (
    EnumCollisionItemA,
    MtiPlace,
    MtiRestaurant,
    NonEditableThing,
    Post,
)


@pytest.mark.parametrize(
    ("format_string", "expected"),
    [
        ("YYYY/MM/DD", "2024/02/29"),
        ("DD-MM-YYYY", "29-02-2024"),
        ("HH:mm:ss", "06:07:08"),
        ("ddd, DD MMM YYYY", "Thu, 29 Feb 2024"),
        ("YYYY.MM.DD ", "2024.02.29 "),
        ("-YYYY", "-2024"),
        ("YYYYd", "20244"),
        ("YYYYDD", "202429"),
    ],
)
def test_native_date_tokens_preserve_calendar_and_literals(
    format_string: str, expected: str
) -> None:
    """Preserve token translation and literal punctuation in a leap-day date.

    Args:
        format_string: The client's token-based format.
        expected: The rendered value for the fixed date.
    """
    fixed = datetime(2024, 2, 29, 6, 7, 8)
    assert _format_dt(fixed, format_string) == expected


@pytest.mark.parametrize("format_string", ["YYYYq", "qYYYY", "YYYY.DDq", ""])
def test_native_date_tokens_reject_unknown_letters(format_string: str) -> None:
    """Reject a malformed token rather than returning a partial date.

    Args:
        format_string: The malformed token sequence.
    """
    assert _format_dt(datetime(2024, 2, 29), format_string) is None


def test_native_date_parse_preserves_aware_instant_and_unsupported_none() -> None:
    """Keep a supplied aware instant and reject unsupported input cleanly.

    Neither path may silently substitute the current time.
    """
    aware = datetime.fromisoformat("2024-02-29T06:07:08+00:00")
    assert _parse(aware) is aware
    assert _parse(object()) is None


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (relativedelta(months=2), "Feb 29, 2024"),
        (relativedelta(years=1), "Feb 29, 2024"),
        (relativedelta(days=0), "Now"),
    ],
)
def test_two_day_wording_uses_calendar_date_outside_neighboring_days(
    delta: relativedelta, expected: str
) -> None:
    """Use a fixed calendar date instead of relative wording for distant dates.

    Args:
        delta: The offset from the reference date.
        expected: The rendered display text.
    """
    assert _format_relativedelta(
        delta, two_days=True, original_dt=datetime(2024, 2, 29)
    ) == (None, expected)


def test_mti_input_keeps_parent_relation_but_not_internal_parent_link() -> None:
    """Expose inherited reverse writes without exposing Django's parent link.

    The parent link is an implementation detail, unlike the reverse relation.
    """
    specs = _resolve_native_relation_input_fields(MtiRestaurant, "create")
    fields = {spec.out_name: spec for spec in specs}
    assert "place_ptr" not in fields
    assert fields["reviews"].is_list is True
    assert fields["reviews"].inject_only is True


def test_reverse_relation_is_not_dropped_with_noneditable_forward_fields() -> None:
    """Exclude server-managed forward writes while retaining reverse writes.

    Reverse relations have no editable concrete column on the owning model.
    """
    specs = _resolve_native_relation_input_fields(NonEditableThing, "create")
    assert not {"owner", "tags"} & {spec.out_name for spec in specs}
    owner_specs = _resolve_native_relation_input_fields(MtiPlace, "create")
    assert any(spec.out_name == "reviews" for spec in owner_specs)


def test_create_and_update_relation_requiredness_differs() -> None:
    """Require an ordinary non-null FK on create but not on update.

    A list relation remains optional regardless of the mutation operation.
    """
    create = {
        spec.out_name: spec
        for spec in _resolve_native_relation_input_fields(Post, "create")
    }
    update = {
        spec.out_name: spec
        for spec in _resolve_native_relation_input_fields(Post, "update")
    }
    assert create["author"].required is True
    assert update["author"].required is False
    assert create["tags"].is_list is True


def test_native_choice_input_uses_shared_enum_and_create_requiredness() -> None:
    """Retain a writable choice's enum identity and operation requiredness.

    Create and update must share the enum instead of compiling two wire types.
    """
    registry = Registry()
    create = _resolve_native_choices_input_fields(
        EnumCollisionItemA, registry, "create"
    )
    update = _resolve_native_choices_input_fields(
        EnumCollisionItemA, registry, "update"
    )
    assert [spec.out_name for spec in create] == ["status"]
    assert create[0].enum_type is update[0].enum_type
    assert create[0].required is True
    assert update[0].required is False


@isolate_apps("tests")
def test_native_choice_input_omits_server_managed_choices() -> None:
    """Omit a server-managed choices column from the input enum surface.

    The ordinary editable scalar is not promoted to a choices enum.
    """

    class ManagedChoices(models.Model):
        status = models.CharField(
            max_length=8, choices=[("a", "Alpha")], editable=False
        )
        label = models.CharField(max_length=8)

        class Meta:
            app_label = "tests"

    assert (
        _resolve_native_choices_input_fields(ManagedChoices, Registry(), "create") == ()
    )


def test_pair_local_nonmutation_field_preserves_field_identity() -> None:
    """Keep a plain field's identity when a schema pair has been forked.

    Only fields with mutation provenance need pair-local payload rebuilding.
    """
    pair = isolated_pair(Registry())
    pair.output_instances = {
        object: GraphQLObjectType("PairNode", {"name": GraphQLField(GraphQLString)})
    }
    field = GraphQLField(GraphQLString, description="ordinary field")
    assert _maybe_refork_mutation_field(field, pair) is field
