"""S-rel-0 — graphene-as-oracle SDL parity seed (DELETE-LATER test scaffold).

This module is **net-new test infrastructure** for the graphene-excision
campaign (plan #1605). It exposes ONE seed model graph that covers the full
Django relation taxonomy and two ways to render its SDL:

* :func:`render_native_sdl` — renders the seed schema on the NATIVE backend,
  IN-PROCESS, via the real :class:`DjangoGraphQLSchema` native compiler. This is
  exactly the SDL the library produces today on ``GDX_BACKEND=native`` (the
  default for ``tests/``).

* :func:`render_graphene_baseline_sdl` — renders the GRAPHENE-side baseline by
  spawning a ``GDX_BACKEND=graphene`` subprocess. Because ``GDX_BACKEND`` is read
  at import time, the backend CANNOT be flipped inside one process, so the
  baseline is generated out-of-process and its stdout captured. The baseline is
  regenerated from the currently-installed graphene each run (LIVE, not a stale
  golden file); callers cache it for the test session.

Why a subprocess and not ``graphene.Schema`` in-process
-------------------------------------------------------
At the campaign's current commit (S8h) the migration is already deep: every
``DjangoObjectType`` is re-parented off graphene (its MRO is native pydantic, no
``graphene.ObjectType``), so ``graphene.Schema`` rejects it via
``assert is_graphene_type``. ``DjangoGraphQLSchema`` itself ALWAYS builds through
the native compiler regardless of ``GDX_BACKEND`` (the graphene assembly branch
was removed in S6f). The ONE graphene producer that still renders a divergent
construct end-to-end is :func:`convert_django_field_with_choices`, which returns
a real ``graphene.Enum`` (with per-choice descriptions via
``EnumWithDescriptionsType``). The graphene baseline therefore reconstructs
graphene-django's historical model-type assembly — pure ``graphene.ObjectType``
classes built from the converter's ``construct_fields`` output — so the
choices-enum aspect produces a genuine, live graphene SDL fragment to compare
against. Relation aspects resolve (via the converter's Dynamic descriptors) to
the SAME related type NAMES the native compiler emits, so they already match
(those assertions are regression guards, not xfails).

Seed taxonomy coverage (all reused from existing ``tests`` models)
------------------------------------------------------------------
* choices field ........... ``EnumCollisionItemA.status`` (CharField + choices,
                            with per-choice labels Alpha/Beta as descriptions)
* ForeignKey .............. ``Post.author`` -> Author, ``Post.category`` -> Category
* forward OneToOne ........ ``AuthorProfile.author`` -> Author
* self-referential O2O .... ``PersonWithSpouse.spouse`` -> self (issue #52 pattern)
* reverse OneToOne ........ ``Author.author_profile`` -> AuthorProfile
* forward ManyToMany ...... ``Post.tags`` -> Tag, ``Post.co_authors`` -> Author
* reverse ForeignKey ...... ``Author.posts`` -> Post, ``Post.comments`` -> Comment
* reverse ManyToMany ...... ``Tag.posts`` -> Post, ``Author.coauthored_posts`` -> Post
* GenericForeignKey (flat)  ``Track2GfkComment.target`` -> GenericForeignKeyType
* GenericRelation (list) .. ``Profile.notes`` -> OptNote (declared in
                            ``tests.test_optimizer_coverage``)

The full node-type closure is registered so EVERY relation resolves on both
sides (an unregistered related node makes the Dynamic resolver drop the field —
that drop is a registration artifact, not a real divergence, so the seed
registers the whole closure to keep the comparison fair).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from typing import Any


# ---------------------------------------------------------------------------
# Seed model imports
#
# Most models live in ``tests/models.py`` and already cover the taxonomy. The
# GenericRelation case (``Profile.notes`` -> ``OptNote``) is declared at module
# scope in ``tests/test_optimizer_coverage.py``; importing it here registers the
# models in the shared ``tests`` app (idempotent — the metaclass registration
# runs once).
# ---------------------------------------------------------------------------
from tests.models import (  # noqa: E402
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
from tests.test_optimizer_coverage import OptNote, Profile  # noqa: E402


# ---------------------------------------------------------------------------
# Native seed schema
# ---------------------------------------------------------------------------
#: The seed model -> GraphQL type-name map. The same names are used on BOTH the
#: native and the graphene-baseline side so per-aspect SDL fragments line up.
SEED_TYPE_NAMES: dict[Any, str] = {
    Author: "PSAuthor",
    AuthorProfile: "PSAuthorProfile",
    Category: "PSCategory",
    Comment: "PSComment",
    EnumCollisionItemA: "PSItem",
    PersonWithSpouse: "PSPerson",
    Post: "PSPost",
    Tag: "PSTag",
    Track2GfkComment: "PSGfkComment",
    Profile: "PSProfile",
    OptNote: "PSNote",
}


def _build_native_seed_schema() -> Any:
    """Build the seed :class:`DjangoGraphQLSchema` on the native backend.

    Registers the FULL node-type closure (so every relation resolves) and a
    Query exposing one single-object field per node. Returns the
    ``DjangoGraphQLSchema`` instance (``str(schema)`` renders its SDL).

    The node types use explicit class statements (NOT ``type(...)``) because the
    ``DjangoObjectType`` (pydantic) metaclass requires a class-statement ``Meta``
    rather than a dynamically attached one. They share one local
    :class:`Registry` so every relation thunk resolves against the same closure;
    pinning ``Meta.name`` keeps the SDL fragment names stable and aligned with
    the graphene baseline.
    """
    from django_graphex import DjangoGraphQLSchema, ObjectType
    from django_graphex.fields import DjangoObjectField
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.registry import Registry
    from django_graphex.types import DjangoObjectType

    seed_registry = Registry()

    class PSAuthor(DjangoObjectType):
        class Meta:
            model = Author
            registry = seed_registry
            name = SEED_TYPE_NAMES[Author]

    class PSAuthorProfile(DjangoObjectType):
        class Meta:
            model = AuthorProfile
            registry = seed_registry
            name = SEED_TYPE_NAMES[AuthorProfile]

    class PSCategory(DjangoObjectType):
        class Meta:
            model = Category
            registry = seed_registry
            name = SEED_TYPE_NAMES[Category]

    class PSComment(DjangoObjectType):
        class Meta:
            model = Comment
            registry = seed_registry
            name = SEED_TYPE_NAMES[Comment]

    class PSItem(DjangoObjectType):
        class Meta:
            model = EnumCollisionItemA
            registry = seed_registry
            name = SEED_TYPE_NAMES[EnumCollisionItemA]

    class PSPerson(DjangoObjectType):
        class Meta:
            model = PersonWithSpouse
            registry = seed_registry
            name = SEED_TYPE_NAMES[PersonWithSpouse]

    class PSPost(DjangoObjectType):
        class Meta:
            model = Post
            registry = seed_registry
            name = SEED_TYPE_NAMES[Post]

    class PSTag(DjangoObjectType):
        class Meta:
            model = Tag
            registry = seed_registry
            name = SEED_TYPE_NAMES[Tag]

    class PSGfkComment(DjangoObjectType):
        class Meta:
            model = Track2GfkComment
            registry = seed_registry
            name = SEED_TYPE_NAMES[Track2GfkComment]

    class PSProfile(DjangoObjectType):
        class Meta:
            model = Profile
            registry = seed_registry
            name = SEED_TYPE_NAMES[Profile]

    class PSNote(DjangoObjectType):
        class Meta:
            model = OptNote
            registry = seed_registry
            name = SEED_TYPE_NAMES[OptNote]

    class Query(ObjectType):
        author = DjangoObjectField(PSAuthor)
        author_profile = DjangoObjectField(PSAuthorProfile)
        category = DjangoObjectField(PSCategory)
        comment = DjangoObjectField(PSComment)
        item = DjangoObjectField(PSItem)
        person = DjangoObjectField(PSPerson)
        post = DjangoObjectField(PSPost)
        tag = DjangoObjectField(PSTag)
        gfk_comment = DjangoObjectField(PSGfkComment)
        profile = DjangoObjectField(PSProfile)
        note = DjangoObjectField(PSNote)

    compile_all_outputs()
    return DjangoGraphQLSchema(query=Query)


def render_native_sdl() -> str:
    """Render the seed schema's SDL on the NATIVE backend (in-process)."""
    return str(_build_native_seed_schema())


