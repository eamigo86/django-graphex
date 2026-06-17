"""S-input-5 — native INPUT relations + choices INPUT enum off graphene.

This is the slice that finally makes a ``DjangoInputObjectType`` class-def
graphene-free, and (with Part 3) lets the ``_yank_fields`` graphene-marker branch
retire entirely.

STEP 0 ground truth (proven by trace probe before writing this slice)
---------------------------------------------------------------------
The native INPUT SDL (``_meta.graphql_input_type``) is built ENTIRELY by
``native.input_compiler.compile_input_type`` from:

* the generated Pydantic model (``build_model_schema``) -> base scalar fields;
* ``RelationInputField`` specs (``types._resolve_native_relation_input_fields``,
  which reads ``model._meta.get_fields()`` DIRECTLY) -> FK/O2O ``ID`` (``ID!`` on
  required create), M2M/reverse ``[ID!]``;
* ``NestedInputField`` specs (``Meta.nested_fields``) -> nested object inputs.

It NEVER reads the converter's graphene ``Dynamic`` / ``ID`` / ``Enum``
descriptors. Those descriptors flow into ``_meta.fields`` / ``_meta.input_fields``
ONLY as PRESENCE markers (e.g. the issue #52 ``"spouse" in PersonCreateInput
._meta.fields`` canary). So migrating the INPUT path off graphene is
DEAD-``_g``-REMOVAL: replace the relation ``_g().Dynamic`` / ``_g().ID`` /
``DjangoListField(_g().ID)`` / ``_g().Enum`` with a graphene-free marker
(``NativeRelationField`` for relations, ``_DEAD_SCALAR`` for the choices enum)
that ``_yank_fields`` keeps via its native-currency branch — never ``None`` (the
silent-drop trap).

What changes in the SDL
-----------------------
* Relations: SDL-NEUTRAL. FK ``id: ID`` (``ID!`` required-create), M2M ``[ID!]``,
  reverse ``[ID!]`` — exactly as ``compile_input_type`` already renders them.
* Choices INPUT: ``String`` -> the native canonical ``GraphQLEnumType`` (the SAME
  shared enum the OUTPUT + FILTER-INPUT paths use, S-enum-1). After this the
  choices field is graphene-free AND enum-typed on BOTH output and input.

Test groups
-----------
* (a) IMPORT-REMOVAL — the BIG one: build a ``DjangoInputObjectType`` (create +
  update) for a model with FK + O2O + M2M + reverse + choices with
  ``converter._g`` monkeypatched-to-RAISE -> no raise. PLUS the full class-def:
  OUTPUT + INPUT build with ``_g`` raising -> no raise (the class-def is now
  fully graphene-free).
* (b) INPUT SDL parity — FK ``id: ID`` (create-required ``ID!``), M2M ``[ID!]``,
  reverse ``[ID!]``; choices input uses the shared enum.
* (c) Part 3 proof — ``_graphene_descriptor_markers`` is never called during a
  comprehensive native build (OUTPUT + INPUT create/update/delete + choices).
* (d) BROAD silent-drop — self-ref O2O present in create input; relation presence
  preserved in ``_meta.fields``.
"""
from __future__ import annotations

import pytest
from graphql import (
    GraphQLEnumType,
    GraphQLID,
    GraphQLList,
    GraphQLNonNull,
)

from django_graphex.native.descriptors import (
    NativeField,
    NativeMountedField,
)
from django_graphex.registry import Registry
from django_graphex.types import DjangoInputObjectType, DjangoObjectType
from tests.models import (
    Author,
    AuthorProfile,
    EnumCollisionItemA,
    PersonWithSpouse,
    Post,
)

pytestmark = pytest.mark.native_only


# NOTE: ``DjangoObjectType`` / ``DjangoInputObjectType`` use a pydantic metaclass
# that requires a class-statement ``Meta``. So each test defines its types with
# explicit ``class`` statements (mirroring the other native relation slices).


