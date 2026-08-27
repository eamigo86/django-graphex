"""Native output registry compiler.

"NativeOutputRegistry" — a lightweight registry that tracks model-to-name
mappings and their inter-type relations for the native compile path.

"compile_all(registry)" — two-phase compilation:
  Phase 1: "model_rebuild()" — reserved for Pydantic model rebuilding (no-op for
           non-Pydantic output classes, but called for completeness).
  Phase 2: "_compile_one()" — compile each registered type, registering a
           "GraphQLObjectType(fields=lambda: ...)" stub in "_in_progress" BEFORE
           recursing into relation fields (memoize-before-recurse).

The default-arg idiom "lambda t=cls: ..." prevents loop-variable capture.
Mutual recursion A->B->A is safe: when B is compiled, A's stub is already in
"_in_progress", so B's field thunk resolves A from the registry, not
recursively.

"BuildError" — raised when any compiled type lacks "extensions[gdx]".

No imports from "graphene".
"""

from __future__ import annotations

import logging
from typing import Any

from graphql import GraphQLField, GraphQLObjectType

from django_graphex.core.bridge import GdxPayload
from django_graphex.core.ir import GdxMeta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BuildError
# ---------------------------------------------------------------------------


class BuildError(RuntimeError):
    """Raised at build time when a native type is misconfigured.

    Currently raised when a compiled "GraphQLObjectType" lacks
    "extensions[gdx]", which means it was created outside the native pipeline and
    bypassed the "GdxPayload" contract.
    """


# ---------------------------------------------------------------------------
# NativeOutputRegistry
# ---------------------------------------------------------------------------


class NativeOutputRegistry:
    """Registry for native output types awaiting compilation.

    Usage::

        registry = NativeOutputRegistry()
        registry.register("MyType", MyModel)
        compile_all(registry)
        gql_type = registry.get_compiled(MyModel)
    """

    def __init__(self) -> None:
        """Initialize an empty registry.

        Starts with no registered entries and no compiled types; both maps are
        populated later by "register" and "set_compiled".
        """
        # Ordered list: (gql_name, model_cls, related_models, skip_gdx)
        self._entries: list[tuple[str, type, list[type], bool]] = []
        # model_cls → compiled GraphQLObjectType
        self._compiled: dict[type, GraphQLObjectType] = {}

    def register(
        self,
        gql_name: str,
        model_cls: type,
        *,
        related_models: list[type] | None = None,
        skip_gdx: bool = False,
    ) -> None:
        """Register a model class for native output compilation.

        Args:
            gql_name: The GraphQL type name (e.g. "Author").
            model_cls: The model class (Django or plain Python) being compiled.
            related_models: List of model classes this type references via
                relation fields. Used to build the fields thunk.
            skip_gdx: Test-only flag. If True, the compiled type will NOT receive
                "extensions[gdx]", triggering "BuildError".
        """
        self._entries.append(
            (
                gql_name,
                model_cls,
                list(related_models or []),
                skip_gdx,
            )
        )

    def get_compiled(self, model_cls: type) -> GraphQLObjectType | None:
        """Return the compiled output type for a model class.

        Args:
            model_cls: The model class whose compiled type is requested.

        Returns:
            The compiled "GraphQLObjectType", or None when the model has not been
            compiled yet.
        """
        return self._compiled.get(model_cls)

    def set_compiled(self, model_cls: type, gql_type: GraphQLObjectType) -> None:
        """Store a compiled type for a model class.

        Called by "_compile_one" once a model's "GraphQLObjectType" is built.

        Args:
            model_cls: The model class the compiled type belongs to.
            gql_type: The compiled "GraphQLObjectType" to store.
        """
        self._compiled[model_cls] = gql_type

    def iter_entries(self) -> list[tuple[str, type, list[type], bool]]:
        """Return the registered entries in registration order.

        Returns:
            A copy of the "(gql_name, model_cls, related_models, skip_gdx)"
            tuples, in the order they were registered.
        """
        return list(self._entries)


# ---------------------------------------------------------------------------
# In-progress stub cache (module-level; cleared at compile_all entry)
# ---------------------------------------------------------------------------

