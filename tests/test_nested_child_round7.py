"""Round-7 settlement of the nested-write host model.

Round 6 left four seams open and the library author settled the design behind
them:

* "Meta.model_operations" is now a "DjangoModelType" option too, so the READ
  half of an ordinary read/write split can say so. A type that declares nothing
  keeps every operation, which is what makes the change a pure opt-out,
* the projection merge is settled on both axes: "exclude_fields" is a
  PROHIBITION unioned across every declared host and applied last, "only_fields"
  is an ALLOWANCE unioned across the hosts that SERVE the operation, and the
  no-allowance branch is reachable only through an explicit declaration,
* the host lookup is the parent's registry UNIONED with the global one, because
  a host that never named a registry legitimately lives in the global one and is
  still that model's host -- a permission gate must never go quiet,
* the primary key always survives on a nested UPDATE surface: it is not a
  projectable column there, it is how the row is identified,
* an emptied projection is refused at build time instead of shipping a schema
  graphql-core considers invalid.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from django.core.exceptions import ImproperlyConfigured
from graphql import get_named_type

from django_graphex.core import ObjectType
from django_graphex.core.registry_compiler import compile_all_outputs
from django_graphex.mutation import DjangoModelMutation, nested_child_input
from django_graphex.nested import hosts_serving
from django_graphex.permissions import BasePermission
from django_graphex.registry import Registry, get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from tests.models import (
    NestedR7BareKid,
    NestedR7BareOwner,
    NestedR7CrossKid,
    NestedR7CrossOwner,
    NestedR7DefaultKid,
    NestedR7DefaultOwner,
    NestedR7EmptyKid,
    NestedR7EmptyOwner,
    NestedR7KeyKid,
    NestedR7KeyOwner,
    NestedR7LastKid,
    NestedR7LastOwner,
    NestedR7MatKid,
    NestedR7MatOwner,
    NestedR7NoServeKid,
    NestedR7NoServeOwner,
    NestedR7OnlyKid,
    NestedR7OnlyOwner,
    NestedR7PkKid,
    NestedR7PkOwner,
    NestedR7ReadKid,
    NestedR7ReadOwner,
    NestedR7SigKid,
    NestedR7SigOwner,
    NestedR7SlotKid,
    NestedR7ThunkKid,
    NestedR7ThunkOwner,
)

#: The label the local registry's host declares. A parent bound to the same
#: registry must stamp it onto its nested field.
_THUNK_LABEL = "tests.publish_nestedr7thunkkid"


class _DenyEverything(BasePermission):
    """Refuse every action, so a missed host is visible as a granted write."""

    def has_permission(self, info: Any, action: str, model: Any, **kwargs: Any) -> bool:
        """Deny the action unconditionally.

        Args:
            info: GraphQL resolve info for the current request.
            action: The CRUD action being checked.
            model: The Django model class the action targets.
            **kwargs: Action-specific extras.

        Returns:
            False, always.
        """
        return False


# --------------------------------------------------------------------------- #
# Declaring nothing must behave EXACTLY as it did before the option existed.  #
# --------------------------------------------------------------------------- #
class NestedR7DefaultKidCard(DjangoModelType):
    """A host declaring no "model_operations": it serves every operation.

    The shape every existing project already has, so the new option is a pure opt-out
    only if this host keeps contributing its projection and its scope to the nested
    write path.
    """

    class Meta:
        """Bind the type to "NestedR7DefaultKid", hiding "secret", scoped.

        A projection and a queryset together, so both halves of "serves every operation"
        can be observed on one host.
        """

        model = NestedR7DefaultKid
        exclude_fields = ("secret",)
        queryset = NestedR7DefaultKid.objects.filter(tenant="a")


class NestedR7DefaultOwnerType(DjangoModelType):
    """The parent nesting the declare-nothing child.

    Its nested create input and its nested update path are the two places the old
    default has to remain visible.
    """

    class Meta:
        """Bind the type to "NestedR7DefaultOwner" with "kids" nested.

        The parent declares nothing itself, so anything the tests find on the child
        surface arrived from the child's default-serving host.
        """

        model = NestedR7DefaultOwner
        nested_fields = {"kids": NestedR7DefaultKid}


# --------------------------------------------------------------------------- #
# A declared READ host stops gating the nested WRITE path.                    #
# --------------------------------------------------------------------------- #
class NestedR7ReadKidCard(DjangoModelType):
    """The read surface, declared as one: it serves the query operations only.

    Its allowance names "secret" and its queryset hides other tenants -- both harmless
    on a card, both damaging the moment they leak into a write.
    """

    class Meta:
        """Bind the type to "NestedR7ReadKid" as a read host.

        "model_operations" naming only the query verbs is the declaration under test;
        everything else here exists to make its effect observable.
        """

        model = NestedR7ReadKid
        model_operations = ("list", "retrieve")
        only_fields = ("id", "secret")
        queryset = NestedR7ReadKid.objects.filter(tenant="a")


class NestedR7ReadKidMutation(DjangoModelMutation):
    """The write surface of the same child.

    The only host that serves the write verbs, so the nested create allowance must be
    exactly what this class declares and nothing more.
    """

    class Meta:
        """Bind the mutation to "NestedR7ReadKid", writing "headline".

        Allows one column the read card never mentions, which is what keeps the two
        allowances distinguishable in the merged surface.
        """

        model = NestedR7ReadKid
        only_fields = ("headline",)


class NestedR7ReadOwnerType(DjangoModelType):
    """The parent nesting the read/write-split child.

    Mounted on the module's schema roots, so this fixture is also what forces a real
    build of the nested input rather than a direct call.
    """

    class Meta:
        """Bind the type to "NestedR7ReadOwner" with "kids" nested.

        The nested entry both halves of the split are observed through: the built create
        input, and a nested update that must ignore the card's queryset.
        """

        model = NestedR7ReadOwner
        nested_fields = {"kids": NestedR7ReadKid}


# --------------------------------------------------------------------------- #
# The two no-allowance branches of the projection merge.                      #
# --------------------------------------------------------------------------- #
class NestedR7BareOwnerType(DjangoModelType):
    """A parent whose child has no declared host at all.

    The no-regression floor: with nothing declared anywhere, the nested payload has to
    keep every writable column, exactly as the library always behaved.
    """

    class Meta:
        """Bind the type to "NestedR7BareOwner" with "kids" nested.

        "NestedR7BareKid" has no host of its own, so this parent is the only declaration
        in the entire fixture.
        """

        model = NestedR7BareOwner
        nested_fields = {"kids": NestedR7BareKid}


class NestedR7NoServeKidMutation(DjangoModelMutation):
    """The child's only host, explicitly declared for "delete" alone.

    It declares both projection axes, so the merge has to keep one and drop the other:
    an allowance is operation-scoped, a prohibition is not.
    """

    class Meta:
        """Bind the mutation to "NestedR7NoServeKid" for "delete" only.

        An explicit "model_operations" is the only way to reach the no-allowance branch,
        which is what keeps that branch from failing open by default.
        """

        model = NestedR7NoServeKid
        model_operations = ("delete",)
        only_fields = ("headline",)
        exclude_fields = ("secret",)


class NestedR7NoServeOwnerType(DjangoModelType):
    """The parent nesting the delete-only-hosted child.

    A nested create through this parent has no serving host at all, which is precisely
    the state the no-allowance branch describes.
    """

    class Meta:
        """Bind the type to "NestedR7NoServeOwner" with "kids" nested.

        The nested CREATE surface is what the test builds, while the child's only host
        serves a different verb entirely.
        """

        model = NestedR7NoServeOwner
        nested_fields = {"kids": NestedR7NoServeKid}


# --------------------------------------------------------------------------- #
# The prohibition axis is applied LAST.                                       #
# --------------------------------------------------------------------------- #
class NestedR7LastKidAllow(DjangoModelType):
    """A host allowing the very column the other host forbids.

    Crossing the two axes on a single column is what makes the merge ORDER observable:
    whichever axis is applied last decides the outcome.
    """

    class Meta:
        """Bind the type to "NestedR7LastKid", allowing "secret".

        Naming "secret" in an allowance is the half that must NOT win, because a
        prohibition elsewhere forbids the column everywhere.
        """

        model = NestedR7LastKid
        only_fields = ("id", "headline", "secret")


class NestedR7LastKidDeny(DjangoModelMutation):
    """A host forbidding that column for every operation.

    Declares no "model_operations", so it serves both write verbs and its prohibition
    cannot be dismissed as out of scope.
    """

    class Meta:
        """Bind the mutation to "NestedR7LastKid", hiding "secret".

        The prohibition that has to survive the union: restoring "secret" from the
        sibling's allowance would be a fail-open.
        """

        model = NestedR7LastKid
        exclude_fields = ("secret",)


class NestedR7LastOwnerType(DjangoModelType):
    """The parent nesting the allow/deny-crossed child.

    The nesting scope the crossed projection is merged for, and the surface a client
    would actually reach the forbidden column through.
    """

    class Meta:
        """Bind the type to "NestedR7LastOwner" with "kids" nested.

        Unprojected itself, so the merged child input is the only thing the assertions
        can be reading.
        """

        model = NestedR7LastOwner
        nested_fields = {"kids": NestedR7LastKid}


# --------------------------------------------------------------------------- #
# A local-registry parent must still find the child's global permission host. #
# --------------------------------------------------------------------------- #
_CROSS_REGISTRY = Registry()


class NestedR7CrossKidType(DjangoModelType):
    """The child's only host: it can only live in the global registry.

    "Meta.registry" is not an option on "DjangoModelType", and this is the only host
    class carrying "permission_classes" -- so a registry-scoped lookup loses the gate
    entirely.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (_DenyEverything,)

    class Meta:
        """Bind the type to "NestedR7CrossKid", hiding "secret".

        The exclusion gives the build side something observable, alongside the deny-
        everything policy the runtime side is measured on.
        """

        model = NestedR7CrossKid
        exclude_fields = ("secret",)


