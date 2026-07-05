# -*- coding: utf-8 -*-
"""Field-labeling tests (P0).

Every generated CRUD/mutation/subscription field carries
extensions["gdx_required_perms"] per the composite table, the schema stows a
global "gdx_label_set", and explicit overrides are honored.

An UNTAGGED field (no extension) is treated as PUBLIC — it carries no
"gdx_required_perms" key.
"""

from __future__ import annotations

from typing import Any

import pytest

# The module-level schema mounts a SubscriptionField, which imports the
# subscriptions package; without the "subscriptions" extra (base-install CI
# env) that import fails, so the whole module skips like its siblings.
pytest.importorskip("channels")

from graphql import GraphQLBoolean, GraphQLField, GraphQLSchema, GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.core.registry_compiler import compile_all_outputs
from django_graphex.mutation import DjangoModelMutation
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType

from .models import HookModel

_ADD = "tests.add_hookmodel"
_CHANGE = "tests.change_hookmodel"
_DELETE = "tests.delete_hookmodel"
_VIEW = "tests.view_hookmodel"


class _HookLabelType(DjangoModelType):
    class Meta:
        model = HookModel
        stream = "hooklabels"
        filter_fields = {"id": ("exact",), "text": ("exact", "icontains")}


class _HookMutation(DjangoModelMutation):
    class Meta:
        model = HookModel


class _Query(ObjectType):
    hook = _HookLabelType.RetrieveField()
    hooks = _HookLabelType.ListField()
    # Untagged custom field -> PUBLIC (no gdx_required_perms).
    server_time = field(GraphQLString)


class _Mutation(ObjectType):
    create_hook = _HookMutation.CreateField()


class _Subscription(ObjectType):
    hook = _HookLabelType.SubscriptionField()


def _build() -> GraphQLSchema:
    """Compile the registry and assemble the query/mutation/subscription schema.

    Returns:
        schema: The built native GraphQL schema for "_Query", "_Mutation" and
            "_Subscription".
    """
    compile_all_outputs()
    return DjangoGraphQLSchema(
        query=_Query, mutation=_Mutation, subscription=_Subscription
    ).graphql_schema


def _perms(gql_field: GraphQLField) -> Any:
    """Read the "gdx_required_perms" extension off a compiled GraphQL field.

    Args:
        gql_field: The compiled field whose extensions are inspected.

    Returns:
        perms: The stamped permission value (frozenset, dict, or None for an
            untagged/public field).
    """
    return (gql_field.extensions or {}).get("gdx_required_perms")


# -- CRUD read fields -------------------------------------------------------- #
def test_retrieve_field_labeled_view_only() -> None:
    """Assert the generated retrieve field is labeled with view-only perms.

    If this fails, a single-object read field would be missing its
    permission stamp, breaking permission enforcement at read time.
    """
    schema = _build()
    perms = _perms(schema.query_type.fields["hook"])
    assert perms == frozenset({_VIEW})


def test_list_field_labeled_view_only() -> None:
    """Assert the generated list field is labeled with view-only perms.

    If this fails, a list-query field would be missing its permission
    stamp, breaking permission enforcement at read time.
    """
    schema = _build()
    perms = _perms(schema.query_type.fields["hooks"])
    assert perms == frozenset({_VIEW})


# -- untagged is public ------------------------------------------------------ #
def test_untagged_field_has_no_perms() -> None:
    """Assert a custom field with no explicit perms carries no perms extension.

    If this fails, untagged fields would be wrongly treated as
    permission-gated instead of public.
    """
    schema = _build()
    assert _perms(schema.query_type.fields["serverTime"]) is None


# -- mutation field ---------------------------------------------------------- #
def test_mutation_field_labeled_composite() -> None:
    """Assert a create mutation field is labeled with add + view perms.

    If this fails, mutation fields would be missing the composite
    permission set needed to both view and modify the underlying model.
    """
    schema = _build()
    perms = _perms(schema.mutation_type.fields["createHook"])
    assert perms == frozenset({_ADD, _VIEW})


# -- subscription field: per-action dict ------------------------------------- #
def test_subscription_field_labeled_per_action_dict() -> None:
    """Assert a subscription field is labeled with a per-action perms dict.

    If this fails, subscription consumers could not distinguish the perms
    required for create/update/delete/all_actions notifications.
    """
    schema = _build()
    perms = _perms(schema.subscription_type.fields["hook"])
    assert isinstance(perms, dict)
    assert perms["create"] == frozenset({_VIEW, _ADD})
    assert perms["update"] == frozenset({_VIEW, _CHANGE})
    assert perms["delete"] == frozenset({_VIEW, _DELETE})
    assert perms["all_actions"] == frozenset({_VIEW, _ADD, _CHANGE, _DELETE})


# -- global label-set -------------------------------------------------------- #
def test_schema_label_set_is_union_of_all_stamped_perms() -> None:
    """Assert the schema-level label set is the union of every stamped perm.

    If this fails, tooling that reads "gdx_label_set" to enumerate every
    permission referenced by the schema would see an incomplete set.
    """
    schema = _build()
    label_set = (schema.extensions or {}).get("gdx_label_set")
    assert isinstance(label_set, frozenset)
    assert label_set == frozenset({_VIEW, _ADD, _CHANGE, _DELETE})


# -- explicit override on field() -------------------------------------------- #
def test_field_required_perms_override() -> None:
    """Assert an explicit "required_perms" passed to field() overrides defaults.

    If this fails, a field author's explicit permission list would be
    ignored in favor of the automatically inferred perms.
    """

    class _QueryOverride(ObjectType):
        thing = field(GraphQLBoolean, required_perms=["tests.view_hookmodel"])

    compile_all_outputs()
    schema = DjangoGraphQLSchema(query=_QueryOverride).graphql_schema
    perms = _perms(schema.query_type.fields["thing"])
    assert perms == frozenset({"tests.view_hookmodel"})


# -- explicit override on Mutation.required_perms ---------------------------- #
def test_mutation_required_perms_class_attr() -> None:
    """Assert a mutation's "required_perms" class attribute overrides defaults.

    If this fails, a mutation class author's explicit permission list would
    be ignored in favor of the automatically inferred composite perms.
    """

    class _CustomHookMutation(DjangoModelMutation):
        required_perms = ["tests.publish_hookmodel"]

        class Meta:
            model = HookModel

    class _MutQuery(ObjectType):
        ok = field(GraphQLBoolean)

    class _CustomMutation(ObjectType):
        create_hook = _CustomHookMutation.CreateField()

    compile_all_outputs()
    schema = DjangoGraphQLSchema(
        query=_MutQuery, mutation=_CustomMutation
    ).graphql_schema
    perms = _perms(schema.mutation_type.fields["createHook"])
    assert perms == frozenset({"tests.publish_hookmodel"})