# id(model_cls) → GraphQLObjectType stub
# Registered BEFORE field recursion (memoize-before-recurse cycle guard)
_in_progress: dict[int, GraphQLObjectType] = {}


def _reset_in_progress() -> None:
    """Clear the in-progress cache. Called at compile_all entry."""
    _in_progress.clear()


# ---------------------------------------------------------------------------
# _compile_one — compile a single type (memoize-before-recurse)
# ---------------------------------------------------------------------------


def _compile_one(
    gql_name: str,
    model_cls: type,
    related_models: list[type],
    registry: NativeOutputRegistry,
    *,
    skip_gdx: bool = False,
) -> GraphQLObjectType:
    """Compile a single model class to a ``GraphQLObjectType``.

    Registers a placeholder stub in ``_in_progress[id(model_cls)]`` BEFORE
    building the fields thunk so mutual recursion terminates:

    - A → B → A: when B is compiled, A's stub is already in ``_in_progress``,
      B's field thunk finds the stub and uses it — no re-entry into A's compile.

    Args:
        gql_name: GraphQL type name.
        model_cls: The model class being compiled.
        related_models: Model classes referenced via relation fields.
        registry: The registry holding already-compiled types.
        skip_gdx: If True, omit ``extensions["gdx"]`` (for error-path tests).
    """
    # Return already-compiled type immediately
    existing = registry.get_compiled(model_cls)
    if existing is not None:
        return existing

    # Return in-progress stub (cycle guard)
    stub = _in_progress.get(id(model_cls))
    if stub is not None:
        return stub

    # Build GdxPayload (or omit for skip_gdx test path)
    if skip_gdx:
        extensions: dict[str, Any] = {}
    else:
        gdx_meta = GdxMeta(name=gql_name)
        payload = GdxPayload(gdx_meta)
        extensions = {"gdx": payload}

    # Register a placeholder stub BEFORE building fields (memoize-before-recurse)
    obj_type = GraphQLObjectType(
        name=gql_name,
        fields=lambda: {},  # Temporary empty thunk; replaced below
        extensions=extensions,
    )
    _in_progress[id(model_cls)] = obj_type

    # Build the real fields thunk. The default-arg idiom captures related_models
    # at this point, avoiding loop-variable capture across multiple calls.
    # Build a mapping of model_cls → (gql_name, skip_gdx) for relation lookup
    _all_entries = {entry[1]: (entry[0], entry[3]) for entry in registry.iter_entries()}

    def _make_fields_thunk(
        _related: list[type] = related_models,
        _reg: NativeOutputRegistry = registry,
        _entries: dict = _all_entries,
    ):
        """Lazily build fields dict; all types are in-progress or compiled by now."""
        fields: dict[str, GraphQLField] = {}

        for related_cls in _related:
            # Use the registered GraphQL name to derive the field name (camelCase)
            registered = _entries.get(related_cls)
            if registered:
                gql_type_name = registered[0]  # e.g. "NodeB"
            else:
                gql_type_name = related_cls.__name__
            # Convert PascalCase → camelCase for the field name
            # e.g. "NodeB" → "nodeB", "Category" → "category"
            field_name = gql_type_name[0].lower() + gql_type_name[1:]

            # Resolve the related type: compiled first, then in-progress stub.
            related_type = _reg.get_compiled(related_cls)
            if related_type is None:
                related_type = _in_progress.get(id(related_cls))

            # Audit rank 6: a related model that was neither compiled nor
            # in-progress must NOT be emitted as a silent ``GraphQLString`` (a
            # wire type mismatch — a String standing in for an object type).
            # Partial registration is a LEGITIMATE use case, so SKIP the field
            # with a logged warning rather than emit a String or fail the build.
            if related_type is None:
                logger.warning(
                    "Dropping relation %r on %r: target model %r is not "
                    "registered/compiled. Register a DjangoObjectType for %r to "
                    "expose this relation (it was previously emitted as a silent "
                    "GraphQLString).",
                    field_name,
                    model_cls.__name__,
                    related_cls.__name__,
                    related_cls.__name__,
                )
                continue

            # Default-arg captures the current related_type (loop-capture fix).
            def _get_related_type(
                _t: GraphQLObjectType = related_type,
            ) -> GraphQLObjectType:
                return _t

            fields[field_name] = GraphQLField(type_=_get_related_type())

        return fields

    # Rebuild the obj_type with the real fields thunk.
    # GraphQL-core allows updating the fields function via the internal API.
    # We reconstruct the type to wire the real thunk.
    real_obj_type = GraphQLObjectType(
        name=gql_name,
        fields=_make_fields_thunk,
        extensions=extensions,
    )

    # Update the in-progress stub to point to the real type
    # (the stub itself is not used by callers — registry.get_compiled() wins)
    _in_progress[id(model_cls)] = real_obj_type

    # Store in registry
    registry.set_compiled(model_cls, real_obj_type)

    return real_obj_type