class NestedR7CrossOwnerMutation(DjangoModelMutation):
    """A parent bound to a local registry, nesting the globally-hosted child.

    The multi-schema shape where parent and host live in different registries -- the
    case a registry-scoped lookup turns into an ungated write.
    """

    class Meta:
        """Bind the mutation to "NestedR7CrossOwner" on a local registry.

        "registry" is what separates the parent from the child's host; without it the
        lookup would find that host trivially.
        """

        model = NestedR7CrossOwner
        registry = _CROSS_REGISTRY
        nested_fields = {"kids": NestedR7CrossKid}


# --------------------------------------------------------------------------- #
# The primary key survives a projection on the nested UPDATE surface.         #
# --------------------------------------------------------------------------- #
class NestedR7PkKidMutation(DjangoModelMutation):
    """A write host whose projection does not list the primary key.

    An ordinary projection, since a pk is not a column a client writes -- but on an
    UPDATE surface it is how the row is named, so stripping it makes the documented
    upsert unreachable.
    """

    class Meta:
        """Bind the mutation to "NestedR7PkKid", writing "headline".

        The allowance deliberately omits "id": that is what a project would actually
        write, and it must not cost the surface its identity field.
        """

        model = NestedR7PkKid
        only_fields = ("headline",)


class NestedR7PkOwnerType(DjangoModelType):
    """The parent whose nested update payload upserts by id.

    The schema assertions and the end-to-end upsert both run through this parent, so the
    wire surface and the behaviour are pinned on one fixture.
    """

    class Meta:
        """Bind the type to "NestedR7PkOwner" with "kids" nested.

        The nested entry the "id" travels on -- and the create surface built from the
        same declaration must NOT carry it.
        """

        model = NestedR7PkOwner
        nested_fields = {"kids": NestedR7PkKid}


