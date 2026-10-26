"""Deterministic concurrency contracts for the two native enum caches."""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from graphql import GraphQLEnumType

from django_graphex import converter
from django_graphex.core import compiler
from django_graphex.core.ir import EnumSpec, FieldSpec, TypeRef, TypeSpec
from django_graphex.registry import Registry

_WAIT_SECONDS = 5


class _ContendedRLock:
    """Expose a competing acquisition while retaining real reentrant locking."""

    def __init__(self, contention: threading.Event) -> None:
        """Create a lock that reports another thread's acquisition attempt.

        Args:
            contention: Event set before a competing thread waits for the lock.
        """
        self._lock = threading.RLock()
        self._state = threading.Lock()
        self._owner: int | None = None
        self._depth = 0
        self._contention = contention

    def __enter__(self) -> _ContendedRLock:
        """Acquire the lock and report contention without altering semantics.

        Returns:
            This lock after acquisition.
        """
        ident = threading.get_ident()
        with self._state:
            if self._owner is not None and self._owner != ident:
                self._contention.set()
        self._lock.acquire()
        with self._state:
            self._owner = ident
            self._depth += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        """Release one level of the lock, including exceptional exits.

        Args:
            exc_type: Exception class when the block failed.
            exc_value: Exception instance when the block failed.
            traceback: Exception traceback when the block failed.
        """
        with self._state:
            self._depth -= 1
            if self._depth == 0:
                self._owner = None
        self._lock.release()


def _choices_field(choices: tuple[tuple[str, str], ...]) -> SimpleNamespace:
    """Create a minimal choices field with a stable native enum name.

    Args:
        choices: Raw values and labels in declaration order.

    Returns:
        A field-shaped object accepted by the native choices builder.
    """
    meta = SimpleNamespace(app_label="triage", object_name="Thing")
    model = SimpleNamespace(_meta=meta)
    return SimpleNamespace(model=model, name="state", choices=choices)


def _assert_event(event: threading.Event, description: str) -> None:
    """Fail safely if a coordinated worker cannot reach its boundary.

    Args:
        event: The boundary signal to await.
        description: Name of the boundary for a useful failure.
    """
    assert event.wait(timeout=_WAIT_SECONDS), f"Worker did not reach {description}"


def _registry_pair(
    monkeypatch: pytest.MonkeyPatch,
    first_field: SimpleNamespace,
    second_field: SimpleNamespace,
) -> tuple[GraphQLEnumType, Future[GraphQLEnumType], Registry, list[GraphQLEnumType]]:
    """Force two actual registry misses or observe the competing lock attempt.

    The first call pauses after reading a real empty slot. On old code the
    second call also reads that empty slot; on synchronized code it attempts
    the held lock instead. No cache entry or result is fabricated.

    Args:
        monkeypatch: Fixture for restoring the getter, constructor and lock.
        first_field: Field compiled before the competing call begins.
        second_field: Field compiled concurrently in the same registry.

    Returns:
        The first result, second future, registry and constructed enum list.
    """
    registry = Registry()
    progress = threading.Event()
    first_miss = threading.Event()
    registry._enum_lock = _ContendedRLock(progress)
    real_getter = Registry.get_type_for_enum
    real_constructor = compiler._new_enum
    misses: list[Any] = []
    constructed: list[GraphQLEnumType] = []

    def observed_getter(self: Registry, key: str) -> Any | None:
        """Pause only after a real missing native enum slot is read.

        Args:
            self: Registry whose actual getter is called.
            key: Native enum registry key.

        Returns:
            The actual unmodified registry value.
        """
        value = real_getter(self, key)
        if self is registry and value is None:
            misses.append(value)
            if len(misses) == 1:
                first_miss.set()
                _assert_event(progress, "a second miss or lock attempt")
            else:
                progress.set()
        return value

    def observed_constructor(spec: EnumSpec) -> GraphQLEnumType:
        """Count actual native enum allocations without changing their result.

        Args:
            spec: Enum definition to construct.

        Returns:
            The production constructor's enum object.
        """
        result = real_constructor(spec)
        constructed.append(result)
        return result

    monkeypatch.setattr(Registry, "get_type_for_enum", observed_getter)
    monkeypatch.setattr(compiler, "_new_enum", observed_constructor)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(converter.build_choices_enum_type, first_field, registry)
        _assert_event(first_miss, "the first registry miss")
        second = pool.submit(converter.build_choices_enum_type, second_field, registry)
        first_result = first.result(timeout=_WAIT_SECONDS)
        second.exception(timeout=_WAIT_SECONDS)
    return first_result, second, registry, constructed