def _unwrap(t):
    while isinstance(t, GraphQLNonNull):
        t = t.of_type
    return t


# --------------------------------------------------------------------------- #
# (a) IMPORT-REMOVAL — the BIG one.                                            #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_input_build_does_not_import_graphene():
    """Building a create + update ``DjangoInputObjectType`` for a model with
    FK + O2O + M2M + reverse + choices is graphene-free.

    S-del-backend-11: the converter has no ``_g()`` graphene accessor (the graphene
    backend was deleted), so the INPUT class-def path is structurally graphene-free.
    This asserts the input types build + their thunks evaluate without error.
    """
    reg = Registry()

    class _PostCreate(DjangoInputObjectType):
        class Meta:
            model = Post  # FK author/category + M2M tags/co_authors + reverse comments
            registry = reg
            input_for = "create"

    class _PostUpdate(DjangoInputObjectType):
        class Meta:
            model = Post
            registry = reg
            input_for = "update"

    class _PersonCreate(DjangoInputObjectType):
        class Meta:
            model = PersonWithSpouse  # self-ref O2O + reverse-O2O
            registry = reg
            input_for = "create"

    class _ProfileCreate(DjangoInputObjectType):
        class Meta:
            model = AuthorProfile  # forward O2O
            registry = reg
            input_for = "create"

    class _ItemCreate(DjangoInputObjectType):
        class Meta:
            model = EnumCollisionItemA  # choices
            registry = reg
            input_for = "create"

    # Force the lazy ``fields`` thunks to evaluate (graphql-core lazy thunk).
    for t in (_PostCreate, _PostUpdate, _PersonCreate, _ProfileCreate, _ItemCreate):
        gql = t._meta.graphql_input_type
        if gql is not None:
            _ = gql.fields  # evaluate the thunk


@pytest.mark.django_db
def test_full_class_def_output_and_input_graphene_free():
    """The FULL class-def is graphene-free: defining a model's OUTPUT type AND its
    create/update INPUT types builds without importing graphene.

    S-del-backend-11: the converter/types class-def seam has no ``_g()`` graphene
    accessor (the graphene backend was deleted), so the build is structurally
    graphene-free. This asserts the OUTPUT + INPUT types build + thunks evaluate.
    """
    reg = Registry()

    # Register the FULL closure so every relation resolves on the output side.
    class _AuthorOut(DjangoObjectType):
        class Meta:
            model = Author
            registry = reg

    class _PostOut(DjangoObjectType):
        class Meta:
            model = Post
            registry = reg

    class _PersonOut(DjangoObjectType):
        class Meta:
            model = PersonWithSpouse
            registry = reg

    class _ItemOut(DjangoObjectType):
        class Meta:
            model = EnumCollisionItemA
            registry = reg

    class _PostCreate(DjangoInputObjectType):
        class Meta:
            model = Post
            registry = reg
            input_for = "create"

    class _PostUpdate(DjangoInputObjectType):
        class Meta:
            model = Post
            registry = reg
            input_for = "update"

    class _PersonCreate(DjangoInputObjectType):
        class Meta:
            model = PersonWithSpouse
            registry = reg
            input_for = "create"

    class _ItemCreate(DjangoInputObjectType):
        class Meta:
            model = EnumCollisionItemA
            registry = reg
            input_for = "create"

    # Evaluate the input thunks too.
    for t in (_PostCreate, _PostUpdate, _PersonCreate, _ItemCreate):
        gql = t._meta.graphql_input_type
        if gql is not None:
            _ = gql.fields


