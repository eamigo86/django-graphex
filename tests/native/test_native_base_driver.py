"""S6a contract tests — graphene-free driver on native ``ObjectType``.

These tests assert the load-bearing parts of graphene's ``SubclassWithMeta_Meta``
reproduced graphene-free on ``django_graphex.native.base.ObjectType`` so that a
later slice (S6b-S6f) can re-parent the 8 public ``Django*`` types onto the
native base WITHOUT graphene's metaclass.

S6a touches ONLY ``native/base.py`` — NO public type is re-parented yet, so the
machinery added here is exercised only by throwaway native subclasses defined in
these tests. The full suite must stay green because nothing public uses it.

Design under test (see engram sdd/graphene-removal/s6-plan #1534):
- ``type(NativeObjectSubclass)`` stays ``pydantic.ModelMetaclass`` (the systemic
  metaclass-identity constraint #1452). The driver runs via ``__init_subclass__``,
  NOT a custom metaclass.
- graphene field descriptors (``Boolean()``, ``List(...)``, ``Field(...)``) on the
  class body survive Pydantic via ``ConfigDict(ignored_types=(UnmountedType,
  MountedType))`` and are collected into ``_meta.fields`` (graphene-free), without
  routing them through Pydantic field inference and without breaking InputType.
- A ``Meta`` (class OR dict) is read, ``props(Meta)`` applied, ``abstract`` popped,
  ``__init_subclass_with_meta__(**options)`` dispatched, then ``Meta`` deleted.
- ``_meta`` is a MUTABLE Options object exposing the FULL parity-table attr surface
  with graphene's defaults — later slices plain-assign instead of the current
  ``object.__setattr__`` freeze workaround.
- ``cls(**kwargs)`` round-trips (the graphene ``cls(**resp)`` payload pattern).
"""
from __future__ import annotations

import pytest
from pydantic._internal._model_construction import ModelMetaclass

# ---------------------------------------------------------------------------
# Metaclass identity — driver runs WITHOUT a custom metaclass
# ---------------------------------------------------------------------------


@pytest.mark.native_only
def test_object_subclass_keeps_pydantic_model_metaclass():
    """A native ObjectType subclass keeps ``type() is ModelMetaclass`` (#1452)."""
    from django_graphex.native.base import ObjectType

    class NativeSub(ObjectType):
        class Meta:
            name = "NativeSub"

    assert type(NativeSub) is ModelMetaclass, (
        f"Expected ModelMetaclass (driver via __init_subclass__, NOT a custom "
        f"metaclass), got {type(NativeSub)}"
    )


# ---------------------------------------------------------------------------
# Meta dispatch — class form and dict form both reach __init_subclass_with_meta__
# ---------------------------------------------------------------------------


@pytest.mark.native_only
def test_meta_class_form_dispatches_options():
    """A class-style ``Meta`` is turned into kwargs and dispatched."""
    from django_graphex.native.base import ObjectType

    captured: dict = {}

    class Base(ObjectType):
        class Meta:
            abstract = True

        @classmethod
        def __init_subclass_with_meta__(cls, **options):
            captured.update(options)

    class Sub(Base):
        class Meta:
            name = "Custom"
            results_field_name = "rows"

    assert captured.get("name") == "Custom"
    assert captured.get("results_field_name") == "rows"


@pytest.mark.native_only
def test_meta_dict_form_dispatches_options():
    """A dict-style ``Meta`` is dispatched identically to the class form.

    Because the base ``ObjectType`` is a ``pydantic.ModelMetaclass`` class, a
    BARE ``dict`` named ``Meta`` would be consumed by Pydantic as a model field
    before ``__init_subclass__`` runs (PydanticUserError). The driver still
    supports the dict FORM faithfully (graphene parity) — the dict just has to be
    declared in a Pydantic-safe way, i.e. ``ClassVar``-annotated. No production
    type uses dict-form ``Meta``; all 8 public types use the class form.
    """
    from typing import ClassVar

    from django_graphex.native.base import ObjectType

    captured: dict = {}

    class Base(ObjectType):
        class Meta:
            abstract = True

        @classmethod
        def __init_subclass_with_meta__(cls, **options):
            captured.update(options)

    class Sub(Base):
        Meta: ClassVar = {"name": "DictForm", "pagination": "page"}

    assert captured.get("name") == "DictForm"
    assert captured.get("pagination") == "page"