def test_compile_enum_shares_one_object_after_contended_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Equivalent concurrent enum calls return the canonical cached object.

    Args:
        monkeypatch: Fixture used to restore the observed constructor and lock.
    """
    compiler._reset_cache()
    spec = EnumSpec(name="TriageCompilerEnum", values=(("ONE", "one"),))
    progress = threading.Event()
    first_constructor = threading.Event()
    monkeypatch.setattr(
        compiler, "_TYPE_CACHE_LOCK", _ContendedRLock(progress), raising=False
    )
    real_constructor = compiler._new_enum
    constructed: list[GraphQLEnumType] = []
    constructor_calls = 0

    def observed_constructor(current: EnumSpec) -> GraphQLEnumType:
        """Pause the first allocation until a second call reaches its boundary.

        Args:
            current: Enum definition passed to the production constructor.

        Returns:
            The production constructor's enum object.
        """
        nonlocal constructor_calls
        constructor_calls += 1
        if constructor_calls == 1:
            first_constructor.set()
            _assert_event(progress, "a second constructor or lock attempt")
        else:
            progress.set()
        result = real_constructor(current)
        constructed.append(result)
        return result

    monkeypatch.setattr(compiler, "_new_enum", observed_constructor)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(compiler.compile_enum, spec)
        _assert_event(first_constructor, "the first enum constructor")
        second = pool.submit(compiler.compile_enum, spec)
        first_result = first.result(timeout=_WAIT_SECONDS)
        second_result = second.result(timeout=_WAIT_SECONDS)

    assert first_result is second_result
    assert compiler._TYPE_CACHE[spec.name] is first_result
    assert constructor_calls == 1
    assert len(constructed) == 1


def test_compile_type_shares_one_object_after_contended_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent object-type cache misses do not replace the first object.

    Args:
        monkeypatch: Fixture used to restore the observed payload and lock.
    """
    compiler._reset_cache()
    spec = TypeSpec(name="TriageObject", fields=())
    progress = threading.Event()
    first_payload = threading.Event()
    monkeypatch.setattr(
        compiler, "_TYPE_CACHE_LOCK", _ContendedRLock(progress), raising=False
    )
    real_payload = compiler.GdxPayload
    payload_calls = 0

    def observed_payload(metadata: Any) -> Any:
        """Hold the first payload build before the type cache write.

        Args:
            metadata: Production GDX metadata.

        Returns:
            The production payload object.
        """
        nonlocal payload_calls
        payload_calls += 1
        if payload_calls == 1:
            first_payload.set()
            _assert_event(progress, "a second payload or lock attempt")
        else:
            progress.set()
        return real_payload(metadata)

    monkeypatch.setattr(compiler, "GdxPayload", observed_payload)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(compiler.compile_type, spec)
        _assert_event(first_payload, "the first payload build")
        second = pool.submit(compiler.compile_type, spec)
        first_result = first.result(timeout=_WAIT_SECONDS)
        second_result = second.result(timeout=_WAIT_SECONDS)

    assert first_result is second_result
    assert compiler._TYPE_CACHE[spec.name] is first_result
    assert payload_calls == 1