# ---------------------------------------------------------------------------
# Graphene baseline (subprocess)
# ---------------------------------------------------------------------------
# The child program runs under ``GDX_BACKEND=graphene``. It rebuilds the SAME
# seed models as PURE ``graphene.ObjectType`` classes from the converter's
# ``construct_fields`` output (graphene-django's historical assembly), renders
# them through ``graphene.Schema``, and prints a JSON envelope:
#   {"choices_enum_sdl": "<SDL fragment for the choices enum + owner type>"}
#
# Only the choices-enum aspect produces a divergent graphene construct at this
# commit; relation aspects resolve to the same related-type names the native
# compiler emits (regression guards on the native side). Keeping the baseline as
# a live subprocess (not a golden file) means it tracks the installed graphene.
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


# ---------------------------------------------------------------------------
# SDL fragment extraction helpers
# ---------------------------------------------------------------------------
def extract_type_block(sdl: str, type_name: str) -> str:
    """Return the ``type <type_name> {{ ... }}`` block from an SDL string.

    Whitespace is normalized (leading/trailing stripped per line) but
    descriptions and field order are PRESERVED so a caller can assert on them.

    Args:
        sdl: the full SDL string.
        type_name: the GraphQL type name whose block to extract.

    Returns:
        The block text (header through closing brace), or ``""`` if absent.
    """
    return _extract_block(sdl, "type", type_name)