@pytest.mark.native_only
def test_meta_deleted_after_dispatch():
    """``Meta`` is removed from the class after dispatch (graphene parity)."""
    from django_graphex.native.base import ObjectType

    class Base(ObjectType):
        class Meta:
            abstract = True

        @classmethod
        def __init_subclass_with_meta__(cls, **options):
            pass

    class Sub(Base):
        class Meta:
            name = "X"

    assert "Meta" not in Sub.__dict__, "Meta should be deleted after dispatch"


@pytest.mark.native_only
def test_invalid_meta_type_raises():
    """A ``Meta`` that is neither a class nor a dict raises (graphene parity)."""
    from django_graphex.native.base import ObjectType

    class Base(ObjectType):
        class Meta:
            abstract = True

        @classmethod
        def __init_subclass_with_meta__(cls, **options):
            pass

    with pytest.raises(Exception, match="Meta"):

        class Sub(Base):
            Meta = "not a class or dict"


# ---------------------------------------------------------------------------
# Abstract bases skip dispatch
# ---------------------------------------------------------------------------


@pytest.mark.native_only
def test_abstract_base_skips_dispatch():
    """An abstract base does NOT invoke ``__init_subclass_with_meta__``."""
    from django_graphex.native.base import ObjectType

    calls: list = []

    class Base(ObjectType):
        @classmethod
        def __init_subclass_with_meta__(cls, **options):
            calls.append(cls.__name__)

    class AbstractMid(Base):
        class Meta:
            abstract = True

    # Only AbstractMid is created so far; abstract must NOT have dispatched.
    assert "AbstractMid" not in calls

    class Concrete(AbstractMid):
        class Meta:
            name = "Concrete"

    assert "Concrete" in calls


@pytest.mark.native_only
def test_no_meta_dispatches_with_empty_options():
    """A subclass with NO ``Meta`` still dispatches (empty options)."""
    from django_graphex.native.base import ObjectType

    captured: list = []

    class Base(ObjectType):
        @classmethod
        def __init_subclass_with_meta__(cls, **options):
            captured.append((cls.__name__, options))

    class Sub(Base):
        pass

    assert ("Sub", {}) in captured


@pytest.mark.native_only
def test_base_defining_driver_does_not_run_it_on_itself():
    """A non-abstract base that DEFINES a driver must NOT run it on ITSELF.

    This locks graphene's ``super(cls, cls).__init_subclass_with_meta__``
    dispatch semantics (graphene.utils.subclass_with_meta.SubclassWithMeta):
    the driver a class declares runs for its SUBCLASSES, never for the class
    that declares it. ``DjangoObjectType`` / ``DjangoListObjectType`` rely on
    this — they define a driver that asserts a Django ``model`` is present, and
    the BASE class itself carries no model. A naive ``cls.__init_subclass_with_meta__``
    dispatch would fire the base's own driver on the base and raise
    ``AssertionError: ... received "None"`` at import time (the S6b crasher).
    """
    from django_graphex.native.base import ObjectType

    ran_on: list[str] = []

    class DriverBase(ObjectType):
        @classmethod
        def __init_subclass_with_meta__(cls, model=None, **options):
            ran_on.append(cls.__name__)
            assert model is not None, (
                f"{cls.__name__}: driver requires a model"
            )

    # Defining DriverBase must NOT have run its own driver on itself (no model).
    assert "DriverBase" not in ran_on

    # A subclass DOES run DriverBase's driver (with its own model).
    class Concrete(DriverBase):
        class Meta:
            model = object()

    assert "Concrete" in ran_on


