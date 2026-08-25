"""Round-6 restructuring of the nested-write host model.

Five correction rounds kept re-opening the same seams because the HOST MODEL
underneath them was never designed. This round settles it:

* an "only_fields" is an ALLOWANCE, so it is UNIONED across the hosts that serve
  the operation. Intersecting it turned an ordinary read-projection /
  write-projection split into an import-time "ImproperlyConfigured" on a
  configuration that used to build. The prohibition axis ("exclude_fields")
  still subtracts from the union afterwards, so a column any host hid stays
  unwritable,
* the host list is per REGISTRY, exactly like the memo and the materialization
  record it feeds, so a host bound to a second registry through "Meta.registry"
  cannot rewrite the first registry's nested projection, permission stamp or
  write-time row scoping,
* the permission stamp resolves LAZILY, in the same thunk and from the same host
  list as the projection it must match, so a child write host declared after the
  parent reaches the nested field on both axes instead of just one,
* a host's "required_perms" is read only for the operations that host serves, so
  a delete-only host's label no longer gates a nested create,
* the nested scope check in "_persist_child" is pinned on the two branches no
  test reached: the forward-FK link that resolves to an already-linked row, and
  the M2M payload naming a row the parent already carries.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from django.core.exceptions import ImproperlyConfigured
from graphql import get_named_type

from django_graphex.core import ObjectType
from django_graphex.core.registry_compiler import compile_all_outputs
from django_graphex.core.schema_pruner import prune_schema
from django_graphex.mutation import DjangoModelMutation, nested_child_input
from django_graphex.permissions import DjangoModelPermissions
from django_graphex.registry import Registry, get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from tests.models import (
    NestedR6IsoKid,
    NestedR6IsoOwner,
    NestedR6LabelKid,
    NestedR6LabelOwner,
    NestedR6LateKid,
    NestedR6LateOwner,
    NestedR6LocalKid,
    NestedR6LocalOwner,
    NestedR6OpsKid,
    NestedR6OpsOwner,
    NestedR6PinKid,
    NestedR6PinOwner,
    NestedR6SigKid,
    NestedR6SigOwner,
    NestedR6SplitKid,
    NestedR6SplitOwner,
)

#: The label the OTHER registry's host declares. It must never reach the first
#: registry's nested surface.
_ISO_LABEL = "tests.publish_nestedr6isokid"

#: The label a write host declared AFTER its parent must still reach.
_LATE_LABEL = "tests.publish_nestedr6latekid"

#: The label a DELETE-only host declares. A nested create is not a delete.
_OPS_LABEL = "tests.purge_nestedr6opskid"


# --------------------------------------------------------------------------- #
# An "only_fields" is an ALLOWANCE: the hosts serving the operation union it.  #
# --------------------------------------------------------------------------- #
class NestedR6SplitKidCard(DjangoModelType):
    """The READ surface, projecting the columns a card displays.

    A read projection and a write projection sharing nothing is an ordinary
    configuration, not a contradiction -- intersecting the two killed schemas that used
    to build.
    """

    class Meta:
        """Bind the type to "NestedR6SplitKid", showing "slug".

        The allowance names "id" and "slug" only, so its union with the write host's
        "headline" is observable in a single input type.
        """

        model = NestedR6SplitKid
        only_fields = ("id", "slug")


class NestedR6SplitKidMutation(DjangoModelMutation):
    """The WRITE surface, projecting the columns a client may set.

    It allows "headline", which the read card never mentions; a nested input missing it
    would refuse a write the child's own mutation accepts.
    """

    class Meta:
        """Bind the mutation to "NestedR6SplitKid", writing "headline".

        Declares no "model_operations", so this host serves both write verbs and the
        operation filter cannot quietly drop it from the merge.
        """

        model = NestedR6SplitKid
        only_fields = ("headline",)


class NestedR6SplitOwnerType(DjangoModelType):
    """The parent nesting the split-projection child.

    The nesting scope the merged child input is built for; the tests read that input
    directly rather than through an assembled schema.
    """

    class Meta:
        """Bind the type to "NestedR6SplitOwner" with "kids" nested.

        The parent's own surface is deliberately unprojected, so every field the tests
        see on the child input arrived from the child's hosts.
        """

        model = NestedR6SplitOwner
        nested_fields = {"kids": NestedR6SplitKid}


# --------------------------------------------------------------------------- #
# The host list is per registry.                                              #
# --------------------------------------------------------------------------- #
_ISO_REGISTRY = Registry()


class NestedR6IsoKidOtherMutation(DjangoModelMutation):
    """A host bound to a SECOND registry, narrowing on every axis it can.

    Projection, permission label and row scope at once, because the isolation rule has
    to hold on all three: a leak on any one of them is a different bug with the same
    cause.
    """

    required_perms: ClassVar[tuple[str, ...]] = (_ISO_LABEL,)

    class Meta:
        """Bind the mutation to "NestedR6IsoKid" on its own registry.

        "Meta.registry" is the documented multi-schema option, so merely importing this
        module must not change what the global registry builds.
        """

        model = NestedR6IsoKid
        registry = _ISO_REGISTRY
        exclude_fields = ("secret",)

    @classmethod
    def filter_queryset(cls, qs: Any, info: Any, **kwargs: Any) -> Any:
        """Hide every row from THIS registry's surface.

        Args:
            qs: The queryset to scope.
            info: GraphQL resolve info for the current request.
            **kwargs: Extra arguments the caller forwarded.

        Returns:
            An empty queryset.
        """
        return qs.none()


class NestedR6IsoKidType(DjangoModelType):
    """The FIRST registry's host: no projection, no scope, no label.

    Contributing nothing is the point: any narrowing the tests observe on this
    registry's surface could only have come from the other registry's host.
    """

    class Meta:
        """Bind the type to "NestedR6IsoKid" on the global registry.

        Naming no registry is what puts a host in the global one, which is the registry
        every assertion here builds against.
        """

        model = NestedR6IsoKid


class NestedR6IsoOwnerType(DjangoModelType):
    """The first registry's parent, nesting the twice-hosted child.

    It declares no "permission_classes" on purpose: this fixture drives the
    nested writer directly, and the only gate under test is the one the OTHER
    registry's host must not impose.
    """

    class Meta:
        """Bind the type to "NestedR6IsoOwner" with "kids" nested.

        The nested entry the writer follows at runtime; with the parent ungated, any
        denial observed can only have come from a child host.
        """

        model = NestedR6IsoOwner
        nested_fields = {"kids": NestedR6IsoKid}


# --------------------------------------------------------------------------- #
# The stamp resolves at the same moment as the projection it must match.      #
# --------------------------------------------------------------------------- #
class NestedR6LateOwnerType(DjangoModelType):
    """The parent, declared BEFORE the child's own write host.

    A parent app importing a child app later is the ordinary order, so a stamp frozen
    eagerly misses the label on the most common layout there is.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)

    class Meta:
        """Bind the type to "NestedR6LateOwner" with "kids" nested.

        This declaration is what used to freeze the stamp: the nested field existed
        before the child's write host had even been imported.
        """

        model = NestedR6LateOwner
        nested_fields = {"kids": NestedR6LateKid}