# --------------------------------------------------------------------------- #
# Two legal declarations that leave the child nothing writable.               #
# --------------------------------------------------------------------------- #
class NestedR7EmptyKidCard(DjangoModelType):
    """A read card allowing exactly one column.

    Both declarations in this fixture are individually legal; only their combination
    leaves the child with nothing writable at all.
    """

    class Meta:
        """Bind the type to "NestedR7EmptyKid", allowing "headline".

        The allowance names the single column its sibling host forbids, which is what
        empties the merged surface.
        """

        model = NestedR7EmptyKid
        only_fields = ("headline",)


class NestedR7EmptyKidMutation(DjangoModelMutation):
    """A write host forbidding that same column.

    The prohibition is applied last, so it subtracts the only allowance and leaves a
    zero-field input object graphql-core will not accept.
    """

    class Meta:
        """Bind the mutation to "NestedR7EmptyKid", hiding "headline".

        Nothing about this declaration is wrong on its own -- the guard exists because
        the pair is only detectable at merge time.
        """

        model = NestedR7EmptyKid
        exclude_fields = ("headline",)


class NestedR7EmptyOwnerType(DjangoModelType):
    """The parent whose nested child input would carry no field at all.

    Building through this parent is what raises the configuration error, both from a
    direct call and from inside a graphql-core field thunk.
    """

    class Meta:
        """Bind the type to "NestedR7EmptyOwner" with "kids" nested.

        Deliberately not mounted on the module's roots: mounting it would make every
        test in the file fail at import time.
        """

        model = NestedR7EmptyOwner
        nested_fields = {"kids": NestedR7EmptyKid}


# --------------------------------------------------------------------------- #
# The build seam that actually runs in production reads the PARENT registry.  #
# --------------------------------------------------------------------------- #
_THUNK_REGISTRY = Registry()


class NestedR7ThunkKidMutation(DjangoModelMutation):
    """The child's only host, declared in a NON-global registry.

    A thunk falling back to the global registry finds no host here at all, so it mints
    an unprojected input and an unlabelled field.
    """

    required_perms: ClassVar[tuple[str, ...]] = (_THUNK_LABEL,)

    class Meta:
        """Bind the mutation to "NestedR7ThunkKid" on the local registry.

        The exclusion and the label above are the two things the parent's thunks have to
        carry over; the registry is what makes finding them non-trivial.
        """

        model = NestedR7ThunkKid
        registry = _THUNK_REGISTRY
        exclude_fields = ("secret",)


class NestedR7ThunkOwnerMutation(DjangoModelMutation):
    """The parent declared in the same local registry.

    The tests read its ALREADY-BUILT input argument, which walks the same seam a real
    request walks instead of calling the builder directly.
    """

    class Meta:
        """Bind the mutation to "NestedR7ThunkOwner" on the local registry.

        Parent and child share one non-global registry, so the correct lookup is
        unambiguous and a global fallback is unmistakable.
        """

        model = NestedR7ThunkOwner
        registry = _THUNK_REGISTRY
        nested_fields = {"kids": NestedR7ThunkKid}


# --------------------------------------------------------------------------- #
# A client-supplied primary key: the only shape where the pk is a real column  #
# of the CREATE surface too.                                                   #
# --------------------------------------------------------------------------- #
class NestedR7KeyKidAllow(DjangoModelMutation):
    """A host allowing one non-key column.

    Paired with a host that forbids "id" outright, so the identity exemption has to
    survive both projection axes rather than just the allowance.
    """

    class Meta:
        """Bind the mutation to "NestedR7KeyKid", writing "headline".

        An allowance that never mentions the identity field, which is the ordinary way a
        projection gets written.
        """

        model = NestedR7KeyKid
        only_fields = ("headline",)


class NestedR7KeyKidDeny(DjangoModelMutation):
    """A host forbidding the identity field itself.

    Exempting "id" from the allowance alone is not enough: this exclusion also reaches
    the validation model, so a field removed here cannot be put back afterwards.
    """

    class Meta:
        """Bind the mutation to "NestedR7KeyKid", hiding "id".

        The prohibition the exemption has to outrank, on the one model in the suite
        whose primary key column is not called "id".
        """

        model = NestedR7KeyKid
        exclude_fields = ("id",)


class NestedR7KeyOwnerType(DjangoModelType):
    """The parent nesting the client-keyed child.

    "NestedR7KeyKid" keys on "code", so this fixture separates the wire name the
    exemption must use from the pk column it must not.
    """

    class Meta:
        """Bind the type to "NestedR7KeyOwner" with "kids" nested.

        The nested update surface built here is where "id" has to appear and "code" has
        to stay out.
        """

        model = NestedR7KeyOwner
        nested_fields = {"kids": NestedR7KeyKid}


# --------------------------------------------------------------------------- #
# The materialization record a LOCAL parent's build leaves behind.            #
# --------------------------------------------------------------------------- #
_MAT_REGISTRY = Registry()


class NestedR7MatOwnerMutation(DjangoModelMutation):
    """A parent on its own registry, nesting a globally-hosted child.

    Its build writes the materialization record. If that record lands only in the local
    registry, a late GLOBAL host is accepted in silence even though it can never reach
    the frozen surface.
    """

    class Meta:
        """Bind the mutation to "NestedR7MatOwner" on a local registry.

        The child is left hostless at declaration time on purpose: the only host for it
        arrives later, inside the test.
        """

        model = NestedR7MatOwner
        registry = _MAT_REGISTRY
        nested_fields = {"kids": NestedR7MatKid}


