"""S-rel-0 — graphene-as-oracle SDL parity tests (DELETE-LATER scaffold).

Per-aspect SDL parity assertions for the graphene-excision campaign (plan #1605).
Each test isolates ONE taxonomy aspect (a single type/field/enum/container) from
the seed schema's NATIVE SDL and compares it against the GRAPHENE baseline so a
later migration slice can flip exactly one aspect from divergent -> matching.

Aspect states at this commit (S8h), verified empirically (NOT assumed):

* choices-enum .............. PASS-NOW (S-enum-1 applied) — native now renders a
                            real ``GraphQLEnumType`` (canonical name + per-choice
                            descriptions) byte-for-byte matching graphene. Was the
                            XFAIL canary until S-enum-1; the marker is removed and
                            this is now a regression guard like the others.
* FK output ................. PASS-NOW (native already renders ``author: PSAuthor``)
* forward-O2O output ........ PASS-NOW
* self-ref-O2O output ....... PASS-NOW (issue #52 spouse pattern, never dropped)
* reverse-O2O output ........ PASS-NOW
* M2M list container ........ PASS-NOW (``tags: TagListType`` results/totalCount)
* reverse-FK list ........... PASS-NOW (``comments: CommentListType``)
* reverse-M2M list .......... PASS-NOW (``coauthoredPosts: PostListType``)
* GFK flat .................. PASS-NOW (``target: GenericForeignKeyType``)
* GenericRelation list ...... PASS-NOW (``notes: OptNoteListType``)
* relation INPUT types ...... PASS-NOW (FK/O2O -> ID in create input)
* pagination container ...... PASS-NOW (``results(limit/offset/ordering)`` + totalCount)
* subscription root args .... PASS-NOW (``action: <Action>!`` enum arg)

The PASS-NOW aspects are NOT xfail: they assert-pass today and act as REGRESSION
GUARDS so a later slice that touches relation rendering cannot silently break a
shape that already matches. Only genuinely-divergent aspects are xfail(strict).

Why the graphene baseline is per-aspect, not a full schema diff: at S8h graphene
can no longer assemble a full schema for the migrated ``DjangoObjectType``s (its
MRO is native; ``graphene.Schema`` rejects it). The ONE graphene producer that
still renders a divergent construct end-to-end is the choices ``graphene.Enum``;
relation aspects resolve (via the converter's Dynamic) to the SAME related type
NAMES native emits, so they already match. See ``_sdl_parity_seed`` for detail.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap

import pytest

from tests.native.conftest import normalize_sdl

from ._sdl_parity_seed import (
    extract_enum_block,
    extract_type_block,
    render_native_sdl,
)

pytestmark = pytest.mark.native_only


# --------------------------------------------------------------------------- #
# Graphene baseline (subprocess) — DELETE-LATER oracle machinery.              #
#                                                                              #
# This block lives in the ORACLE (a graphene-dependent, delete-later artifact) #
# rather than in ``_sdl_parity_seed`` so that the seed — imported by the       #
# PERMANENT relation verifiers and the zero-graphene gate — stays graphene-    #
# free. The child program runs under ``GDX_BACKEND=graphene``. It rebuilds the #
# choices owner as a PURE ``graphene.ObjectType`` from the converter's         #
# ``construct_fields`` output (graphene-django's historical assembly), renders #
# it through ``graphene.Schema``, and prints a JSON envelope:                  #
#   {"choices_enum_sdl": "<SDL fragment for the choices enum + owner type>"}   #
#                                                                              #
# Only the choices-enum aspect produces a divergent graphene construct at this #
# commit; relation aspects resolve to the same related-type names the native   #
# compiler emits (regression guards on the native side). Keeping the baseline  #
# a live subprocess (not a golden file) means it tracks the installed graphene.#
# --------------------------------------------------------------------------- #
_GRAPHENE_CHILD = textwrap.dedent(
    '''
    import json
    import django
    from django.conf import settings

    settings.configure(
        ALLOWED_HOSTS=["*"],
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        SITE_ID=1,
        SECRET_KEY="x",
        USE_I18N=True,
        STATIC_URL="/static/",
        INSTALLED_APPS=(
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.sites",
            "django.contrib.staticfiles",
            "tests",
        ),
        PASSWORD_HASHERS=("django.contrib.auth.hashers.MD5PasswordHasher",),
        GRAPHEX={"SCHEMA": "tests.schema.schema"},
    )
    django.setup()

    import graphene
    from graphql.utilities import print_schema

    from django_graphex.converter import convert_django_field_with_choices
    from django_graphex.registry import Registry
    from tests.models import EnumCollisionItemA

    # Reconstruct graphene-django's historical assembly for the choices owner:
    # a PURE graphene.ObjectType whose ``status`` field is the converter's real
    # graphene.Enum (with per-choice descriptions via EnumWithDescriptionsType).
    reg = Registry()
    status_field = convert_django_field_with_choices(
        EnumCollisionItemA._meta.get_field("status"), reg
    )

    PSItem = type(
        "PSItem",
        (graphene.ObjectType,),
        {"__module__": __name__, "id": graphene.ID(), "status": status_field},
    )

    class Query(graphene.ObjectType):
        item = graphene.Field(PSItem)

    schema = graphene.Schema(query=Query, types=[PSItem])
    sdl = print_schema(schema.graphql_schema)

    print("GDX_PARITY_JSON:" + json.dumps({"choices_enum_sdl": sdl}))
    '''
)


def render_graphene_baseline() -> dict[str, str]:
    """Render the GRAPHENE-side baseline via a ``GDX_BACKEND=graphene`` subprocess.

    Returns a dict of per-aspect graphene SDL fragments. Spawns the child with
    the SAME interpreter (``sys.executable``) and the repo root on ``PYTHONPATH``
    so ``tests`` and ``django_graphex`` import identically.

    Returns:
        A mapping with at least ``"choices_enum_sdl"`` — the full SDL the
        graphene path renders for the choices owner type + its enum.

    Raises:
        RuntimeError: if the subprocess fails or its marker line is missing.
    """
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
    )
    env = dict(os.environ)
    env["GDX_BACKEND"] = "graphene"
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(
        [sys.executable, "-c", _GRAPHENE_CHILD],
        capture_output=True,
        text=True,
        env=env,
        cwd=repo_root,
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "graphene baseline subprocess failed "
            f"(rc={proc.returncode}).\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )

    marker = "GDX_PARITY_JSON:"
    for line in proc.stdout.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker):])

    raise RuntimeError(
        "graphene baseline subprocess produced no GDX_PARITY_JSON marker.\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )


# --------------------------------------------------------------------------- #
# Session-scoped fixtures: render each SDL ONCE.                                #
# - native SDL: in-process (fast).                                             #
# - graphene baseline: spawns ONE GDX_BACKEND=graphene subprocess; cached for  #
#   the whole module so per-aspect assertions don't re-spawn it.               #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def native_sdl() -> str:
    """The seed schema's NATIVE SDL (rendered in-process, once per module)."""
    return render_native_sdl()


