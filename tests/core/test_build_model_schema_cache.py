"""P2: "build_model_schema" memoization.

"build_model_schema" builds a Pydantic model with "create_model" on every
call. It is invoked once per mutation request from the hot save path, yet its
output is a pure function of its arguments (the derived Pydantic class is
stateless per "validate" call). These tests pin the memoization contract:

  (a) two identical calls run "create_model" exactly ONCE and return the SAME
      class object (cache hit),
  (b) distinct cache keys build DISTINCT classes (no collision),
  (c) "exclude" is normalized so equivalent iterables (set/frozenset/None)
      share a cache slot, while a different exclusion misses,
  (d) behavior is unchanged, a cached schema still validates payloads.

Run with:
    .venv/bin/python -m pytest tests/core/test_build_model_schema_cache.py -q --no-cov
"""

from __future__ import annotations

from typing import Iterator

import pytest
from pytest import MonkeyPatch

from django_graphex.core import fields as fields_mod
from django_graphex.core.fields import build_model_schema
from tests.models import Post


@pytest.fixture(autouse=True)
def _clear_schema_cache() -> Iterator[None]:
    """Reset the module cache before and after each test for isolation.

    Yields:
        None. Clears "fields_mod._SCHEMA_CACHE" both before the test body
            runs and again during teardown.
    """
    fields_mod._SCHEMA_CACHE.clear()
    yield
    fields_mod._SCHEMA_CACHE.clear()


@pytest.mark.django_db
def test_identical_calls_build_schema_once(monkeypatch: MonkeyPatch) -> None:
    """Assert that two identical calls invoke "create_model" once and share a class.

    If this fails, memoization is broken and every mutation request would
    rebuild the Pydantic schema from scratch on the hot save path.

    Args:
        monkeypatch: The pytest fixture used to spy on "fields_mod.create_model".
    """
    calls = {"n": 0}
    original = fields_mod.create_model

    def _spy(*args: object, **kwargs: object) -> object:
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(fields_mod, "create_model", _spy)

    first = build_model_schema(Post, partial=False)
    second = build_model_schema(Post, partial=False)

    assert calls["n"] == 1, f"create_model must run once, ran {calls['n']} times"
    assert first is second, "Identical calls must return the SAME cached class object"


@pytest.mark.django_db
def test_distinct_keys_build_distinct_classes() -> None:
    """Assert that different (partial / exclude) keys build distinct classes.

    If this fails, unrelated schema variants would collide in the cache and
    callers could receive a schema shaped for the wrong request.
    """
    create = build_model_schema(Post, partial=False)
    update = build_model_schema(Post, partial=True)
    excl = build_model_schema(Post, partial=False, exclude={"author"})

    assert create is not update, "partial=True must not share the create slot"
    assert create is not excl, "a different exclude set must not share the slot"


@pytest.mark.django_db
def test_exclude_normalized_across_iterable_types() -> None:
    """Assert that "exclude" as set / frozenset / list / None normalizes to one slot.

    If this fails, semantically equivalent exclude arguments would be treated
    as distinct cache keys, defeating memoization for callers that pass
    different iterable types for the same exclusion set.
    """
    a = build_model_schema(Post, partial=False, exclude={"author"})
    b = build_model_schema(Post, partial=False, exclude=frozenset({"author"}))
    c = build_model_schema(Post, partial=False, exclude=["author"])
    assert a is b is c, "Equivalent exclude iterables must hit the same cache slot"

    none_a = build_model_schema(Post, partial=False, exclude=None)
    none_b = build_model_schema(Post, partial=False, exclude=set())
    assert none_a is none_b, "None and empty exclude must share the same cache slot"


@pytest.mark.django_db
def test_cached_schema_still_validates() -> None:
    """Assert that a cached schema class still validates payloads correctly.

    If this fails, memoization would return a cached class that no longer
    behaves like a fresh Pydantic model, breaking mutation validation.
    """
    schema = build_model_schema(Post, partial=False)
    again = build_model_schema(Post, partial=False)
    assert schema is again
    validated = again(title="Hello", author=1, body="body")
    assert validated.title == "Hello"
    assert validated.author == 1
