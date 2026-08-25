"""Django model-based GraphQL mutations."""

from __future__ import annotations

import hashlib
import warnings
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, ClassVar, Optional, Sequence

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Manager
from graphql import GraphQLBoolean

from ._strconv import to_camel_case
from .backends import resolve_backend
from .base_types import factory_type
from .core.base import NativeObjectTypeOptions, _props
from .core.base import ObjectType as NativeObjectType
from .core.descriptors import NativeList, NativeMountedField
from .core.descriptors import field as native_field
from .core.validators import build_validator_model
from .errors import ErrorType
from .nested import (
    NestedFieldsMixin,
    hosts_for_nested,
    hosts_serving,
    record_nested_input,
    register_nested_host,
)
from .registry import get_global_registry
from .types import (
    DjangoInputObjectType,
    DjangoObjectType,
    _check_nested_field_keys,
    _check_unknown_options,
)
from .uploads import merge_uploaded_files
from .utils import get_Object_or_None, not_found_error

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from graphql import GraphQLField, GraphQLResolveInfo

# ---------------------------------------------------------------------------
# Backend-keyed native field registry (WU-3)
# ---------------------------------------------------------------------------
# Keys: (model, operation, "native")  e.g. (Category, "create", "native")
# Values: GraphQLField built during __init_subclass_with_meta__
# Graphene fields are NEVER stored here; they live on the class directly.
# Phase 7 removes the graphene path; this registry is then the only path.
#
# NOTE: this registry holds ONE field per (model, operation): a later subclass
# for the same model OVERWRITES the slot (last-built wins). It is the lookup
# table for ``*Field()`` reads (DjangoModelMutation) and is overwritten by the
# DjangoModelType path too.
_NATIVE_FIELD_REGISTRY: dict[tuple, Any] = {}

# Identity set of EVERY native mutation GraphQLField ever built (by either the
# DjangoModelMutation or DjangoModelType path). Used by the native root compiler
# (``_collect_root_attrs``) to recognise a provably-native mutation field even
# after its single ``_NATIVE_FIELD_REGISTRY`` slot was overwritten by a sibling
# subclass for the same model. Membership here (NOT a blanket
# ``isinstance(value, GraphQLField)`` scan) keeps the gate: an unrelated
# user-declared raw GraphQLField is never silently mounted onto the native root.
_NATIVE_FIELD_IDENTITIES: set[int] = set()

#: The wire name of the identity field a generated UPDATE input exposes. It is
#: the literal ``id`` whatever the model's primary-key column is called, because
#: ``core.fields.build_model_schema`` adds it under that name for the partial
#: (update) case only -- the pk COLUMN is never client-writable on either
#: surface.
IDENTITY_FIELD = "id"


def _projection_signature(
    only_fields: Any, exclude_fields: Any, include_fields: Any
) -> tuple[tuple[str, ...] | None, ...]:
    """Normalize the parent field projection into a hashable signature.

    Each component is a sorted tuple of field names, or None when empty, so
    two builds with equivalent projections share an identical signature and two
    builds with different projections differ. Used by "_nested_input_name" to
    derive a collision-free name suffix.

    Args:
        only_fields: "Meta.only_fields" (any iterable, possibly empty).
        exclude_fields: "Meta.exclude_fields".
        include_fields: "Meta.include_fields".

    Returns:
        A 3-tuple of normalized projection components.
    """
    return tuple(
        tuple(sorted(proj)) if proj else None
        for proj in (only_fields, exclude_fields, include_fields)
    )


def _short_hash(payload: str) -> str:
    """Return a short, stable, NON-cryptographic 6-hex digest of "payload".

    Used only to disambiguate a generated GraphQL type NAME; never for
    security. "usedforsecurity=False" documents that intent (and avoids the
    bandit B324 finding on hashlib).

    Args:
        payload: The string to digest.

    Returns:
        The first 6 hex characters of the SHA1 digest.
    """
    return hashlib.sha1(payload.encode("utf-8"), usedforsecurity=False).hexdigest()[:6]


def _nested_keys_are_ambiguous(sorted_keys: list[str]) -> bool:
    """Whether camelCasing the joined nested keys would lose field boundaries.

    "_nested_input_name" joins the sorted nested field names with "_" and
    runs the result through "to_camel_case", which STRIPS every underscore.
    That collapse makes the multi-field JOIN delimiter indistinguishable from a
    field-internal snake_case underscore: "{'blog_comments'}" and
    "{'blog', 'comments'}" both camelCase to "...BlogComments..." and would
    silently share one GraphQL type name (graphene de-duplicates by name and
    drops the shadowed type's fields with NO error).

    A name is unambiguous ONLY when there is exactly one key AND that key has no
    internal underscore -- then no boundary information can be lost. In every
    other case (two or more keys, or any key containing "_") the camelCased
    join is potentially ambiguous and the name MUST carry a keys-derived suffix.

    Args:
        sorted_keys: The nested field names, already sorted.

    Returns:
        True when a disambiguating suffix is required.
    """
    return len(sorted_keys) > 1 or any("_" in key for key in sorted_keys)


