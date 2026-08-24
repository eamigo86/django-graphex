"""The native (Pydantic) "SerializerBackend" implementation.

DRF-free validate/save/output for a Django model, selected by "Meta.model".
Reuses the model-to-Pydantic schema in "fields", validates with Pydantic,
performs the DB-level checks Pydantic cannot (FK existence, uniqueness,
"unique_together", and "Meta.constraints" "UniqueConstraint" entries),
persists scalars plus FK plus M2M, and serializes output.
"""

from __future__ import annotations

import base64
import enum
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any

from django.db import IntegrityError, connection, models, transaction
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


def _json_safe(field: models.Field, value: Any) -> Any:
    """Coerce a concrete field's Python value into a JSON-encodable one.

    Only the two field kinds whose value is NOT JSON-encodable are touched; every
    other value is returned unchanged (dates and decimals are normalized further
    downstream by "DjangoJSONEncoder").

    Args:
        field: The concrete model field the value was read from.
        value: The raw attribute value read off the instance.

    Returns:
        The storage name for a file field, the base64 text for a binary field,
        or "value" unchanged.
    """
    if isinstance(field, models.FileField):
        # ``FieldFile`` is not JSON-encodable; ``.name`` is the stored path and
        # matches the field's ``String`` output.
        return value.name if value is not None else None
    if isinstance(field, models.BinaryField):
        if value is None:
            return None
        return base64.b64encode(bytes(value)).decode("ascii")
    return value