class NestedR6LateKidMutation(DjangoModelMutation):
    """The child's own write host, declared after the parent but before build.

    Late, but still in time for the build, so both halves of its declaration are
    reachable -- the projection always was, and the label is the half that used to be
    missed.
    """

    required_perms: ClassVar[tuple[str, ...]] = (_LATE_LABEL,)

    class Meta:
        """Bind the mutation to "NestedR6LateKid" for both write verbs.

        Serving create and update puts the label on both of this host's roots, so a
        caller lacking it loses them and must lose the nested field with them.
        """

        model = NestedR6LateKid
        model_operations = ("create", "update")


# --------------------------------------------------------------------------- #
# A label is read only for the operations its host serves.                    #
# --------------------------------------------------------------------------- #
class NestedR6OpsKidDeleteMutation(DjangoModelMutation):
    """A delete-only host carrying a destructive project-specific label.

    A purge permission says nothing about creating a child through its parent, so
    unioning it into the nested create stamp locks out callers who may legitimately
    write.
    """

    required_perms: ClassVar[tuple[str, ...]] = (_OPS_LABEL,)

    class Meta:
        """Bind the mutation to "NestedR6OpsKid" for "delete" only.

        "model_operations" is what scopes the label; without the narrowing this fixture
        would be indistinguishable from an ordinary write host.
        """

        model = NestedR6OpsKid
        model_operations = ("delete",)