# --------------------------------------------------------------------------- #
# The allowance axis of the late-host no-op signature.                        #
# --------------------------------------------------------------------------- #
class NestedR7OnlyKidEarly(DjangoModelType):
    """The early host, allowing one column.

    The peer a late host claims to repeat. If allowances are missing from the no-op
    signature, a late host widening this one compares equal and is waved straight
    through.
    """

    class Meta:
        """Bind the type to "NestedR7OnlyKid", allowing "headline".

        A single column, so a late host adding a second differs on exactly one axis and
        nothing else can explain the refusal.
        """

        model = NestedR7OnlyKid
        only_fields = ("headline",)


class NestedR7OnlyOwnerType(DjangoModelType):
    """The parent nesting the allowance-signature child.

    Building through it freezes the nested input, which is the precondition the late-
    host guard needs before it can fire at all.
    """

    class Meta:
        """Bind the type to "NestedR7OnlyOwner" with "kids" nested.

        Its name appears in the refusal message, which is what proves the error came
        from the late-host guard and not the emptied-projection one.
        """

        model = NestedR7OnlyOwner
        nested_fields = {"kids": NestedR7OnlyKid}


# --------------------------------------------------------------------------- #
# The exclusion axis of the late-host no-op signature.                        #
# --------------------------------------------------------------------------- #
class NestedR7SigKidEarly(DjangoModelType):
    """The early host, forbidding one column.

    The exclusion twin of the allowance fixture: the late host differs only in what it
    forbids, so exclusions have to be part of the signature too.
    """

    class Meta:
        """Bind the type to "NestedR7SigKid", hiding "headline".

        A single exclusion, so a late host hiding a different column differs on exactly
        one axis.
        """

        model = NestedR7SigKid
        exclude_fields = ("headline",)


class NestedR7SigOwnerType(DjangoModelType):
    """The parent nesting the exclusion-signature child.

    The parent whose frozen nested input the late host could never have narrowed, and
    whose name the refusal has to carry.
    """

    class Meta:
        """Bind the type to "NestedR7SigOwner" with "kids" nested.

        A parent of its own rather than a shared one: the guard is keyed per parent, so
        reusing another fixture's parent would arm this one by accident.
        """

        model = NestedR7SigOwner
        nested_fields = {"kids": NestedR7SigKid}


# --------------------------------------------------------------------------- #
# Two mutations for one model, projecting different columns.                  #
# --------------------------------------------------------------------------- #
class NestedR7SlotKidPublic(DjangoModelMutation):
    """The first-declared host, which owns the shared generic input slot.

    Whoever reached that slot first used to decide the wire surface for every later host
    on the same model, which is the asymmetry the tests below break.
    """

    class Meta:
        """Bind the mutation to "NestedR7SlotKid", writing "headline".

        The narrower of the two projections; a second host declaring more is what
        exposes the slot's first-come ownership.
        """

        model = NestedR7SlotKid
        only_fields = ("headline",)


class _Query(ObjectType):
    """Root exposing the read field of the parents the schema build needs."""

    r7_read_owner_retrieve = NestedR7ReadOwnerType.RetrieveField()


class _Mutation(ObjectType):
    """Root exposing the parents whose built input the tests inspect."""

    r7_read_owner_create = NestedR7ReadOwnerType.CreateField()


compile_all_outputs()
_schema = DjangoGraphQLSchema(query=_Query, mutation=_Mutation).graphql_schema


def _info() -> SimpleNamespace:
    """Build a bare GraphQL resolve-info stand-in for direct resolver calls.

    Returns:
        An object shaped like a GraphQL resolve info, with a "context" carrying
        empty "META" and "FILES".
    """
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _update(host: Any, data: dict[str, Any]) -> Any:
    """Invoke the generated "update" resolver of a host.

    Args:
        host: The "DjangoModelType" / "DjangoModelMutation" class to call.
        data: The input payload, keyed by the host's input field name.

    Returns:
        The mutation result object (exposes "ok" and, on failure, "errors").
    """
    return host.update(None, _info(), **{host._meta.input_field_name: data})


def _nested_fields(child: Any, op: str, parent: Any, registry: Any = None) -> set[str]:
    """Return the field names of a child's nested input for one parent.

    Args:
        child: The nested child's Django model.
        op: The parent's operation ("create" or "update").
        parent: The nesting parent's Django model.
        registry: The registry to build against; the global one by default.

    Returns:
        The built input object type's field names.
    """
    built = nested_child_input(child, op, registry or get_global_registry(), parent)
    return set(built._meta.graphql_input_type.fields)


def _input_type(host: Any, op: str) -> Any:
    """Return the graphql-core input object a host's operation argument takes.

    Args:
        host: The host class.
        op: The operation whose input argument is inspected.

    Returns:
        The unwrapped "GraphQLInputObjectType".
    """
    argument = host._meta.arguments[op][host._meta.input_field_name]
    return get_named_type(argument.type)


def _input_field_names(host: Any, op: str) -> set[str]:
    """Return the wire field names of a host's operation input.

    Args:
        host: The host class.
        op: The operation whose input argument is inspected.

    Returns:
        The input object type's field names.
    """
    return set(_input_type(host, op).fields)