def test_compile_schema_keeps_reset_and_build_in_one_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second schema cannot reset the shared cache inside another build.

    Args:
        monkeypatch: Fixture used to restore the observed reset and lock.
    """
    progress = threading.Event()
    first_reset = threading.Event()
    monkeypatch.setattr(
        compiler, "_TYPE_CACHE_LOCK", _ContendedRLock(progress), raising=False
    )
    real_reset = compiler._reset_cache
    reset_calls = 0
    overlap_at_first_resume: list[int] = []
    query = TypeSpec(
        name="Query",
        fields=(FieldSpec(name="value", type=TypeRef(name="String")),),
    )

    def observed_reset() -> None:
        """Record whether another reset enters before the first build resumes."""
        nonlocal reset_calls
        reset_calls += 1
        if reset_calls == 1:
            first_reset.set()
            _assert_event(progress, "a second reset or lock attempt")
            overlap_at_first_resume.append(reset_calls)
        else:
            progress.set()
        real_reset()

    monkeypatch.setattr(compiler, "_reset_cache", observed_reset)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(compiler.compile_schema, [query], [], query)
        _assert_event(first_reset, "the first cache reset")
        second = pool.submit(compiler.compile_schema, [query], [], query)
        first_schema = first.result(timeout=_WAIT_SECONDS)
        second_schema = second.result(timeout=_WAIT_SECONDS)

    assert overlap_at_first_resume == [1]
    assert first_schema.query_type is not second_schema.query_type
    assert list(first_schema.query_type.fields) == ["value"]
    assert list(second_schema.query_type.fields) == ["value"]


def test_native_choices_reuse_one_object_after_contended_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One registry shares the first native enum and constructs it once.

    Args:
        monkeypatch: Fixture used to restore native cache instrumentation.
    """
    field = _choices_field((("one", "One"),))
    first, second, registry, constructed = _registry_pair(monkeypatch, field, field)
    second_result = second.result(timeout=_WAIT_SECONDS)
    key = "__native__" + converter.choices_enum_name(field)

    assert first is second_result
    assert registry.get_type_for_enum(key) is first
    assert len(constructed) == 1
    assert list(first.values) == ["ONE"]
    assert first.values["ONE"].value == "one"
    assert first.values["ONE"].description == "One"


def test_native_choices_reject_incompatible_concurrent_definition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The losing definition raises the existing M-D7 error, not overwrites.

    Args:
        monkeypatch: Fixture used to restore native cache instrumentation.
    """
    first_field = _choices_field((("one", "One"),))
    second_field = _choices_field((("two", "Two"),))
    first, second, registry, constructed = _registry_pair(
        monkeypatch, first_field, second_field
    )
    key = "__native__" + converter.choices_enum_name(first_field)

    with pytest.raises(
        ImproperlyConfigured,
        match=(
            "Choices enum 'triageThingStateEnum' has incompatible definitions "
            "from triage\\.Thing\\.state and triage\\.Thing\\.state\\."
        ),
    ):
        second.result(timeout=_WAIT_SECONDS)
    assert registry.get_type_for_enum(key) is first
    assert len(constructed) == 2


def test_native_choices_keep_serial_ambiguity_and_registry_isolation() -> None:
    """L-C7 remains fail-fast and distinct registries own distinct enums.

    This serial control needs no fixture or concurrent worker.
    """
    ambiguous = _choices_field((("", "Alpha"), ("", "Alpha")))
    with pytest.raises(
        ImproperlyConfigured,
        match="Ambiguous generated choices enum member 'ALPHA'",
    ):
        converter.build_choices_enum_type(ambiguous, Registry())

    field = _choices_field((("one", "One"), ("two", "Two")))
    first_registry = Registry()
    second_registry = Registry()
    first = converter.build_choices_enum_type(field, first_registry)
    second = converter.build_choices_enum_type(field, second_registry)
    assert first is converter.build_choices_enum_type(field, first_registry)
    assert first is not second
    assert list(first.values) == ["ONE", "TWO"]