class PydanticBackend(SerializerBackend):
    """Validate, persist, and serialize a Django model with Pydantic (no DRF).

    Selected by "Meta.model", this backend derives a Pydantic schema from the
    model, validates incoming payloads with it, runs the DB-level checks
    Pydantic cannot express (FK/M2M existence, per-field uniqueness,
    "unique_together", and unconditional "UniqueConstraint" entries), then
    persists scalar, FK, and M2M values and serializes the result back to a
    JSON-safe dict.
    """

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
        """Return the Django model this backend writes.

        Returns:
            model: The Django model class configured on this backend.
        """
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
        """Validate "data" and create or update one object.

        The payload is validated against a Pydantic schema derived from the
        model. On success the object is written, applying FK and M2M values,
        and any "save_kwargs" (such as a reverse-FK link to a parent) are set
        on the instance before saving. DB integrity checks (FK/M2M existence,
        uniqueness) are deferred to the failure path: on "IntegrityError" the
        same diagnostics run to reproduce a structured per-field error envelope.

        Args:
            host: The owning mutation/type, forwarded for hook parity; unused
                here.
            root: The GraphQL resolver root value; unused here.
            info: The GraphQL resolve info for the current request.
            data: The client-supplied field values to validate and persist.
            instance: The existing object to update, or None to create a new one.
            partial: When True, treat all fields as optional (partial update).
            serializer_kwargs: Extra serializer options, accepted for backend
                parity; unused here.
            save_kwargs: Field values injected at save time (excluded from
                validation and set directly on the instance).

        Returns:
            result: A "(ok, value)" tuple; on success "value" is the saved
                instance, on validation/integrity failure "ok" is False and
                "value" is a list of "ErrorType" entries.

        Raises:
            IntegrityError: When the write fails with an integrity error that
                cannot be attributed to a missing FK/M2M or uniqueness clash,
                re-raised for the generic upstream handling.
        """
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

        fks = self._fk_fields()
        m2m = self._m2m_names()
        # Snapshot the full payload (M2M keys included) BEFORE popping, so the
        # failure-path diagnostics can attribute a bad M2M pk the same way the
        # eager ``_db_check_errors`` call did.
        diagnostic_payload = dict(payload)
        m2m_values = {name: payload.pop(name) for name in list(payload) if name in m2m}

        obj = instance or self.model()
        for name, value in payload.items():
            setattr(obj, f"{name}_id" if name in fks else name, value)
        for name, value in (save_kwargs or {}).items():
            setattr(obj, name, value)  # reverse-FK link to the parent

        # FK/M2M existence checks MOVE to the failure path (perf): the happy
        # path skips the per-FK ``SELECT 1`` pre-probe that ``_db_check_errors``
        # issued before every insert/update and instead attempts the write
        # directly.  On the rare ``IntegrityError`` we run the SAME
        # ``_db_check_errors`` diagnostics to reproduce the exact per-field
        # ``ErrorType`` envelope callers already assert.
        #
        # Recovery boundary invariant: the write needs a rollback boundary only
        # when (1) we are already inside an outer transaction — a failed
        # statement there poisons the transaction until it is rolled back to a
        # savepoint, and the diagnostic SELECTs that follow must run on a usable
        # connection — or (2) the write spans MORE than one statement (M2M
        # ``.set()`` runs AFTER the parent ``save()``), so a mid-write failure
        # must not leave an orphaned parent row.  A plain scalar/FK create in
        # autocommit needs NO wrapper: a failed INSERT autocommits/rolls back
        # itself and leaves the connection usable, so the hot path stays a
        # single INSERT with zero savepoint SQL.
        need_boundary = connection.in_atomic_block or bool(m2m_values)
        boundary = transaction.atomic() if need_boundary else nullcontext()
        try:
            with boundary:
                obj.save()
                for name, pks in m2m_values.items():
                    # Only present keys reach here (``model_fields_set`` gates
                    # the payload), so an OMITTED M2M never appears in
                    # ``m2m_values`` and is left untouched. An EXPLICIT ``null``
                    # (``pks is None``) CLEARS the relation -- identical to an
                    # empty ``[]`` -- honouring explicit-null semantics (REPLACE
                    # surface, non-nested ID list).
                    getattr(obj, name).set([] if pks is None else pks)
                if need_boundary:
                    # Force deferred FK validation while still INSIDE the
                    # savepoint. Backends that defer referential integrity to
                    # the end of a transaction (SQLite disables FK enforcement
                    # inside an atomic block; MySQL/Postgres may use DEFERRED
                    # constraints) would otherwise let a bad FK slip past this
                    # ``save()`` and only surface at the OUTERMOST commit — long
                    # after this recovery boundary, where the connection is no
                    # longer positioned to run the diagnostic SELECTs. Checking
                    # here makes the ``IntegrityError`` land in the ``except``
                    # below so the savepoint rolls back and diagnostics run on a
                    # usable connection. One ``check_constraints`` call covers
                    # ALL FKs of the touched tables (vs the old per-FK
                    # ``SELECT 1``), and it only runs on the boundary path —
                    # never on the autocommit hot path. The M2M through tables
                    # are included so a bad M2M pk (its violation lives in the
                    # link row, not the parent) is caught too.
                    check_tables = [self.model._meta.db_table]
                    for name in m2m_values:
                        through = self.model._meta.get_field(name).remote_field.through
                        check_tables.append(through._meta.db_table)
                    connection.check_constraints(table_names=check_tables)
        except IntegrityError:
            # Reproduce the exact structured envelope the eager check produced.
            errors = self._db_check_errors(diagnostic_payload, instance)
            if errors:
                return False, _errors_to_type(errors)
            # Integrity error of another kind (not a missing FK/M2M we can
            # attribute): re-raise so the existing generic handling upstream
            # surfaces it unchanged.
            raise
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
        """Serialize an instance to a JSON-safe dict.

        Foreign keys are emitted as their primary-key value and many-to-many
        relations as a list of primary keys. Concrete scalar fields are copied
        as-is EXCEPT the two whose Python value is not JSON-encodable:

          * a "FileField"/"ImageField" yields a "FieldFile", so its storage
            NAME is emitted (the same string the field's GraphQL "String"
            output carries);
          * a "BinaryField" yields "bytes" (or a "memoryview" once reloaded
            from some backends), so it is base64-encoded into an ASCII string.

        Without those two, a subscription on a model carrying either column
        crashed on EVERY save with "Object of type FieldFile is not JSON
        serializable" — the payload is JSON-encoded before it crosses the
        channel layer.

        Args:
            instance: The model instance to serialize.

        Returns:
            data: A mapping of output field name to its JSON-safe value.
        """
        data: dict[str, Any] = {}
        for field in self._output_fields():
            if isinstance(field, models.ManyToManyField):
                data[field.name] = list(
                    getattr(instance, field.name).values_list("pk", flat=True)
                )
            elif isinstance(field, (models.ForeignKey, models.OneToOneField)):
                data[field.name] = getattr(instance, f"{field.name}_id")
            else:
                data[field.name] = _json_safe(field, getattr(instance, field.name))
        return data

    def output_field_names(self) -> list[str]:
        """Return the field names emitted by "to_representation".

        Returns:
            names: The output field names, in model field order.
        """
        return [field.name for field in self._output_fields()]
