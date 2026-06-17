"""S-milestone-9 — the PERMANENT zero-graphene FULL-RUNTIME gate (KEEP-AS-IS).

This is the go/no-go INTEGRATION GATE of the graphene-excision campaign (plan
#1605, gate-strategy #1608) and the proof that the NATIVE code path is
graphene-free at RUNTIME, not merely at build time.

What it proves
--------------
A schema whose EVERY root is a native ``django_graphex.ObjectType`` —
``Query`` + ``Mutation`` + ``Subscription`` + paginated list fields — is built
AND fully EXERCISED at runtime (SDL render, create/update mutation execution,
limit/offset + cursor pagination resolution, one end-to-end subscription
delivery, and a choices field on output + as a filter arg + in a mutation input)
while graphene is BLOCKED via ``sys.meta_path`` — and ``graphene`` is absent from
``sys.modules`` BOTH before importing ``django_graphex`` and after the full
exercise, with the blocking finder NEVER having fired.

Why a clean subprocess
----------------------
The assertion ``'graphene' not in sys.modules`` is process-global, so it is only
trustworthy in a process that did not already import graphene for an unrelated
reason. Many other tests in this suite import graphene at module scope (the
graphene-ROOT contract tests + the parity oracle), and ``_sdl_parity_seed`` leaks
``ListType`` containers into the global output registry (#1611 item 3). Running in
a fresh subprocess sidesteps BOTH: a pristine ``sys.modules`` and an isolated
global registry.

Why graphene must still be INSTALLED for this gate to be meaningful
-------------------------------------------------------------------
graphene is still installed at this slice (it is uninstalled only at S8i). With
graphene present, a PASS means *no production path imported it* — a real proof.
If graphene were merely absent, the meta_path block would be a no-op and the
assertions would hold vacuously. This test is KEEP-AS-IS: it MUST keep passing
after the eventual uninstall too — with graphene absent the finder simply never
matches and the ``not in sys.modules`` assertions still hold.

Run:
    .venv/bin/python -m pytest -q tests/native/test_zero_graphene_full_exercise.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# The child program runs in a CLEAN subprocess. It (1) asserts graphene is not yet
# imported, (2) installs a sys.meta_path finder that RAISES on any graphene import,
# (3) builds a fully-native-root schema over the full Django relation taxonomy,
# (4) EXERCISES it at runtime, and (5) re-asserts graphene never entered
# sys.modules and the finder never fired. Any graphene import fails LOUD with the
# offending name; the child exits non-zero and the parent surfaces its output.
_CHILD = r'''
import sys

# (1) BASELINE: graphene must NOT be imported before django_graphex.
assert "graphene" not in sys.modules, (
    "graphene was imported before the exercise even began: "
    + ", ".join(n for n in sys.modules if n.startswith("graphene"))
)

import django
from django.conf import settings

settings.configure(
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
    ALLOWED_HOSTS=["*"],
    DEBUG_PROPAGATE_EXCEPTIONS=True,
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    SITE_ID=1,
    SECRET_KEY="not very secret in the zero-graphene gate",
    USE_I18N=True,
    STATIC_URL="/static/",
    INSTALLED_APPS=(
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.sites",
        "django.contrib.staticfiles",
        "channels",
        "tests",
    ),
    PASSWORD_HASHERS=("django.contrib.auth.hashers.MD5PasswordHasher",),
    DJANGO_GRAPHEX={"SCHEMA": "tests.schema.schema"},
)
django.setup()

from django.core.management import call_command
call_command("migrate", run_syncdb=True, verbosity=0)


class _BlockGraphene:
    """A sys.meta_path finder that RAISES on any graphene(.*) import.

    KEEP-AS-IS: when graphene is eventually uninstalled this finder simply never
    matches (nothing tries to import graphene) so it is a harmless no-op.
    """

    fired = []

    def find_spec(self, name, path=None, target=None):
        if name == "graphene" or name.startswith("graphene."):
            self.fired.append(name)
            raise ModuleNotFoundError(
                "graphene import BLOCKED by the S-milestone-9 zero-graphene gate: "
                + name
            )
        return None


# WARM-UP imports BEFORE installing the block, so only graphene imports that fire
# DURING the runtime exercise are caught (not unrelated import-time machinery).
import asyncio
import re

from channels.layers import InMemoryChannelLayer
from graphql import (
    GraphQLBoolean,
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    graphql_sync,
    parse,
)
from graphql.utilities import print_schema

from django.contrib.auth.models import User  # noqa: F401 (warm Django auth)

from django_graphex import (
    CursorGraphqlPagination,
    DjangoGraphQLSchema,
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoModelMutation,
    DjangoModelType,
    LimitOffsetGraphqlPagination,
    ObjectType,
    field,
)
from django_graphex.fields import DjangoFilterPaginateListField, DjangoObjectField
from django_graphex.native.base import compile_all_inputs
from django_graphex.native.registry_compiler import compile_all_outputs
from django_graphex.registry import Registry
from django_graphex.subscriptions.streaming import drive_subscription
from django_graphex.types import DjangoObjectType
from tests.models import (
    Author,
    AuthorProfile,
    Category,
    Comment,
    EnumCollisionItemA,
    PersonWithSpouse,
    Post,
    Tag,
    Track2GfkComment,
)

_REG = Registry()

# --- INSTALL THE BLOCK. EVERYTHING BELOW IS THE EXERCISE. ------------------- #
guard = _BlockGraphene()
sys.meta_path.insert(0, guard)
try:
    # ---- types: FK + O2O + M2M + reverse + choices + GFK ------------------ #
    class PostType(DjangoObjectType):
        class Meta:
            model = Post            # FK author/category, M2M tags/co_authors, reverse comments
            registry = _REG

    class AuthorType(DjangoObjectType):
        class Meta:
            model = Author          # reverse-FK posts, reverse-O2O author_profile
            registry = _REG

    class CategoryType(DjangoObjectType):
        class Meta:
            model = Category
            registry = _REG

    class TagType(DjangoObjectType):
        class Meta:
            model = Tag
            registry = _REG

    class CommentType(DjangoObjectType):
        class Meta:
            model = Comment
            registry = _REG

    class AuthorProfileType(DjangoObjectType):
        class Meta:
            model = AuthorProfile   # forward O2O author
            registry = _REG

    class PersonType(DjangoObjectType):
        class Meta:
            model = PersonWithSpouse  # self-referential O2O spouse (issue #52)
            registry = _REG

    class ItemType(DjangoObjectType):
        class Meta:
            model = EnumCollisionItemA  # choices field: status
            registry = _REG
            filter_fields = {"status": ("exact",)}

    class GfkCommentType(DjangoObjectType):
        class Meta:
            model = Track2GfkComment    # GenericForeignKey target
            registry = _REG

    # ---- paginated list types: limit/offset AND cursor ------------------- #
    class PostListType(DjangoListObjectType):
        class Meta:
            model = Post
            registry = _REG
            pagination = LimitOffsetGraphqlPagination(default_limit=25)

    class PostCursorListType(DjangoListObjectType):
        class Meta:
            model = Post
            registry = _REG
            pagination = CursorGraphqlPagination(ordering="id")

    # ---- mutations: create + update with relation + choices args --------- #
    class PostMutation(DjangoModelMutation):
        class Meta:
            model = Post
            registry = _REG
            model_operations = ("create", "update")

    class ItemMutation(DjangoModelMutation):
        class Meta:
            model = EnumCollisionItemA
            registry = _REG
            model_operations = ("create", "update")

    # ---- native subscription --------------------------------------------- #
    class PostModelType(DjangoModelType):
        class Meta:
            model = Post
            stream = "gate-posts"
            serialize_data = True

    class Query(ObjectType):
        # native scalar field() WITH a resolve_<name> method (the
        # get_unbound_function fire-point on a pure-native root).
        server_time = field(__import__("graphql").GraphQLString)
        all_posts = DjangoListObjectField(PostListType)
        posts_cursor = DjangoListObjectField(PostCursorListType)
        items = DjangoFilterPaginateListField(
            ItemType, pagination=LimitOffsetGraphqlPagination()
        )
        post = DjangoObjectField(PostType)
        author = DjangoObjectField(AuthorType)
        person = DjangoObjectField(PersonType)
        author_profile = DjangoObjectField(AuthorProfileType)
        gfk_comment = DjangoObjectField(GfkCommentType)

        def resolve_server_time(self, info):
            return "2026-06-16T00:00:00"

    class Mutation(ObjectType):
        post_create = PostMutation.CreateField()
        post_update = PostMutation.UpdateField()
        item_create = ItemMutation.CreateField()
        item_update = ItemMutation.UpdateField()

    class SubRoot(ObjectType):
        post = PostModelType.SubscriptionField()

    compile_all_outputs()
    compile_all_inputs()
    schema = DjangoGraphQLSchema(query=Query, mutation=Mutation, subscription=SubRoot)
    gql = schema.graphql_schema

    # === EXERCISE 1: render SDL (full build) =============================== #
    sdl = print_schema(gql)
    assert "serverTime" in sdl
    assert "allPosts" in sdl
    assert "postsCursor" in sdl
    assert "postCreate" in sdl
    assert "postUpdate" in sdl
    assert "GenericForeignKeyType" in sdl, "GFK output type must be in the SDL"
    # choices ENUM on OUTPUT (canonical per-(model,field) enum, never String).
    status_enum = re.search(r"enum (\w*StatusEnum)\b", sdl)
    assert status_enum, f"choices output enum missing from SDL:\n{sdl[:2000]}"
    enum_name = status_enum.group(1)
    enum_block = re.search(
        r"enum %s \{(.*?)\}" % re.escape(enum_name), sdl, re.DOTALL
    )
    assert enum_block and "A" in enum_block.group(1) and "B" in enum_block.group(1), (
        "choices enum must expose the A/B value names"
    )
    # choices used as a FILTER ARG: the items() field exposes a `filter:` input
    # object whose `status` lookup carries the choices field.
    filter_in = re.search(
        r"input (\w*Filterinput) \{(.*?)\}", sdl, re.DOTALL | re.IGNORECASE
    )
    assert filter_in and "status" in filter_in.group(2), (
        "choices field must be usable as a filter arg (filter input `status`)"
    )
    # choices in a MUTATION INPUT: the item create input carries `status` typed as
    # the canonical choices Enum (never String).
    item_in = re.search(
        r"input (\w*ItemA\w*Create\w*) \{(.*?)\}", sdl, re.DOTALL
    )
    assert item_in and "status" in item_in.group(2), (
        "choices field must appear in the mutation create input type"
    )
    assert enum_name in item_in.group(2), (
        "the mutation input `status` must be typed as the canonical choices Enum, "
        f"not String; create input block:\n{item_in.group(0)}"
    )

    # A request-like context for the mutations (they read info.context.META).
    from django.test import RequestFactory

    _request = RequestFactory().post("/graphql/", content_type="application/json")

    # === EXERCISE 2: seed data ============================================= #
    author = Author.objects.create(name="alice")
    bob = Author.objects.create(name="bob")
    cat = Category.objects.create(title="news")
    for i in range(12):
        Post.objects.create(title="P%02d" % i, author=author, category=cat)

    # === EXERCISE 3: CREATE mutation (relation FK arg), child persisted ==== #
    create_field = re.search(r"postCreate\((\w+): (\w+)", sdl)
    assert create_field, "postCreate field/input not found in SDL"
    input_name = create_field.group(1)
    input_type = create_field.group(2)
    create_res = graphql_sync(
        gql,
        """mutation($newPost: %s!) {
              postCreate(%s: $newPost) {
                post { id title }
                ok
                errors { field messages }
              }
           }""" % (input_type, input_name),
        variable_values={"newPost": {"title": "fresh", "author": str(author.pk),
                                     "category": str(cat.pk)}},
        context_value=_request,
    )
    assert create_res.errors is None, create_res.errors
    created = create_res.data["postCreate"]
    assert created["ok"] is True, created
    assert created["post"]["title"] == "fresh", created
    new_pk = created["post"]["id"]
    assert Post.objects.filter(pk=new_pk, title="fresh", author=author).exists(), (
        "the CREATE mutation must persist the row with its FK relation"
    )

    # === EXERCISE 4: UPDATE mutation, relation re-pointed ================== #
    update_field = re.search(r"postUpdate\((\w+): (\w+)", sdl)
    assert update_field, "postUpdate field/input not found in SDL"
    u_input_name = update_field.group(1)
    u_input_type = update_field.group(2)
    update_res = graphql_sync(
        gql,
        """mutation($up: %s!) {
              postUpdate(%s: $up) {
                post { id title }
                ok
                errors { field messages }
              }
           }""" % (u_input_type, u_input_name),
        variable_values={"up": {"id": int(new_pk), "title": "edited",
                                "author": str(bob.pk)}},
        context_value=_request,
    )
    assert update_res.errors is None, update_res.errors
    updated = update_res.data["postUpdate"]
    assert updated["ok"] is True, updated
    assert updated["post"]["title"] == "edited", updated
    assert Post.objects.filter(pk=new_pk, title="edited", author=bob).exists(), (
        "the UPDATE mutation must persist the changed field + re-pointed FK"
    )

    # === EXERCISE 5: choices in a mutation INPUT (create an Item) ========== #
    item_create_field = re.search(r"itemCreate\((\w+): (\w+)", sdl)
    assert item_create_field, "itemCreate field/input not found in SDL"
    item_res = graphql_sync(
        gql,
        """mutation($it: %s!) {
              itemCreate(%s: $it) {
                enumcollisionitema { id status }
                ok
                errors { field messages }
              }
           }""" % (item_create_field.group(2), item_create_field.group(1)),
        variable_values={"it": {"status": "A"}},
        context_value=_request,
    )
    assert item_res.errors is None, item_res.errors
    item_payload = item_res.data["itemCreate"]
    assert item_payload["ok"] is True, item_payload
    # The Enum input value "A" deserializes to the raw stored value "a"; output
    # re-renders it as the Enum member "A".
    assert item_payload["enumcollisionitema"]["status"] == "A", item_payload
    assert EnumCollisionItemA.objects.filter(status="a").exists(), (
        "the choices Enum input value must persist as its raw stored value"
    )

    # === EXERCISE 6: limit/offset pagination (results + totalCount) ======== #
    lo = graphql_sync(
        gql,
        "query { allPosts { results(limit: 3, offset: 2) { title } totalCount } }",
    )
    assert lo.errors is None, lo.errors
    lo_data = lo.data["allPosts"]
    assert lo_data["totalCount"] == 13, lo_data  # 12 seeded + 1 created
    assert len(lo_data["results"]) == 3, lo_data

    # === EXERCISE 7: cursor pagination (results + pageInfo + cursors) ====== #
    cur = graphql_sync(
        gql,
        "query { postsCursor { results(first: 5) { id title } "
        "pageInfo(first: 5) { endCursor hasNextPage } totalCount } }",
    )
    assert cur.errors is None, cur.errors
    cur_data = cur.data["postsCursor"]
    assert cur_data["totalCount"] == 13, cur_data
    assert len(cur_data["results"]) == 5, cur_data
    assert cur_data["pageInfo"]["hasNextPage"] is True, cur_data
    assert cur_data["pageInfo"]["endCursor"], "cursor pageInfo must carry an endCursor"

    # === EXERCISE 8: choices on OUTPUT + as a FILTER ARG (runtime) ========= #
    # DjangoFilterPaginateListField returns a flat list (no `results` wrapper).
    out = graphql_sync(gql, "query { items { id status } }")
    assert out.errors is None, out.errors
    assert any(row["status"] == "A" for row in out.data["items"]), (
        "the choices field must render its Enum member on OUTPUT"
    )
    filt = graphql_sync(
        gql,
        "query { items(filter: { status: { exact: A } }) { id status } }",
    )
    assert filt.errors is None, filt.errors
    filtered = filt.data["items"]
    assert filtered and all(row["status"] == "A" for row in filtered), (
        "filtering by the choices Enum value must return only matching rows"
    )

    # === EXERCISE 9: deliver ONE subscription event end-to-end ============= #
    async def _drive_subscription_event():
        layer = InMemoryChannelLayer()
        sub = PostModelType.subscription_type()
        event_type = sub._build_native_event_type()
        ev_schema = GraphQLSchema(
            query=GraphQLObjectType("Query", lambda: {"ok": GraphQLField(GraphQLBoolean)}),
            subscription=GraphQLObjectType(
                "Subscription",
                lambda: {"postEvent": GraphQLField(event_type, resolve=lambda r, _i: r)},
            ),
        )
        doc = parse("subscription { postEvent { id title } }")
        spec = sub._build_native_spec(ev_schema, doc)
        source = await sub._native_subscribe(
            layer, ev_schema, doc, action="create", obj_id=None, filters=None,
            context=None,
        )
        delivery = drive_subscription(source, spec)
        group = source.joined_groups[0]
        await layer.group_send(group, {
            "type": "subscription.notify",
            "stream": "gate-posts",
            "group": group,
            "pk": 99,
            "payload": {"action": "create", "model": "tests.post",
                        "data": {"id": 99, "title": "live"}},
        })
        result = await asyncio.wait_for(delivery.__anext__(), timeout=2.0)
        await delivery.aclose()
        return result

    sub_result = asyncio.run(_drive_subscription_event())
    assert sub_result.errors is None, sub_result.errors
    assert sub_result.data == {"postEvent": {"id": "99", "title": "live"}}, sub_result.data

finally:
    sys.meta_path.remove(guard)

# === FINAL ASSERTIONS: graphene never entered the process. ================= #
leaked = [m for m in sys.modules if m == "graphene" or m.startswith("graphene.")]
assert not leaked, (
    "graphene LEAKED into sys.modules during the full native runtime exercise: "
    + ", ".join(sorted(leaked))
)
assert guard.fired == [], (
    "the graphene-blocking finder FIRED during the exercise — a production path "
    "tried to import graphene: " + ", ".join(guard.fired)
)
assert "graphene" not in sys.modules

print("ZERO_GRAPHENE_GATE_OK")
'''


def _run_gate_subprocess() -> subprocess.CompletedProcess:
    """Run the zero-graphene full-runtime exercise in a clean subprocess.

    A fresh process guarantees a pristine ``sys.modules`` and an isolated global
    output registry (sidestepping #1611 item 3), so the
    ``'graphene' not in sys.modules`` assertions are trustworthy.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-c", _CHILD],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_zero_graphene_full_runtime_exercise():
    """The full native runtime exercise imports ZERO graphene (permanent gate).

    Build SDL + execute create/update mutations (relation + choices args, child
    persisted) + resolve limit/offset and cursor pagination + deliver one
    subscription event + exercise a choices field on output/filter/input — all
    with graphene blocked at ``sys.meta_path`` — and ``graphene`` is absent from
    ``sys.modules`` before AND after, with the block never firing.
    """
    proc = _run_gate_subprocess()
    assert proc.returncode == 0, (
        "the zero-graphene full-runtime gate FAILED — a production runtime path "
        "imported graphene (or an exercise assertion failed).\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    assert "ZERO_GRAPHENE_GATE_OK" in proc.stdout, (
        "the gate child did not reach its success marker.\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