# --------------------------------------------------------------------------- #
# (b) INPUT SDL parity — relations + choices enum.                             #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_input_relation_sdl_parity():
    """FK ``id: ID`` (create-required ``ID!``); M2M / reverse ``[ID!]``."""
    reg = Registry()

    class _PostCreate(DjangoInputObjectType):
        class Meta:
            model = Post
            registry = reg
            input_for = "create"

    class _PostUpdate(DjangoInputObjectType):
        class Meta:
            model = Post
            registry = reg
            input_for = "update"

    create_fields = _PostCreate._meta.graphql_input_type.fields
    update_fields = _PostUpdate._meta.graphql_input_type.fields

    # FK author -> ID; required (NonNull) on create, nullable on update.
    assert _unwrap(create_fields["author"].type) is GraphQLID
    assert isinstance(create_fields["author"].type, GraphQLNonNull), (
        "required FK on create must be ID!, got "
        f"{create_fields['author'].type!r}"
    )
    assert update_fields["author"].type is GraphQLID, (
        "FK on update must be a nullable ID, got "
        f"{update_fields['author'].type!r}"
    )
    # nullable FK category -> ID (nullable) on create too.
    assert create_fields["category"].type is GraphQLID

    # M2M tags -> [ID!]; reverse-FK comments -> [ID!].
    for name in ("tags", "comments", "coAuthors"):
        ftype = _unwrap(create_fields[name].type)
        assert isinstance(ftype, GraphQLList), f"{name} must be a list"
        assert isinstance(ftype.of_type, GraphQLNonNull), f"{name} element must be ID!"
        assert ftype.of_type.of_type is GraphQLID


@pytest.mark.django_db
def test_choices_input_uses_shared_enum():
    """The choices INPUT field renders as the native ``GraphQLEnumType`` (the
    SAME shared enum the OUTPUT path uses), NOT ``GraphQLString``."""
    from django_graphex.converter import build_choices_enum_type

    reg = Registry()

    class _ItemCreate(DjangoInputObjectType):
        class Meta:
            model = EnumCollisionItemA
            registry = reg
            input_for = "create"

    fields = _ItemCreate._meta.graphql_input_type.fields
    status_type = _unwrap(fields["status"].type)
    assert isinstance(status_type, GraphQLEnumType), (
        f"choices input field must be a GraphQLEnumType, got {status_type!r}"
    )

    # Must be the SAME shared canonical enum instance the output path uses.
    shared = build_choices_enum_type(
        EnumCollisionItemA._meta.get_field("status"), reg
    )
    assert status_type is shared, (
        "the choices input enum must be the SAME shared (model, field) enum "
        "instance the output path resolves"
    )
    # Canonical name (graphene to_camel_case, lowercase first char).
    assert status_type.name == "testsEnumcollisionitemaStatusEnum"


# --------------------------------------------------------------------------- #
# (c) PART 3 — ZERO graphene descriptors reach _yank_fields on a comprehensive  #
#     native build (OUTPUT + INPUT create/update/delete + choices); the         #
#     graphene-marker branch + _graphene_descriptor_markers are RETIRED.        #
# --------------------------------------------------------------------------- #
def test_graphene_marker_branch_retired():
    """Part 3 retirement: ``types._graphene_descriptor_markers`` is GONE.

    After S-input-5 no graphene MountedType/UnmountedType descriptor reaches
    ``_yank_fields`` on ANY native build (OUTPUT or INPUT) — proven by
    ``test_comprehensive_build_reaches_yank_fields_graphene_free`` below — so the
    lazy graphene-marker branch and its helper retire entirely (the long-deferred
    Part B from #1609 / S-enum-2)."""
    import django_graphex.types as types_mod

    assert not hasattr(types_mod, "_graphene_descriptor_markers"), (
        "the graphene-marker branch helper must be RETIRED in S-input-5 (no "
        "graphene descriptor reaches _yank_fields on any native build)"
    )