class NestedR6OpsOwnerType(DjangoModelType):
    """The parent nesting the delete-labelled child.

    Model-permission gated so the test can grant the full composite write set and still
    observe whether the delete label crept into the stamp.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)

    class Meta:
        """Bind the type to "NestedR6OpsOwner" with "kids" nested.

        The nested CREATE surface is the one the pruner is asked about -- an operation
        the labelled host does not serve at all.
        """

        model = NestedR6OpsOwner
        nested_fields = {"kids": NestedR6OpsKid}


# --------------------------------------------------------------------------- #
# The two link branches that reach "_persist_child" with an existing row.     #
# --------------------------------------------------------------------------- #
class NestedR6PinKidType(DjangoModelType):
    """A tenant-scoped host: rows of any other tenant are invisible.

    Both link branches below resolve to a row this scope hides, which is the only reason
    attaching a row can be a disclosure.
    """

    class Meta:
        """Bind the type to "NestedR6PinKid", scoped to one tenant.

        Scoped through "Meta.queryset", so the hiding is declarative and applies to
        every operation the host serves.
        """

        model = NestedR6PinKid
        queryset = NestedR6PinKid.objects.filter(tenant="a")


class NestedR6PinOwnerType(DjangoModelType):
    """The parent nesting the same child through a forward FK and an M2M.

    One child model on two relation kinds, so the two "_persist_child" branches no other
    test reaches are both driven from a single fixture.
    """

    class Meta:
        """Bind the type to "NestedR6PinOwner" with both links nested.

        Nesting "fwd" and "tags" is what turns an "id"-carrying payload into a write
        path rather than a plain link.
        """

        model = NestedR6PinOwner
        nested_fields = {"fwd": NestedR6PinKid, "tags": NestedR6PinKid}


# --------------------------------------------------------------------------- #
# The late-twin escape hatch compares EVERYTHING a host contributes.          #
# --------------------------------------------------------------------------- #
class NestedR6SigKidCreateMutation(DjangoModelMutation):
    """A create-only host allowing exactly one column.

    The peer a late update-only host would claim to repeat -- and the repeat is only a
    no-op if the operations match as well as the columns.
    """

    class Meta:
        """Bind the mutation to "NestedR6SigKid" for "create" only.

        The operation narrowing is half the no-op signature: the same "only_fields" on
        another verb narrows a surface this host never touched.
        """

        model = NestedR6SigKid
        model_operations = ("create",)
        only_fields = ("headline",)


class NestedR6SigOwnerType(DjangoModelType):
    """The parent nesting the operation-split child.

    The test materializes this parent's nested UPDATE input first, which is the surface
    a late host would otherwise have narrowed in silence.
    """

    class Meta:
        """Bind the type to "NestedR6SigOwner" with "kids" nested.

        This parent's name appears in the guard's error message, which is what proves
        the refusal came from the late-host check and not another guard.
        """

        model = NestedR6SigOwner
        nested_fields = {"kids": NestedR6SigKid}


class NestedR6LabelKidTypeA(DjangoModelType):
    """The early host of the late-twin label fixture, hiding one column.

    Its exclusion is the projection the late twin repeats verbatim, leaving the
    permission label as the only thing that differs between them.
    """

    class Meta:
        """Bind the type to "NestedR6LabelKid", hiding "secret".

        Exactly the declaration the late twin repeats: if the label were not part of the
        no-op signature, that twin would be waved straight through.
        """

        model = NestedR6LabelKid
        exclude_fields = ("secret",)


class NestedR6LabelOwnerType(DjangoModelType):
    """The parent nesting the late-twin label child.

    Materializing through this parent freezes the nested input, after which no newly
    declared label can ever reach it.
    """

    class Meta:
        """Bind the type to "NestedR6LabelOwner" with "kids" nested.

        Its name appears only in the late-host refusal, so asserting on it rules out a
        different guard raising the same exception type.
        """

        model = NestedR6LabelOwner
        nested_fields = {"kids": NestedR6LabelKid}


# --------------------------------------------------------------------------- #
# A parent bound to a LOCAL registry reads that registry's hosts AND the        #
# global one's, because a host that never named a registry lives there.         #
# --------------------------------------------------------------------------- #
_LOCAL_REGISTRY = Registry()


class NestedR6LocalKidType(DjangoModelType):
    """The GLOBAL registry's host: the only place a type host can live.

    "Meta.registry" is not an option on "DjangoModelType", which is exactly why scoping
    the lookup to the parent's registry alone left this child with no host at all.
    """

    class Meta:
        """Bind the type to "NestedR6LocalKid", hiding "secret" and scoping.

        It declares both a projection and a queryset, so the build side and the runtime
        side of the host lookup can be checked against the same host.
        """

        model = NestedR6LocalKid
        exclude_fields = ("secret",)
        queryset = NestedR6LocalKid.objects.filter(tenant="a")


class NestedR6LocalOwnerMutation(DjangoModelMutation):
    """A parent bound to its own registry, nesting the globally-hosted child.

    The multi-schema shape that must still see the global hosts: missing them costs
    projection, scope, label and permission gate in one go.
    """

    class Meta:
        """Bind the mutation to "NestedR6LocalOwner" on a local registry.

        "registry" is what makes this parent's lookup non-trivial -- the child's only
        host lives somewhere else entirely.
        """

        model = NestedR6LocalOwner
        registry = _LOCAL_REGISTRY
        nested_fields = {"kids": NestedR6LocalKid}


class _Query(ObjectType):
    """Root exposing every round-6 parent's read field."""

    r6_iso_owner_retrieve = NestedR6IsoOwnerType.RetrieveField()
    r6_late_owner_retrieve = NestedR6LateOwnerType.RetrieveField()
    r6_ops_owner_retrieve = NestedR6OpsOwnerType.RetrieveField()