def _nested_input_name(
    model: Any,
    op: str,
    nested_fields: Any,
    only_fields: Any = (),
    exclude_fields: Any = (),
    include_fields: Any = (),
) -> str:
    """Build a deterministic, collision-free name for a nested input type.

    The base name encodes the model, operation and the sorted set of nested
    field names (e.g. "PostCreateNestedCommentsType").

    Two independent disambiguation suffixes may be appended (each as a literal
    underscore segment AFTER "to_camel_case" so it survives camelCasing):

    * "_n<6hex>" -- a hash of the sorted nested-key TUPLE, appended whenever
      the keys are ambiguous (more than one key, or any key with an internal
      underscore). Because "to_camel_case" strips underscores, the join of
      "{'blog_comments'}" and of "{'blog', 'comments'}" would otherwise
      collapse to the SAME name; the keys-hash keeps structurally different
      nested sets on DIFFERENT names. A single key with no underscore is
      provably unambiguous, so the common human-readable name
      ("PostCreateNestedCommentsType") is kept suffix-free.
    * "_p<6hex>" -- a hash of the parent field projection
      (only/exclude/include), appended when that projection is
      non-empty, so two mutations on the same model with the same
      "nested_fields" but different projections never collide.

    Both suffixes are deterministic, so identical builds produce identical
    names (idempotent), while structurally distinct builds never share a name.

    Args:
        model: The Django model the input is built for.
        op: The mutation operation ("create" or "update").
        nested_fields: The "{field: Model}" nested mapping (non-empty).
        only_fields: "Meta.only_fields".
        exclude_fields: "Meta.exclude_fields".
        include_fields: "Meta.include_fields".

    Returns:
        The GraphQL type name for the nested input.
    """
    sorted_keys = sorted(nested_fields.keys())
    joined = "_".join(sorted_keys)
    name = to_camel_case(f"{model.__name__}_{op}_Nested_{joined}_Type")
    # Keys-hash: survives camelCasing the join delimiter (NC-1). The literal
    # underscore is appended AFTER to_camel_case so it is never stripped.
    if _nested_keys_are_ambiguous(sorted_keys):
        name = f"{name}_n{_short_hash(repr(tuple(sorted_keys)))}"
    # Projection-hash: distinguishes same-keys/different-projection mutations.
    projection = _projection_signature(only_fields, exclude_fields, include_fields)
    if any(component is not None for component in projection):
        name = f"{name}_p{_short_hash(repr(projection))}"
    return name


def _keep_identity_field(factory_kwargs: dict[str, Any], op: str) -> dict[str, Any]:
    """Return the factory kwargs with "id" restored on an update projection.

    Args:
        factory_kwargs: The host's "factory_type" keyword arguments.
        op: The operation the input is built for.

    Returns:
        The kwargs unchanged for any operation but "update", and otherwise a
        copy whose projection cannot drop the identity field.
    """
    if op != "update":
        return factory_kwargs
    only_fields = factory_kwargs.get("only_fields")
    exclude_fields = factory_kwargs.get("exclude_fields")
    if not only_fields and not exclude_fields:
        return factory_kwargs
    patched = dict(factory_kwargs)
    if only_fields:
        patched["only_fields"] = tuple(sorted({*only_fields, IDENTITY_FIELD}))
    if exclude_fields:
        patched["exclude_fields"] = tuple(
            name for name in exclude_fields if name != IDENTITY_FIELD
        )
    return patched


def generic_input_type(
    registry: Any, model: Any, op: str, factory_kwargs: dict[str, Any]
) -> Any:
    """Build (memoized) a host's own create/update input for a model.

    The shared "(model, operation)" registry slot holds ONE input per model, so
    the first host to reach it decided the wire surface for every later one: a
    "DjangoModelMutation" declaring "only_fields" behind an already-registered
    display card had its projection silently dropped and its own root accepted
    every writable column -- the exact leak "only_fields" is documented to
    close. A projection therefore does NOT go in the shared slot: it gets its
    own type, named after the projection so two hosts declaring the same one
    share it and two declaring different ones never collide.

    Args:
        registry: The registry owning the shared slot and the projection memo.
        model: The Django model the input is built for.
        op: The operation ("create" or "update").
        factory_kwargs: The host's "factory_type" keyword arguments, carrying
            the "only_fields" / "exclude_fields" this input must honour.

    Returns:
        The "DjangoInputObjectType" subclass for this host's projection.
    """
    # "only_fields" projects the writable COLUMNS of a surface. On an UPDATE it
    # cannot project away the identity field: "id" is how the resolver finds the
    # row, not something the client writes. A host declaring
    # ``only_fields = ("headline",)`` was shipping an update root no client could
    # address. The nested child input exempts it for the same reason, and the
    # two surfaces have to agree. Create is untouched -- an identity field there
    # would be a client-supplied primary key.
    factory_kwargs = _keep_identity_field(factory_kwargs, op)

    # Keyed on the two axes an input actually honours. "include_fields" is not
    # forwarded to an input type at all, so splitting on it would mint a second,
    # byte-identical type under a second name for no gain.
    projection = _projection_signature(
        factory_kwargs.get("only_fields"),
        factory_kwargs.get("exclude_fields"),
        None,
    )
    if not any(component is not None for component in projection):
        # No opinion: the shared slot is exactly right, and keeping the
        # unprojected input there is what every plain host and the converter's
        # child lookups already rely on.
        input_type = registry.get_type_for_model(model, for_input=op)
        if not input_type:
            input_type = factory_type(
                "input", DjangoInputObjectType, op, **factory_kwargs
            )
        return input_type

    key = (model, op, projection)
    built = registry.projected_input_cache.get(key)
    if built is None:
        built = factory_type(
            "input",
            DjangoInputObjectType,
            op,
            **{
                **factory_kwargs,
                "name": "{}_p{}".format(
                    to_camel_case(f"{model.__name__}_{op}_Generic_Type"),
                    _short_hash(repr(projection)),
                ),
                "skip_registry": True,
            },
        )
        registry.projected_input_cache[key] = built
    return built


