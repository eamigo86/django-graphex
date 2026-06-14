"""ObjectType and InputType base classes for the native backend.

Pydantic ``ModelMetaclass`` is the sole metaclass for all public input types.
Zero custom metaclass written — ``InputType`` is a plain ``BaseModel`` subclass.

Design contracts:
- ``type(AnyInputSubclass) is pydantic.ModelMetaclass``
- ``ConfigDict(alias_generator=to_camel, populate_by_name=True)``
- ``__init_subclass__`` pushes every ``InputType`` subclass to the module-level
  ``_gdx_input_registry`` list.
- ``compile_all_inputs()`` runs in two passes after ``AppConfig.ready()``:
    PASS 1: ``model_rebuild(raise_errors=True)`` for all registered classes.
    PASS 2: ``compile_input_type(...)`` for all; duplicate GraphQL names →
            ``ImproperlyConfigured``.
- ``_GdxGetItemMixin.__getitem__`` enables ``data["field_name"]`` access on
  validated instances.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


# ---------------------------------------------------------------------------
# __getitem__ mixin
# ---------------------------------------------------------------------------


class _GdxGetItemMixin:
    """Mixin that adds ``data["key"]`` access to Pydantic model instances.

    ``model_dump()`` is called once per ``__getitem__`` call, which is
    acceptable at resolve time (not a hot path).
    """

    def __getitem__(self, key: str) -> Any:
        return self.model_dump()[key]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _GdxInputOptions — carries the compiled GraphQLInputObjectType
# ---------------------------------------------------------------------------


@dataclass
class _GdxInputOptions:
    """Options object stored on ``InputType`` subclasses after compilation.

    Accessed via ``cls._meta.graphql_input_type``.
    """

    graphql_input_type: Any = None  # set by compile_all_inputs()


class _GdxInputMeta:
    """Simple proxy over ``_GdxInputOptions`` to expose ``graphql_input_type``."""

    __slots__ = ("_opts",)

    def __init__(self, opts: _GdxInputOptions) -> None:
        object.__setattr__(self, "_opts", opts)

    @property
    def graphql_input_type(self) -> Any:
        return object.__getattribute__(self, "_opts").graphql_input_type


# ---------------------------------------------------------------------------
# ObjectType base (model-free output, Phase 3+)
# ---------------------------------------------------------------------------


class ObjectType(_GdxGetItemMixin, BaseModel):
    """Base class for model-free GraphQL output types.

    Uses Pydantic's ``ModelMetaclass`` as the class metaclass.
    ``alias_generator=to_camel`` wires camelCase SDL names automatically.
    ``populate_by_name=True`` lets callers construct with either snake or camel keys.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# ---------------------------------------------------------------------------
# Module-level registry of all InputType subclasses
# ---------------------------------------------------------------------------

_gdx_input_registry: list[type["InputType"]] = []


# ---------------------------------------------------------------------------
# InputType base (model-free inputs)
# ---------------------------------------------------------------------------


class InputType(ObjectType):
    """Base class for model-free GraphQL input types.

    Every subclass is automatically registered in ``_gdx_input_registry`` via
    ``__init_subclass__`` and compiled by ``compile_all_inputs()`` at startup.

    Usage::

        from django_graphex import InputType

        class SearchInput(InputType):
            query: str
            limit: int = 10
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _gdx_input_registry.append(cls)

        # Attach an empty _meta (graphql_input_type populated by compile_all_inputs)
        opts = _GdxInputOptions()
        cls._meta = _GdxInputMeta(opts)  # type: ignore[attr-defined]
        # Keep a reference to the options so compile_all_inputs can mutate it
        cls._gdx_opts = opts  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# compile_all_inputs
# ---------------------------------------------------------------------------


def compile_all_inputs() -> None:
    """Compile all registered ``InputType`` subclasses into ``GraphQLInputObjectType``.

    Called by ``DjangoGraphexConfig.ready()`` after all app models are loaded.

    Algorithm (two-pass to resolve forward refs deterministically):
    1. ``model_rebuild(raise_errors=True)`` for every registered class.
       ``PydanticUserError(code='model-not-fully-defined')`` is re-raised as
       ``ImproperlyConfigured`` naming the class and the unresolved ref.
    2. ``compile_input_type(...)`` for every class.
       Duplicate GraphQL names raise ``ImproperlyConfigured``.
    """
    from django.core.exceptions import ImproperlyConfigured

    from django_graphex.native.input_compiler import compile_input_type

    # PASS 1: model_rebuild for all (resolves cross-module forward refs)
    for cls in _gdx_input_registry:
        try:
            cls.model_rebuild(raise_errors=True)
        except Exception as exc:
            raise ImproperlyConfigured(
                f"compile_all_inputs: could not rebuild model for {cls.__name__!r}. "
                f"Unresolved forward reference in annotations. "
                f"Original error: {exc}"
            ) from exc

    # PASS 2: compile_input_type for all (detect duplicates)
    seen_names: dict[str, type] = {}
    for cls in _gdx_input_registry:
        # GraphQL type name defaults to the class name
        gql_name = cls.__name__
        if gql_name in seen_names:
            raise ImproperlyConfigured(
                f"compile_all_inputs: duplicate GraphQL input type name "
                f"{gql_name!r} — defined by both "
                f"{seen_names[gql_name].__module__}.{seen_names[gql_name].__qualname__} "
                f"and {cls.__module__}.{cls.__qualname__}."
            )
        seen_names[gql_name] = cls

        # Compile and store on _meta
        graphql_input_type = compile_input_type(
            cls,
            name=gql_name,
            description=getattr(cls, "__doc__", None),
        )
        cls._gdx_opts.graphql_input_type = graphql_input_type  # type: ignore[attr-defined]