@pytest.fixture(scope="module")
def graphene_baseline() -> dict[str, str]:
    """The GRAPHENE baseline fragments (one subprocess, cached per module)."""
    return render_graphene_baseline()


# --------------------------------------------------------------------------- #
# Description-preserving enum normalizer (requirement #7).                      #
#                                                                              #
# ``normalize_sdl`` STRIPS all descriptions. For the choices-enum aspect that  #
# would let S-enum-1 silently drop the per-choice descriptions graphene emits  #
# (Alpha/Beta via EnumWithDescriptionsType). This normalizer sorts enum value  #
# lines but KEEPS the description lines so the comparison fails if descriptions #
# disappear.                                                                    #
# --------------------------------------------------------------------------- #
def _normalize_enum_with_descriptions(enum_block: str) -> str:
    """Normalize an ``enum`` SDL block, PRESERVING value descriptions.

    Drops the block-level description and leading ``enum X {`` header noise but
    keeps each value's preceding ``\"\"\"...\"\"\"`` description paired with the
    value, then sorts the (description, value) pairs for order independence.
    """
    lines = [ln.strip() for ln in enum_block.splitlines() if ln.strip()]
    # Find the body between { and }.
    try:
        open_i = next(i for i, ln in enumerate(lines) if ln.endswith("{"))
        close_i = next(i for i, ln in enumerate(lines) if ln == "}")
    except StopIteration:
        return enum_block.strip()

    body = lines[open_i + 1 : close_i]
    # Pair each value with its immediately-preceding inline description, if any.
    pairs: list[tuple[str, str]] = []
    pending_desc = ""
    for ln in body:
        if ln.startswith('"""') and ln.endswith('"""') and len(ln) > 3:
            pending_desc = ln
            continue
        if ln.startswith('"""'):
            pending_desc = ln
            continue
        # An enum VALUE token (identifier).
        pairs.append((pending_desc, ln))
        pending_desc = ""

    pairs.sort()
    rendered = "\n".join(f"{d}\n{v}" if d else v for d, v in pairs)
    return rendered.strip()


