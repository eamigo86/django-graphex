"""The native (Pydantic) :class:`SerializerBackend` implementation.

DRF-free validate/save/output for a Django model, selected by ``Meta.model``.
Reuses the model->Pydantic schema in :mod:`.fields`, validates with Pydantic,
performs the DB-level checks Pydantic can't (FK existence, uniqueness,
``unique_together``), persists scalars + FK + M2M, and serializes output.
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Any

from django.db import models
from pydantic import ValidationError

from .._compat import ErrorType
from ..backends import SerializerBackend
from .fields import build_model_schema

if TYPE_CHECKING:
    from graphql import GraphQLResolveInfo


def _errors_to_type(errors: dict[str, list[str]]) -> list[ErrorType]:
    """Convert a ``{field: [messages]}`` mapping to an ``ErrorType`` list."""
    return [ErrorType(field=field, messages=msgs) for field, msgs in errors.items()]


def _translate(exc: ValidationError) -> dict[str, list[str]]:
    """Translate a Pydantic ``ValidationError`` to ``{field: [messages]}``."""
    out: dict[str, list[str]] = {}
    for err in exc.errors():
        loc = [p for p in err["loc"] if not isinstance(p, int)]
        field = ".".join(str(p) for p in loc) or "non_field_errors"
        out.setdefault(field, []).append(err["msg"])
    return out


class PydanticBackend(SerializerBackend):
    """Validate/persist/serialize a Django model with Pydantic (no DRF)."""

    def __init__(
        self, model: type[models.Model], pydantic_model: type | None = None
    ) -> None:
        """Store the model and an optional user Pydantic base.

        Args:
            model: The Django model this backend writes.
            pydantic_model: Optional user Pydantic model carrying custom
                validators, used as the base of the derived schema.
        """
        self.model = model
        self.pydantic_model = pydantic_model

    def get_model(self) -> type[models.Model]:
        """Return the configured model."""
        return self.model

    # -- helpers --------------------------------------------------------------- #
    def _fk_fields(self) -> dict[str, models.ForeignKey]:
        return {
            f.name: f
            for f in self.model._meta.get_fields()
            if isinstance(f, (models.ForeignKey, models.OneToOneField)) and f.concrete
        }

    def _m2m_names(self) -> set[str]:
        return {
            f.name
            for f in self.model._meta.get_fields()
            if isinstance(f, models.ManyToManyField)
        }

    def _db_check_errors(
        self, payload: dict[str, Any], instance: models.Model | None
    ) -> dict[str, list[str]]:
        """Run the DB-level checks Pydantic can't (FK existence, uniqueness)."""
        errors: dict[str, list[str]] = {}
        fks = self._fk_fields()
        for name, fk in fks.items():
            pk = payload.get(name)
            if (
                pk is not None
                and not fk.related_model._default_manager.filter(pk=pk).exists()
            ):
                errors.setdefault(name, []).append(
                    f'Invalid pk "{pk}" - object does not exist.'
                )

        for field in self.model._meta.get_fields():
            if (
                getattr(field, "unique", False)
                and not field.primary_key
                and field.name in payload
            ):
                qs = self.model._default_manager.filter(
                    **{field.name: payload[field.name]}
                )
                if instance is not None:
                    qs = qs.exclude(pk=instance.pk)
                if qs.exists():
                    errors.setdefault(field.name, []).append(
                        f"{self.model.__name__} with this {field.name} already exists."
                    )

        for group in self.model._meta.unique_together:
            lookup = {}
            for name in group:
                value = payload.get(
                    name, getattr(instance, name, None) if instance else None
                )
                lookup[name] = value
            if all(v is not None for v in lookup.values()):
                qs = self.model._default_manager.filter(**lookup)
                if instance is not None:
                    qs = qs.exclude(pk=instance.pk)
                if qs.exists():
                    errors.setdefault("non_field_errors", []).append(
                        "The fields {} must make a unique set.".format(", ".join(group))
                    )
        return errors

    # -- backend API ----------------------------------------------------------- #
    def save_object(
        self,
        host: Any,
        root: Any,
        info: GraphQLResolveInfo,
        data: dict[str, Any],
        *,
        instance: models.Model | None = None,
        partial: bool = False,
        serializer_kwargs: dict[str, Any] | None = None,
        save_kwargs: dict[str, Any] | None = None,
    ) -> tuple[bool, Any]:
        """Validate ``data`` and create/update one object."""
        # Fields injected at save time (e.g. a reverse FK linking to the parent)
        # are excluded from validation so they aren't treated as required.
        schema = build_model_schema(
            self.model,
            partial=partial,
            base=self.pydantic_model,
            exclude=set(save_kwargs or {}),
        )
        try:
            validated = schema(**data)
        except ValidationError as exc:
            return False, _errors_to_type(_translate(exc))

        # Only client-provided fields (so Django defaults apply on create and
        # untouched fields are left alone on update).
        payload = validated.model_dump(include=set(validated.model_fields_set))
        # Unwrap enum (choices) members to their stored value.
        payload = {
            key: (value.value if isinstance(value, enum.Enum) else value)
            for key, value in payload.items()
        }

        errors = self._db_check_errors(payload, instance)
        if errors:
            return False, _errors_to_type(errors)

        fks = self._fk_fields()
        m2m = self._m2m_names()
        m2m_values = {name: payload.pop(name) for name in list(payload) if name in m2m}

        obj = instance or self.model()
        for name, value in payload.items():
            setattr(obj, f"{name}_id" if name in fks else name, value)
        for name, value in (save_kwargs or {}).items():
            setattr(obj, name, value)  # reverse-FK link to the parent
        obj.save()
        for name, pks in m2m_values.items():
            if pks is not None:
                getattr(obj, name).set(pks)
        return True, obj

    def _output_fields(self) -> list[models.Field]:
        """Return the fields ``to_representation`` emits (concrete + FK + M2M)."""
        return [
            field
            for field in self.model._meta.get_fields()
            if isinstance(field, models.ManyToManyField)
            or getattr(field, "concrete", False)
        ]

    def to_representation(self, instance: models.Model) -> dict[str, Any]:
        """Serialize an instance to a JSON-safe dict (FK -> pk, M2M -> [pk])."""
        data: dict[str, Any] = {}
        for field in self._output_fields():
            if isinstance(field, models.ManyToManyField):
                data[field.name] = list(
                    getattr(instance, field.name).values_list("pk", flat=True)
                )
            elif isinstance(field, (models.ForeignKey, models.OneToOneField)):
                data[field.name] = getattr(instance, f"{field.name}_id")
            else:
                data[field.name] = getattr(instance, field.name)
        return data

    def output_field_names(self) -> list[str]:
        """Return the field names emitted by ``to_representation``."""
        return [field.name for field in self._output_fields()]