@pytest.mark.django_db
def test_comprehensive_build_reaches_yank_fields_graphene_free():
    """A comprehensive native build — OUTPUT types + create/update/delete inputs
    + choices — reaches ``_yank_fields`` with ZERO graphene descriptors (the
    Part 3 STEP 0-B proof that authorizes retiring the marker branch)."""
    import django_graphex.types as types_mod
    from django_graphex.converter import _DEAD_SCALAR

    graphene_reached: list[tuple[str, str]] = []
    orig_yank = types_mod._yank_fields

    def _spy_yank(attrs, _as, sort=True):
        for name, value in attrs.items():
            if isinstance(value, (NativeMountedField, NativeField)):
                continue
            if value is _DEAD_SCALAR:
                continue
            mod = type(value).__module__
            if mod.startswith("graphene"):
                graphene_reached.append((name, mod + "." + type(value).__name__))
        return orig_yank(attrs, _as, sort=sort)

    types_mod._yank_fields = _spy_yank
    try:
        reg = Registry()

        class _AuthorOut(DjangoObjectType):
            class Meta:
                model = Author
                registry = reg

        class _PostOut(DjangoObjectType):
            class Meta:
                model = Post
                registry = reg

        class _PersonOut(DjangoObjectType):
            class Meta:
                model = PersonWithSpouse
                registry = reg

        class _ItemOut(DjangoObjectType):
            class Meta:
                model = EnumCollisionItemA
                registry = reg

        # Create inputs.
        class _PostCreate(DjangoInputObjectType):
            class Meta:
                model = Post
                registry = reg
                input_for = "create"

        class _PersonCreate(DjangoInputObjectType):
            class Meta:
                model = PersonWithSpouse
                registry = reg
                input_for = "create"

        class _ItemCreate(DjangoInputObjectType):
            class Meta:
                model = EnumCollisionItemA
                registry = reg
                input_for = "create"

        # Update inputs.
        class _PostUpdate(DjangoInputObjectType):
            class Meta:
                model = Post
                registry = reg
                input_for = "update"

        class _PersonUpdate(DjangoInputObjectType):
            class Meta:
                model = PersonWithSpouse
                registry = reg
                input_for = "update"

        class _ItemUpdate(DjangoInputObjectType):
            class Meta:
                model = EnumCollisionItemA
                registry = reg
                input_for = "update"

        # Delete inputs (no input object type; exercises the delete branch).
        class _PostDelete(DjangoInputObjectType):
            class Meta:
                model = Post
                registry = reg
                input_for = "delete"

        for t in (
            _PostCreate,
            _PersonCreate,
            _ItemCreate,
            _PostUpdate,
            _PersonUpdate,
            _ItemUpdate,
            _PostDelete,
        ):
            gql = t._meta.graphql_input_type
            if gql is not None:
                _ = gql.fields
    finally:
        types_mod._yank_fields = orig_yank

    assert not graphene_reached, (
        "graphene descriptors still reach _yank_fields on a comprehensive native "
        f"OUTPUT + INPUT build: {graphene_reached}"
    )


# --------------------------------------------------------------------------- #
# (e) issue #65 — Meta only/include/exclude gates the choices INPUT field.      #
#     REGRESSION: S-input-5 moved the choices field out of the base            #
#     ``model_fields`` loop (which honored only/exclude/include) into a         #
#     dedicated injection loop that injected UNCONDITIONALLY, so an excluded /   #
#     filtered-out choices field LEAKED onto the mutation INPUT. The choices     #
#     injection loop must mirror the base loop's gating on ``cf.out_name``.      #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_choices_input_field_dropped_when_excluded():
    """A choices field named in ``Meta.exclude_fields`` must NOT land on the
    compiled INPUT type (issue #65; the leak S-input-5 introduced)."""
    reg = Registry()

    class _ItemCreate(DjangoInputObjectType):
        class Meta:
            model = EnumCollisionItemA  # has a ``status`` choices field
            registry = reg
            input_for = "create"
            exclude_fields = ("status",)

    fields = _ItemCreate._meta.graphql_input_type.fields
    assert "status" not in fields, (
        "choices field 'status' was excluded via Meta.exclude_fields but LEAKED "
        f"onto the compiled INPUT type; got fields {list(fields)}"
    )