# ---------------------------------------------------------------------------
# compile_all — two-phase compilation
# ---------------------------------------------------------------------------


def compile_all(registry: NativeOutputRegistry) -> None:
    """Compile all registered output types.

    Phase 1: "model_rebuild()" -- reserved for Pydantic model rebuilding.
             For non-Pydantic classes, this is a no-op.

    Phase 2: "_compile_one()" -- compile each registered type in registration
             order. Each type's stub is registered in "_in_progress" BEFORE
             recursing into relation fields (cycle guard).

    Phase 3: Build-time assertion -- verify every compiled "GraphQLObjectType"
             carries extensions["gdx"].

    Args:
        registry: The native output registry holding the entries to compile;
            each compiled type is stored back into it.

    Raises:
        BuildError: If any registered type fails to compile or a compiled type
            lacks extensions["gdx"].
    """
    _reset_in_progress()

    entries = registry.iter_entries()

    # Phase 1: model_rebuild (no-op for non-Pydantic types)
    for _gql_name, model_cls, _related, _skip_gdx in entries:
        if hasattr(model_cls, "model_rebuild"):
            try:
                model_cls.model_rebuild()  # type: ignore[union-attr]
            except Exception:
                pass  # nosec B110 — not all classes support model_rebuild

    # Phase 2: compile each type
    for gql_name, model_cls, related_models, skip_gdx in entries:
        _compile_one(
            gql_name,
            model_cls,
            related_models,
            registry,
            skip_gdx=skip_gdx,
        )

    # Phase 3: build-time assertion — all compiled types must carry extensions["gdx"]
    for gql_name, model_cls, _related, _skip_gdx in entries:
        compiled = registry.get_compiled(model_cls)
        if compiled is None:
            raise BuildError(
                f"compile_all: {gql_name!r} (model: {model_cls.__name__!r}) "
                f"failed to compile."
            )
        if "gdx" not in (compiled.extensions or {}):
            raise BuildError(
                f"compile_all: type {gql_name!r} (model: {model_cls.__name__!r}) "
                f"is missing extensions['gdx']. All native output types must be "
                f"compiled via compile_all to receive GdxPayload. "
                f"If this is an intentional test, use skip_gdx=True only in tests."
            )


# ---------------------------------------------------------------------------
# compile_all_outputs — global output registry compilation
# ---------------------------------------------------------------------------