def _enum_name_in(sdl: str) -> str | None:
    """Return the first ``enum <Name>`` name in an SDL string, or None."""
    match = re.search(r"\benum\s+(\w+)", sdl)
    return match.group(1) if match else None


# --------------------------------------------------------------------------- #
# choices-enum aspect — THE CANARY (XFAIL strict, pending S-enum-1)            #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_choices_enum_output_parity(native_sdl, graphene_baseline):
    """The choices field's OUTPUT must render as the SAME enum on both backends.

    Since S-enum-1 the native output_compiler renders ``status: <Enum>`` plus an
    ``enum`` block WITH per-choice descriptions, matching graphene. The assertion
    compares the enum BLOCK (description-preserving) AND that the owner type's
    ``status`` field references an enum, not String.
    """
    graphene_sdl = graphene_baseline["choices_enum_sdl"]
    graphene_enum_name = _enum_name_in(graphene_sdl)
    assert graphene_enum_name, "graphene baseline must contain an enum block"

    # 1) The graphene owner type renders ``status`` as the enum (sanity on the
    #    oracle's baseline — proves the divergence is real, not a test artifact).
    graphene_owner = extract_type_block(graphene_sdl, "PSItem")
    assert f"status: {graphene_enum_name}" in graphene_owner

    # 2) Native must reference an enum for ``status`` (today it renders String).
    native_owner = extract_type_block(native_sdl, "PSItem")
    assert "status: String" not in native_owner, (
        "native still renders the choices field as String (S-enum-1 not applied)"
    )
    native_enum_name = _enum_name_in(native_sdl)
    assert native_enum_name, "native SDL must contain an enum block for the choices field"

    # 3) The enum BLOCKS must match WITH descriptions preserved (so S-enum-1
    #    cannot silently drop the per-choice help_text descriptions).
    native_enum = _normalize_enum_with_descriptions(
        extract_enum_block(native_sdl, native_enum_name)
    )
    graphene_enum = _normalize_enum_with_descriptions(
        extract_enum_block(graphene_sdl, graphene_enum_name)
    )
    assert native_enum == graphene_enum, (
        "choices enum block (with descriptions) diverges:\n"
        f"native:\n{native_enum}\n\ngraphene:\n{graphene_enum}"
    )


# --------------------------------------------------------------------------- #
# Relation OUTPUT aspects — PASS-NOW regression guards.                         #
#                                                                              #
# Each asserts the native SDL renders the expected related-type reference. The #
# graphene producer (the converter's Dynamic) resolves to the SAME type names, #
# so these match today; the guards lock that parity so a later relation slice  #
# cannot regress a shape that already agrees.                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_fk_output_renders_related_type(native_sdl):
    """ForeignKey output renders ``author: PSAuthor`` / ``category: PSCategory``."""
    post = normalize_sdl(extract_type_block(native_sdl, "PSPost"))
    assert "author: PSAuthor" in post
    assert "category: PSCategory" in post


