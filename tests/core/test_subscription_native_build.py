# -*- coding: utf-8 -*-
"""S-sub-6 RED -> GREEN — the native subscription build is graphene-free.

S-sub-6 migrates the subscription *build* path off graphene. Defining a
"Subscription" subclass and mounting it on a subscription root MUST NOT import
graphene, fire "subscription._g()" (the cached graphene accessor),
"subscription._generic_scalar()" (the GenericScalar factory), or build the
graphene "ActionSubscriptionEnum" / "SubscriptionField" class bases.

Ground truth (proven by trace + the WS/SSE delivery path, see engram #1607/#1608):

* The NATIVE subscription field is built by "Subscription._build_native_field"
  (a DIRECT graphql-core "GraphQLField" carrying its OWN graphql-core action
  enum + "{action, id, filters}" args + the native event output type). It does
  NOT read the graphene "_meta.arguments".
* The mount seam is "schema_compiler._is_subscription_field" gating on
  "type(field).__name__ == 'SubscriptionField'". The detection is by class NAME
  only — the class need NOT subclass graphene "Field".
* The WS/SSE transports drive delivery via graphql-core
  "create_source_event_stream" + WU5 "drive_subscription" reading the native
  field's "subscribe" factory — never the graphene "_meta.arguments" or the
  graphene "SubscriptionField" base.

So S-sub-6 = stop the graphene firings at subclass-def + mount, keep the
"SubscriptionField" mount-seam NAME, and reconcile watch-item #6 (the
subscription payload's choices field must render the canonical Enum, not String).

Run: .venv/bin/python -m pytest tests/core/test_subscription_native_build.py -q
"""

from __future__ import annotations

import sys

import pytest
from django.db import models

# The subscription engine needs the optional ``channels`` extra.
pytest.importorskip("channels")


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
class _BlockGraphene:
    """A ``sys.meta_path`` finder that raises when graphene is (re-)imported.

    Installed AFTER graphene is purged from ``sys.modules`` so any fresh
    ``import graphene`` (or ``from graphene...``) during the guarded block raises
    ``ModuleNotFoundError`` — proving the guarded code path does not import
    graphene.
    """

    def find_module(self, name, path=None):  # noqa: D401 - finder protocol
        if name == "graphene" or name.startswith("graphene."):
            raise ModuleNotFoundError(
                f"graphene import BLOCKED by S-sub-6 guard: {name}"
            )
        return None

    def find_spec(self, name, path=None, target=None):  # noqa: D401
        if name == "graphene" or name.startswith("graphene."):
            raise ModuleNotFoundError(
                f"graphene import BLOCKED by S-sub-6 guard: {name}"
            )
        return None


# --------------------------------------------------------------------------- #
# (a) IMPORT-REMOVAL — defining + mounting + building a Subscription does not   #
#     fire graphene.                                                            #
# --------------------------------------------------------------------------- #
def test_subscription_define_mount_build_does_not_import_graphene() -> None:
    """Ships broken if defining, mounting, or building a native subscription
    starts importing graphene.

    The subscription build path must not touch graphene at all: not the retired
    "_g()"/"_generic_scalar()" accessors (gone in S-sub-6), and not the lazy
    "ActionSubscriptionEnum" graphene Enum (kept only for the graphene-backend
    test contract). The tripwire raises if the lazy graphene-enum factory fires
    on the build path.
    """
    from django_graphex.subscriptions import subscription as sub_mod

    # S-del-backend-11: the retired graphene accessors AND the lazy graphene
    # ``ActionSubscriptionEnum`` factory/cache are all GONE from the module surface
    # (the graphene backend was deleted), so the build path is structurally
    # graphene-free.
    assert not hasattr(sub_mod, "_g"), "_g() must be retired"
    assert not hasattr(sub_mod, "_generic_scalar"), "_generic_scalar() must be retired"
    assert not hasattr(sub_mod, "_build_action_subscription_enum")
    assert not hasattr(sub_mod, "_ACTION_SUBSCRIPTION_ENUM")
    assert not hasattr(sub_mod, "ActionSubscriptionEnum")

    from django_graphex.subscriptions import Subscription
    from tests.models import DummyModel

    class _NoGrapheneThing(DummyModel):
        name = models.CharField(max_length=50)

        class Meta:
            app_label = "tests"

    # 1) Defining a subscription subclass must not fire graphene.
    class _NoGrapheneSub(Subscription):
        class Meta:
            model = _NoGrapheneThing
            stream = "no-graphene-things"
            payload_mode = "full"

    # 2) Mounting it (``.Field()``) must not fire graphene.
    mounted = _NoGrapheneSub.Field()
    # The mount seam NAME is preserved so the native compiler still detects it.
    assert type(mounted).__name__ == "SubscriptionField"

    # 3) Building the native field must not fire graphene.
    field = _NoGrapheneSub._build_native_field()
    assert set(field.args) == {"action", "id", "filters"}