@pytest.mark.native_only
def test_intermediate_override_runs_only_on_subclasses():
    """A subclass overriding the driver runs the PARENT's driver, not its own.

    Mirrors the ``DjangoObjectType`` family: each public type OVERRIDES
    ``__init_subclass_with_meta__``; that override runs only when a FURTHER
    subclass is defined, dispatched via ``super(cls, cls)``.
    """
    from django_graphex.native.base import ObjectType

    calls: list[str] = []

    class Mid(ObjectType):
        class Meta:
            abstract = True

        @classmethod
        def __init_subclass_with_meta__(cls, **options):
            calls.append(f"Mid:{cls.__name__}")

    class Override(Mid):
        # Override defines its OWN driver. Per super(cls, cls) semantics this
        # runs Mid's driver on Override (dispatched from __init_subclass__),
        # and Override's own driver runs only for Override's subclasses.
        class Meta:
            abstract = True

        @classmethod
        def __init_subclass_with_meta__(cls, **options):
            calls.append(f"Override:{cls.__name__}")

    class Leaf(Override):
        class Meta:
            name = "Leaf"

    # Override is abstract -> no dispatch on Override itself.
    # Leaf -> super(Leaf, Leaf) -> Override.__init_subclass_with_meta__.
    assert "Override:Leaf" in calls
    assert "Mid:Override" not in calls  # Override is abstract, never dispatched


# ---------------------------------------------------------------------------
# Mutable _meta Options — full parity-table attr surface + graphene defaults
# ---------------------------------------------------------------------------

#: The union of every attribute the parity table (#1534) requires the native
#: Options object to expose so later re-parented types never hit a silent
#: AttributeError. Defaults mirror graphene's
#: DjangoObjectOptions / DjangoModelTypeOptions / DjangoListObjectOptions /
#: SerializerMutationOptions / SubscriptionOptions.
_PARITY_ATTRS = (
    "model",
    "registry",
    "name",
    "fields",
    "interfaces",
    "gfk_unions",
    "graphql_output_type",
    "graphql_input_type",
    "baseType",
    "results_field_name",
    "pagination",
    "arguments",
    "output",
    "output_type",
    "output_list_type",
    "mutation_output",
    "input_field_name",
    "output_field_name",
    "backend",
    "stream",
    "serialize_data",
    "subscription_index_fields",
    "index_fields",
    "nested_fields",
    "model_operations",
    "types",
    "container",
)


@pytest.mark.native_only
def test_meta_exposes_full_parity_attr_surface():
    """``_meta`` exposes every parity-table attribute (no AttributeError)."""
    from django_graphex.native.base import ObjectType

    class Sub(ObjectType):
        class Meta:
            name = "Sub"

    for attr in _PARITY_ATTRS:
        assert hasattr(Sub._meta, attr), f"_meta missing parity attribute {attr!r}"


@pytest.mark.native_only
def test_meta_defaults_match_graphene():
    """``_meta`` defaults mirror graphene's Options defaults exactly."""
    from django_graphex.native.base import ObjectType

    class Sub(ObjectType):
        class Meta:
            name = "Sub"

    m = Sub._meta
    # None-defaulted scalars
    assert m.model is None
    assert m.registry is None
    # No graphene descriptors declared -> the driver's else-branch sets
    # ``fields = descriptor_fields or None`` deterministically to None.
    assert m.fields is None
    assert m.gfk_unions is None
    assert m.graphql_output_type is None
    assert m.graphql_input_type is None
    assert m.results_field_name is None
    assert m.pagination is None
    assert m.arguments is None
    assert m.output is None
    assert m.output_type is None
    assert m.output_list_type is None
    assert m.mutation_output is None
    assert m.input_field_name is None
    assert m.output_field_name is None
    assert m.backend is None
    assert m.stream is None
    assert m.serialize_data is None
    assert m.nested_fields is None
    assert m.types is None
    assert m.container is None
    # tuple/iterable defaults
    assert m.interfaces == ()
    assert m.subscription_index_fields == ()
    assert m.index_fields == ()
    assert m.model_operations == ("create", "update", "delete")