def _built_nested_field(host: Any, op: str, alias: str) -> Any:
    """Return one nested input field of a host's ALREADY-BUILT input argument.

    This walks the seam a real request walks -- the parent input's own field
    thunk -- rather than calling "nested_child_input" directly, so a thunk that
    ignores the parent's registry is visible here.

    Args:
        host: The parent host class.
        op: The operation whose input argument is inspected.
        alias: The nested field's wire name.

    Returns:
        The parent input's "GraphQLInputField" for that nested relation.
    """
    argument = host._meta.arguments[op][host._meta.input_field_name]
    return get_named_type(argument.type).fields[alias]


class TestDeclaringNothingKeepsEveryOperation:
    """The new option must be a pure opt-out, not a behaviour change.

    Host membership, projection and scope are all asserted, because narrowing the
    default would quietly drop a declare-nothing host out of the nested write path --
    the very gate this lot exists to close.
    """

    def test_a_host_that_declares_nothing_serves_every_operation(self) -> None:
        """The default is EVERY operation, so an existing project is untouched.

        This test breaks if the default is narrowed: a plain "DjangoModelType"
        would silently stop contributing its projection and its scope to the
        nested write path, which is the whole gate this lot exists to close.
        """
        registry = get_global_registry()
        for op in ("create", "update", "delete", "list", "retrieve"):
            assert NestedR7DefaultKidCard in hosts_serving(
                registry, NestedR7DefaultKid, op
            )

    def test_its_projection_still_reaches_the_nested_input(self) -> None:
        """A declare-nothing host is still a write host.

        This test breaks if the opt-out is applied by default rather than on
        request.
        """
        fields = _nested_fields(NestedR7DefaultKid, "create", NestedR7DefaultOwner)
        assert "secret" not in fields
        assert "headline" in fields

    @pytest.mark.django_db()
    def test_its_queryset_still_gates_a_nested_update(self) -> None:
        """The scope half of a declare-nothing host is unchanged too.

        A projection can be read off the built schema, but scoping only shows up at
        write time, so this drives a real nested update at a row the host's queryset
        hides.
        """
        owner = NestedR7DefaultOwner.objects.create(name="o")
        hidden = NestedR7DefaultKid.objects.create(
            owner=owner, headline="hidden", tenant="b"
        )

        result = _update(
            NestedR7DefaultOwnerType,
            {"id": owner.pk, "kids": [{"id": hidden.pk, "headline": "PWNED"}]},
        )

        assert not result.ok
        hidden.refresh_from_db()
        assert hidden.headline == "hidden"


class TestADeclaredReadHostStopsGatingWrites:
    """A host that says it serves reads only has no say over a nested write.

    The declaration has to bind in both directions: its column list and its display
    queryset leave the write path, AND its own write roots stop being mounted --
    otherwise it writes columns it claims not to serve.
    """

    def test_its_allowance_drops_out_of_the_nested_write_surface(self) -> None:
        """A read card's column list is not a write allowance.

        This test breaks if "model_operations" stops being read on
        "DjangoModelType": the card's "secret" would be unioned into the write
        allowance and become settable through the parent.
        """
        fields = _nested_fields(NestedR7ReadKid, "create", NestedR7ReadOwner)
        assert fields == {"headline"}

    @pytest.mark.django_db()
    def test_its_queryset_stops_gating_a_nested_update(self) -> None:
        """The display default stops refusing rows the write host can see.

        This is the remedy the docs prescribe: the read card's "Meta.queryset"
        is a display default, and declaring the card a read host takes it out
        of the nested write path.
        """
        owner = NestedR7ReadOwner.objects.create(name="o")
        kid = NestedR7ReadKid.objects.create(owner=owner, headline="old", tenant="b")

        result = _update(
            NestedR7ReadOwnerType,
            {"id": owner.pk, "kids": [{"id": kid.pk, "headline": "new"}]},
        )

        assert result.ok, getattr(result, "errors", None)
        kid.refresh_from_db()
        assert kid.headline == "new"

    def test_a_read_hosts_write_field_builders_refuse(self) -> None:
        """A declared read host must not mount the write roots it disclaimed.

        Without this the declaration would be a lie in one direction: the
        nested path treats the host as read-only while its own create root
        writes the very columns it says it does not serve.
        """
        with pytest.raises(AttributeError) as excinfo:
            NestedR7ReadKidCard.CreateField()

        assert "model_operations" in str(excinfo.value)

    def test_a_read_hosts_query_field_builders_still_work(self) -> None:
        """The operations it DID declare stay mounted.

        The refusal above has to be scoped to the disclaimed verbs; a builder that
        refused everything would leave a read host with no surface at all.
        """
        assert NestedR7ReadKidCard.RetrieveField() is not None
        assert NestedR7ReadKidCard.ListField() is not None

    def test_a_read_host_builds_no_write_argument_at_all(self) -> None:
        """It must not mint, nor register, an input it says it does not serve.

        The generic "(model, operation)" input slot holds one type per model,
        so a read card that still built its write inputs would keep taking a
        slot the project's real write host needs -- and would keep paying to
        compile a surface no field exposes. This test breaks if the argument
        loop stops honouring "Meta.model_operations".
        """
        assert NestedR7ReadKidCard._meta.arguments == {}

    def test_the_field_bundles_return_only_what_is_enabled(self) -> None:
        """A read host's bundles must not raise, and must not invent fields.

        "MutationFields()" calls all three builders, every one of which now
        refuses on a read host. This test breaks if the bundles stop filtering:
        the call raises "AttributeError" instead of returning what the host
        actually serves.
        """
        assert NestedR7ReadKidCard.MutationFields() == ()
        assert len(NestedR7ReadKidCard.QueryFields()) == 2
        assert len(NestedR7DefaultKidCard.MutationFields()) == 3
        assert len(NestedR7DefaultKidCard.QueryFields()) == 2

    def test_an_unknown_operation_is_refused(self) -> None:
        """A typo must not silently turn a host into a read host.

        An unrecognised verb that is merely ignored removes the host from the write
        path, taking its projection, its scope and its permission gate with it.
        """
        with pytest.raises(ImproperlyConfigured) as excinfo:

            class NestedR7TypoCard(DjangoModelType):
                """A host whose "model_operations" carries a typo."""

                class Meta:
                    """Bind the type to "NestedR7ReadKid" with a bad option."""

                    model = NestedR7ReadKid
                    model_operations = ("retreive",)

        assert "retreive" in str(excinfo.value)


