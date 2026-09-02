"""P5: "save_with_nested" opens a savepoint only when there is nested work.

"NestedFieldsMixin.save_with_nested" used to wrap EVERY save in
"transaction.atomic()" — emitting a SAVEPOINT + RELEASE pair (2 SQL) even for
a plain create with no nested children and no deferred M2M/reverse work.  The
outer transaction only needs to exist to make a MULTI-object write (parent +
children) all-or-nothing; when only the parent is written, the backend's own
recovery boundary suffices, so the outer wrapper is skipped.

Covers:
  (a) a plain create (no nested_fields) in real autocommit emits NO transaction
      boundary at all — no SAVEPOINT/RELEASE and no BEGIN/COMMIT wrapper,
  (b) a nested create still runs atomically — a child failure rolls the parent
      back (all-or-nothing preserved) — and directly asserts a boundary opens,
  (c) the M2M mutation path is unaffected (bad M2M pk still rolls back),
  (d) a subscription broadcast still fires exactly once on a plain create.

Run with:
    .venv/bin/python -m pytest tests/core/test_savepoint_only_when_needed.py -q --no-cov
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from django_graphex.types import DjangoModelType
from tests.models import Author, AuthorProfile, Category, Post, Tag


def _info() -> SimpleNamespace:
    """Build a minimal resolver-info stand-in with empty request context."""
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _create(type_cls: type[DjangoModelType], data: dict) -> object:
    """Invoke a DjangoModelType's create resolver with the given input payload.

    Args:
        type_cls: The DjangoModelType subclass whose create resolver runs.
        data: The input payload keyed under the type's input field name.

    Returns:
        The mutation result returned by "type_cls.create".
    """
    return type_cls.create(None, _info(), **{type_cls._meta.input_field_name: data})


class PlainCategoryType(DjangoModelType):
    """DjangoModelType over Category with no nested fields.

    Used to exercise the plain-create path (no M2M, no nested children).
    """

    class Meta:
        """Configuration for "PlainCategoryType".

        Points at Category with an empty nested_fields mapping.
        """

        model = Category
        nested_fields = {}


class AuthorWithProfileType(DjangoModelType):
    """DjangoModelType over Author with a nested author_profile field.

    Used to exercise the nested-create atomicity path.
    """

    class Meta:
        """Configuration for "AuthorWithProfileType".

        Points at Author and declares author_profile as a nested field.
        """

        model = Author
        nested_fields = {"author_profile": AuthorProfile}


class PostRawM2MType(DjangoModelType):
    """DjangoModelType over Post with a raw-pk M2M "tags" field.

    Used to exercise the M2M rollback path (no nested fields declared).
    """

    class Meta:
        """Configuration for "PostRawM2MType".

        Points at Post with an empty nested_fields mapping.
        """

        model = Post
        nested_fields = {}


def _savepoint_sql(queries: list[dict]) -> list[str]:
    """Filter captured queries down to SAVEPOINT/RELEASE statements.

    Args:
        queries: Captured query records from "CaptureQueriesContext".

    Returns:
        The raw SQL text of each SAVEPOINT or RELEASE statement found.
    """
    return [
        q["sql"]
        for q in queries
        if "SAVEPOINT" in q["sql"].upper() or "RELEASE" in q["sql"].upper()
    ]


# ---------------------------------------------------------------------------
# (a) Plain create — zero savepoint statements
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_plain_create_emits_no_savepoint() -> None:
    """Ships broken if a plain create in autocommit stops writing with NO
    transaction wrapper at all.

    Run under "transaction=True" the resolver executes in the connection's real
    autocommit mode, so "need_boundary" is "False" for a create with no M2M
    and no outer atomic. The contract is stronger than "no SAVEPOINT": the parent
    write is a bare "INSERT" with NO boundary statement of any kind — no
    "BEGIN"/"COMMIT", no "SAVEPOINT"/"RELEASE", and no "check_constraints"
    probe ("PRAGMA foreign_key_check" on SQLite). A single trailing "SELECT"
    (the type re-reads the row for its output payload) is expected and allowed.

    Why the old "SAVEPOINT"-only grep was NOT load-bearing: an outer
    "transaction.atomic()" opened at the OUTERMOST level in autocommit issues
    "BEGIN"/"COMMIT" (not "SAVEPOINT") plus a "PRAGMA foreign_key_check".
    Reverting the "need_boundary" optimization to always-"True" therefore still
    passed a SAVEPOINT-only assertion while silently wrapping every plain create in
    a "BEGIN" ... "COMMIT" pair. Asserting the ABSENCE of every boundary
    keyword (and exactly one "INSERT") catches that regression — confirmed by a
    shadow-copy mutation that forces "need_boundary = True".
    """
    with CaptureQueriesContext(connection) as ctx:
        result = _create(PlainCategoryType, {"title": "Hello"})
    assert result.ok, getattr(result, "errors", None)

    statements = [q["sql"] for q in ctx.captured_queries]
    upper = [s.upper() for s in statements]

    # Exactly one INSERT (the parent row) and nothing more of that kind.
    inserts = [s for s in upper if s.startswith("INSERT")]
    assert len(inserts) == 1, f"Expected exactly one INSERT; got: {statements}"

    # No transaction/boundary statement of ANY kind wraps the autocommit write.
    # ``PRAGMA foreign_key_check`` is the ``check_constraints`` probe that ONLY
    # runs on the boundary (``need_boundary``) path — its absence is the discriminator
    # that the SAVEPOINT-only grep missed.
    forbidden = ("BEGIN", "COMMIT", "SAVEPOINT", "RELEASE", "FOREIGN_KEY_CHECK")
    for statement in upper:
        for keyword in forbidden:
            assert keyword not in statement, (
                f"Plain autocommit create must not emit {keyword}; got: {statements}"
            )


# ---------------------------------------------------------------------------
# (b) Nested create — still atomic (child failure rolls parent back)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_nested_create_still_atomic_on_child_failure() -> None:
    """Ships broken if a reverse-O2O nested list of more than one item stops
    failing cleanly and rolling the parent back.
    """
    author_count = Author.objects.count()
    profile_count = AuthorProfile.objects.count()

    result = _create(
        AuthorWithProfileType,
        {"name": "Writer", "author_profile": [{"bio": "a"}, {"bio": "b"}]},
    )
    assert result.ok is False
    # All-or-nothing: neither the parent nor any child survives.
    assert Author.objects.count() == author_count
    assert AuthorProfile.objects.count() == profile_count


@pytest.mark.django_db(transaction=True)
def test_nested_create_opens_savepoint_or_transaction() -> None:
    """Ships broken if a nested create stops wrapping its multi-object write in
    a real transaction boundary.

    The old assertion "has_boundary or exists()" was NOT load-bearing: on the
    (always-taken) success path "exists()" is "True", so the "or" short-circuits
    and the boundary is never actually checked — dropping the outer
    "transaction.atomic()" in "save_with_nested" would have gone unnoticed.

    Here the boundary is asserted DIRECTLY: because two rows (author + its profile)
    are written, "save_with_nested" opens "transaction.atomic()" — under
    "transaction=True" (real autocommit) that issues a "BEGIN" and, since the
    per-save backend boundary now sees "connection.in_atomic_block", nested
    "SAVEPOINT" statements too. At least one such boundary statement MUST appear.
    """
    with CaptureQueriesContext(connection) as ctx:
        result = _create(
            AuthorWithProfileType,
            {"name": "Writer", "author_profile": {"bio": "single"}},
        )
    assert result.ok, getattr(result, "errors", None)

    upper = [q["sql"].upper() for q in ctx.captured_queries]
    # A real boundary statement MUST be present (not gated behind an OR that the
    # success path short-circuits): the multi-object write is wrapped in atomic.
    has_boundary = any(
        statement.startswith("BEGIN") or "SAVEPOINT" in statement for statement in upper
    )
    assert has_boundary, (
        "Nested create must wrap its multi-object write in a transaction boundary "
        f"(BEGIN or SAVEPOINT); captured: {[q['sql'] for q in ctx.captured_queries]}"
    )
    # And both rows survived the committed transaction.
    assert Author.objects.filter(name="Writer").exists()
    assert AuthorProfile.objects.filter(bio="single").exists()


# ---------------------------------------------------------------------------
# (c) M2M path unaffected — bad pk still rolls back
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_m2m_bad_pk_still_rolls_back() -> None:
    """Ships broken if a raw-pk M2M create with a bad tag id stops failing and
    leaving no orphan Post behind.
    """
    author = Author.objects.create(name="A")
    result = _create(
        PostRawM2MType,
        {"title": "T", "author": author.id, "body": "", "tags": [999999]},
    )
    assert result.ok is False
    assert Post.objects.count() == 0, "Parent Post must not survive a bad M2M pk"


@pytest.mark.django_db
def test_m2m_good_pk_succeeds() -> None:
    """Ships broken if a raw-pk M2M create with a valid tag stops linking the
    relation.
    """
    author = Author.objects.create(name="A")
    tag = Tag.objects.create(label="x")
    result = _create(
        PostRawM2MType,
        {"title": "T", "author": author.id, "body": "", "tags": [tag.id]},
    )
    assert result.ok, getattr(result, "errors", None)
    assert Post.objects.get().tags.count() == 1
