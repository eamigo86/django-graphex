"""DRF-style inline validators for the native backend.

Lets a "DjangoModelType" / "DjangoModelMutation" declare custom rules as
methods directly on the class — "validate_<field>(self, value)" per field and an
object-level "validate(self, data)" — instead of a separate "Meta.pydantic_model".

They are collected at class-creation time and compiled into a synthetic Pydantic
base ("field_validator" / "model_validator") that the native backend uses as
the base of its derived schema. If a "Meta.pydantic_model" is also given, the
synthetic class inherits from it, so the two compose.
"""

from __future__ import annotations

import warnings
from typing import Any, Callable

from django.db import models
from pydantic import BaseModel, field_validator, model_validator

from .fields import m2m_fields, writable_fields

_PREFIX = "validate_"


def _unwrap(attr: Any) -> Any:
    """Return the underlying function of a (class/static)method, else the value."""
    if isinstance(attr, (classmethod, staticmethod)):
        return attr.__func__
    return attr


def _collect(host_cls: type) -> tuple[dict[str, Callable], Callable | None]:
    """Collect ``validate_<field>`` and ``validate`` callables down the MRO.

    The most-derived definition of each name wins (subclasses override bases).

    Returns:
        A ``({field: fn}, object_fn_or_None)`` tuple.
    """
    field_fns: dict[str, Callable] = {}
    object_fn: Callable | None = None
    seen: set[str] = set()
    for klass in host_cls.__mro__:
        for name, attr in vars(klass).items():
            if name in seen:
                continue
            fn = _unwrap(attr)
            if not callable(fn):
                continue
            if name == "validate":
                seen.add(name)
                object_fn = fn
            elif name.startswith(_PREFIX) and len(name) > len(_PREFIX):
                seen.add(name)
                field_fns[name[len(_PREFIX) :]] = fn
    return field_fns, object_fn


def _field_wrapper(fn: Callable, host_cls: type) -> Callable:
    """Wrap a user ``validate_<field>`` as a Pydantic field-validator classmethod."""

    def _validator(cls: type, value: Any) -> Any:
        return fn(host_cls, value)

    return _validator


def _object_wrapper(fn: Callable, host_cls: type) -> Callable:
    """Wrap a user ``validate`` as a Pydantic ``model_validator(mode="after")``.

    Exposes the set fields as a ``dict`` (DRF's ``validate(self, data)`` shape) and
    writes any returned keys back onto the model so transforms persist.
    """

    def _validator(self: BaseModel) -> BaseModel:
        data = {name: getattr(self, name) for name in self.model_fields_set}
        result = fn(host_cls, data)
        if isinstance(result, dict):
            for key, value in result.items():
                setattr(self, key, value)
        return self

    return _validator


def build_validator_model(
    host_cls: type,
    model: type[models.Model] | None,
    pydantic_model: type | None = None,
) -> type | None:
    """Compile inline "validate_*" methods into a Pydantic base, or pass through.

    Args:
        host_cls: The "DjangoModelType" / "DjangoModelMutation" subclass.
        model: The Django model the host is backed by (used to warn on a
            "validate_<field>" that matches no writable field).
        pydantic_model: An optional user Pydantic base to inherit from (so inline
            validators and "Meta.pydantic_model" compose).

    Returns:
        A synthetic Pydantic class carrying the validators (inheriting
        "pydantic_model" when given), or "pydantic_model" unchanged when the
        host declares no inline validators.
    """
    if model is None:
        return pydantic_model

    field_fns, object_fn = _collect(host_cls)
    if not field_fns and object_fn is None:
        return pydantic_model

    valid = {f.name for f in writable_fields(model)} | {
        f.name for f in m2m_fields(model)
    }
    namespace: dict[str, Any] = {}
    for field_name, fn in field_fns.items():
        if field_name not in valid:
            warnings.warn(
                f"{host_cls.__name__}.{_PREFIX}{field_name} does not match any "
                f"writable field of {model.__name__}; it will never run.",
                UserWarning,
                stacklevel=2,
            )
        namespace[f"_inline_{_PREFIX}{field_name}"] = field_validator(
            field_name, check_fields=False
        )(classmethod(_field_wrapper(fn, host_cls)))

    if object_fn is not None:
        namespace["_inline_validate_object"] = model_validator(mode="after")(
            _object_wrapper(object_fn, host_cls)
        )

    base = pydantic_model if pydantic_model is not None else BaseModel
    return type(f"{host_cls.__name__}InlineValidators", (base,), namespace)