@pytest.mark.django_db
def test_forward_o2o_output_renders_related_type(native_sdl):
    """Forward OneToOne output renders ``author: PSAuthor`` on the profile type."""
    profile = normalize_sdl(extract_type_block(native_sdl, "PSAuthorProfile"))
    assert "author: PSAuthor" in profile


@pytest.mark.django_db
def test_self_ref_o2o_output_renders_self(native_sdl):
    """Self-referential O2O renders ``spouse: PSPerson`` (issue #52: never dropped)."""
    person = normalize_sdl(extract_type_block(native_sdl, "PSPerson"))
    assert "spouse: PSPerson" in person


@pytest.mark.django_db
def test_reverse_o2o_output_renders_related_type(native_sdl):
    """Reverse OneToOne renders ``authorProfile: PSAuthorProfile`` on the author."""
    author = normalize_sdl(extract_type_block(native_sdl, "PSAuthor"))
    assert "authorProfile: PSAuthorProfile" in author


@pytest.mark.django_db
def test_m2m_list_container_output(native_sdl):
    """Forward M2M renders a list CONTAINER: ``tags: TagListType`` / ``coAuthors``."""
    post = normalize_sdl(extract_type_block(native_sdl, "PSPost"))
    assert "tags: TagListType" in post
    assert "coAuthors: AuthorListType" in post


@pytest.mark.django_db
def test_reverse_fk_list_output(native_sdl):
    """Reverse FK renders a list container: ``comments: CommentListType``."""
    post = normalize_sdl(extract_type_block(native_sdl, "PSPost"))
    assert "comments: CommentListType" in post


@pytest.mark.django_db
def test_reverse_m2m_list_output(native_sdl):
    """Reverse M2M renders ``posts: PostListType`` (Tag) and ``coauthoredPosts``."""
    tag = normalize_sdl(extract_type_block(native_sdl, "PSTag"))
    assert "posts: PostListType" in tag
    author = normalize_sdl(extract_type_block(native_sdl, "PSAuthor"))
    assert "coauthoredPosts: PostListType" in author


@pytest.mark.django_db
def test_gfk_flat_output(native_sdl):
    """GFK (flat) renders ``target: GenericForeignKeyType`` + the flat type block."""
    comment = normalize_sdl(extract_type_block(native_sdl, "PSGfkComment"))
    assert "target: GenericForeignKeyType" in comment
    gfk = normalize_sdl(extract_type_block(native_sdl, "GenericForeignKeyType"))
    assert "appLabel: String" in gfk
    assert "id: ID" in gfk
    assert "modelName: String" in gfk


@pytest.mark.django_db
def test_generic_relation_list_output(native_sdl):
    """GenericRelation renders a list container: ``notes: OptNoteListType``."""
    profile = normalize_sdl(extract_type_block(native_sdl, "PSProfile"))
    assert "notes: OptNoteListType" in profile


@pytest.mark.django_db
def test_pagination_container_shape(native_sdl):
    """A list container exposes ``results(limit/offset/ordering)`` + ``totalCount``."""
    container = extract_type_block(native_sdl, "PostListType")
    assert container, "PostListType container must be present in the native SDL"
    # The results field carries limit/offset/ordering args; totalCount is Int.
    assert "results(" in container
    assert "limit: Int" in container
    assert "offset: Int" in container
    assert "ordering: String" in container
    assert "totalCount: Int" in container
    # The element type is the seed node.
    assert "[PSPost]" in container


