"""S-rel-0 — native SDL parity seed (DELETE-LATER test scaffold).

This module is NET-NEW test infrastructure for the graphene-excision
campaign (plan #1605). It exposes ONE seed model graph that covers the full
Django relation taxonomy and renders its SDL on the native backend:

* "render_native_sdl" renders the seed schema on the NATIVE backend,
  IN-PROCESS, via the real "DjangoGraphQLSchema" native compiler. This is
  exactly the SDL the library produces today (the default for "tests/").

This module is GRAPHENE-FREE: every helper here builds and renders SDL through
the native compiler only. The S-rel-0 graphene-as-oracle scaffold that once
consumed a graphene baseline has been removed (S-del-tests-10); this seed, now
imported only by the permanent relation verifiers ("test_relation_*_native.py")
and the zero-graphene gate, carries no graphene dependency. The native helpers
below ("render_native_sdl" / "extract_type_block" / "extract_enum_block")
are the graphene-free surface those consumers rely on.

Seed taxonomy coverage (all reused from existing "tests" models):

* choices field: "EnumCollisionItemA.status" (CharField + choices,
  with per-choice labels Alpha/Beta as descriptions).
* ForeignKey: "Post.author" -> Author, "Post.category" -> Category.
* forward OneToOne: "AuthorProfile.author" -> Author.
* self-referential O2O: "PersonWithSpouse.spouse" -> self (issue #52 pattern).
* reverse OneToOne: "Author.author_profile" -> AuthorProfile.
* forward ManyToMany: "Post.tags" -> Tag, "Post.co_authors" -> Author.
* reverse ForeignKey: "Author.posts" -> Post, "Post.comments" -> Comment.
* reverse ManyToMany: "Tag.posts" -> Post, "Author.coauthored_posts" -> Post.
* GenericForeignKey (flat): "Track2GfkComment.target" -> GenericForeignKeyType.
* GenericRelation (list): "Profile.notes" -> OptNote (declared in
  "tests.test_optimizer_coverage").

The full node-type closure is registered so EVERY relation resolves on both
sides (an unregistered related node makes the Dynamic resolver drop the field,
that drop is a registration artifact, not a real divergence, so the seed
registers the whole closure to keep the comparison fair).
"""

from __future__ import annotations

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
    """Build the seed :class:DjangoGraphQLSchema on the native backend.

    Registers the FULL node-type closure (so every relation resolves) and a
    Query exposing one single-object field per node. Returns the
    DjangoGraphQLSchema instance (str(schema) renders its SDL).

    The node types use explicit class statements (NOT type(...)) because the
    DjangoObjectType (pydantic) metaclass requires a class-statement Meta
    rather than a dynamically attached one. They share one local
    :class:Registry so every relation thunk resolves against the same closure;
    pinning Meta.name keeps the SDL fragment names stable and aligned with
    the graphene baseline.
    """
    from django_graphex.core import ObjectType
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.fields import DjangoObjectField
    from django_graphex.registry import Registry
    from django_graphex.schema import DjangoGraphQLSchema
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
    """Render the seed schema's SDL on the NATIVE backend (in-process).

    Returns:
        sdl: The full SDL text produced by the native compiler for the seed
            schema built in "_build_native_seed_schema".
    """
    return str(_build_native_seed_schema())


# ---------------------------------------------------------------------------
# SDL fragment extraction helpers
# ---------------------------------------------------------------------------
def extract_type_block(sdl: str, type_name: str) -> str:
    """Return the "type <type_name> { ... }" block from an SDL string.

    Whitespace is normalized (leading/trailing stripped per line) but
    descriptions and field order are PRESERVED so a caller can assert on them.

    Args:
        sdl: The full SDL string.
        type_name: The GraphQL type name whose block to extract.

    Returns:
        block: The block text (header through closing brace), or an empty
            string if absent.
    """
    return _extract_block(sdl, "type", type_name)


def extract_enum_block(sdl: str, enum_name: str) -> str:
    """Return the "enum <enum_name> { ... }" block from an SDL string.

    Args:
        sdl: The full SDL string.
        enum_name: The GraphQL enum name whose block to extract.

    Returns:
        block: The block text (header through closing brace), or an empty
            string if absent.
    """
    return _extract_block(sdl, "enum", enum_name)


def _extract_block(sdl: str, keyword: str, name: str) -> str:
    """Extract a single <keyword> <name> {{ ... }} block, brace-balanced.

    Captures the (optional) description line immediately preceding the header so
    a leading \"\"\"...\"\"\" block-description travels with the block.
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
            if (
                len(tokens) >= 2
                and tokens[0] == keyword
                and tokens[1].rstrip("{") == name
            ):
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