def compile_all_outputs() -> None:
    """Populate and validate per-CLASS "GraphQLObjectType" instances.

    Operates on the single per-class instances registered in the global
    "_gdx_output_registry".

    Called by "DjangoGraphexConfig.ready()" after "compile_all_inputs()".

    IDENTITY INVARIANT (the whole point of this function): there is EXACTLY ONE
    "GraphQLObjectType" per "DjangoObjectType" class, created ONCE at class
    definition ("DjangoObjectType.__init_subclass_with_meta__" native branch)
    with relation-field THUNKS bound to the SHARED global registry
    ("get_shared_output_registry()"). This function MUST:

    - REUSE those existing per-class instances (read from
      "cls._meta.graphql_output_type") -- it NEVER creates a second
      "GraphQLObjectType". (A second instance with the same name poisons the
      mutation-pinned reference and makes "GraphQLSchema" raise "multiple
      types named '<TypeName>'".)
    - Register each model's CANONICAL instance in the module-level
      "_in_progress" cycle guard so relation thunks resolve cross-type
      references (A to B to A) to the related type's real "GraphQLObjectType"
      instead of a "GraphQLString" fallback.
    - FORCE thunk evaluation (read ".fields") -- after invalidating any stale
      "@cached_property" from a premature class-def read -- so silent build
      errors surface deterministically at app-ready, not lazily on first query.
    - Assert every per-class instance carries extensions["gdx"].

    "_in_progress" is cleared at BOTH entry and exit ("finally") so no stale
    stubs leak into later reads via "_get_related_type".

    Note on multiple classes per model: distinct DjangoObjectType classes may
    wrap the same model (different "only_fields", "complexity", and so on). Each
    keeps its OWN per-class instance on "_meta"; the SHARED registry holds the
    model's CANONICAL (last-registered, non-"skip_registry") instance, mirroring
    the graphene "Registry.get_type_for_model(model)" rule that mutations and
    relation fields both consult.

    Raises:
        BuildError: If any registered class has no instance or lacks
            extensions["gdx"].
    """
    from django_graphex.core.base import (
        _gdx_output_registry,
        get_shared_output_registry,
        recompile_fields,
    )
    from django_graphex.registry import get_global_registry

    _reset_in_progress()

    if not _gdx_output_registry:
        return

    # item-b (B5): the app-ready compile owns ONLY the GLOBAL-registry types.
    # A type declared in a CUSTOM (non-global) graphene ``Registry`` is
    # SCHEMA-SCOPED — it is compiled into its schema's pair by
    # ``compile_outputs_into`` (forked) or reused via its class-def instance
    # (default pair). Such a type must NOT enter the global app-ready compile:
    # forked schemas auto-create per-pair ``<Model>ListType`` containers that
    # land in this global list, and compiling several same-named ones here would
    # poison the global shared registry (the duplicate-name hazard the fork
    # exists to avoid). Filtering them out keeps the global app-ready compile
    # byte-identical to the pre-fork single-namespace behavior.
    _global_graphene = get_global_registry()

    def _is_global_entry(entry: Any) -> bool:
        reg = getattr(getattr(entry.cls, "_meta", None), "registry", None)
        # No registry recorded (legacy / model-free) -> treat as global so we
        # never silently drop a type that the global app-ready compile owned.
        return reg is None or reg is _global_graphene

    _global_entries = [e for e in _gdx_output_registry if _is_global_entry(e)]
    if not _global_entries:
        return

    # The SAME shared registry the class-def compile used.  Each model's
    # canonical instance is already registered there (last-wins).
    shared_registry = get_shared_output_registry()

    def _class_instance(entry: Any) -> GraphQLObjectType:
        """Return the per-class GraphQLObjectType built at class-def time."""
        meta = getattr(entry.cls, "_meta", None)
        inst = getattr(meta, "graphql_output_type", None)
        if inst is None:
            raise BuildError(
                f"compile_all_outputs: {entry.gql_name!r} "
                f"(model: {entry.model.__name__!r}) has no compiled "
                f"GraphQLObjectType on _meta. The class-def native branch must "
                f"create the single per-class instance before compile_all_outputs()."
            )
        return inst

    try:
        # ── Phase 1: register each model's CANONICAL instance in the cycle guard
        # so relation thunks of OTHER classes resolve A→B→A to that object.  We
        # do NOT create any new instance — the canonical one was set at class-def.
        for entry in _global_entries:
            canonical = shared_registry.get_compiled(entry.model)
            if canonical is None:
                # No non-skip_registry class claimed the model slot (e.g. every
                # class for it used skip_registry=True).  Fall back to this
                # class's own instance so relations still resolve to a real type.
                canonical = _class_instance(entry)
                shared_registry.set_compiled(entry.model, canonical)
            _in_progress[id(entry.model)] = canonical

        # ── Phase 2: force thunk evaluation on EACH per-class instance against
        # the now-complete shared registry.  graphql-core's
        # ``GraphQLObjectType.fields`` is a @cached_property: a premature
        # class-def read (e.g. a test) may have cached a GraphQLString fallback
        # for a relation whose target was not yet registered.  Invalidate that
        # cache first, then re-evaluate so relations resolve to real types.
        for entry in _global_entries:
            recompile_fields(_class_instance(entry))

        # ── Phase 3: assertion — every per-class instance must carry gdx ─────
        for entry in _global_entries:
            inst = _class_instance(entry)
            if "gdx" not in (inst.extensions or {}):
                raise BuildError(
                    f"compile_all_outputs: type {entry.gql_name!r} "
                    f"(model: {entry.model.__name__!r}) is missing "
                    f"extensions['gdx']."
                )
    finally:
        # Reset at exit too: no stale stubs leak into later reads via
        # _get_related_type / a subsequent compile_all() run.
        _reset_in_progress()