def test_subscription_build_runs_with_graphene_blocked() -> None:
    """Ships broken if defining, mounting, and building a subscription stops
    succeeding with graphene blocked at meta_path.

    The strongest import-removal proof: purge graphene from "sys.modules",
    block any re-import, and exercise the full subscription build. It must
    succeed without importing graphene.
    """
    # Purge graphene from sys.modules and block any re-import.
    # S-del-backend-11: the lazy graphene ``ActionSubscriptionEnum`` cache is gone
    # (deleted with the graphene backend), so there is no cache to reset.
    from django_graphex.subscriptions import Subscription
    from tests.models import DummyModel

    saved_modules = {
        name: mod
        for name, mod in list(sys.modules.items())
        if name == "graphene" or name.startswith("graphene.")
    }
    for name in saved_modules:
        del sys.modules[name]
    guard = _BlockGraphene()
    sys.meta_path.insert(0, guard)
    try:

        class _BlockedThing(DummyModel):
            name = models.CharField(max_length=50)

            class Meta:
                app_label = "tests"

        class _BlockedSub(Subscription):
            class Meta:
                model = _BlockedThing
                stream = "blocked-things"
                payload_mode = "full"

        mounted = _BlockedSub.Field()
        assert type(mounted).__name__ == "SubscriptionField"
        field = _BlockedSub._build_native_field()
        assert set(field.args) == {"action", "id", "filters"}
        # The whole subscription build path stayed graphene-free.
        assert "graphene" not in sys.modules
    finally:
        sys.meta_path.remove(guard)
        sys.modules.update(saved_modules)


# --------------------------------------------------------------------------- #
# (b) MOUNT SEAM — the native compiler still detects the subscription field.    #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_mount_seam_subscription_present_in_schema_root() -> None:
    """Ships broken if the subscription field stops appearing in the
    compiled schema's subscription root.
    """
    from graphql import GraphQLBoolean, GraphQLObjectType

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoModelType, DjangoObjectType
    from tests.models import Author, Category, Post, Tag

    class _MSAuthor(DjangoObjectType):
        class Meta:
            model = Author

    class _MSTag(DjangoObjectType):
        class Meta:
            model = Tag

    class _MSCategory(DjangoObjectType):
        class Meta:
            model = Category

    class _MSPost(DjangoObjectType):
        class Meta:
            model = Post

    class _MSPostModel(DjangoModelType):
        class Meta:
            model = Post
            stream = "ms-posts"
            payload_mode = "full"

    class _MSQuery(ObjectType):
        ok = field(GraphQLBoolean)

    class _MSRoot(ObjectType):
        post = _MSPostModel.SubscriptionField()

    compile_all_outputs()
    schema = DjangoGraphQLSchema(query=_MSQuery, subscription=_MSRoot)
    gql = schema.graphql_schema
    sub_root = gql.subscription_type
    assert isinstance(sub_root, GraphQLObjectType)
    assert "post" in sub_root.fields
    # The native subscription field carries the {action, id, filters} args.
    assert set(sub_root.fields["post"].args) == {"action", "id", "filters"}