@pytest.mark.native_only
def test_meta_is_mutable_plain_assignment():
    """``_meta`` allows plain attribute assignment (no freeze workaround)."""
    from django_graphex.native.base import ObjectType

    class Sub(ObjectType):
        class Meta:
            name = "Sub"

    sentinel = object()
    # Plain assignment must work — later slices replace the current
    # object.__setattr__(_meta, ...) freeze bypass (types.py:655,1341).
    Sub._meta.graphql_output_type = sentinel
    assert Sub._meta.graphql_output_type is sentinel
    Sub._meta.model = "SomeModel"
    assert Sub._meta.model == "SomeModel"


@pytest.mark.native_only
def test_meta_name_defaults_to_class_name():
    """``_meta.name`` defaults to the class name when ``Meta`` omits ``name``."""
    from django_graphex.native.base import ObjectType

    class NoNameSub(ObjectType):
        class Meta:
            pass

    assert NoNameSub._meta.name == "NoNameSub"


# ---------------------------------------------------------------------------
# graphene field descriptors collected into _meta.fields (the HARD PART)
# ---------------------------------------------------------------------------


@pytest.mark.native_only
def test_graphene_descriptors_collected_into_meta_fields():
    """``Boolean()`` / ``List(...)`` / ``Field(...)`` land in ``_meta.fields``.

    They must NOT be parsed as Pydantic model fields and must NOT crash class
    creation (the PydanticUserError 'non-annotated attribute' blocker).
    """
    from graphene import Boolean, Field, List, String

    from django_graphex.native.base import ObjectType

    class WithDescriptors(ObjectType):
        ok = Boolean(description="ok flag")
        errors = List(String, description="errors")
        node = Field(String)

        class Meta:
            name = "WithDescriptors"

    fields = WithDescriptors._meta.fields
    assert fields is not None
    assert "ok" in fields
    assert "errors" in fields
    assert "node" in fields


@pytest.mark.native_only
def test_graphene_descriptors_not_pydantic_fields():
    """Descriptors must NOT leak into Pydantic ``model_fields``."""
    from graphene import Boolean, List, String

    from django_graphex.native.base import ObjectType

    class WithDescriptors(ObjectType):
        ok = Boolean()
        errors = List(String)

        class Meta:
            name = "WithDescriptors"

    assert "ok" not in WithDescriptors.model_fields
    assert "errors" not in WithDescriptors.model_fields


@pytest.mark.native_only
def test_descriptors_survive_without_crash():
    """Declaring graphene descriptors does not raise PydanticUserError."""
    from graphene import Boolean

    from django_graphex.native.base import ObjectType

    # The bare act of class creation is the assertion: no exception.
    class NoCrash(ObjectType):
        flag = Boolean(description="x")

        class Meta:
            name = "NoCrash"

    assert NoCrash._meta.name == "NoCrash"


# ---------------------------------------------------------------------------
# Container-style constructor — cls(**kwargs) round-trips
# ---------------------------------------------------------------------------


@pytest.mark.native_only
def test_container_constructor_round_trips_descriptor_payload():
    """``cls(**kwargs)`` round-trips a payload keyed by descriptor field names.

    Mirrors graphene's mutation payload pattern ``cls(**resp)`` /
    ``cls(**errors_dict)`` (mutation.py:504,519; types.py:1750,1828).
    """
    from graphene import Boolean, List, String

    from django_graphex.native.base import ObjectType

    class Payload(ObjectType):
        ok = Boolean()
        errors = List(String)

        class Meta:
            name = "Payload"

    inst = Payload(ok=True, errors=["boom"])
    assert inst.ok is True
    assert inst.errors == ["boom"]