# ---------------------------------------------------------------------------
# compile_outputs_into — fork per-class output instances into a registry pair
# ---------------------------------------------------------------------------


def _forked_interfaces_thunk(meta: Any, class_inst: Any, registries: Any) -> Any:
    """Return the ``interfaces=`` value a forked object type must carry.

    A class-def ``GraphQLObjectType`` compiles its implemented interfaces against
    the DEFAULT interface cache (the class body cannot know which pair a later
    schema will use). Copying that compiled list onto the fork mixes namespaces:
    a root ``field(SomeInterface)`` in the SAME forked schema compiles a SECOND,
    pair-local ``GraphQLInterfaceType`` with the same name, and graphql-core
    rejects the schema with "Schema must contain uniquely named types".

    So the declared interface CLASSES are re-compiled through the pair's own
    cache. The result is a THUNK (never an eager list) so a self-referential
    interface field still terminates, mirroring the class-def contract.

    Args:
        meta: The output class' ``_meta`` (carries the declared ``interfaces``).
        class_inst: The class-def ``GraphQLObjectType`` used as the fallback when
            nothing interface-shaped was declared.
        registries: The ``SchemaRegistries`` pair the fork belongs to.

    Returns:
        A zero-argument thunk returning this pair's compiled interfaces, or the
        class-def interface list (possibly ``None``) when none were declared.
    """
    declared = tuple(getattr(meta, "interfaces", None) or ())
    if not declared:
        return getattr(class_inst, "interfaces", None) or None

    def _interfaces(
        _declared: tuple[Any, ...] = declared, _registries: Any = registries
    ) -> list[Any]:
        from django_graphex.core.polymorphic_compiler import (
            compile_interface_type,
            is_interface_type,
        )

        return [
            compile_interface_type(iface, _registries)
            for iface in _declared
            if is_interface_type(iface)
        ]

    return _interfaces