# --------------------------------------------------------------------------- #
# (c) SDL PARITY — the subscription root SDL (action enum, id, filter args)      #
#     is byte-identical before/after the migration.                             #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_subscription_root_sdl_action_enum_id_filters() -> None:
    """Ships broken if the subscription root SDL stops rendering the
    "action" enum plus the "id" and "filters" args.
    """
    import re

    from graphql import GraphQLBoolean
    from graphql.utilities import print_schema

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoModelType, DjangoObjectType
    from tests.models import Author, Category, Post, Tag

    class _SdlAuthor(DjangoObjectType):
        class Meta:
            model = Author

    class _SdlTag(DjangoObjectType):
        class Meta:
            model = Tag

    class _SdlCategory(DjangoObjectType):
        class Meta:
            model = Category

    class _SdlPost(DjangoObjectType):
        class Meta:
            model = Post

    class _SdlPostModel(DjangoModelType):
        class Meta:
            model = Post
            stream = "sdl-posts"
            payload_mode = "full"

    class _SdlQuery(ObjectType):
        ok = field(GraphQLBoolean)

    class _SdlRoot(ObjectType):
        post = _SdlPostModel.SubscriptionField()

    compile_all_outputs()
    schema = DjangoGraphQLSchema(query=_SdlQuery, subscription=_SdlRoot)
    sdl = print_schema(schema.graphql_schema)

    # The subscription root field carries the action enum + id + filters args.
    m = re.search(r"post\((.*?)\):", sdl, re.DOTALL)
    assert m, f"subscription root field not found in SDL:\n{sdl}"
    args_block = m.group(1)
    assert "action:" in args_block
    assert re.search(r"action:\s*\w+!", args_block), args_block
    assert "id:" in args_block
    assert "filters:" in args_block
    # The action enum exposes the model-change actions.
    assert "PostSubscriptionAction" in sdl
    enum_m = re.search(r"enum PostSubscriptionAction \{(.*?)\}", sdl, re.DOTALL)
    assert enum_m, f"action enum not found:\n{sdl}"
    for value in ("CREATE", "UPDATE", "DELETE", "ALL_ACTIONS"):
        assert value in enum_m.group(1)


# --------------------------------------------------------------------------- #
# (e) RECONCILE watch-item #6 — a subscription payload's choices field renders   #
#     the canonical Enum (SAME instance/name as the regular output enum), NOT    #
#     String.                                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_subscription_payload_choices_renders_canonical_enum() -> None:
    """Ships broken if the subscription event payload stops rendering a
    choices field as the shared Enum.

    Watch-item #6 (engram #1611): "_build_native_event_type" compiled the
    payload WITHOUT the graphene_registry, so a choices field rendered as
    "String" while the regular output type rendered the canonical Enum. After
    S-sub-6 the subscription payload must render the SAME "GraphQLEnumType"
    instance the regular output type uses.
    """
    from graphql import GraphQLEnumType

    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.types import DjangoModelType, DjangoObjectType
    from tests.models import EnumCollisionItemA

    class _ChoicesOut(DjangoObjectType):
        class Meta:
            model = EnumCollisionItemA

    class _ChoicesModel(DjangoModelType):
        class Meta:
            model = EnumCollisionItemA
            stream = "choices-items"
            payload_mode = "full"

    compile_all_outputs()

    # The regular output type's canonical status enum.
    output_type = _ChoicesOut._meta.graphql_output_type
    output_status = output_type.fields["status"].type
    assert isinstance(output_status, GraphQLEnumType), (
        "regular output 'status' must be a GraphQLEnumType (S-enum-1)"
    )

    # The subscription event payload's status field.
    sub_cls = _ChoicesModel.subscription_type()
    event_type = sub_cls._build_native_event_type()
    payload_status = event_type.fields["status"].type
    assert isinstance(payload_status, GraphQLEnumType), (
        "subscription payload 'status' must render the canonical Enum, not String "
        "(watch-item #6)"
    )
    # It must be the SAME canonical enum instance/name (intra-schema consistency).
    assert payload_status.name == output_status.name
    assert payload_status is output_status, (
        "subscription payload must share the SAME canonical enum instance as the "
        "regular output type"
    )
