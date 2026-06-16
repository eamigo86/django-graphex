"""Django model-based GraphQL mutations."""

from __future__ import annotations

import hashlib
import warnings
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured
from graphene import Field
from graphql import GraphQLBoolean

from ._strconv import to_camel_case
from .backends import resolve_backend
from .base_types import factory_type
from .errors import ErrorType
from .native.base import NativeObjectTypeOptions, _props
from .native.base import ObjectType as NativeObjectType
from .native.descriptors import NativeList
from .native.descriptors import field as native_field
from .native.validators import build_validator_model
from .nested import NestedFieldsMixin
from .registry import get_global_registry
from .types import DjangoInputObjectType, DjangoObjectType
from .utils import get_Object_or_None, not_found_error

if TYPE_CHECKING:
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


def _projection_signature(
    only_fields: Any, exclude_fields: Any, include_fields: Any
) -> tuple[tuple[str, ...] | None, ...]:
    """Normalize the parent field projection into a hashable signature.

    Each component is a sorted tuple of field names, or ``None`` when empty, so
    two builds with equivalent projections share an identical signature and two
    builds with different projections differ. Used by ``_nested_input_name`` to
    derive a collision-free name suffix.

    Args:
        only_fields: ``Meta.only_fields`` (any iterable, possibly empty).
        exclude_fields: ``Meta.exclude_fields``.
        include_fields: ``Meta.include_fields``.

    Returns:
        A 3-tuple of normalized projection components.
    """
    return tuple(
        tuple(sorted(proj)) if proj else None
        for proj in (only_fields, exclude_fields, include_fields)
    )


def _short_hash(payload: str) -> str:
    """Return a short, stable, NON-cryptographic 6-hex digest of ``payload``.

    Used only to disambiguate a generated GraphQL type NAME; never for
    security. ``usedforsecurity=False`` documents that intent (and avoids the
    bandit B324 finding on hashlib).

    Args:
        payload: The string to digest.

    Returns:
        The first 6 hex characters of the SHA1 digest.
    """
    return hashlib.sha1(payload.encode("utf-8"), usedforsecurity=False).hexdigest()[:6]