def _fork_output_class(
    cls: Any, entry: Any, registries: Any, output_registry: Any, graphene_registry: Any
) -> GraphQLObjectType:
    """Build (or return) the FORKED ``GraphQLObjectType`` for *cls* in *registries*.

    item-b (B5): the single-entry fork builder shared by ``compile_outputs_into``
    (the eager pass) and ``fork_output_class`` (the on-demand path for lazily
    auto-created ``<Model>ListType`` containers reached during thunk eval). Builds
    a pair-local instance whose thunk closes over THIS pair's registries, copies
    the class-def gdx payload (R4), and registers it in the pair's caches.

    Returns the existing fork when *cls* is already forked into this pair.
    """
    from django_graphex.types import (
        DjangoListObjectType,
        _make_list_fields_thunk_for,
        _make_output_thunk_for,
    )

    forks = registries.output_instances
    existing = forks.get(cls)
    if existing is not None:
        return existing

    meta = getattr(cls, "_meta", None)
    class_inst = getattr(meta, "graphql_output_type", None)
    if class_inst is None:
        raise BuildError(
            f"_fork_output_class: {entry.gql_name!r} "
            f"(model: {entry.model.__name__!r}) has no class-def "
            f"GraphQLObjectType on _meta — cannot fork."
        )
    # Copy the class-def gdx payload VERBATIM (R4): same GdxMeta object, so the
    # forked instance carries graphene_type / model / depth / cost / name.
    extensions = dict(class_inst.extensions or {})

    is_list = isinstance(cls, type) and issubclass(cls, DjangoListObjectType)
    if is_list:
        thunk = _make_list_fields_thunk_for(
            entry.model,
            getattr(meta, "results_field_name", None) or "results",
            output_registry,
            # item-b (B6): use the RESOLVED paginator (``_meta.paginator``, set at
            # class-def from ``Meta.pagination`` OR the global default), NOT the raw
            # ``_meta.pagination`` (often ``None`` when only the global default
            # applies). Falling back to raw pagination would drop the results-field
            # pagination resolver on the fork — a renamed results field (e.g.
            # ``items``) would then return ``None`` via the default attr resolver.
            getattr(meta, "paginator", None) or getattr(meta, "pagination", None),
        )
    else:
        thunk = _make_output_thunk_for(
            cls,
            entry.model,
            output_registry,
            graphene_registry,
            entry.only_fields,
            entry.exclude_fields,
            registries,
            include_fields=getattr(entry, "include_fields", None),
        )

    forked = GraphQLObjectType(
        name=entry.gql_name,
        fields=thunk,
        interfaces=_forked_interfaces_thunk(meta, class_inst, registries),
        extensions=extensions,
    )
    # Register BEFORE returning so a self-referential / mutually-recursive
    # relation thunk resolves through this same instance.
    forks[cls] = forked
    # A ``DjangoListObjectType`` CONTAINER must NOT claim the model's output slot:
    # that slot belongs to the element node (the ``<Model>GenericType`` /
    # ``DjangoObjectType``) so a list container's ``results`` thunk
    # (``output_registry.get_compiled(model)``) resolves to the NODE, not to the
    # container itself. This mirrors the class-def native branch, which builds the
    # list container WITHOUT a ``_shared_registry.set_compiled(model, ...)`` call
    # (types.py ``DjangoListObjectType`` branch). Registering the container here
    # (the pre-fix behavior) overwrote the model slot last-wins, so the forked
    # ``results`` node degraded to ``[<Container>]`` and every nested field query
    # raised "Cannot query field '<f>' on type '<Model>ListType'".
    if not getattr(meta, "skip_registry", False) and not is_list:
        output_registry.set_compiled(entry.model, forked)
    return forked


def fork_output_class(cls: Any, registries: Any) -> GraphQLObjectType | None:
    """Fork "cls" into "registries" ON DEMAND, returning the pair-local instance.

    item-b (B5): the on-demand fork path for a "DjangoObjectType" or
    "DjangoListObjectType" that was NOT present when "compile_outputs_into"
    ran (e.g. an auto-created "<Model>ListType" container materialized lazily
    inside a relation thunk). Without this, the reverse-relation container would
    fall back to its class-def instance (bound to the GLOBAL output registry),
    re-introducing the same-named-instance collision the fork exists to prevent.

    Returns None when "registries" is not a forked pair (its
    "output_instances" map is absent), so the caller falls back to the class-def
    instance -- byte-identical for the default pair.

    The entry's projection and pagination metadata is recovered from the LAST
    "_gdx_output_registry" entry for "cls" (the one carrying the right
    "only_fields", "exclude_fields", and model the class was registered with).

    Args:
        cls: The output class to fork into the pair.
        registries: The schema registries pair to fork into; when not a forked
            pair the function returns None.

    Returns:
        forked: The pair-local forked object type, or None when the pair is not
            a forked pair or the class cannot be forked (no model/_meta).
    """
    forks = getattr(registries, "output_instances", None)
    if forks is None:
        return None
    existing = forks.get(cls)
    if existing is not None:
        return existing

    from django_graphex.core.base import (
        _gdx_output_registry,
        _GdxOutputEntry,
        recompile_fields,
    )

    # Find the registry entry for this class (last-registered wins, matching the
    # canonical-instance rule).
    entry = None
    for candidate in reversed(_gdx_output_registry):
        if candidate.cls is cls:
            entry = candidate
            break
    if entry is None:
        # No global entry: this is a type AUTO-CREATED during a forked build (its
        # class-def skipped the global append by design — item-b B5). Synthesize
        # an entry from its ``_meta`` so the fork has the model + projection it
        # needs. A class with no model/_meta cannot be forked.
        meta = getattr(cls, "_meta", None)
        model = getattr(meta, "model", None)
        if model is None:
            return None
        entry = _GdxOutputEntry(
            cls=cls,
            gql_name=getattr(meta, "name", None) or cls.__name__,
            model=model,
            only_fields=None,
            exclude_fields=None,
            max_depth=getattr(meta, "max_depth", None),
            complexity=getattr(meta, "complexity", None),
        )

    graphene_registry = getattr(registries, "graphene", None)
    output_registry = getattr(registries, "output", None)
    if graphene_registry is None or output_registry is None:
        return None

    forked = _fork_output_class(
        cls, entry, registries, output_registry, graphene_registry
    )
    # Force eval so the on-demand container's results node resolves against the
    # pair now (it is reached mid-thunk, so warm its cache immediately).
    recompile_fields(forked)
    return forked