@pytest.mark.native_only
def test_container_constructor_round_trips_driver_injected_field():
    """``cls(**resp)`` round-trips a DYNAMIC output field injected by the driver.

    S6c anti-regression lock. The mutation / model-type payload pattern is
    ``cls(**{output_field_name: obj, "ok": True, "errors": None})`` where
    ``output_field_name`` (e.g. ``post`` / ``category``) is NOT a class-body
    descriptor — it is a ``graphene.Field`` the concrete driver injects into
    ``_meta.fields``. graphene's value-object ``__init__`` is a dataclass over
    EVERY ``_meta.fields`` key, so it round-trips. The native container
    ``__init__`` must do the same: it consults ``_meta.fields`` (not just
    class-body descriptors), otherwise the dynamic output key is SILENTLY DROPPED
    by Pydantic and the mutation response's output object resolves to NULL on the
    wire (the S6c silent-null bug). This locks the ``_meta.fields``-driven stash.
    """
    from collections import OrderedDict

    from graphene import Boolean, Field, List, String

    from django_graphex.native.base import NativeObjectTypeOptions, ObjectType

    class _Inner(ObjectType):
        class Meta:
            abstract = True

    class _PayloadBase(ObjectType):
        ok = Boolean()
        errors = List(String)

        class Meta:
            abstract = True

        @classmethod
        def __init_subclass_with_meta__(cls, _meta=None, **opts):
            _meta = _meta or NativeObjectTypeOptions(cls)
            # Driver injects the dynamic output field into _meta.fields (NOT a
            # class attribute) — exactly like DjangoModelType / DjangoModelMutation.
            _meta.fields = OrderedDict({"category": Field(_Inner)})
            super().__init_subclass_with_meta__(_meta=_meta, **opts)

    class _Payload(_PayloadBase):
        class Meta:
            name = "_Payload"

    # _meta.fields must carry BOTH the driver-injected output field and the merged
    # class-body descriptors (the terminal mounts ok/errors on top).
    assert set(_Payload._meta.fields) == {"category", "ok", "errors"}

    inst = _Payload(category="THE_OBJECT", ok=True, errors=["e"])
    # The dynamic output field survived (NOT silently dropped by Pydantic).
    assert inst.category == "THE_OBJECT"
    assert inst.ok is True
    assert inst.errors == ["e"]


@pytest.mark.native_only
def test_container_constructor_partial_payload():
    """``cls(**kwargs)`` accepts a partial payload (missing keys default safely)."""
    from graphene import Boolean, List, String

    from django_graphex.native.base import ObjectType

    class Payload(ObjectType):
        ok = Boolean()
        errors = List(String)

        class Meta:
            name = "Payload"

    inst = Payload(ok=False)
    assert inst.ok is False
    # The omitted descriptor was NOT stashed as an instance attribute (only
    # payload keys are stashed), so it is absent from the instance __dict__ ...
    assert "errors" not in inst.__dict__
    # ... and it never leaked into Pydantic's model_fields. Attribute access
    # falls back to the class-body graphene descriptor (kept by ignored_types).
    assert "errors" not in type(inst).model_fields
    from graphene.types.unmountedtype import UnmountedType

    assert isinstance(inst.errors, UnmountedType)


# ---------------------------------------------------------------------------
# Terminal __init_subclass_with_meta__ — the super() chain endpoint that the 8
# public Django* drivers call after building their own _meta (S6b-shaped).
# ---------------------------------------------------------------------------