def _nested_keys_are_ambiguous(sorted_keys: list[str]) -> bool:
    """Whether camelCasing the joined nested keys would lose field boundaries.

    ``_nested_input_name`` joins the sorted nested field names with ``"_"`` and
    runs the result through ``to_camel_case``, which STRIPS every underscore.
    That collapse makes the multi-field JOIN delimiter indistinguishable from a
    field-internal snake_case underscore: ``{"blog_comments"}`` and
    ``{"blog", "comments"}`` both camelCase to ``...BlogComments...`` and would
    silently share one GraphQL type name (graphene de-duplicates by name and
    drops the shadowed type's fields with NO error).

    A name is unambiguous ONLY when there is exactly one key AND that key has no
    internal underscore -- then no boundary information can be lost. In every
    other case (two or more keys, or any key containing ``_``) the camelCased
    join is potentially ambiguous and the name MUST carry a keys-derived suffix.

    Args:
        sorted_keys: The nested field names, already sorted.

    Returns:
        ``True`` when a disambiguating suffix is required.
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
    field names (e.g. ``PostCreateNestedCommentsType``).

    Two independent disambiguation suffixes may be appended (each as a literal
    underscore segment AFTER ``to_camel_case`` so it survives camelCasing):

    * ``_n<6hex>`` -- a hash of the sorted nested-key TUPLE, appended whenever
      the keys are ambiguous (more than one key, or any key with an internal
      underscore). Because ``to_camel_case`` strips underscores, the join of
      ``{"blog_comments"}`` and of ``{"blog", "comments"}`` would otherwise
      collapse to the SAME name; the keys-hash keeps structurally different
      nested sets on DIFFERENT names. A single key with no underscore is
      provably unambiguous, so the common human-readable name
      (``PostCreateNestedCommentsType``) is kept suffix-free.
    * ``_p<6hex>`` -- a hash of the parent field projection
      (``only``/``exclude``/``include``), appended when that projection is
      non-empty, so two mutations on the same model with the same
      ``nested_fields`` but different projections never collide.

    Both suffixes are deterministic, so identical builds produce identical
    names (idempotent), while structurally distinct builds never share a name.

    Args:
        model: The Django model the input is built for.
        op: The mutation operation ("create" or "update").
        nested_fields: The ``{field: Model}`` nested mapping (non-empty).
        only_fields: ``Meta.only_fields``.
        exclude_fields: ``Meta.exclude_fields``.
        include_fields: ``Meta.include_fields``.

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


def _ensure_child_generic_input(
    child_model: Any, op: str, registry: Any, parent_model: Any = None
) -> None:
    """Ensure the GENERIC ``(child_model, op)`` input type exists.

    The converter resolves each nested child lazily via
    ``registry.get_type_for_model(child_model, for_input=op)``; when no explicit
    child mutation/type was declared that lookup would return ``None`` and the
    converter would silently drop the field. Building the child's GENERIC input
    on demand (with EMPTY ``nested_fields`` and ``skip_registry=False`` so it
    self-registers at ``(child_model, op)``) makes that lookup succeed.

    The empty ``nested_fields`` guarantees termination: a self-referential model
    produces a generic child whose own nested relation is ``[ID!]`` -- no
    recursion. Already-registered children are a no-op.

    ``parent_model`` (the nesting host) makes the child's back-reference FK
    OPTIONAL on the INPUT surface: a reverse-FK / M2M child is linked to the
    parent AFTER it saves (``NestedFieldsMixin._attach_children`` injects the FK
    via ``save_kwargs``, and ``save_object`` excludes those keys from
    validation), so the client must NOT be forced to supply the parent id inline.
    The child's pydantic VALIDATION model still requires the FK, so a STANDALONE
    child create that genuinely omits it still fails cleanly — only the inline
    nested path is relaxed.

    Args:
        child_model: The related Django model to build the input for.
        op: The parent's operation ("create" or "update"); the child input is
            built for the same operation.
        registry: The active type registry.
        parent_model: The nesting parent model; its back-reference FK on the
            child is rendered optional on the input surface (or ``None`` for a
            plain ensure with no relaxation).
    """
    if registry.get_type_for_model(child_model, for_input=op) is not None:
        return
    factory_type(
        "input",
        DjangoInputObjectType,
        op,
        model=child_model,
        nested_fields={},
        registry=registry,
        skip_registry=False,
        nested_parent_model=parent_model,
    )


class DjangoModelMutation(NestedFieldsMixin, NativeObjectType):
    """Django model mutation type definition."""

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
        """Meta configuration for DjangoModelMutation."""

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
                ``("create", "update", "delete")``. Operations left out are not
                built and their ``*Field()`` builders raise.
            registry: The graphene ``Registry`` the mutation's output node /
                input type resolve against. Defaults to the process-global
                registry (byte-identical). A CUSTOM registry scopes the whole
                mutation subgraph to a schema's own pair (item-b B6), so a forked
                ``DjangoGraphQLSchema`` re-forks the payload's output node into
                its own namespace instead of reaching the global last-wins node.
            **options: Additional options forwarded to the base class.

        Raises:
            ImproperlyConfigured: If no "Meta.model" is provided, or if
                "model_operations" contains an unknown operation.
        """
        pydantic_model = build_validator_model(cls, model, pydantic_model)
        backend = resolve_backend(model, pydantic_model=pydantic_model)
        model = backend.get_model()

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

        django_fields = OrderedDict({output_field_name: Field(output_type)})

        model_operations = tuple(op.lower() for op in model_operations)
        unknown = set(model_operations) - {"create", "update", "delete"}
        if unknown:
            raise ImproperlyConfigured(
                "Meta.model_operations of {} contains unknown operation(s) {}; "
                'only "create", "update" and "delete" are valid.'.format(
                    cls.__name__, sorted(unknown)
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
                    # reference it directly. Each nested child's GENERIC input is
                    # ensured up front so the converter never silently drops the
                    # field (see ``_ensure_child_generic_input``).
                    for child_model in nested_map.values():
                        _ensure_child_generic_input(
                            child_model, operation, registry, parent_model=model
                        )
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
                    input_type = registry.get_type_for_model(model, for_input=operation)

                    if not input_type:
                        input_type = factory_type(
                            "input", DjangoInputObjectType, operation, **factory_kwargs
                        )

                # S6c: DjangoModelMutation is now NATIVE-ONLY (re-parented off
                # graphene onto ``native.base.ObjectType``). The input argument is
                # wrapped in a graphql-core ``GraphQLArgument`` UNCONDITIONALLY;
                # the old ``GDX_BACKEND == "native"`` env guard and the graphene
                # ``Argument(...)`` else-branch were removed — graphene can no
                # longer build a schema from this re-parented type.
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

        super().__init_subclass_with_meta__(
            _meta=_meta, description=description, **options
        )

        # ---------------------------------------------------------------------------
        # Native field construction (WU-3): build GraphQLField per operation and
        # store in the backend-keyed registry so *Field() can retrieve them.
        # S6c: DjangoModelMutation is now NATIVE-ONLY (re-parented off graphene),
        # so this runs UNCONDITIONALLY — the old ``GDX_BACKEND == "native"`` guard
        # was removed; graphene can no longer build a schema from this type.
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
        from django_graphex.native.schema_compiler import (
            _compile_plain_object_type,
        )

        _gql_output_type = _compile_plain_object_type(cls)

        from django_graphex.native._compat import _adapt_self

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

            from django_graphex.native._args import (
                graphene_arg_to_graphql_argument as _arg_conv,
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
                description=description or f"Native {_op} mutation for {model.__name__}",
            )
            # item-b (B6): record the mutation SOURCE class on the field's
            # extensions so a FORKED schema can RE-COMPILE the payload against its
            # own registry pair. The payload built here pins relation/output thunks
            # to the pair the class was DEFINED under (the global pair at class-def
            # time); a forked schema must re-fork the payload so its output field
            # (e.g. ``post: PostGenericType``) resolves to the SCHEMA's forked node,
            # not the global last-wins one (else assert_schema_pair_isolation fires).
            _gql_field.extensions = {
                **(_gql_field.extensions or {}),
                "gdx_mutation_source": cls,
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
        request_type = info.context.META.get("CONTENT_TYPE", "")
        if "multipart/form-data" in request_type:
            data.update({name: value for name, value in info.context.FILES.items()})

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

        old_obj = get_Object_or_None(cls._meta.model, pk=pk)
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
        request_type = info.context.META.get("CONTENT_TYPE", "")
        if "multipart/form-data" in request_type:
            data.update({name: value for name, value in info.context.FILES.items()})

        # Use .pop('id', None) so that an update input where 'id' was excluded
        # via only_fields/exclude_fields does not raise KeyError.  A None pk
        # means no object can be found, so old_obj will be None and the resolver
        # returns a clean "not found" error rather than a 500.
        pk = data.pop("id", None)
        # Optional inputs the client omitted (relational fields especially)
        # arrive as an explicit ``null`` because the generated update input
        # gives them a ``None`` default. On a partial update treat ``null`` as
        # "not provided" so an untouched value isn't wrongly cleared -- a
        # required FK would otherwise fail validation with "This field may not
        # be null". Send an explicit value to change a field.
        data = {name: value for name, value in data.items() if value is not None}
        old_obj = get_Object_or_None(cls._meta.model, pk=pk)
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
        """Return THIS mutation class's field for ``operation``.

        Prefers the per-class ``_native_fields`` map (built in
        ``__init_subclass_with_meta__``) so two distinct mutations on the SAME
        model never hand back each other's field. Falls back to the model-keyed
        ``_NATIVE_FIELD_REGISTRY`` only when the per-class map is absent (legacy
        / defensive path).

        Args:
            operation: The mutation operation ("create", "delete", "update").

        Returns:
            The graphql-core ``GraphQLField`` for this class + operation.
        """
        own = getattr(cls, "_native_fields", None)
        if own is not None and operation in own:
            return own[operation]
        return _NATIVE_FIELD_REGISTRY[(cls._meta.model, operation, "native")]

    @classmethod
    def CreateField(cls, *args: Any, **kwargs: Any) -> Any:
        """Build a GraphQL field for the create mutation.

        Returns this class's ``create`` ``GraphQLField`` (see
        ``_native_field_for``).

        Args:
            *args: Positional arguments (unused).
            **kwargs: Extra keyword arguments (unused).

        Returns:
            The field resolving to the create mutation.

        Raises:
            AttributeError: If "create" is not in Meta.model_operations.
        """
        cls._assert_operation("create")
        return cls._native_field_for("create")

    @classmethod
    def DeleteField(cls, *args: Any, **kwargs: Any) -> Any:
        """Build a GraphQL field for the delete mutation.

        Returns this class's ``delete`` ``GraphQLField`` (see
        ``_native_field_for``).

        Args:
            *args: Positional arguments (unused).
            **kwargs: Extra keyword arguments (unused).

        Returns:
            The field resolving to the delete mutation.

        Raises:
            AttributeError: If "delete" is not in Meta.model_operations.
        """
        cls._assert_operation("delete")
        return cls._native_field_for("delete")

    @classmethod
    def UpdateField(cls, *args: Any, **kwargs: Any) -> Any:
        """Build a GraphQL field for the update mutation.

        Returns this class's ``update`` ``GraphQLField`` (see
        ``_native_field_for``).

        Args:
            *args: Positional arguments (unused).
            **kwargs: Extra keyword arguments (unused).

        Returns:
            The field resolving to the update mutation.

        Raises:
            AttributeError: If "update" is not in Meta.model_operations.
        """
        cls._assert_operation("update")
        return cls._native_field_for("update")

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
            for every operation enabled in ``Meta.model_operations``.
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