def compile_outputs_into(registries: Any) -> None:
    """FORK pair-local output "GraphQLObjectType" instances into "registries".

    item-b (B5, THE CRUX). This is the counterpart to "compile_all_outputs()"
    for a NON-default "SchemaRegistries" pair. Where "compile_all_outputs()"
    REUSES the single class-def instance on "_meta.graphql_output_type",
    "compile_outputs_into" BUILDS a SECOND, pair-local instance for every
    registered output class whose "_meta.registry" is THIS pair's graphene
    "Registry" -- so two "DjangoGraphQLSchema" over the same model (each with
    a distinct pair) own DISTINCT same-named "GraphQLObjectType" instances and
    graphql-core never raises "Schema must contain uniquely named types".

    The forked instances:

    - close their relation thunks over THIS pair's "output"
      "NativeOutputRegistry" plus the schema's graphene registry (so a relation
      resolves to the SAME schema's forked instance, NOT the global last-wins
      slot -- the R1 leak fix);
    - copy the class-def gdx meta ("graphene_type" = source class, "model",
      name, depth/cost) onto the fork so the optimizer (which reads
      "info.schema" plus the gdx bridge) works on forked schemas (R4);
    - are stored BOTH in "registries.output_instances[cls]" (read by
      "base.resolved_output_type") AND registered (last-wins, non-skip) in
      "registries.output" so the FK and list-container thunks resolve them.

    The DEFAULT pair NEVER calls this (the schema build skips it), so the
    single/default-schema path stays byte-identical: every read-site falls
    through "resolved_output_type" to the class-def instance.

    Scoping rule: only classes registered in THIS pair's graphene "Registry"
    are forked ("_meta.registry is registries.graphene"). A schema only
    references types declared in its own registry; forking the global registry's
    unrelated classes would needlessly pull foreign subgraphs into the pair.

    Args:
        registries: A NON-default "SchemaRegistries" pair (its "graphene" and
            "output" members are this schema's fresh registries).

    Raises:
        BuildError: If the pair lacks a graphene or output registry, or a
            forked instance ends up without extensions["gdx"].
    """
    from django_graphex.core.base import (
        _gdx_output_registry,
        recompile_fields,
        resolved_output_type,
    )
    from django_graphex.types import DjangoListObjectType

    graphene_registry = getattr(registries, "graphene", None)
    output_registry = getattr(registries, "output", None)
    if graphene_registry is None or output_registry is None:
        raise BuildError(
            "compile_outputs_into: the pair must carry a graphene Registry and a "
            "NativeOutputRegistry (got graphene=%r, output=%r)."
            % (graphene_registry, output_registry)
        )

    # Pair-local map of forked per-class instances (read by resolved_output_type).
    forks: dict[type, GraphQLObjectType] = {}
    if registries.output_instances is None:
        registries.output_instances = forks
    else:
        forks = registries.output_instances

    # The entries belonging to THIS pair's registry, in registration order.
    pair_entries = [
        entry
        for entry in _gdx_output_registry
        if getattr(getattr(entry.cls, "_meta", None), "registry", None)
        is graphene_registry
    ]
    if not pair_entries:
        return

    def _is_list_entry(entry: Any) -> bool:
        return isinstance(entry.cls, type) and issubclass(
            entry.cls, DjangoListObjectType
        )

    # ── Phase 1: build a FORKED GraphQLObjectType per entry (NON-list first so a
    # list container's results node is already in the pair's output registry).
    _ordered = sorted(pair_entries, key=_is_list_entry)
    for entry in _ordered:
        _fork_output_class(
            entry.cls, entry, registries, output_registry, graphene_registry
        )

    # ── Phase 2: force thunk evaluation on each fork against the now-complete
    # pair registry (mirrors compile_all_outputs Phase 2) so relations resolve to
    # the forked instances, not a GraphQLString fallback. Thunk eval may FORK
    # MORE classes on demand (auto-created <Model>ListType containers reached via
    # a reverse relation); iterate over a SNAPSHOT and re-drain until stable so
    # every transitively-reached fork is warmed against the pair.
    _warmed: set[int] = set()
    while True:
        pending = [
            (cls, forked)
            for cls, forked in list(forks.items())
            if id(forked) not in _warmed
        ]
        if not pending:
            break
        for cls, forked in pending:
            recompile_fields(forked)
            _warmed.add(id(forked))

    # ── Phase 3: assertion — every fork must carry the gdx bridge (R4 sanity).
    for cls, forked in forks.items():
        if "gdx" not in (forked.extensions or {}):
            raise BuildError(
                f"compile_outputs_into: forked type {forked.name!r} is missing "
                f"extensions['gdx']."
            )

    # Touch resolved_output_type so the symbol is exercised (it is the read path
    # the schema build relies on; keeps the import meaningful for linters).
    assert resolved_output_type is not None