class TestTheNoAllowanceBranches:
    """The two ways an allowance restriction is legitimately absent.

    One is the plain unhosted child, where inventing a projection would delete columns
    from every existing payload. The other takes an explicit declaration -- and the
    prohibition still has to survive it.
    """

    def test_a_child_with_no_host_at_all_keeps_every_writable_column(self) -> None:
        """The ordinary "nested_fields" case: the child is a plain model.

        This is what the library has always done and is correct; a projection
        invented here would silently delete columns from every existing nested
        payload.
        """
        fields = _nested_fields(NestedR7BareKid, "create", NestedR7BareOwner)
        assert {"headline", "secret"} <= fields

    def test_a_host_that_serves_nothing_leaves_the_prohibition_behind(self) -> None:
        """The allowance goes, the prohibition stays.

        Reaching this branch takes an EXPLICIT "model_operations" saying the
        host is not a write host. This test breaks if the prohibition axis is
        ever scoped to the operation its host serves: "secret" would become
        writable through the parent although the project's only host for the
        model forbids it everywhere.
        """
        fields = _nested_fields(NestedR7NoServeKid, "create", NestedR7NoServeOwner)
        assert "secret" not in fields
        assert "headline" in fields

    def test_the_branch_needs_an_explicit_declaration_to_reach(self) -> None:
        """Both host classes serve both write verbs unless told otherwise.

        This is the reasoning the branch rests on. If a host class ever ships a
        default that serves neither write verb, the branch becomes reachable
        without the project saying anything and the merge fails OPEN.
        """
        registry = get_global_registry()
        for op in ("create", "update"):
            assert NestedR7BareOwnerType in hosts_serving(
                registry, NestedR7BareOwner, op
            )
            assert NestedR7LastKidDeny in hosts_serving(registry, NestedR7LastKid, op)

    def test_a_prohibition_beats_another_hosts_allowance(self) -> None:
        """ "exclude_fields" is applied LAST, so a forbidden column never lands.

        This test breaks if the two axes are merged in the other order: a
        column one host explicitly forbids would be restored by any other
        host's "only_fields" naming it.
        """
        fields = _nested_fields(NestedR7LastKid, "create", NestedR7LastOwner)
        assert "secret" not in fields
        assert "headline" in fields


@pytest.mark.django_db()
class TestALocalParentStillFindsTheGlobalHost:
    """The permission gate must not go quiet for a multi-schema project.

    A host that never named a registry lives in the global one and is still that model's
    host, so scoping the lookup to the parent's registry leaves a "Meta.registry" parent
    with no gate, no projection and no scope.
    """

    def test_the_global_hosts_projection_reaches_the_local_parents_input(
        self,
    ) -> None:
        """A host that never named a registry lives in the global one.

        "Meta.registry" is not an option on "DjangoModelType", the only host
        class carrying "permission_classes", so a child's permission host can
        only live in the global registry. This test breaks if the lookup goes
        back to the parent's registry alone: the host disappears and its
        exclusion with it.
        """
        fields = _nested_fields(
            NestedR7CrossKid, "create", NestedR7CrossOwner, _CROSS_REGISTRY
        )
        assert "secret" not in fields

    def test_the_global_hosts_permission_still_denies_the_nested_write(self) -> None:
        """The runtime gate is the security property, and it is absolute.

        A parent bound to a second registry must not be a back door around the
        child's own "permission_classes".
        """
        from graphql import GraphQLError

        owner = NestedR7CrossOwner.objects.create(name="o")

        with pytest.raises(GraphQLError):
            NestedR7CrossOwnerMutation.update(
                None,
                _info(),
                **{
                    NestedR7CrossOwnerMutation._meta.input_field_name: {
                        "id": owner.pk,
                        "kids": [{"headline": "written"}],
                    }
                },
            )

        assert not NestedR7CrossKid.objects.exists()