class _Mutation(ObjectType):
    """Root exposing every round-6 parent whose input the pruner is asked about."""

    r6_iso_owner_create = NestedR6IsoOwnerType.CreateField()
    r6_late_owner_create = NestedR6LateOwnerType.CreateField()
    r6_ops_owner_create = NestedR6OpsOwnerType.CreateField()


compile_all_outputs()
_schema = DjangoGraphQLSchema(query=_Query, mutation=_Mutation).graphql_schema


def _perms(model: Any, *verbs: str) -> set[str]:
    """Return the Django permission codenames for a model and verbs.

    Args:
        model: The Django model the codenames target.
        *verbs: The permission verbs ("view", "add", "change").

    Returns:
        The "{app_label}.{verb}_{model_name}" codenames.
    """
    opts = model._meta
    return {f"{opts.app_label}.{verb}_{opts.model_name}" for verb in verbs}


def _input_fields(granted: set[str], root: str) -> set[str]:
    """Return the field names of a pruned mutation root's input argument.

    Args:
        granted: The permission codenames the caller holds.
        root: The mutation field name to inspect.

    Returns:
        The input object type's field names.
    """
    label_set = frozenset((_schema.extensions or {}).get("gdx_label_set") or ())
    pruned = prune_schema(_schema, frozenset(granted) & label_set)
    (argument,) = pruned.mutation_type.fields[root].args.values()
    return set(get_named_type(argument.type).fields)