# ---------------------------------------------------------------------------
# assert_schema_pair_isolation — R1 build-invariant check
# ---------------------------------------------------------------------------


def assert_schema_pair_isolation(schema: Any, registries: Any) -> None:
    """Assert every reachable object type in "schema" belongs to "registries".

    item-b (B5) R1 MITIGATION -- the detection for the crux's HIGHEST risk:
    a relation thunk in schema A silently resolving to schema B's same-named
    instance. After building a NON-default (forked) schema, walk the reachable
    object types and assert that any type whose source class was forked into THIS
    pair IS the pair's forked instance (identity match in
    "registries.output_instances"). A mismatch means a cross-schema leak --
    raise loudly rather than ship a schema that silently resolves to the wrong
    instance.

    Mirrors "bridge.assert_gdx_bridge" (walk "schema.type_map", skip
    introspection, scalars, enums, and unions). For each "GraphQLObjectType"
    whose gdx "graphene_type" is a class forked into this pair, the schema's
    instance MUST be "registries.output_instances[graphene_type]".

    Args:
        schema: The built "GraphQLSchema".
        registries: The (non-default) "SchemaRegistries" pair the schema was
            forked into.

    Raises:
        BuildError: On the FIRST type whose schema instance does not match the
            pair's forked instance (cross-schema leakage).
    """
    from graphql import GraphQLEnumType, GraphQLScalarType, GraphQLUnionType

    forks = getattr(registries, "output_instances", None) or {}
    if not forks:
        # No fork happened (default pair) — nothing to isolate; byte-identical.
        return

    # Index the pair's forked instances by GraphQL NAME. The isolation guarantee
    # is per-NAME: if THIS pair forked an instance named ``X``, then every
    # ``X``-named object type reachable in the schema MUST be that exact instance
    # (a same-named instance from a DIFFERENT pair is the R1 cross-schema leak).
    forks_by_name: dict[str, GraphQLObjectType] = {}
    for forked in forks.values():
        forks_by_name[forked.name] = forked

    for type_name, gql_type in schema.type_map.items():
        if type_name.startswith("__"):
            continue
        if isinstance(gql_type, (GraphQLScalarType, GraphQLEnumType, GraphQLUnionType)):
            continue
        if not isinstance(gql_type, GraphQLObjectType):
            continue
        expected = forks_by_name.get(type_name)
        if expected is None:
            # This pair did not fork a type of this name — the schema may legally
            # reference a default/global type for it (a type it did not fork).
            continue
        if gql_type is not expected:
            payload = (gql_type.extensions or {}).get("gdx")
            try:
                source_cls = payload._meta.graphene_type if payload else None
            except AttributeError:  # pragma: no cover — defensive
                source_cls = None
            raise BuildError(
                f"assert_schema_pair_isolation: type {type_name!r} in the schema "
                f"is NOT this pair's forked instance (cross-schema leakage). "
                f"source_cls={source_cls!r}. A relation thunk resolved to a "
                f"different schema's same-named instance — the R1 crux risk."
            )
