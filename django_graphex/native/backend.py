"""The native (Pydantic) :class:`SerializerBackend` implementation.

DRF-free validate/save/output for a Django model, selected by ``Meta.model``.
Reuses the model->Pydantic schema in :mod:`.fields`, validates with Pydantic,
performs the DB-level checks Pydantic can't (FK existence, uniqueness,
``unique_together``, and ``Meta.constraints`` :class:`~django.db.models.UniqueConstraint`
entries), persists scalars + FK + M2M, and serializes output.
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Any

from django.db import models
from pydantic import ValidationError

from ..backends import SerializerBackend
from ..errors import ErrorType
from .fields import build_model_schema
from .input_compiler import translate_validation_error

if TYPE_CHECKING:
    from graphql import GraphQLResolveInfo


def _errors_to_type(errors: dict[str, list[str]]) -> list[ErrorType]:
    """Convert a ``{field: [messages]}`` mapping to an ``ErrorType`` list."""
    return [ErrorType(field=field, messages=msgs) for field, msgs in errors.items()]


# _translate is promoted to input_compiler.translate_validation_error (with
# include_url=False). The alias below keeps internal callers working without
# changing every call site in this file.
_translate = translate_validation_error


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
        # Exclude multi-table-inheritance parent_link fields: they are injected
        # by Django's MTI machinery and are not part of the user-supplied payload.
        # The type converter already guards against parent_link on the output side;
        # this mirrors that guard on the input side.
        #
        # Parent links are identified via _meta.parents: the dict maps each parent
        # model class to the OneToOneField that links child -> parent table.
        parent_link_fields: frozenset[models.Field] = frozenset(
            link for link in self.model._meta.parents.values() if link is not None
        )
        return {
            f.name: f
            for f in self.model._meta.get_fields()
            if isinstance(f, (models.ForeignKey, models.OneToOneField))
            and f.concrete
            and f not in parent_link_fields
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

        # M2M pk existence — mirrors the FK loop above.  A non-existent M2M pk
        # would otherwise reach getattr(obj, name).set(pks) and raise an
        # uncaught IntegrityError (HTTP 500).
        for field in self.model._meta.get_fields():
            if not isinstance(field, models.ManyToManyField):
                continue
            pks = payload.get(field.name)
            if not isinstance(pks, (list, tuple)) or not pks:
                continue
            unique_pks = list(dict.fromkeys(pks))  # deduplicate, preserve order
            existing_count = field.related_model._default_manager.filter(
                pk__in=unique_pks
            ).count()
            if existing_count != len(unique_pks):
                missing = [
                    pk
                    for pk in unique_pks
                    if not field.related_model._default_manager.filter(pk=pk).exists()
                ]
                for pk in missing:
                    errors.setdefault(field.name, []).append(
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

        # Validate Meta.constraints UniqueConstraint entries.
        #
        # Unconditional constraints (no `condition` and no `expressions`) are
        # checked here so violations surface as structured ErrorType errors
        # instead of propagating as an IntegrityError 500.
        #
        # Constraints with `condition` (partial/conditional unique) or with
        # `expressions` (functional unique) are skipped: replicating their
        # predicate cheaply is not feasible, so they remain DB-enforced.
        #
        # Single-field constraints whose field already carries `unique=True` are
        # also skipped to avoid emitting a duplicate error message (the per-field
        # unique loop above already handled those fields).
        unique_field_names: set[str] = {
            f.name
            for f in self.model._meta.get_fields()
            if getattr(f, "unique", False) and not getattr(f, "primary_key", False)
        }
        checked_field_sets: set[frozenset[str]] = {
            frozenset([name]) for name in unique_field_names if name in payload
        }
        for constraint in self.model._meta.constraints:
            if not isinstance(constraint, models.UniqueConstraint):
                continue
            # Skip conditional/partial constraints — cannot replicate cheaply.
            if constraint.condition is not None:
                continue
            # Skip functional/expression-based constraints.
            if constraint.expressions:
                continue

            field_set = frozenset(constraint.fields)

            # Skip if a field-level unique check already covers this exact set
            # (avoids double errors for single-field constraints where the field
            # also has unique=True).
            if field_set in checked_field_sets:
                continue

            # For single-field constraints: if the field has unique=True the
            # per-field loop above already emitted an error — skip here too.
            # NOTE: in practice `checked_field_sets` is pre-populated with
            # frozenset({name}) for every unique-field name that is in the
            # payload, so the `field_set in checked_field_sets` guard above
            # already catches this case.  The outer `if len(field_set) == 1`
            # branch IS reachable (exercised by single-field CheckConstraints),
            # but the inner `continue` is unreachable because the pre-init of
            # `checked_field_sets` means the outer guard at :172 always fires
            # first.  Only the inner short-circuit needs the pragma.
            if len(field_set) == 1:
                (field_name,) = field_set
                if field_name in unique_field_names and field_name in payload:
                    continue  # pragma: no cover

            lookup = {}
            for name in constraint.fields:
                value = payload.get(
                    name, getattr(instance, name, None) if instance else None
                )
                lookup[name] = value
            if all(v is not None for v in lookup.values()):
                qs = self.model._default_manager.filter(**lookup)
                if instance is not None:
                    qs = qs.exclude(pk=instance.pk)
                if qs.exists():
                    field_list = ", ".join(constraint.fields)
                    if len(constraint.fields) == 1:
                        (field_name,) = constraint.fields
                        errors.setdefault(field_name, []).append(
                            "{} with this {} already exists.".format(
                                self.model.__name__, field_name
                            )
                        )
                    else:
                        errors.setdefault("non_field_errors", []).append(
                            "The fields {} must make a unique set.".format(field_list)
                        )
                    checked_field_sets.add(field_set)

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
        # List/tuple values are also recursed into so that multi-valued choice
        # fields (e.g. DjangoListField(enum)) arrive with plain Python values.
        def _unwrap(value: Any) -> Any:
            if isinstance(value, enum.Enum):
                return value.value
            if isinstance(value, (list, tuple)):
                return [v.value if isinstance(v, enum.Enum) else v for v in value]
            return value

        payload = {key: _unwrap(value) for key, value in payload.items()}

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