def _info() -> SimpleNamespace:
    """Build a bare GraphQL resolve-info stand-in for direct resolver calls.

    Returns:
        An object shaped like a GraphQL resolve info, with a "context" carrying
        empty "META" and "FILES".
    """
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _update(host: Any, data: dict[str, Any]) -> Any:
    """Invoke the generated "update" resolver of a type host.

    Args:
        host: The "DjangoModelType" class to call.
        data: The input payload, keyed by the host's input field name.

    Returns:
        The mutation result object (exposes "ok" and, on failure, "errors").
    """
    return host.update(None, _info(), **{host._meta.input_field_name: data})


class TestOnlyFieldsUnionAcrossHosts:
    """A read projection and a write projection must not annihilate each other.

    The union has to widen without granting amnesty: a column no host allows must still
    stay out, or a failed merge quietly degrades into "no projection declared" and mints
    every writable column.
    """

    def test_a_read_card_and_a_write_host_both_reach_the_nested_input(self) -> None:
        """Splitting the read and write surfaces is an ORDINARY configuration.

        Intersecting the two "only_fields" leaves nothing in common and killed
        the whole schema at import on a project that builds at HEAD. This test
        breaks if the allowance axis goes back to an intersection.
        """
        built = nested_child_input(
            NestedR6SplitKid, "create", get_global_registry(), NestedR6SplitOwner
        )
        assert set(built._meta.graphql_input_type.fields) == {"headline", "slug"}

    def test_a_column_no_host_allows_stays_out(self) -> None:
        """The union is still a projection, not an amnesty.

        This test breaks if a failed merge falls back to "no projection
        declared", which mints an input carrying every writable column.
        """
        built = nested_child_input(
            NestedR6SplitKid, "create", get_global_registry(), NestedR6SplitOwner
        )
        assert "extra" not in built._meta.graphql_input_type.fields


@pytest.mark.django_db()
class TestHostsAreScopedToTheirRegistry:
    """A second registry's host must not reach the first registry's surface.

    All three axes are asserted because a process-wide host list leaks on all three:
    importing another schema's module would narrow this one's projection, gate its
    nested field, and turn its updates into not-founds.
    """

    def test_another_registrys_exclusion_does_not_narrow_the_projection(self) -> None:
        """The projection merge reads the hosts of the registry it builds for.

        This test breaks if the host list goes back to a process-wide module
        global: merely importing another schema's module then deletes a column
        from this registry's nested payload, while the child's own mutation here
        still accepts it.
        """
        built = nested_child_input(
            NestedR6IsoKid, "create", get_global_registry(), NestedR6IsoOwner
        )
        assert "secret" in built._meta.graphql_input_type.fields

    def test_another_registrys_label_does_not_gate_the_nested_field(self) -> None:
        """The permission stamp reads the same registry-scoped list.

        A caller holding every composite write verb on both models must keep the
        nested field; the other registry's project-specific label is not part of
        this schema's contract at all.
        """
        granted = _perms(NestedR6IsoOwner, "view", "add") | _perms(
            NestedR6IsoKid, "view", "add"
        )
        assert "kids" in _input_fields(granted, "r6IsoOwnerCreate")

    def test_another_registrys_scope_does_not_gate_a_nested_write(self) -> None:
        """The runtime pk scope reads the parent's OWN registry.

        The reviewer's end-to-end break: importing the other schema's module
        turned every nested update in this schema into a not-found, because the
        row lookup ran the OTHER registry's "filter_queryset".
        """
        owner = NestedR6IsoOwner.objects.create(name="o")
        kid = NestedR6IsoKid.objects.create(owner=owner, headline="old")

        result = _update(
            NestedR6IsoOwnerType,
            {"id": owner.pk, "kids": [{"id": kid.pk, "headline": "new"}]},
        )

        assert result.ok, getattr(result, "errors", None)
        kid.refresh_from_db()
        assert kid.headline == "new"