@pytest.mark.native_only
def test_concrete_driver_super_call_assigns_meta():
    """An S6b-shaped concrete driver's ``super().__init_subclass_with_meta__``
    must assign ``cls._meta`` via the native terminal (graphene-free).

    This mirrors EXACTLY what the 8 public ``Django*`` types do: build a
    ``NativeObjectTypeOptions`` fully, populate a few attrs, then call
    ``super().__init_subclass_with_meta__(_meta=_meta, name=..., description=...)``
    and read ``cls._meta.name`` AFTER super() (types.py:801,857). Before FIX 1
    the super() resolves to graphene's ``BaseType`` terminal (which freezes) or
    — after re-parent — to nothing; the native terminal is the load-bearing
    endpoint of the chain.
    """
    from django_graphex.native.base import NativeObjectTypeOptions, ObjectType

    class DriverBase(ObjectType):
        class Meta:
            abstract = True

        @classmethod
        def __init_subclass_with_meta__(cls, _meta=None, **options):
            _meta = _meta or NativeObjectTypeOptions(cls)
            _meta.model = "FakeModel"
            _meta.results_field_name = "rows"
            super().__init_subclass_with_meta__(_meta=_meta, **options)

    class Concrete(DriverBase):
        """A concrete driver subclass."""

        class Meta:
            name = "ConcreteName"

    # The terminal MUST have assigned cls._meta and set name from Meta.name.
    assert Concrete._meta is not None
    assert Concrete._meta.name == "ConcreteName"
    # Driver-populated attrs survive the terminal (it only touches name/desc).
    assert Concrete._meta.model == "FakeModel"
    assert Concrete._meta.results_field_name == "rows"


@pytest.mark.native_only
def test_terminal_defaults_name_to_class_name():
    """When the driver passes no ``name``, the terminal defaults to ``cls.__name__``."""
    from django_graphex.native.base import NativeObjectTypeOptions, ObjectType

    class DriverBase(ObjectType):
        class Meta:
            abstract = True

        @classmethod
        def __init_subclass_with_meta__(cls, _meta=None, **options):
            _meta = _meta or NativeObjectTypeOptions(cls)
            super().__init_subclass_with_meta__(_meta=_meta, **options)

    class NoNameConcrete(DriverBase):
        class Meta:
            pass

    assert NoNameConcrete._meta.name == "NoNameConcrete"


@pytest.mark.native_only
def test_terminal_trims_docstring_into_description():
    """The terminal sets ``_meta.description`` to the trimmed class docstring."""
    from django_graphex.native.base import NativeObjectTypeOptions, ObjectType

    class DriverBase(ObjectType):
        class Meta:
            abstract = True

        @classmethod
        def __init_subclass_with_meta__(cls, _meta=None, **options):
            _meta = _meta or NativeObjectTypeOptions(cls)
            super().__init_subclass_with_meta__(_meta=_meta, **options)

    class Documented(DriverBase):
        """First line.

        Second paragraph that is indented in source.
        """

        class Meta:
            name = "Documented"

    # Trimmed (PEP 257 / inspect.cleandoc) — leading indentation removed, the
    # paragraph break preserved.
    assert Documented._meta.description == (
        "First line.\n\nSecond paragraph that is indented in source."
    )


@pytest.mark.native_only
def test_terminal_explicit_description_wins_over_docstring():
    """An explicit ``description=`` passed to the terminal wins over the docstring."""
    from django_graphex.native.base import NativeObjectTypeOptions, ObjectType

    class DriverBase(ObjectType):
        class Meta:
            abstract = True

        @classmethod
        def __init_subclass_with_meta__(cls, _meta=None, **options):
            _meta = _meta or NativeObjectTypeOptions(cls)
            super().__init_subclass_with_meta__(
                _meta=_meta, description="explicit", **options
            )

    class HasDocstring(DriverBase):
        """This docstring must be ignored."""

        class Meta:
            name = "HasDocstring"

    assert HasDocstring._meta.description == "explicit"


@pytest.mark.native_only
def test_terminal_keeps_meta_mutable_post_assignment():
    """The terminal must NOT freeze ``_meta`` — plain assignment works after it.

    The whole point of S6a is a mutable Options. graphene's ``BaseType`` calls
    ``_meta.freeze()`` before assigning; the native terminal must NOT, so later
    slices can plain-assign instead of the ``object.__setattr__`` workaround.
    """
    from django_graphex.native.base import NativeObjectTypeOptions, ObjectType

    class DriverBase(ObjectType):
        class Meta:
            abstract = True

        @classmethod
        def __init_subclass_with_meta__(cls, _meta=None, **options):
            _meta = _meta or NativeObjectTypeOptions(cls)
            super().__init_subclass_with_meta__(_meta=_meta, **options)

    class Concrete(DriverBase):
        class Meta:
            name = "Concrete"

    sentinel = object()
    # Plain assignment AFTER the terminal ran — must not raise (no freeze).
    Concrete._meta.graphql_output_type = sentinel
    assert Concrete._meta.graphql_output_type is sentinel