def extract_enum_block(sdl: str, enum_name: str) -> str:
    """Return the ``enum <enum_name> {{ ... }}`` block from an SDL string."""
    return _extract_block(sdl, "enum", enum_name)


def _extract_block(sdl: str, keyword: str, name: str) -> str:
    """Extract a single ``<keyword> <name> {{ ... }}`` block, brace-balanced.

    Captures the (optional) description line immediately preceding the header so
    a leading ``\"\"\"...\"\"\"`` block-description travels with the block.
    """
    lines = sdl.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{keyword} {name} ") or stripped in (
            f"{keyword} {name}",
            f"{keyword} {name}{{",
            f"{keyword} {name} {{",
        ):
            # Confirm the next token is the name exactly (avoid prefix matches).
            tokens = stripped.split()
            if len(tokens) >= 2 and tokens[0] == keyword and tokens[1].rstrip("{") == name:
                header_idx = i
                break
    if header_idx is None:
        return ""

    # Walk back over an immediately-preceding block description (\"\"\" ... \"\"\").
    start_idx = header_idx
    j = header_idx - 1
    desc_lines: list[str] = []
    if j >= 0 and lines[j].strip().endswith('"""'):
        # collect a (possibly multi-line) description block above the header
        k = j
        while k >= 0:
            desc_lines.insert(0, lines[k])
            if lines[k].strip().startswith('"""') and (
                k != j or lines[k].strip() != '"""'
            ):
                break
            if lines[k].strip() == '"""' and k != j:
                break
            k -= 1
        start_idx = k

    # Walk forward, brace-balanced.
    depth = 0
    end_idx = header_idx
    seen_open = False
    for i in range(header_idx, len(lines)):
        depth += lines[i].count("{")
        depth -= lines[i].count("}")
        if "{" in lines[i]:
            seen_open = True
        end_idx = i
        if seen_open and depth <= 0:
            break

    block = lines[start_idx : end_idx + 1]
    return "\n".join(ln.rstrip() for ln in block).strip()