class TestTheStampResolvesWithTheProjection:
    """The two halves of a host declaration must be read at the same moment.

    Reading them at different times is what let a late host's projection land while its
    label did not: the child's own roots were pruned away and the very same write
    survived inside the parent's payload.
    """

    def test_a_write_host_declared_after_the_parent_still_reaches_the_stamp(
        self,
    ) -> None:
        """Declaration order must not decide whether a label is honoured.

        The parent app importing the child app later is the ordinary order. With
        the stamp frozen eagerly at the parent's class-definition time, the late
        host's "exclude_fields" landed and its "required_perms" did not: a caller
        with the child's own roots pruned away kept the identical write inside
        the parent's payload. This test breaks if the stamp stops resolving in
        the same thunk as the projection.
        """
        granted = _perms(NestedR6LateOwner, "view", "add") | _perms(
            NestedR6LateKid, "view", "add"
        )
        assert "kids" not in _input_fields(granted, "r6LateOwnerCreate")

    def test_the_caller_holding_that_label_keeps_the_field(self) -> None:
        """The union stays satisfiable.

        This test breaks if the lazy stamp is widened into something no caller
        can hold -- a self-inflicted outage rather than a fix.
        """
        granted = (
            _perms(NestedR6LateOwner, "view", "add")
            | _perms(NestedR6LateKid, "view", "add")
            | {_LATE_LABEL}
        )
        assert "kids" in _input_fields(granted, "r6LateOwnerCreate")


class TestALabelIsReadPerOperation:
    """A host has no say over an operation it does not generate.

    The label axis has to follow the allowance axis, or a delete permission declared
    once removes the nested create field from every caller entitled to use it.
    """

    def test_a_delete_only_hosts_label_does_not_gate_a_nested_create(self) -> None:
        """The label axis follows the same rule the allowance axis follows.

        A destructive label declared on a delete-only host says nothing about
        creating a child through its parent. This test breaks if the stamp goes
        back to unioning every declared host regardless of the operation, which
        deletes the nested field for a caller who may legitimately write it.
        """
        granted = _perms(NestedR6OpsOwner, "view", "add") | _perms(
            NestedR6OpsKid, "view", "add"
        )
        assert "kids" in _input_fields(granted, "r6OpsOwnerCreate")


@pytest.mark.django_db()
class TestPersistChildScopeOnTheLinkBranches:
    """The scope check in "_persist_child" is load-bearing on two more paths.

    Every other scope test drives the reverse path, where the row is rejected earlier,
    so deleting this check left the whole suite green while both link branches happily
    rewrote a hidden row.
    """

    def test_a_forward_fk_already_linked_to_a_hidden_row_is_refused(self) -> None:
        """The forward branch reaches "_persist_child" for the CURRENT target.

        A pk equal to the one the parent already holds is not a link, it is a
        write of that row -- and the row is hidden from every host serving the
        child's update. Deleting the scope check in "_persist_child" left the
        whole suite green because every other scope test drives the reverse
        path, where "_attach_children" has already rejected the row.
        """
        hidden = NestedR6PinKid.objects.create(headline="hidden", tenant="b")
        owner = NestedR6PinOwner.objects.create(name="o", fwd=hidden)

        result = _update(
            NestedR6PinOwnerType,
            {"id": owner.pk, "fwd": {"id": hidden.pk, "headline": "PWNED"}},
        )

        assert not result.ok
        hidden.refresh_from_db()
        assert hidden.headline == "hidden"

    def test_an_m2m_row_already_linked_to_the_parent_is_refused(self) -> None:
        """The M2M branch reaches "_persist_child" for an already-linked row.

        A payload naming a row the parent already carries is not a link either;
        it falls through to the writer, which issues an UPDATE on the row the
        scope was hiding.
        """
        hidden = NestedR6PinKid.objects.create(headline="hidden", tenant="b")
        owner = NestedR6PinOwner.objects.create(name="o")
        owner.tags.add(hidden)

        result = _update(
            NestedR6PinOwnerType,
            {"id": owner.pk, "tags": [{"id": hidden.pk, "headline": "PWNED"}]},
        )

        assert not result.ok
        hidden.refresh_from_db()
        assert hidden.headline == "hidden"