@pytest.mark.django_db
def test_choices_input_field_dropped_when_not_in_only():
    """A choices field absent from ``Meta.only_fields`` must NOT land on the
    compiled INPUT type (issue #65; the leak S-input-5 introduced)."""
    reg = Registry()

    class _ItemCreate(DjangoInputObjectType):
        class Meta:
            model = EnumCollisionItemA
            registry = reg
            input_for = "create"
            only_fields = ("id",)

    fields = _ItemCreate._meta.graphql_input_type.fields
    assert "status" not in fields, (
        "choices field 'status' is not in Meta.only_fields but LEAKED onto the "
        f"compiled INPUT type; got fields {list(fields)}"
    )


@pytest.mark.django_db
def test_choices_input_field_force_included_overrides_only():
    """``Meta.include_fields`` force-includes a choices field even when
    ``only_fields`` would otherwise drop it — EXACT base-loop semantics."""
    reg = Registry()

    class _ItemCreate(DjangoInputObjectType):
        class Meta:
            model = EnumCollisionItemA
            registry = reg
            input_for = "create"
            only_fields = ("id",)
            include_fields = ("status",)

    fields = _ItemCreate._meta.graphql_input_type.fields
    assert "status" in fields, (
        "choices field 'status' was force-included via Meta.include_fields but "
        f"is missing from the compiled INPUT type; got fields {list(fields)}"
    )
    status_type = _unwrap(fields["status"].type)
    assert isinstance(status_type, GraphQLEnumType), (
        f"force-included choices field must still be a GraphQLEnumType, got "
        f"{status_type!r}"
    )


@pytest.mark.django_db
def test_choices_input_field_present_without_field_selection():
    """Control: with no only/exclude/include the choices field stays present
    (guards the gating from over-dropping)."""
    reg = Registry()

    class _ItemCreate(DjangoInputObjectType):
        class Meta:
            model = EnumCollisionItemA
            registry = reg
            input_for = "create"

    fields = _ItemCreate._meta.graphql_input_type.fields
    assert "status" in fields, (
        "choices field 'status' must stay present when no field selection is "
        f"applied; got fields {list(fields)}"
    )


# --------------------------------------------------------------------------- #
# (d) BROAD silent-drop — relation presence preserved in _meta.fields.         #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_self_ref_o2o_present_in_create_input():
    """The self-ref O2O ``spouse`` stays present in the create-input
    ``_meta.fields`` (the issue #52 silent-drop canary, INPUT side)."""
    reg = Registry()

    class _PersonCreate(DjangoInputObjectType):
        class Meta:
            model = PersonWithSpouse
            registry = reg
            input_for = "create"

    field_names = list(_PersonCreate._meta.fields.keys())
    assert "spouse" in field_names, (
        f"self-ref O2O 'spouse' must be present in the create-input _meta.fields; "
        f"got {field_names}"
    )
    # And it must be a graphene-free native marker (not a graphene Dynamic).
    spouse = _PersonCreate._meta.fields["spouse"]
    assert isinstance(spouse, NativeMountedField), (
        f"'spouse' input marker must be a NativeMountedField, got {type(spouse)!r}"
    )
    assert not type(spouse).__module__.startswith("graphene")


@pytest.mark.django_db
def test_post_input_relation_presence_preserved():
    """FK + M2M + reverse relations stay present in the create-input
    ``_meta.fields`` (broad silent-drop guard) and are native markers."""
    reg = Registry()

    class _PostCreate(DjangoInputObjectType):
        class Meta:
            model = Post
            registry = reg
            input_for = "create"

    fields = _PostCreate._meta.fields
    for name in ("author", "category", "tags", "co_authors", "comments"):
        assert name in fields, (
            f"relation {name!r} must stay present in create-input _meta.fields; "
            f"got {list(fields)}"
        )
        assert isinstance(fields[name], NativeMountedField)
        assert not type(fields[name]).__module__.startswith("graphene")
