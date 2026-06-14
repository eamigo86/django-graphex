"""Native output registry compiler.

``NativeOutputRegistry`` — a lightweight registry that tracks model→name
mappings and their inter-type relations for the native compile path.

``compile_all(registry)`` — two-phase compilation:
  Phase 1: ``model_rebuild()`` — reserved for Pydantic model rebuilding
           (no-op for non-Pydantic output classes, but called for completeness).
  Phase 2: ``_compile_one()`` — compile each registered type, registering a
           ``GraphQLObjectType(fields=lambda: …)`` stub in ``_in_progress``
           BEFORE recursing into relation fields (memoize-before-recurse).

The default-arg idiom ``lambda t=cls: ...`` prevents loop-variable capture.
Mutual recursion A→B→A is safe: when B is compiled, A's stub is already in
``_in_progress``, so B's field thunk resolves A from the registry, not recursively.

``BuildError`` — raised when any compiled type lacks ``extensions["gdx"]``.

No imports from ``graphene``.
"""

from __future__ import annotations

from typing import Any

from graphql import GraphQLField, GraphQLObjectType, GraphQLString

from django_graphex.native.bridge import GdxPayload
from django_graphex.native.ir import GdxMeta


# ---------------------------------------------------------------------------
# BuildError
# ---------------------------------------------------------------------------


class BuildError(RuntimeError):
    """Raised at build time when a native type is misconfigured.

    Currently raised when a compiled ``GraphQLObjectType`` lacks
    ``extensions["gdx"]``, which means it was created outside the native
    pipeline and bypassed the ``GdxPayload`` contract.
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
            gql_name: The GraphQL type name (e.g. ``"Author"``).
            model_cls: The model class (Django or plain Python) being compiled.
            related_models: List of model classes this type references via
                relation fields. Used to build the fields thunk.
            skip_gdx: Test-only flag. If True, the compiled type will NOT
                receive ``extensions["gdx"]``, triggering ``BuildError``.
        """
        self._entries.append((
            gql_name,
            model_cls,
            list(related_models or []),
            skip_gdx,
        ))

    def get_compiled(self, model_cls: type) -> GraphQLObjectType | None:
        """Return the compiled ``GraphQLObjectType`` for ``model_cls``, or None."""
        return self._compiled.get(model_cls)

    def set_compiled(self, model_cls: type, gql_type: GraphQLObjectType) -> None:
        """Store a compiled type (called by ``_compile_one``)."""
        self._compiled[model_cls] = gql_type

    def iter_entries(self) -> list[tuple[str, type, list[type], bool]]:
        """Return entries in registration order."""
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

            # Default-arg captures the current related_cls (loop-capture fix)
            def _get_related_type(
                _cls: type = related_cls,
                _r: NativeOutputRegistry = _reg,
            ) -> GraphQLObjectType:
                # Try compiled first, then in-progress stub
                compiled = _r.get_compiled(_cls)
                if compiled is not None:
                    return compiled
                stub = _in_progress.get(id(_cls))
                if stub is not None:
                    return stub
                return GraphQLString  # type: ignore[return-value]  # fallback

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

    Phase 1: ``model_rebuild()`` — reserved for Pydantic model rebuilding.
             For non-Pydantic classes, this is a no-op.

    Phase 2: ``_compile_one()`` — compile each registered type in registration
             order. Each type's stub is registered in ``_in_progress`` BEFORE
             recursing into relation fields (cycle guard).

    Phase 3: Build-time assertion — verify every compiled ``GraphQLObjectType``
             carries ``extensions["gdx"]``.

    Raises:
        BuildError: If any compiled type lacks ``extensions["gdx"]``.
    """
    _reset_in_progress()

    entries = registry.iter_entries()

    # Phase 1: model_rebuild (no-op for non-Pydantic types)
    for _gql_name, model_cls, _related, _skip_gdx in entries:
        if hasattr(model_cls, "model_rebuild"):
            try:
                model_cls.model_rebuild()  # type: ignore[union-attr]
            except Exception:
                pass  # Not all classes support model_rebuild

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