class TestTheLateTwinHatchComparesEverything:
    """A late host is a no-op only when it contributes exactly what a peer does.

    Operations and labels are contributions too. Comparing projections alone waves
    through a host that narrows a different operation, or one that adds a permission the
    frozen stamp can never carry.
    """

    def test_a_twin_projection_on_another_operation_is_refused(self) -> None:
        """The same "only_fields" for a DIFFERENT operation is not a repeat.

        The allowance axis is read per operation, so a late update-only host
        allowing the same column contributes to a surface the create-only host
        never touched. This test breaks if the operations drop out of the
        no-op signature: the late host is then waved through and its projection
        is baked out of the nested UPDATE input for the process lifetime.
        """
        nested_child_input(
            NestedR6SigKid, "update", get_global_registry(), NestedR6SigOwner
        )

        with pytest.raises(ImproperlyConfigured) as excinfo:

            class NestedR6SigKidUpdateMutation(DjangoModelMutation):
                """A late host repeating the projection on the other verb."""

                class Meta:
                    """Bind the mutation to "NestedR6SigKid" for "update" only."""

                    model = NestedR6SigKid
                    model_operations = ("update",)
                    only_fields = ("headline",)

        message = str(excinfo.value)
        assert "NestedR6SigKidUpdateMutation" in message
        assert "NestedR6SigOwner" in message

    def test_a_twin_projection_carrying_a_new_label_is_refused(self) -> None:
        """The label is part of what a host contributes, so it is part of the key.

        This test breaks if "required_perms" drops out of the no-op signature: a
        late host repeating an existing projection but adding a project-specific
        label is then accepted, and that label never reaches the nested stamp.
        """
        nested_child_input(
            NestedR6LabelKid, "create", get_global_registry(), NestedR6LabelOwner
        )

        with pytest.raises(ImproperlyConfigured) as excinfo:

            class NestedR6LabelKidMutationB(DjangoModelMutation):
                """A late twin whose only new contribution is a label."""

                required_perms: ClassVar[tuple[str, ...]] = (
                    "tests.publish_nestedr6labelkid",
                )

                class Meta:
                    """Bind the mutation to "NestedR6LabelKid", hiding "secret"."""

                    model = NestedR6LabelKid
                    exclude_fields = ("secret",)

        message = str(excinfo.value)
        assert "NestedR6LabelKidMutationB" in message
        # The nesting parent's name appears only in the late-host refusal, so
        # this cannot pass on a different guard that also names the class.
        assert "NestedR6LabelOwner" in message


@pytest.mark.django_db()
class TestALocalRegistryParentStillReadsTheGlobalHosts:
    """The mirror of the isolation rule: the GLOBAL registry is never skipped.

    Round 6 asserted the opposite, and that was wrong: "Meta.registry" is not an
    option on "DjangoModelType", the only host class that carries
    "permission_classes", so scoping the lookup to the parent's registry alone
    left a "Meta.registry" parent with NO hosts for its children -- projection,
    scope, label and permission gate all gone at once.
    """

    def test_a_global_hosts_projection_reaches_a_local_parents_input(
        self,
    ) -> None:
        """The build side reads the parent's registry AND the global one.

        This test breaks if the host lookup goes back to the parent's registry
        alone: the child's only host disappears and its exclusion with it.
        """
        built = nested_child_input(
            NestedR6LocalKid, "create", _LOCAL_REGISTRY, NestedR6LocalOwner
        )
        assert "secret" not in built._meta.graphql_input_type.fields

    def test_a_global_hosts_scope_gates_a_local_parents_write(self) -> None:
        """The runtime side reads the same union.

        The child's only host hides every row of another tenant, and a parent
        bound to a second registry must not be a way around it.
        """
        owner = NestedR6LocalOwner.objects.create(name="o")
        kid = NestedR6LocalKid.objects.create(owner=owner, headline="old", tenant="b")

        result = NestedR6LocalOwnerMutation.update(
            None,
            _info(),
            **{
                NestedR6LocalOwnerMutation._meta.input_field_name: {
                    "id": owner.pk,
                    "kids": [{"id": kid.pk, "headline": "new"}],
                }
            },
        )

        assert not result.ok
        kid.refresh_from_db()
        assert kid.headline == "old"