@pytest.mark.native_only
def test_terminal_builds_meta_when_none():
    """A driver that calls the terminal with ``_meta=None`` gets a fresh ``_meta``.

    The native terminal now collapses graphene's two-step
    ``ObjectType.__init_subclass_with_meta__`` (which builds an Options object when
    ``_meta`` is falsy) + ``BaseType.__init_subclass_with_meta__`` (name/desc/
    assign) into one endpoint. So a ``_meta=None`` call no longer no-ops — it
    builds a fresh mutable ``NativeObjectTypeOptions``, mirroring graphene's
    ``ObjectType`` parity (a plain ``ObjectType`` with no driver gets a real
    ``_meta``).
    """
    from django_graphex.native.base import NativeObjectTypeOptions, ObjectType

    class DriverBase(ObjectType):
        class Meta:
            abstract = True

        @classmethod
        def __init_subclass_with_meta__(cls, _meta=None, **options):
            # Intentionally forwards _meta=None to the terminal.
            super().__init_subclass_with_meta__(_meta=None, **options)

    class Concrete(DriverBase):
        class Meta:
            name = "Concrete"

    # The terminal built a fresh mutable _meta (graphene ObjectType parity).
    assert isinstance(Concrete._meta, NativeObjectTypeOptions)
    assert Concrete._meta.name == "Concrete"


# ---------------------------------------------------------------------------
# Regression guard — InputType's existing Pydantic behavior is UNCHANGED
# ---------------------------------------------------------------------------


@pytest.mark.native_only
def test_input_type_still_pydantic_model_metaclass():
    """InputType subclass still has ``type() is ModelMetaclass``."""
    from django_graphex.native.base import InputType

    # Unique class name: InputType subclasses persist in the shared
    # _gdx_input_registry, and compile_all_inputs() rejects duplicate GraphQL
    # names. Each regression-guard subclass below uses a distinct name.
    class DriverGuardSearchInput(InputType):
        query: str
        limit: int = 10

    assert type(DriverGuardSearchInput) is ModelMetaclass


@pytest.mark.native_only
def test_input_type_real_fields_still_work():
    """InputType real annotated fields still validate and round-trip."""
    from django_graphex.native.base import InputType

    class DriverGuardFieldsInput(InputType):
        query: str
        limit: int = 10

    obj = DriverGuardFieldsInput(query="hi")
    assert obj.query == "hi"
    assert obj.limit == 10
    assert obj["query"] == "hi"  # __getitem__ mixin unchanged


@pytest.mark.native_only
def test_input_type_camel_alias_still_works():
    """InputType camelCase alias construction is unchanged."""
    from django_graphex.native.base import InputType

    class DriverGuardCamelInput(InputType):
        first_name: str

    obj = DriverGuardCamelInput.model_validate({"firstName": "Carol"})
    assert obj.first_name == "Carol"


@pytest.mark.native_only
def test_input_type_still_registers_and_has_input_meta():
    """InputType still auto-registers and keeps its graphql_input_type _meta."""
    from django_graphex.native.base import InputType, _gdx_input_registry

    initial = len(_gdx_input_registry)

    class DriverGuardRegInput(InputType):
        value: str

    assert len(_gdx_input_registry) == initial + 1
    assert DriverGuardRegInput in _gdx_input_registry
    # InputType keeps its own _meta carrying graphql_input_type (compiled later).
    assert hasattr(DriverGuardRegInput, "_meta")
    assert hasattr(DriverGuardRegInput._meta, "graphql_input_type")