def _empty_projection_message(
    child_model: Any, parent_model: Any, op: str, hosts: tuple[Any, ...]
) -> str:
    """Describe an emptied nested projection in terms of what declared it.

    Args:
        child_model: The nested child's Django model.
        parent_model: The nesting parent's Django model.
        op: The operation the input was being built for.
        hosts: Every host that contributed to the merge.

    Returns:
        The "ImproperlyConfigured" message, naming each contributing host with
        both of its projection axes.
    """
    declarations = "; ".join(
        "{} only_fields={} exclude_fields={}".format(
            host.__name__,
            tuple(getattr(host._meta, "only_fields", ()) or ()),
            tuple(getattr(host._meta, "exclude_fields", ()) or ()),
        )
        for host in hosts
    )
    return (
        "The nested {op} input for {child} inside {parent} would carry no "
        "field at all, which graphql-core rejects as an invalid schema. The "
        'hosts declared for {child} are: {declarations}. An "only_fields" is an '
        'allowance and an "exclude_fields" is a prohibition applied last, so a '
        "column one host allows and another forbids is not writable; widen one "
        "of them, or declare the read host with "
        'model_operations = ("list", "retrieve").'
    ).format(
        op=op,
        child=child_model.__name__,
        parent=parent_model.__name__,
        declarations=declarations or "none",
    )


def nested_child_input(
    child_model: Any, op: str, registry: Any, parent_model: Any
) -> Any:
    """Build (memoized) the child's input type for ONE parent's nested surface.

    The nested child input used to be whatever object occupied the shared
    "(child_model, op)" registry slot, which made the result depend on
    declaration order: a parent declared first minted an UNPROJECTED input from
    the bare Django model and parked it in that slot, so the child's own
    "exclude_fields" was dropped from BOTH surfaces; a child declared first kept
    its projection but handed the parent an input whose back-reference foreign
    key is still required, which graphql-core rejects before a resolver runs.

    Building it here, per parent, removes the shared slot from the picture:

    * the projection comes from the child's hosts (see "hosts_for_nested"), on
      two axes that say different things. An "exclude_fields" is a PROHIBITION
      -- "this column is never client-writable" -- so EVERY declared host's
      exclusions apply, whatever operation that host happens to serve, and they
      are applied LAST. An "only_fields" is an ALLOWANCE, so only the hosts that
      SERVE this operation (see "hosts_serving") UNION theirs: the union of
      allowances is what some declared host would permit, and the prohibition
      axis still subtracts from it afterwards, so a column any host hid stays
      unwritable. Intersecting instead turned an ordinary read-projection /
      write-projection split -- a display card and a write mutation naming
      different columns, neither escalating anything -- into an import-time
      "ImproperlyConfigured" that killed the whole schema,
    * NO allowance restriction is applied when the union is empty, and that is
      correct on both of the branches that reach it. With no host declared at
      all the child is a plain related model and the unprojected surface minus
      the prohibitions is what the library has always built. With hosts declared
      but none serving this operation, the project has EXPLICITLY said so: both
      host classes default "Meta.model_operations" to every operation they can
      generate, so a host that declares nothing serves this one and the branch
      cannot be reached by accident,
    * "skip_registry=True" means the shared slot is NEVER written, so the
      child's own mutation keeps building its own input from its own Meta,
    * "nested_parent_model" makes the child's back-reference foreign key
      OPTIONAL on this surface only: a reverse-FK / M2M child is linked to the
      parent AFTER it saves ("NestedFieldsMixin._attach_children" injects the FK
      via "save_kwargs"), so the client must not be forced to supply the parent
      id inline. The child's own standalone input keeps it required,
    * the primary key always survives on the UPDATE surface. It is not a
      projectable column there -- it is how the row is identified, and the
      nested writer reads it to decide upsert-vs-create and to run the child's
      scope check. A host's "only_fields" that happens not to list it silently
      broke the documented upsert-by-id, and a client dropping the rejected
      "id" got a duplicate CREATE instead of an update,
    * the EMPTY "nested_fields" guarantees termination: a self-referential model
      produces a child whose own nested relation stays the scalar "[ID!]".

    "include_fields" is deliberately NOT forwarded: it force-includes, so
    honouring it here could only WIDEN the nested write surface.

    Args:
        child_model: The related Django model to build the input for.
        op: The parent's operation ("create" or "update"); the child input is
            built for the same operation.
        registry: The active type registry (owns the memo).
        parent_model: The nesting parent model.

    Returns:
        The child's "DjangoInputObjectType" subclass for this parent and
        operation.

    Raises:
        ImproperlyConfigured: If the merged projection leaves the child input
            with no field at all. graphql-core treats a zero-field input object
            as an INVALID schema, so every request through the built schema
            would fail validation -- not just the nested field.
    """
    cache = registry.nested_input_cache
    key = (child_model, op, parent_model)
    built = cache.get(key)
    if built is None:
        hosts = hosts_for_nested(registry, child_model)
        # An exclusion is a PROHIBITION, so it is not scoped to the operation
        # its host happens to serve. Filtering it dropped a create host's
        # exclusion from the nested UPDATE surface, and a client then wrote, on
        # an EXISTING row through the parent, a column the project's only write
        # mutation refuses.
        excluded = {
            name
            for host in hosts
            for name in getattr(host._meta, "exclude_fields", ()) or ()
        }
        # An allowance, unioned across the hosts that serve the operation. An
        # empty union is "no host has an opinion here", not "nothing writable";
        # see the docstring for why both branches that produce one are safe.
        allowed: set[str] = set()
        for host in hosts_serving(registry, child_model, op):
            allowed |= set(getattr(host._meta, "only_fields", ()) or ())
        if op == "update":
            # Exempt from BOTH axes: an update payload without its identity
            # field cannot name a row. The name is the literal "id" and not the
            # model's pk column: the generated update input exposes the pk as
            # "id: ID" whatever the column is called (see
            # "core.fields.build_model_schema"), and the pk COLUMN itself is
            # never client-writable on either surface.
            excluded.discard(IDENTITY_FIELD)
            if allowed:
                allowed.add(IDENTITY_FIELD)
        only_fields = tuple(sorted(allowed))
        built = factory_type(
            "input",
            DjangoInputObjectType,
            op,
            model=child_model,
            nested_fields={},
            registry=registry,
            skip_registry=True,
            nested_parent_model=parent_model,
            only_fields=only_fields,
            exclude_fields=tuple(excluded),
            # Assembled by hand rather than through "to_camel_case": that helper
            # "str.capitalize()"-s every component after the first, which would
            # flatten a multi-word parent ("NestedTeam" -> "Nestedteam") into a
            # wire-visible name no documentation mentions.
            name=(
                f"{child_model.__name__}{op.capitalize()}In{parent_model.__name__}Type"
            ),
        )
        if not built._meta.graphql_input_type.fields:
            raise ImproperlyConfigured(
                _empty_projection_message(child_model, parent_model, op, hosts)
            )
        cache[key] = built
        # The surface is now frozen: graphql-core caches the parent input's
        # resolved field map, so a host declared from here on could never
        # contribute to it. Recorded so that host is REFUSED rather than
        # silently ignored (see "register_nested_host"). Recorded on THIS
        # registry, like the memo above: another registry has frozen nothing.
        record_nested_input(registry, child_model, parent_model)
    return built


