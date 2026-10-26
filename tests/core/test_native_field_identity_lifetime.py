"""Native mutation field markers follow live GraphQLField instances."""

from __future__ import annotations

import gc
import weakref

import pytest
from graphql import GraphQLBoolean, GraphQLField, GraphQLString

from django_graphex.core import Mutation, field
from django_graphex.core.schema_compiler import _collect_root_attrs
from django_graphex.mutation import _NATIVE_FIELD_IDENTITIES, _NATIVE_FIELD_REGISTRY


class _PingMutation(Mutation):
    """Provide an unpinned native mutation field for identity checks."""

    ok = field(GraphQLBoolean)

    @staticmethod
    def mutate(root: object, info: object) -> None:
        """Provide a resolver without retaining a returned field.

        Args:
            root: Parent mutation value.
            info: GraphQL execution context.
        """


class _SyntheticStaleMarkers(set[int]):
    """Model an obsolete integer marker alongside one actual live field."""

    def __init__(self, stale_id: int, actual_field: GraphQLField) -> None:
        """Keep the stale integer and the different tracked object.

        Args:
            stale_id: Recycled integer identity to challenge the collector.
            actual_field: The distinct object that remains registered.
        """
        super().__init__([stale_id])
        self.actual_field = actual_field

    def values(self) -> tuple[GraphQLField, ...]:
        """Expose the actual object to an object-based collector.

        Returns:
            The real tracked field, never the unrelated field.
        """
        return (self.actual_field,)


def test_native_field_marker_expires_when_field_dies() -> None:
    """A dead native field must leave no integer identity marker behind.

    This uses field lifetime rather than allocator-dependent identifier reuse.
    """
    native = _PingMutation.Field()
    marker = id(native)
    reference = weakref.ref(native)

    assert marker in _NATIVE_FIELD_IDENTITIES
    del native
    gc.collect()

    assert reference() is None
    assert marker not in _NATIVE_FIELD_IDENTITIES


def test_live_native_field_survives_registry_slot_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live earlier field remains recognizable after a later slot write.

    Args:
        monkeypatch: Restores the synthetic registry slot after the test.
    """
    earlier = _PingMutation.Field()
    later = _PingMutation.Field()
    key = (object(), "create", "native")
    monkeypatch.setitem(_NATIVE_FIELD_REGISTRY, key, earlier)
    monkeypatch.setitem(_NATIVE_FIELD_REGISTRY, key, later)
    root = type("Root", (), {"earlier": earlier})

    assert _collect_root_attrs(root)["earlier"] is earlier


def test_current_registry_value_is_a_defensive_identity_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An out-of-band current registry value remains recognizable.

    Args:
        monkeypatch: Restores the synthetic registry slot after the test.
    """
    untracked = GraphQLField(GraphQLString)
    monkeypatch.setitem(
        _NATIVE_FIELD_REGISTRY, (object(), "create", "native"), untracked
    )
    root = type("Root", (), {"untracked": untracked})

    assert _collect_root_attrs(root)["untracked"] is untracked


def test_stale_identity_key_cannot_admit_an_unrelated_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A synthetic stale key cannot stand in for actual object identity.

    Args:
        monkeypatch: Restores the real identity map after the test.
    """
    native = _PingMutation.Field()
    unrelated = GraphQLField(GraphQLString)
    monkeypatch.setattr(
        "django_graphex.mutation._NATIVE_FIELD_IDENTITIES",
        _SyntheticStaleMarkers(id(unrelated), native),
    )
    root = type("Root", (), {"unrelated": unrelated})

    assert "unrelated" not in _collect_root_attrs(root)


@pytest.mark.django_db
def test_modeltype_builder_tracks_its_actual_native_field() -> None:
    """The model-type builder registers its GraphQLField instance.

    Its registration path is separate from the model-mutation builder.
    """
    from tests.core.test_wu9_modeltype_mutation_execution import (
        _build_post_modeltype_schema,
    )

    _, model_type = _build_post_modeltype_schema()
    native = model_type.CreateField()

    assert _NATIVE_FIELD_IDENTITIES.get(id(native)) is native


@pytest.mark.django_db
def test_model_mutation_builder_tracks_its_actual_native_field() -> None:
    """The model-mutation builder registers its GraphQLField instance.

    The resulting native field must remain recognizable after assembly.
    """
    from tests._schema_isolation import isolated_default_pair
    from tests.core.test_wu9_mutation_execution import _build_post_mutation_schema

    with isolated_default_pair():
        _, mutation_type = _build_post_mutation_schema()
        native = mutation_type.CreateField()

    assert _NATIVE_FIELD_IDENTITIES.get(id(native)) is native
