"""P4: FK existence check moves to the failure path.

The happy path must not issue a pre-"SELECT 1" per FK: it attempts
"obj.save()" directly and, only on "IntegrityError", runs the existing
"_db_check_errors" diagnostics to produce the same per-field "ErrorType"
envelope as before.

Covers:
  (a) a happy-path create issues no "SELECT 1" FK pre-existence probe,
  (b) a bad FK id still returns "ok=False" with the exact same "errors[]"
      payload as the eager check produced (captured as the golden),
  (c) the update path behaves the same,
  (d) a multi-FK model attributes the error to the correct field,
  (e) the true-autocommit hot path ("need_boundary=False", run under
      "transaction=True"): a bad FK still yields the golden envelope with zero
      rows persisted, and a good FK is a single INSERT with no boundary SQL.

Run with:
    .venv/bin/python -m pytest tests/core/test_fk_check_failure_path.py -q
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from django_graphex.core.backend import PydanticBackend
from django_graphex.types import DjangoModelType
from tests.models import Author, Category, Post


def _info() -> SimpleNamespace:
    """Build a minimal GraphQL "info"-like object for direct backend calls.

    Returns:
        info: A "SimpleNamespace" exposing the "context.META"/"context.FILES"
            attributes the backend reads off "info.context".
    """
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _fk_existence_probes(
    queries: list[dict[str, str]], related_model: type
) -> list[str]:
    """Return Django ``QuerySet.exists()`` probes for a related model pk."""
    table = connection.ops.quote_name(related_model._meta.db_table)
    pk_column = connection.ops.quote_name(related_model._meta.pk.column)
    return [
        query["sql"]
        for query in queries
        if "SELECT 1 AS" in query["sql"].upper()
        and f"FROM {table}" in query["sql"]
        and f"{table}.{pk_column}" in query["sql"]
        and "LIMIT 1" in query["sql"].upper()
    ]


class PostType(DjangoModelType):
    """Native "DjangoModelType" mount for "Post".

    Used to exercise "create"/"update" end-to-end through the type's public
    mutation classmethods.
    """

    class Meta:
        """Mounting configuration: model "Post" with no nested input fields.

        "nested_fields" is empty so FK inputs are plain scalar ids, which is
        what this module's FK-existence-check tests exercise.
        """

        model = Post
        nested_fields = {}


def _create(type_cls: type[DjangoModelType], data: dict) -> object:
    """Call a "DjangoModelType" subclass's "create" classmethod with the given input payload.

    Args:
        type_cls: The "DjangoModelType" subclass to invoke "create" on.
        data: The input field payload to pass under the type's declared
            input field name.

    Returns:
        result: The mutation result object returned by "type_cls.create".
    """
    return type_cls.create(None, _info(), **{type_cls._meta.input_field_name: data})


def _update(type_cls: type[DjangoModelType], data: dict) -> object:
    """Call a "DjangoModelType" subclass's "update" classmethod with the given input payload.

    Args:
        type_cls: The "DjangoModelType" subclass to invoke "update" on.
        data: The input field payload to pass under the type's declared
            input field name.

    Returns:
        result: The mutation result object returned by "type_cls.update".
    """
    return type_cls.update(None, _info(), **{type_cls._meta.input_field_name: data})


# ---------------------------------------------------------------------------
# (a) Happy path issues NO pre-existence SELECT 1 for the FK
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_happy_create_issues_no_fk_existence_select() -> None:
    """A valid create must not issue an FK ``exists()`` probe beforehand.

    If this fails, the happy path would regress to issuing an eager
    "SELECT" against the FK's table before every create, reintroducing the
    extra round-trip P4 was meant to remove.
    """
    author = Author.objects.create(name="A")

    backend = PydanticBackend(Post)
    with CaptureQueriesContext(connection) as ctx:
        ok, obj = backend.save_object(
            None, None, _info(), {"title": "T", "author": author.id, "body": ""}
        )

    assert ok, obj
    fk_probes = _fk_existence_probes(ctx.captured_queries, Author)
    assert not fk_probes, (
        f"Happy-path create must not issue an FK SELECT 1 probe; got: {fk_probes}"
    )


# ---------------------------------------------------------------------------
# (b) Bad FK id -> same ErrorType payload as the eager check (golden)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bad_fk_create_returns_same_error_payload_as_eager_check() -> None:
    """A non-existent FK still returns the exact eager-check error envelope.

    If this fails, the failure-path (post-IntegrityError) diagnostic would
    produce a different "errors[]" payload than the old eager pre-check,
    breaking any client relying on the exact error message shape.
    """
    backend = PydanticBackend(Post)
    payload = {"title": "T", "author": 999999, "body": ""}

    # Golden: the message the eager diagnostic produces for this bad FK.
    golden = backend._db_check_errors(payload, instance=None)
    assert golden == {"author": ['Invalid pk "999999" - object does not exist.']}

    ok, errors = backend.save_object(None, None, _info(), dict(payload))
    assert ok is False
    got = {e.field: e.messages for e in errors}
    assert got == golden, f"Failure-path payload {got} must equal golden {golden}"
    assert Post.objects.count() == 0


# ---------------------------------------------------------------------------
# (c) Update path — same behavior
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bad_fk_update_returns_same_error_payload() -> None:
    """Updating a row to a non-existent FK returns the same error envelope.

    If this fails, the update path's failure-path diagnostic would diverge
    from the eager check's error payload, and/or the update would silently
    persist a bad FK reference instead of leaving the row untouched.
    """
    author = Author.objects.create(name="A")
    post = Post.objects.create(title="orig", author=author)

    backend = PydanticBackend(Post)
    payload = {"author": 999999}
    golden = backend._db_check_errors(payload, instance=post)
    assert golden == {"author": ['Invalid pk "999999" - object does not exist.']}

    ok, errors = backend.save_object(
        None, None, _info(), dict(payload), instance=post, partial=True
    )
    assert ok is False
    got = {e.field: e.messages for e in errors}
    assert got == golden
    post.refresh_from_db()
    assert post.author_id == author.id  # untouched


@pytest.mark.django_db
def test_happy_update_issues_no_fk_existence_select() -> None:
    """A valid update must not issue an FK ``exists()`` probe beforehand.

    If this fails, the update path would regress to issuing an eager
    "SELECT" against the FK's table before every update, reintroducing the
    extra round-trip P4 was meant to remove.
    """
    author = Author.objects.create(name="A")
    other = Author.objects.create(name="B")
    post = Post.objects.create(title="orig", author=author)

    backend = PydanticBackend(Post)
    with CaptureQueriesContext(connection) as ctx:
        ok, obj = backend.save_object(
            None, None, _info(), {"author": other.id}, instance=post, partial=True
        )
    assert ok, obj
    fk_probes = _fk_existence_probes(ctx.captured_queries, Author)
    assert not fk_probes, f"Happy-path update probed the FK table: {fk_probes}"


# ---------------------------------------------------------------------------
# (d) Multi-FK model: correct per-field attribution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_multi_fk_attributes_bad_field() -> None:
    """With a valid "author" but a bad "category", the error names category.

    If this fails, the failure-path diagnostic would misattribute the error
    to the wrong FK field on a model with more than one FK, or would flag
    the already-valid "author" field instead of the actually-bad one.
    """
    author = Author.objects.create(name="A")
    backend = PydanticBackend(Post)
    payload = {"title": "T", "author": author.id, "category": 888888, "body": ""}

    golden = backend._db_check_errors(payload, instance=None)
    assert golden == {"category": ['Invalid pk "888888" - object does not exist.']}

    ok, errors = backend.save_object(None, None, _info(), dict(payload))
    assert ok is False
    got = {e.field: e.messages for e in errors}
    assert got == golden
    assert Post.objects.count() == 0


@pytest.mark.django_db
def test_e2e_bad_fk_via_type_create() -> None:
    """End-to-end through DjangoModelType.create: bad FK -> ok=False, right msg.

    If this fails, the public "DjangoModelType.create" entry point would
    stop surfacing the failure-path envelope end-to-end, even if the lower-
    level backend call is verified correct elsewhere.
    """
    result = _create(PostType, {"title": "T", "author": 999999, "body": ""})
    assert result.ok is False
    fields = {e.field for e in result.errors}
    assert "author" in fields
    msgs = [m for e in result.errors for m in e.messages]
    assert any('Invalid pk "999999" - object does not exist.' == m for m in msgs)
    assert Post.objects.count() == 0


@pytest.mark.django_db
def test_unrelated_category_probe_absent_but_author_ok() -> None:
    """The nullable category (omitted) must not be probed on the happy path.

    If this fails, an omitted nullable FK would still trigger an eager
    existence probe against its table, adding an unnecessary query even
    though the field was never supplied.
    """
    author = Author.objects.create(name="A")
    Category.objects.create(title="C")
    backend = PydanticBackend(Post)
    with CaptureQueriesContext(connection) as ctx:
        ok, _ = backend.save_object(
            None, None, _info(), {"title": "T", "author": author.id, "body": ""}
        )
    assert ok
    cat_probes = [
        q["sql"]
        for q in ctx.captured_queries
        if Category._meta.db_table in q["sql"] and "SELECT" in q["sql"].upper()
    ]
    assert not cat_probes, f"Category was probed on happy path: {cat_probes}"


# ---------------------------------------------------------------------------
# (e) TRUE-AUTOCOMMIT hot path (need_boundary=False): the failure path is
#     exercised WITHOUT an enclosing atomic.
#
# Every test above runs under the default ``@pytest.mark.django_db`` fixture,
# which wraps the body in an atomic transaction — so ``connection.in_atomic_block``
# is ``True`` and ``save_object`` always takes the ``need_boundary=True`` boundary
# path (``transaction.atomic()`` + a ``check_constraints`` probe). The P4 hot path
# (``need_boundary=False``) — a plain scalar/FK create in real autocommit — was
# therefore NEVER exercised with a bad FK. These ``transaction=True`` tests run in
# the connection's genuine autocommit mode so the failed INSERT autocommits/rolls
# back itself, the ``except IntegrityError`` reproduces the SAME golden envelope,
# and no orphan row survives.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_bad_fk_create_in_true_autocommit_returns_golden_envelope() -> None:
    """A bad FK create in real autocommit -> ok=False, golden errors, zero rows.

    "transaction=True" disables the outer test-atomic, so
    "connection.in_atomic_block" is "False" and (no M2M) "need_boundary" is
    "False": the write is a bare INSERT with no "transaction.atomic()" wrapper.
    The bad FK still surfaces the exact per-field envelope the eager diagnostic
    produces, and no "Post" row is left behind.

    If this fails, the true-autocommit hot path's exception handling would
    diverge from the boundary-wrapped path's golden envelope, or would leave
    an orphaned "Post" row behind after a failed insert.
    """
    assert connection.in_atomic_block is False  # the hot path is truly exercised
    backend = PydanticBackend(Post)
    payload = {"title": "T", "author": 999999, "body": ""}

    golden = backend._db_check_errors(payload, instance=None)
    assert golden == {"author": ['Invalid pk "999999" - object does not exist.']}

    ok, errors = backend.save_object(None, None, _info(), dict(payload))
    assert ok is False
    got = {e.field: e.messages for e in errors}
    assert got == golden, (
        f"Autocommit failure envelope {got} must equal golden {golden}"
    )
    assert Post.objects.count() == 0, (
        "A bad-FK autocommit create must persist zero rows"
    )


@pytest.mark.django_db(transaction=True)
def test_good_fk_create_in_true_autocommit_is_single_insert() -> None:
    """A good FK create in real autocommit is exactly one INSERT and persists.

    The autocommit hot path skips the boundary entirely, so a valid create is a
    single statement (the parent INSERT) with no "SELECT" pre-probe, no
    "BEGIN"/"SAVEPOINT" wrapper, and no "check_constraints" ("PRAGMA
    foreign_key_check") call.

    If this fails, the true-autocommit hot path would regress to wrapping a
    valid create in an unnecessary transaction boundary or issuing an extra
    probe query, defeating the P5/P4 fast-path optimizations.
    """
    assert connection.in_atomic_block is False
    author = Author.objects.create(name="A")
    backend = PydanticBackend(Post)
    with CaptureQueriesContext(connection) as ctx:
        ok, obj = backend.save_object(
            None, None, _info(), {"title": "T", "author": author.id, "body": ""}
        )
    assert ok, obj

    statements = [q["sql"] for q in ctx.captured_queries]
    inserts = [s for s in statements if s.upper().startswith("INSERT")]
    assert len(inserts) == 1, f"Expected exactly one INSERT; got: {statements}"
    for statement in statements:
        upper = statement.upper()
        for keyword in ("BEGIN", "COMMIT", "SAVEPOINT", "RELEASE", "FOREIGN_KEY_CHECK"):
            assert keyword not in upper, (
                f"Autocommit hot path must not emit {keyword}; got: {statements}"
            )
    assert Post.objects.count() == 1