@pytest.mark.django_db()
class TestThePrimaryKeySurvivesOnUpdate:
    """A projected child must stay upsertable through its parent.

    On an update surface "id" identifies the row rather than being written, so both
    projection axes have to leave it alone -- and neither may add it to the create
    surface, which would turn every nested create into an upsert.
    """

    def test_the_nested_update_input_still_exposes_the_pk(self) -> None:
        """The pk is not a projectable column on an update surface.

        This test breaks if a host's "only_fields" is allowed to strip it: the
        documented upsert-by-id becomes unreachable over the wire and a client
        that drops the rejected "id" gets a duplicate CREATE instead.
        """
        fields = _nested_fields(NestedR7PkKid, "update", NestedR7PkOwner)
        assert "id" in fields

    def test_the_nested_create_input_still_has_no_pk(self) -> None:
        """The create surface stays create-only.

        This test breaks if the pk is force-included on both operations, which
        would turn every nested create into an unguarded upsert.
        """
        fields = _nested_fields(NestedR7PkKid, "create", NestedR7PkOwner)
        assert "id" not in fields

    def test_a_hosts_exclusion_cannot_strip_the_identity_field(self) -> None:
        """The prohibition axis does not reach the identity field on an update.

        Exempting it from the allowance alone is not enough: a host naming
        "id" in "exclude_fields" would still delete it -- and that exclusion
        reaches the validation model too, so the field cannot be put back
        afterwards. The nested update input would again be unable to identify a
        row.
        """
        fields = _nested_fields(NestedR7KeyKid, "update", NestedR7KeyOwner)
        assert "id" in fields

    def test_the_identity_field_is_id_not_the_pk_column(self) -> None:
        """The exemption is keyed on the wire name, not the model's pk column.

        A generated update input exposes the pk as "id" whatever the column is
        called, and the column itself is never client-writable. Keying the
        exemption on "Meta.pk.name" therefore exempted a name that is not on
        the surface at all, and the real identity field stayed strippable.
        """
        assert NestedR7KeyKid._meta.pk.name == "code"
        fields = _nested_fields(NestedR7KeyKid, "update", NestedR7KeyOwner)
        assert "code" not in fields

    def test_an_upsert_by_id_updates_the_row_instead_of_duplicating_it(self) -> None:
        """The end-to-end behaviour the guide's worked example promises.

        The schema-level assertions above only prove "id" is present; this one proves
        the resolver still uses it to find the row instead of minting a second one.
        """
        owner = NestedR7PkOwner.objects.create(name="o")
        kid = NestedR7PkKid.objects.create(owner=owner, headline="old")

        result = _update(
            NestedR7PkOwnerType,
            {"id": owner.pk, "kids": [{"id": kid.pk, "headline": "new"}]},
        )

        assert result.ok, getattr(result, "errors", None)
        kid.refresh_from_db()
        assert kid.headline == "new"
        assert NestedR7PkKid.objects.count() == 1


class TestAnEmptiedProjectionIsRefused:
    """Shipping a schema graphql-core rejects is worse than a build error.

    A zero-field input object fails validation for the WHOLE schema, not just the nested
    field, so the guard has to fire at build time and name the hosts a project would
    have to change.
    """

    def test_the_build_names_every_contributing_host(self) -> None:
        """The error has to be actionable: it names what to change.

        This test breaks if the guard is deleted again: the schema then builds
        and returns SILENTLY with a zero-field input object, and every request
        through it fails schema validation -- not just the nested field.
        """
        with pytest.raises(ImproperlyConfigured) as excinfo:
            nested_child_input(
                NestedR7EmptyKid, "create", get_global_registry(), NestedR7EmptyOwner
            )

        message = str(excinfo.value)
        assert "NestedR7EmptyKidCard" in message
        assert "NestedR7EmptyKidMutation" in message
        assert "NestedR7EmptyKid" in message
        assert "headline" in message

    def test_the_error_escapes_a_graphql_core_fields_thunk(self) -> None:
        """The guard runs inside an input field thunk, which wraps exceptions.

        graphql-core re-raises anything a field thunk throws as a bare
        "TypeError" whose message buries the cause. This test breaks if the
        unwrap is dropped: the project gets a "TypeError" instead of the
        configuration error naming its own classes.
        """

        class _EmptyMutation(ObjectType):
            """Root mounting the parent whose nested child input is empty."""

            r7_empty_owner_create = NestedR7EmptyOwnerType.CreateField()

        with pytest.raises(ImproperlyConfigured) as excinfo:
            DjangoGraphQLSchema(query=_Query, mutation=_EmptyMutation).graphql_schema

        assert "NestedR7EmptyKid" in str(excinfo.value)


class TestTheBuildSeamReadsTheParentsRegistry:
    """The thunks that run in production must not fall back to the global.

    The direct builder is handed a registry; the thunks have to fetch one. A thunk
    reaching for the global registry loses the child's projection and its label at once,
    and only an already-built input shows it.
    """

    def test_the_child_thunk_honours_the_parents_registry(self) -> None:
        """The projection half, driven through the parent's own field thunk.

        The child's only host lives in a NON-global registry, so a thunk
        reading "get_global_registry()" finds no host and mints an unprojected
        child input. This test breaks the moment that happens.
        """
        field = _built_nested_field(NestedR7ThunkOwnerMutation, "create", "kids")
        assert "secret" not in get_named_type(field.type).fields

    def test_the_stamp_thunk_honours_the_parents_registry(self) -> None:
        """The label half, driven through the same thunk.

        This test breaks if the stamp thunk reads the global registry: the
        local host's project-specific label never reaches the nested field and
        the pruner leaves the write reachable for a caller who may not hold it.
        """
        field = _built_nested_field(NestedR7ThunkOwnerMutation, "create", "kids")
        perms = (field.extensions or {}).get("gdx_required_perms") or ()
        assert _THUNK_LABEL in perms