# --------------------------------------------------------------------------- #
# Relation INPUT aspect — PASS-NOW regression guard.                            #
#                                                                              #
# For non-nested create input types, FK/O2O relations become ID scalars and    #
# M2M/reverse become [ID]. Asserted on the native input-type compile output.    #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_relation_input_types_use_id(native_sdl):
    """FK/O2O input fields become ID; M2M/reverse become list-of-ID.

    Builds a native create input type for Post and asserts the relation fields
    are ID-shaped (the input-side parity each later input slice preserves).
    """
    from graphql import (
        GraphQLID,
        GraphQLInputObjectType,
        GraphQLList,
        GraphQLNonNull,
    )

    from django_graphex.registry import Registry
    from django_graphex.types import DjangoInputObjectType
    from tests.models import Post

    # Use a LOCAL registry so the (Post, "create") global slot is NOT polluted —
    # GenericFirstOrderingTest in tests/test_nested_input_types.py asserts on the
    # GLOBAL (Post, "create") input type name and would break otherwise.
    input_registry = Registry()

    class _ParityPostCreateInput(DjangoInputObjectType):
        class Meta:
            model = Post
            input_for = "create"
            registry = input_registry

    gql_input = _ParityPostCreateInput._meta.graphql_input_type
    assert isinstance(gql_input, GraphQLInputObjectType)
    fields = gql_input.fields

    def _unwrap(t):
        while isinstance(t, GraphQLNonNull):
            t = t.of_type
        return t

    # FK author -> ID (non-nested input).
    assert "author" in fields
    assert _unwrap(fields["author"].type) is GraphQLID, (
        f"FK input field must be ID, got {fields['author'].type!r}"
    )

    # M2M tags -> [ID] (a list whose element unwraps to ID).
    assert "tags" in fields
    tags_type = _unwrap(fields["tags"].type)
    assert isinstance(tags_type, GraphQLList), (
        f"M2M input field must be a list, got {fields['tags'].type!r}"
    )
    assert _unwrap(tags_type.of_type) is GraphQLID, (
        f"M2M input list element must be ID, got {tags_type.of_type!r}"
    )


# --------------------------------------------------------------------------- #
# Subscription root args aspect — PASS-NOW regression guard.                    #
#                                                                              #
# A native subscription field carries an ``action: <Model>SubscriptionAction!`` #
# enum arg. S-sub-6 retires the graphene subscription factories; this guard     #
# locks that the native subscription root arg + action enum stay intact.        #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_subscription_root_action_arg_and_enum():
    """The native subscription root renders an ``action`` enum argument."""
    import graphene
    from graphql.utilities import print_schema

    from django_graphex import DjangoModelType
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import Author, Category, Post, Tag

    # Register the node closure so the event payload type assembles.
    class _SubAuthor(DjangoObjectType):
        class Meta:
            model = Author

    class _SubTag(DjangoObjectType):
        class Meta:
            model = Tag

    class _SubCategory(DjangoObjectType):
        class Meta:
            model = Category

    class _SubPost(DjangoObjectType):
        class Meta:
            model = Post

    class _SubPostModel(DjangoModelType):
        class Meta:
            model = Post
            stream = "posts"
            serialize_data = True

    class _SubQuery(graphene.ObjectType):
        ok = graphene.Boolean()

    class _SubRoot(graphene.ObjectType):
        post = _SubPostModel.SubscriptionField()

    compile_all_outputs()
    schema = DjangoGraphQLSchema(query=_SubQuery, subscription=_SubRoot)
    sdl = print_schema(schema.graphql_schema)

    sub_block = extract_type_block(sdl, "_SubRoot")
    assert sub_block, "subscription root type must be present in the SDL"
    # The ``post`` subscription field carries an ``action`` arg typed as a
    # non-null action enum.
    assert "action:" in sub_block
    action_enum = re.search(r"action:\s*(\w+)!", sub_block)
    assert action_enum, f"subscription field must carry a non-null action enum arg:\n{sub_block}"
    enum_block = normalize_sdl(extract_enum_block(sdl, action_enum.group(1)))
    # The action enum exposes the model-change actions.
    for value in ("CREATE", "UPDATE", "DELETE"):
        assert value in enum_block, f"action enum missing {value}:\n{enum_block}"