class DjangoModelMutation(NestedFieldsMixin, NativeObjectType):
    """Django model mutation type definition.

    Abstract base for generating create/update/delete GraphQL mutations from a
    Django model. Subclasses configure the model and behaviour through an inner
    "Meta" class; "__init_subclass_with_meta__" builds the mutation payload,
    input types (including nested inputs) and the per-operation GraphQL fields
    that "CreateField" / "UpdateField" / "DeleteField" expose.
    """

    #: Declared here although this host reads it NOWHERE: without a base
    #: ``ClassVar``, Pydantic's ``ModelMetaclass`` rejected the plain assignment
    #: with advice to annotate it ``ClassVar`` — and following that advice bought
    #: a class that builds and a permission that never fires. With the attribute
    #: declared, a subclass assigning it reaches this library's own guard in
    #: ``__init_subclass_with_meta__`` instead.
    permission_classes: ClassVar[tuple[Any, ...]] = ()

    #: Opt-in override (P0) for the permissions this mutation's field requires.
    #: When set (a sequence of codenames), it REPLACES the composite-table
    #: default and is stamped onto the built field's
    #: ``extensions["gdx_required_perms"]``. Declared ``ClassVar`` so a subclass
    #: may assign it without tripping the Pydantic field-annotation check.
    required_perms: ClassVar[Optional[Sequence[str]]] = None

    # S-ROOTS-c: ``ok`` / ``errors`` are NATIVE ``field()`` descriptors (not
    # graphene ``Boolean()`` / ``List(ErrorType)``). The SDL is byte-identical
    # (``ok: Boolean``, ``errors: [ErrorType]``). ``errors`` uses ``NativeList``
    # because ``ErrorType`` is a native plain ``ObjectType`` whose graphql-core
    # type compiles lazily — ``GraphQLList(ErrorType)`` cannot be built eagerly.
    ok = native_field(
        GraphQLBoolean,
        description="Boolean field that return mutation result request.",
    )
    errors = native_field(
        NativeList(ErrorType), description="Errors list for the field"
    )

    class Meta:
        """Meta configuration for DjangoModelMutation.

        Marks the base class as abstract so it is never itself compiled into a
        schema; concrete subclasses declare their own "Meta" with the target
        model and options.
        """

        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        model: Any = None,
        pydantic_model: Any = None,
        only_fields: tuple[str, ...] = (),
        include_fields: tuple[str, ...] = (),
        exclude_fields: tuple[str, ...] = (),
        input_field_name: str | None = None,
        output_field_name: str | None = None,
        description: str = "",
        nested_fields: Any = (),
        model_operations: Any = ("create", "update", "delete"),
        registry: Any = None,
        **options: Any,
    ) -> None:
        """Initialize the subclass with its meta configuration.

        Args:
            only_fields: Field names to expose exclusively.
            include_fields: Field names to include.
            exclude_fields: Field names to exclude.
            input_field_name: Name of the input argument field.
            output_field_name: Name of the output field.
            description: Description for the generated mutation.
            nested_fields: Nested serializer fields configuration.
            model_operations: The mutation operations to generate; any subset of
                ("create", "update", "delete"). Operations left out are not
                built and their "*Field()" builders raise.
            registry: The graphene "Registry" the mutation's output node /
                input type resolve against. Defaults to the process-global
                registry (byte-identical). A CUSTOM registry scopes the whole
                mutation subgraph to a schema's own pair (item-b B6), so a forked
                "DjangoGraphQLSchema" re-forks the payload's output node into
                its own namespace instead of reaching the global last-wins node.
            **options: Additional options forwarded to the base class.

        Raises:
            ImproperlyConfigured: If no "Meta.model" is provided, if any unknown
                Meta option is supplied, if a "nested_fields" key names no
                relation on the model, if "permission_classes" is declared, or
                if "model_operations" contains an unknown operation.
        """
        # The twin of the call "DjangoModelType" has run since 2.0. Without it
        # an "exclude_field" typo left the column it named writable, and a
        # "Meta.queryset" was taken and then never consulted -- both in silence.
        # The known set is this signature: whatever the parameters above did not
        # claim is what lands in "options".
        _check_unknown_options(cls.__name__, options)

        pydantic_model = build_validator_model(cls, model, pydantic_model)
        backend = resolve_backend(model, pydantic_model=pydantic_model)
        model = backend.get_model()
        _check_nested_field_keys(cls.__name__, model, nested_fields)

        description = description or f"DjangoModelMutation for {model.__name__} model"

        input_field_name = input_field_name or f"new_{model._meta.model_name}"
        output_field_name = output_field_name or model._meta.model_name

        input_class = getattr(cls, "Arguments", None)
        if not input_class:
            input_class = getattr(cls, "Input", None)
            if input_class:
                warnings.warn(
                    (
                        "Please use {name}.Arguments instead of {name}.Input."
                        "Input is now only used in ClientMutationID.\nRead more: "
                        "https://github.com/graphql-python/graphene/blob/2.0/UPGRADE-v2.0.md#mutation-input"
                    ).format(name=cls.__name__),
                    DeprecationWarning,
                    stacklevel=2,
                )
        if input_class:
            arguments = _props(input_class)
        else:
            arguments = {}

        # item-b (B6): honor an explicit ``Meta.registry`` so the mutation's
        # output node + nested input types resolve against the schema's own
        # graphene ``Registry`` (a forked pair). Defaults to the process-global
        # registry, so the default/single-schema path is byte-identical.
        if registry is None:
            registry = get_global_registry()

        factory_kwargs = {
            "model": model,
            "only_fields": only_fields,
            "include_fields": include_fields,
            "exclude_fields": exclude_fields,
            "nested_fields": nested_fields,
            "registry": registry,
            "skip_registry": False,
        }

        output_type = registry.get_type_for_model(model)

        if not output_type:
            output_type = factory_type("output", DjangoObjectType, **factory_kwargs)

        django_fields = OrderedDict(
            {output_field_name: NativeMountedField(output_type)}
        )

        model_operations = tuple(op.lower() for op in model_operations)
        unknown = set(model_operations) - {"create", "update", "delete"}
        if unknown:
            raise ImproperlyConfigured(
                "Meta.model_operations of {} contains unknown operation(s) {}; "
                'only "create", "update" and "delete" are valid.'.format(
                    cls.__name__, sorted(unknown)
                )
            )

        # A no-op is worse than a refusal here: the declaration reads as a gate
        # and is not one. Nothing in this class consults "permission_classes" --
        # the base declares it only so this message is what a subclass meets,
        # instead of Pydantic's advice to annotate it "ClassVar" (which used to
        # make the class build with the permission still never firing).
        if cls.permission_classes:
            raise ImproperlyConfigured(
                "{}: permission_classes is not honored by DjangoModelMutation; "
                "this host reads it nowhere, so the checks would never run. "
                "Declare the model on a DjangoModelType, which runs them per "
                "action, or gate the mutation field at the schema root.".format(
                    cls.__name__
                )
            )

        global_arguments = {}
        for operation in ("create", "delete", "update"):
            if operation not in model_operations:
                continue
            global_arguments.update({operation: OrderedDict()})

            if operation != "delete":
                nested_map = nested_fields if isinstance(nested_fields, dict) else {}
                if nested_map:
                    # Nested mutations MUST NOT reuse -- nor overwrite -- the
                    # generic ``(model, operation)`` input: the converter's child
                    # lookups and every plain mutation rely on that slot holding
                    # the generic. Build a DISTINCT, collision-free input with
                    # ``skip_registry=True`` so it never touches ``_types``, and
                    # reference it directly. Each nested CHILD's input is built
                    # per parent, inside the parent's own fields thunk (see
                    # ``nested_child_input``), so it too stays out of ``_types``.
                    input_type = factory_type(
                        "input",
                        DjangoInputObjectType,
                        operation,
                        **{
                            **factory_kwargs,
                            "name": _nested_input_name(
                                model,
                                operation,
                                nested_map,
                                only_fields,
                                exclude_fields,
                                include_fields,
                            ),
                            "skip_registry": True,
                        },
                    )
                else:
                    input_type = generic_input_type(
                        registry, model, operation, factory_kwargs
                    )

                # S6c: DjangoModelMutation is NATIVE-ONLY (parented on
                # ``native.base.ObjectType``). The input argument is wrapped in a
                # graphql-core ``GraphQLArgument`` UNCONDITIONALLY.
                from graphql import GraphQLArgument as _GraphQLArgument
                from graphql import GraphQLNonNull as _GraphQLNonNull

                _gql_input_type = input_type._meta.graphql_input_type
                global_arguments[operation].update(
                    {
                        input_field_name: _GraphQLArgument(
                            _GraphQLNonNull(_gql_input_type),
                            out_name=input_field_name,
                        )
                    }
                )
            else:
                # S6c: native-only ``id`` argument (graphene else-branch removed).
                from graphql import GraphQLArgument as _GraphQLArgument
                from graphql import GraphQLID as _GraphQLID
                from graphql import GraphQLNonNull as _GraphQLNonNull

                global_arguments[operation].update(
                    {
                        "id": _GraphQLArgument(
                            _GraphQLNonNull(_GraphQLID),
                            description="Django object unique identification field",
                            out_name="id",
                        )
                    }
                )
            global_arguments[operation].update(arguments)

        _meta = NativeObjectTypeOptions(cls)
        _meta.output = cls
        _meta.arguments = global_arguments
        _meta.model_operations = model_operations
        _meta.fields = django_fields
        _meta.output_type = output_type
        _meta.model = model
        _meta.backend = backend
        _meta.input_field_name = input_field_name
        _meta.output_field_name = output_field_name
        _meta.nested_fields = nested_fields
        # Stored so a PARENT nesting this model reads the projection this host
        # declared instead of minting an unprojected input from the bare model
        # (see "nested_child_input"). "DjangoModelType" already carries both.
        _meta.only_fields = tuple(only_fields or ())
        _meta.exclude_fields = tuple(exclude_fields or ())
        # The nested writer reads it back at REQUEST time, to decide which
        # registry's hosts scope and authorize a nested child write.
        _meta.registry = registry

        super().__init_subclass_with_meta__(
            _meta=_meta, description=description, **options
        )

        # Declared here, not on demand: see the twin call in "DjangoModelType".
        # This host carries no "permission_classes", so it contributes the
        # queryset-scoping half of the nested gate only.
        register_nested_host(model, cls, registry)

        # ---------------------------------------------------------------------------
        # Native field construction (WU-3): build GraphQLField per operation and
        # store in the registry so *Field() can retrieve them.
        # S6c: DjangoModelMutation is NATIVE-ONLY (parented on
        # ``native.base.ObjectType``), so this runs UNCONDITIONALLY.
        # ---------------------------------------------------------------------------
        from graphql import GraphQLField as _GraphQLField

        # WU9: the mutation field's output type is the compiled MUTATION
        # PAYLOAD type (``ok`` / ``errors`` + the output field), NOT the bare
        # model node type.  The graphene path used ``cls._meta.output`` (the
        # mutation result class itself); the native path mirrors that by
        # compiling THIS mutation class to a native GraphQLObjectType.  Using
        # the node type (the WU<9 bug) left ``ok``/``errors``/output
        # unqueryable on the wire.  ``cls`` is a plain (now native) ObjectType
        # subclass (not a Django output type), so the plain-object compiler
        # handles it; its inner fields are lazy thunks, so the node's
        # ``graphql_output_type`` is resolved at schema-build time (after
        # compile_all_outputs), not here.
        from django_graphex.core.schema_compiler import (
            _compile_plain_object_type,
        )

        _gql_output_type = _compile_plain_object_type(cls)

        from django_graphex.core._compat import _adapt_self

        op_to_resolver = {
            "create": cls.create,
            "delete": cls.delete,
            "update": cls.update,
        }
        # Per-class operation→field map. The model-keyed ``_NATIVE_FIELD_REGISTRY``
        # holds only ONE field per (model, op) — a later sibling mutation for the
        # SAME model overwrites it (last-built wins). That collapses two distinct
        # mutations on one model (e.g. a PLAIN ``PostMutation`` and a nested
        # ``PostWithCommentsMutation``) onto a single field, so ``CreateField()``
        # would hand back the wrong one (and its wrong — possibly nested — input
        # type). Storing each operation's field on the CLASS keeps every
        # mutation's own field intact; ``*Field()`` prefers this per-class map and
        # only falls back to the model-keyed registry for legacy reads. The
        # registry (and ``_NATIVE_FIELD_IDENTITIES``) is still populated so the
        # native root compiler's provably-native recognition gate is unaffected.
        cls._native_fields = {}
        for _op in model_operations:
            # WU9: graphql-core does NOT auto-camelCase argument names, so the
            # arg dict keys must be the camelCase WIRE names while each
            # GraphQLArgument keeps ``out_name`` = the snake Python kwarg
            # (already set when the arg was built).  Without this the wire arg
            # would be ``new_<model>`` and a ``new<Model>: {...}`` document
            # would be rejected.
            # Legacy ``Input`` / ``Arguments`` classes may declare graphene
            # scalar args (e.g. ``extra = graphene.String()``); native builds
            # GraphQLField args as graphql-core ``GraphQLArgument`` instances, so
            # convert any non-``GraphQLArgument`` entry (a graphene mounted type)
            # before mounting. Already-native args (the ``input`` / ``id`` args
            # built above) pass through unchanged.
            from graphql import GraphQLArgument as _GQLArg

            from django_graphex.core._args import (
                to_graphql_argument as _arg_conv,
            )

            _args = {}
            for _arg_name, _arg in global_arguments.get(_op, {}).items():
                _wire = to_camel_case(_arg_name)
                if isinstance(_arg, _GQLArg):
                    _args[_wire] = _arg
                else:
                    _args[_wire] = _arg_conv(_arg, name=_arg_name)
            _resolver = op_to_resolver.get(_op)
            if _resolver is None:
                continue  # pragma: no cover — model_operations already validated
            # classmethods are bound (inspect.ismethod → True), passthrough
            _resolver = _adapt_self(_resolver, owner=cls)
            _gql_field = _GraphQLField(
                _gql_output_type,
                args=_args,
                resolve=_resolver,
                description=description
                or f"Native {_op} mutation for {model.__name__}",
            )
            # item-b (B6): record the mutation SOURCE class on the field's
            # extensions so a FORKED schema can RE-COMPILE the payload against its
            # own registry pair. The payload built here pins relation/output thunks
            # to the pair the class was DEFINED under (the global pair at class-def
            # time); a forked schema must re-fork the payload so its output field
            # (e.g. ``post: PostGenericType``) resolves to the SCHEMA's forked node,
            # not the global last-wins one (else assert_schema_pair_isolation fires).
            # P0: stamp the composite permissions this mutation field requires.
            # An explicit ``Mutation.required_perms`` class attr (opt-in) wins;
            # else the composite table maps the write op to write+view.
            from django_graphex.core.perm_labels import required_perms_for

            _override = getattr(cls, "required_perms", None)
            _perms = (
                frozenset(_override)
                if _override is not None
                else required_perms_for(model, _op)
            )
            _gql_field.extensions = {
                **(_gql_field.extensions or {}),
                "gdx_mutation_source": cls,
                "gdx_required_perms": _perms,
            }
            cls._native_fields[_op] = _gql_field
            _NATIVE_FIELD_REGISTRY[(model, _op, "native")] = _gql_field
            _NATIVE_FIELD_IDENTITIES.add(id(_gql_field))

    @classmethod
    def get_errors(cls, errors: list[Any]) -> DjangoModelMutation:
        """Create an error response wrapping the provided errors.

        Args:
            errors: The list of error objects to report.

        Returns:
            A mutation instance carrying the errors and a falsy "ok".
        """
        errors_dict = {cls._meta.output_field_name: None, "ok": False, "errors": errors}

        return cls(**errors_dict)

    @classmethod
    def perform_mutate(cls, obj: Any, info: GraphQLResolveInfo) -> DjangoModelMutation:
        """Build a successful mutation response for the given object.

        Args:
            obj: The saved model instance to return.
            info: The GraphQL resolve info for the current field.

        Returns:
            A mutation instance carrying the object and a truthy "ok".
        """
        resp = {cls._meta.output_field_name: obj, "ok": True, "errors": None}

        return cls(**resp)

    @classmethod
    def create(
        cls, root: Any, info: GraphQLResolveInfo, **kwargs: Any
    ) -> DjangoModelMutation:
        """Create a new object using the provided data.

        Nested children declared in "Meta.nested_fields" are written atomically
        with the parent (see "NestedFieldsMixin.save_with_nested").

        Args:
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the current field.
            **kwargs: The mutation arguments, including the input data.

        Returns:
            A mutation response carrying the created object or errors.
        """
        data = kwargs.get(cls._meta.input_field_name)
        merge_uploaded_files(
            data,
            info,
            cls._meta.arguments["create"][cls._meta.input_field_name].type,
        )

        ok, obj = cls.save_with_nested(
            root,
            info,
            data,
            instance=None,
        )
        if not ok:
            return cls.get_errors(obj)
        return cls.perform_mutate(obj, info)

    @classmethod
    def get_queryset(
        cls, manager: Manager | QuerySet, info: GraphQLResolveInfo, **kwargs: Any
    ) -> QuerySet:
        """Return the base queryset "update" and "delete" resolve their row from.

        Override to customize the base queryset. "info.context" is the request.
        The default takes the manager it is handed and applies
        "filter_queryset". Same name and signature as the
        "DjangoModelType" hook, so an override moves between the two hosts
        unchanged.

        Args:
            manager: Default manager or queryset to scope.
            info: The GraphQL resolve info for the current request.
            **kwargs: Extra arguments forwarded to "filter_queryset".

        Returns:
            The scoped queryset to resolve the target row from.
        """
        qs = manager.all() if isinstance(manager, Manager) else manager
        return cls.filter_queryset(qs, info, **kwargs)

    @classmethod
    def filter_queryset(
        cls, qs: QuerySet, info: GraphQLResolveInfo, **kwargs: Any
    ) -> QuerySet:
        """Scope the queryset per request.

        This is a hook meant to be overridden. The default returns "qs"
        unchanged. Unlike "DjangoModelType" this host has no read
        operations, so the scope applies to "update" and "delete" only.

        Args:
            qs: Queryset to scope.
            info: The GraphQL resolve info for the current request.
            **kwargs: Extra arguments available for scoping.

        Returns:
            The (optionally) scoped queryset.
        """
        return qs

    @classmethod
    def delete(
        cls, root: Any, info: GraphQLResolveInfo, **kwargs: Any
    ) -> DjangoModelMutation:
        """Delete an object identified by its ID.

        Args:
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the current field.
            **kwargs: The mutation arguments, including the object "id".

        Returns:
            A mutation response carrying the deleted object or errors.
        """
        pk = kwargs.get("id")

        # SECURITY: resolve the target row through "get_queryset" ->
        # "filter_queryset", never the bare model, so a declared scope hides a
        # row from a write exactly as it does on "DjangoModelType". A row
        # outside the scope answers as missing, so the response cannot be used
        # to probe another tenant's primary keys.
        scoped = cls.get_queryset(cls._meta.model._default_manager, info, **kwargs)
        old_obj = get_Object_or_None(scoped, pk=pk)
        if old_obj:
            old_obj.delete()
            setattr(old_obj, old_obj._meta.pk.attname, pk)
            return cls.perform_mutate(old_obj, info)
        else:
            return cls.get_errors(not_found_error(cls._meta.model, pk))

    @classmethod
    def update(
        cls, root: Any, info: GraphQLResolveInfo, **kwargs: Any
    ) -> DjangoModelMutation:
        """Update an existing object with the provided data.

        Args:
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the current field.
            **kwargs: The mutation arguments, including the input data.

        Returns:
            A mutation response carrying the updated object or errors.
        """
        data = kwargs.get(cls._meta.input_field_name)
        merge_uploaded_files(
            data,
            info,
            cls._meta.arguments["update"][cls._meta.input_field_name].type,
        )

        # Use .pop('id', None) so that an update input where 'id' was excluded
        # via only_fields/exclude_fields does not raise KeyError.  A None pk
        # means no object can be found, so old_obj will be None and the resolver
        # returns a clean "not found" error rather than a 500.
        pk = data.pop("id", None)
        # Explicit-null semantics (GraphQL-spec-correct: omitted != null). The
        # coercion layer delivers ONLY the keys the client actually sent: an
        # OMITTED field is absent from ``data`` (untouched on a partial update),
        # while an EXPLICIT ``null`` arrives as a present ``None`` and MUST flow
        # through so a nullable field/FK is set NULL and an M2M is cleared. A
        # ``null`` on a REQUIRED field surfaces as a clean validation ErrorType
        # (never a 500). NOTE: nested (``Meta.nested_fields``) inputs treat
        # ``null``/``[]``/``{}`` as a NO-OP (see ``NestedMutationMixin`` in
        # ``nested.py``); that asymmetry is deliberate and documented there.
        # SECURITY: same scoped lookup as ``delete`` -- see the comment there.
        scoped = cls.get_queryset(cls._meta.model._default_manager, info, **kwargs)
        old_obj = get_Object_or_None(scoped, pk=pk)
        if old_obj:
            ok, obj = cls.save_with_nested(
                root,
                info,
                data,
                instance=old_obj,
            )
            if not ok:
                return cls.get_errors(obj)
            return cls.perform_mutate(obj, info)
        else:
            return cls.get_errors(not_found_error(cls._meta.model, pk))

    @classmethod
    def _native_field_for(cls, operation: str) -> Any:
        """Return THIS mutation class's field for "operation".

        Prefers the per-class "_native_fields" map (built in
        "__init_subclass_with_meta__") so two distinct mutations on the SAME
        model never hand back each other's field. Falls back to the model-keyed
        "_NATIVE_FIELD_REGISTRY" only when the per-class map is absent (legacy
        / defensive path).

        Args:
            operation: The mutation operation ("create", "delete", "update").

        Returns:
            The graphql-core "GraphQLField" for this class + operation.
        """
        own = getattr(cls, "_native_fields", None)
        if own is not None and operation in own:
            return own[operation]
        return _NATIVE_FIELD_REGISTRY[(cls._meta.model, operation, "native")]

    @staticmethod
    def _with_deprecation(field: Any, deprecation_reason: str | None) -> Any:
        """Return "field" deprecated by "deprecation_reason" (a copy when set).

        The native mutation field is built ONCE in
        "__init_subclass_with_meta__" and cached on the class (identity-tracked
        in "_NATIVE_FIELD_IDENTITIES" so the root compiler recovers it). A
        caller-supplied "deprecation_reason" must therefore NOT mutate the shared
        cached field -- return a shallow "GraphQLField" copy carrying the reason,
        preserving every attribute (type / args / resolver / description /
        extensions, including "gdx_mutation_source" + "gdx_required_perms").
        The copy's identity is registered in "_NATIVE_FIELD_IDENTITIES" so the
        native root compiler recognises it via BOTH the "_meta.fields" verbatim
        path AND "_collect_root_attrs". None returns the field unchanged.

        Args:
            field: The compiled graphql-core "GraphQLField".
            deprecation_reason: The deprecation reason, or None for no change.

        Returns:
            The field unchanged (None reason) or a deprecated copy.
        """
        if deprecation_reason is None:
            return field
        from graphql import GraphQLField as _GraphQLField

        copy = _GraphQLField(
            field.type,
            args=field.args,
            resolve=field.resolve,
            subscribe=field.subscribe,
            description=field.description,
            deprecation_reason=deprecation_reason,
            extensions=field.extensions,
        )
        _NATIVE_FIELD_IDENTITIES.add(id(copy))
        return copy

    @classmethod
    def CreateField(
        cls, *args: Any, deprecation_reason: str | None = None, **kwargs: Any
    ) -> Any:
        """Build a GraphQL field for the create mutation.

        Returns this class's "create" "GraphQLField" (see "_native_field_for").

        Args:
            *args: Positional arguments (unused).
            deprecation_reason: Optional reason wired onto the compiled field so
                the SDL renders "@deprecated(reason: ...)".
            **kwargs: Extra keyword arguments (unused).

        Returns:
            The field resolving to the create mutation.

        Raises:
            AttributeError: If "create" is not in Meta.model_operations.
        """
        cls._assert_operation("create")
        return cls._with_deprecation(
            cls._native_field_for("create"), deprecation_reason
        )

    @classmethod
    def DeleteField(
        cls, *args: Any, deprecation_reason: str | None = None, **kwargs: Any
    ) -> Any:
        """Build a GraphQL field for the delete mutation.

        Returns this class's "delete" "GraphQLField" (see "_native_field_for").

        Args:
            *args: Positional arguments (unused).
            deprecation_reason: Optional reason wired onto the compiled field so
                the SDL renders "@deprecated(reason: ...)".
            **kwargs: Extra keyword arguments (unused).

        Returns:
            The field resolving to the delete mutation.

        Raises:
            AttributeError: If "delete" is not in Meta.model_operations.
        """
        cls._assert_operation("delete")
        return cls._with_deprecation(
            cls._native_field_for("delete"), deprecation_reason
        )

    @classmethod
    def UpdateField(
        cls, *args: Any, deprecation_reason: str | None = None, **kwargs: Any
    ) -> Any:
        """Build a GraphQL field for the update mutation.

        Returns this class's "update" "GraphQLField" (see "_native_field_for").

        Args:
            *args: Positional arguments (unused).
            deprecation_reason: Optional reason wired onto the compiled field so
                the SDL renders "@deprecated(reason: ...)".
            **kwargs: Extra keyword arguments (unused).

        Returns:
            The field resolving to the update mutation.

        Raises:
            AttributeError: If "update" is not in Meta.model_operations.
        """
        cls._assert_operation("update")
        return cls._with_deprecation(
            cls._native_field_for("update"), deprecation_reason
        )

    @classmethod
    def _assert_operation(cls, operation: str) -> None:
        """Ensure "operation" is enabled in Meta.model_operations.

        Args:
            operation: The mutation operation being built.

        Raises:
            AttributeError: If the operation was excluded from model_operations.
        """
        if operation not in cls._meta.model_operations:
            raise AttributeError(
                '"{}" mutation is not enabled on {}; '
                "Meta.model_operations is {}.".format(
                    operation, cls.__name__, cls._meta.model_operations
                )
            )

    @classmethod
    def MutationFields(cls, *args: Any, **kwargs: Any) -> tuple[GraphQLField, ...]:
        """Build the mutation fields enabled by Meta.model_operations.

        Args:
            *args: Positional arguments forwarded to each field builder.
            **kwargs: Keyword arguments forwarded to each field builder.

        Returns:
            The create, delete and update graphql-core fields (in that order)
            for every operation enabled in "Meta.model_operations".
        """
        builders = (
            ("create", cls.CreateField),
            ("delete", cls.DeleteField),
            ("update", cls.UpdateField),
        )
        return tuple(
            build(*args, **kwargs)
            for operation, build in builders
            if operation in cls._meta.model_operations
        )