class TestTheLateTwinSignatureComparesBothProjectionAxes:
    """A late host declaring a FRESH projection is a real narrowing.

    Whatever is missing from the no-op signature becomes a silent failure: the late host
    compares equal, is waved through, and its declaration never reaches the frozen
    surface.
    """

    def test_a_late_host_differing_only_in_allowances_is_refused(self) -> None:
        """The allowance axis is part of what a host contributes.

        This test breaks if "only_fields" drops out of the no-op signature: a
        late host widening the allowance compares equal to the early one, is
        waved through, and the column it meant to allow never appears on the
        already-built nested surface -- silently, for the process lifetime.
        """
        nested_child_input(
            NestedR7OnlyKid, "create", get_global_registry(), NestedR7OnlyOwner
        )

        with pytest.raises(ImproperlyConfigured) as excinfo:

            class NestedR7OnlyKidLate(DjangoModelMutation):
                """A late host whose only new contribution is an allowance."""

                class Meta:
                    """Bind the mutation to "NestedR7OnlyKid", adding a column."""

                    model = NestedR7OnlyKid
                    only_fields = ("headline", "secret")

        message = str(excinfo.value)
        assert "NestedR7OnlyKidLate" in message
        assert "NestedR7OnlyOwner" in message

    def test_a_late_global_host_is_refused_for_a_local_parents_build(self) -> None:
        """The materialization record follows the host lookup.

        A parent on its own registry reads the global hosts too, so a global
        host declared after that parent's build can no longer reach it. This
        test breaks if the record is written to the parent's registry alone:
        the late host is then accepted in silence and its projection never
        reaches the surface it was meant for.
        """
        nested_child_input(NestedR7MatKid, "create", _MAT_REGISTRY, NestedR7MatOwner)

        with pytest.raises(ImproperlyConfigured) as excinfo:

            class NestedR7MatKidLate(DjangoModelType):
                """A global host arriving after the local parent's build."""

                class Meta:
                    """Bind the type to "NestedR7MatKid", hiding "secret"."""

                    model = NestedR7MatKid
                    exclude_fields = ("secret",)

        message = str(excinfo.value)
        assert "NestedR7MatKidLate" in message
        assert "NestedR7MatOwner" in message

    def test_a_late_host_differing_only_in_exclusions_is_refused(self) -> None:
        """The exclusion axis is part of what a host contributes.

        This test breaks if "exclude_fields" drops out of the no-op signature:
        two hosts differing only there compare equal, the late one is waved
        through, and its prohibition never reaches the already-built nested
        input -- the silent fail-open the guard exists to make loud.
        """
        nested_child_input(
            NestedR7SigKid, "create", get_global_registry(), NestedR7SigOwner
        )

        with pytest.raises(ImproperlyConfigured) as excinfo:

            class NestedR7SigKidLate(DjangoModelMutation):
                """A late host whose only new contribution is an exclusion."""

                class Meta:
                    """Bind the mutation to "NestedR7SigKid", hiding "secret"."""

                    model = NestedR7SigKid
                    exclude_fields = ("secret",)

        message = str(excinfo.value)
        assert "NestedR7SigKidLate" in message
        assert "NestedR7SigOwner" in message


class TestASecondHostCannotLoseItsProjection:
    """A projection the shared input slot drops is a lie in both directions.

    The host's own root accepts columns it declared away, while the nested merge --
    which reads the DECLARATION rather than the slot -- still honours them. One model,
    two contradictory surfaces.
    """

    def test_each_host_gets_the_projection_it_declared(self) -> None:
        """The shared "(model, operation)" slot must not decide for everyone.

        The first host to reach the slot used to own the wire surface for every
        later one, so a mutation declaring "only_fields" behind an already
        registered host had its projection silently dropped and its own root
        accepted every writable column -- while the nested merge, which reads
        the DECLARATION, still unioned it. This test breaks if a projected
        input goes back into the shared slot.
        """

        class NestedR7SlotKidStaff(DjangoModelMutation):
            """A second host projecting a wider column list."""

            class Meta:
                """Bind the mutation to "NestedR7SlotKid", adding a column."""

                model = NestedR7SlotKid
                only_fields = ("headline", "is_admin")

        assert _input_field_names(NestedR7SlotKidPublic, "create") == {"headline"}
        assert _input_field_names(NestedR7SlotKidStaff, "create") == {
            "headline",
            "isAdmin",
        }

    def test_two_hosts_declaring_one_projection_share_a_type(self) -> None:
        """The memo is load-bearing: one name must mean one type.

        Two hosts declaring the SAME projection would otherwise mint two
        distinct types under one name, which graphql-core refuses to build a
        schema from. This test breaks if the projected input stops being
        memoized.
        """

        class NestedR7SlotKidTwin(DjangoModelMutation):
            """A third host repeating the first host's projection."""

            class Meta:
                """Bind the mutation to "NestedR7SlotKid", writing "headline"."""

                model = NestedR7SlotKid
                only_fields = ("headline",)

        assert _input_type(NestedR7SlotKidTwin, "create") is _input_type(
            NestedR7SlotKidPublic, "create"
        )


class TestAProjectedUpdateRootKeepsItsIdentityField:
    """A projected host's OWN update input must still carry "id".

    "only_fields" projects the writable COLUMNS of a surface. On an update it
    does not, and cannot, project away the identity field: "id" is how the
    resolver finds the row, not a column the client writes. Stripping it ships
    an update root no client can call, and the nested path already exempts it —
    the two surfaces must agree.
    """

    def test_a_projected_update_input_still_exposes_id(self) -> None:
        """Assert a host projecting one column keeps "id" on its update input.

        The nested path already exempts the identity field, so a host's own update root
        dropping it ships a mutation no client can address a row through.
        """

        class NestedR7IdKidMutation(DjangoModelMutation):
            """A host whose projection deliberately omits the identity field."""

            class Meta:
                """Bind to "NestedR7SlotKid", writing "headline" only."""

                model = NestedR7SlotKid
                only_fields = ("headline",)

        fields = set(_input_type(NestedR7IdKidMutation, "update").fields)
        assert "id" in fields, (
            "A projected update input dropped 'id', so no client can address a "
            f"row through it; fields were {sorted(fields)}"
        )

    def test_a_projected_create_input_still_has_no_id(self) -> None:
        """Assert the exemption is scoped to update and never adds "id" to create.

        The create surface mints a row, so an identity field there would be a
        client-supplied primary key -- the opposite of what this exemption is
        for.
        """

        class NestedR7IdKidCreateMutation(DjangoModelMutation):
            """A create-side host carrying the same projection."""

            class Meta:
                """Bind to "NestedR7SlotKid", writing "headline" only."""

                model = NestedR7SlotKid
                only_fields = ("headline",)
                model_operations = ("create",)

        fields = set(_input_type(NestedR7IdKidCreateMutation, "create").fields)
        assert "id" not in fields, (
            f"A projected create input grew an 'id' field; fields were {sorted(fields)}"
        )
