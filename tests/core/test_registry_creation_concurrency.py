"""Identity contracts for global and model-list registry creation."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from graphql import GraphQLField, GraphQLObjectType, GraphQLSchema

import django_graphex.registry as registry_module
import django_graphex.types as types_module
from django_graphex.registry import Registry
from django_graphex.types import DjangoListObjectType, get_or_create_list_object_type
from tests.models import Author, BasicModel

_WAIT_SECONDS = 5


class _ObservedRLock:
    """Report a competing acquisition without changing reentrant semantics."""

    def __init__(self, contention: threading.Event) -> None:
        """Keep the real lock and the signal for a competing thread.

        Args:
            contention: Signal raised before another thread blocks.
        """
        self._lock = threading.RLock()
        self._state = threading.Lock()
        self._owner: int | None = None
        self._depth = 0
        self.reentries = 0
        self._contention = contention

    def __enter__(self) -> _ObservedRLock:
        """Acquire the real lock and report contention or reentry.

        Returns:
            This lock after acquisition.
        """
        ident = threading.get_ident()
        with self._state:
            if self._owner is not None and self._owner != ident:
                self._contention.set()
        self._lock.acquire()
        with self._state:
            if self._owner == ident:
                self.reentries += 1
            self._owner = ident
            self._depth += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        """Release one level, including exceptional exits.

        Args:
            exc_type: Raised exception class, if any.
            exc_value: Raised exception instance, if any.
            traceback: Raised exception traceback, if any.
        """
        with self._state:
            self._depth -= 1
            if self._depth == 0:
                self._owner = None
        self._lock.release()


def _reached(event: threading.Event, boundary: str) -> None:
    """Require a coordination boundary without using elapsed-time assertions.

    Args:
        event: Signal to await.
        boundary: Boundary name for a useful failure.
    """
    assert event.wait(_WAIT_SECONDS), f"Worker did not reach {boundary}"


def test_global_registry_concurrent_cold_calls_share_one_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second construction or lock attempt cannot mint another singleton.

    Args:
        monkeypatch: Fixture restoring the module-level constructor and slot.
    """
    real_class = registry_module.Registry
    first_entered = threading.Event()
    progress = threading.Event()
    lock = _ObservedRLock(progress)
    constructed: list[Registry] = []
    state = threading.Lock()

    class ObservedRegistry(real_class):
        """Count actual constructor entries without fabricating an instance."""

        def __init__(self) -> None:
            """Pause the first real construction at the cold boundary."""
            super().__init__()
            with state:
                constructed.append(self)
                ordinal = len(constructed)
            if ordinal == 1:
                first_entered.set()
                _reached(progress, "second construction or singleton lock attempt")
            else:
                progress.set()

    monkeypatch.setattr(registry_module, "registry", None)
    monkeypatch.setattr(registry_module, "Registry", ObservedRegistry)
    monkeypatch.setattr(registry_module, "_GLOBAL_REGISTRY_LOCK", lock, raising=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(registry_module.get_global_registry)
        _reached(first_entered, "first real singleton construction")
        second = pool.submit(registry_module.get_global_registry)
        first_result = first.result(timeout=_WAIT_SECONDS)
        second_result = second.result(timeout=_WAIT_SECONDS)

    assert len(constructed) == 1
    assert first_result is second_result is registry_module.registry
    assert registry_module.get_global_registry() is first_result


def test_global_registry_failed_construction_retries_and_reset_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure leaves the slot empty, and serial reset creates a fresh value.

    Args:
        monkeypatch: Fixture restoring the module-level constructor and slot.

    Raises:
        RuntimeError: The synthetic constructor failure is asserted.
    """
    real_class = registry_module.Registry

    class BrokenRegistry(real_class):
        """Fail construction before the singleton can be published."""

        def __init__(self) -> None:
            """Raise a stable synthetic constructor error."""
            raise RuntimeError("synthetic registry construction failure")

    monkeypatch.setattr(registry_module, "registry", None)
    monkeypatch.setattr(registry_module, "Registry", BrokenRegistry)
    with pytest.raises(RuntimeError, match="synthetic registry construction failure"):
        registry_module.get_global_registry()
    assert registry_module.registry is None

    monkeypatch.setattr(registry_module, "Registry", real_class)
    first = registry_module.get_global_registry()
    assert registry_module.get_global_registry() is first
    monkeypatch.setattr(registry_module, "registry", None)
    second = registry_module.get_global_registry()
    assert second is not first
    assert first._list_types == second._list_types == {}


def test_concurrent_list_misses_share_class_graphql_object_and_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second real miss or lock attempt cannot mint a duplicate container.

    Args:
        monkeypatch: Fixture restoring the observed getter and real factory.
    """
    registry = Registry()
    first_miss = threading.Event()
    progress = threading.Event()
    lock = _ObservedRLock(progress)
    registry._list_lock = lock
    real_get = Registry.get_list_type_for_model
    real_factory = types_module.factory_type
    misses = 0
    constructions: list[type] = []
    state = threading.Lock()

    def observed_get(self: Registry, model: type) -> Any | None:
        """Pause only after a real missing model slot is read.

        Args:
            self: Registry receiving the lookup.
            model: Model key requested by the caller.

        Returns:
            The unmodified registry value.
        """
        nonlocal misses
        value = real_get(self, model)
        if self is registry and model is BasicModel and value is None:
            with state:
                misses += 1
                ordinal = misses
            if ordinal == 1:
                first_miss.set()
                _reached(progress, "second list miss or list lock attempt")
            else:
                progress.set()
        return value

    def observed_factory(operation: str, cls: type, *args: Any, **kwargs: Any) -> Any:
        """Count real list class allocations without changing their result.

        Args:
            operation: Factory operation.
            cls: Class used as the generated type base.
            *args: Additional positional factory arguments.
            **kwargs: Factory configuration.

        Returns:
            The actual generated class.
        """
        result = real_factory(operation, cls, *args, **kwargs)
        if operation == "list" and kwargs.get("registry") is registry:
            constructions.append(result)
        return result

    monkeypatch.setattr(Registry, "get_list_type_for_model", observed_get)
    monkeypatch.setattr(types_module, "factory_type", observed_factory)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(get_or_create_list_object_type, BasicModel, registry)
        _reached(first_miss, "first real list registry miss")
        second = pool.submit(get_or_create_list_object_type, BasicModel, registry)
        first_result = first.result(timeout=_WAIT_SECONDS)
        second_result = second.result(timeout=_WAIT_SECONDS)

    assert misses == 1
    assert len(constructions) == 1
    assert lock.reentries >= 2
    assert first_result is second_result is real_get(registry, BasicModel)
    assert first_result._meta.model is BasicModel
    assert first_result._meta.registry is registry
    gql = first_result._meta.graphql_output_type
    assert isinstance(gql, GraphQLObjectType)
    assert gql is second_result._meta.graphql_output_type
    assert gql.name == "BasicModelListType"
    GraphQLSchema(
        query=GraphQLObjectType(
            "RegistryCreationQuery",
            fields={"first": GraphQLField(gql), "second": GraphQLField(gql)},
        )
    )


def test_explicit_list_registration_keeps_last_registration_wins() -> None:
    """Keep an explicit container canonical until a later registration.

    A later explicit registration retains the historical last-wins rule.
    """
    registry = Registry()
    generated = get_or_create_list_object_type(BasicModel, registry)
    explicit_registry = registry

    class ExplicitList(DjangoListObjectType):
        """An explicit list type for registration precedence."""

        class Meta:
            """Bind the explicit list type to the isolated registry."""

            model = BasicModel
            registry = explicit_registry
            name = "ExplicitBasicModelList"

    assert registry.get_list_type_for_model(BasicModel) is ExplicitList
    assert get_or_create_list_object_type(BasicModel, registry) is ExplicitList
    registry.register_list_type(BasicModel, generated)
    assert get_or_create_list_object_type(BasicModel, registry) is generated


def test_list_creation_is_scoped_to_each_model_and_registry() -> None:
    """Keep canonical list types separate across models and registries.

    A model lookup in one registry cannot reuse another registry's class.
    """
    first_registry = Registry()
    second_registry = Registry()
    basic = get_or_create_list_object_type(BasicModel, first_registry)
    author = get_or_create_list_object_type(Author, first_registry)
    other_basic = get_or_create_list_object_type(BasicModel, second_registry)

    assert basic is not author
    assert basic is not other_basic
    assert basic._meta.registry is first_registry
    assert author._meta.registry is first_registry
    assert other_basic._meta.registry is second_registry
    assert first_registry.get_list_type_for_model(BasicModel) is basic
    assert first_registry.get_list_type_for_model(Author) is author
    assert second_registry.get_list_type_for_model(BasicModel) is other_basic
