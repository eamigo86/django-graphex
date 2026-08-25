"""Round-5 hardening of the nested-write gate.

A fourth adversarial pass showed the previous rounds swung the same seam twice
and left five more open:

* the nested input stamp treated a child host's "required_perms" as a
  REPLACEMENT for the composite default -- first honouring it (so a READ host's
  view label collapsed the nested WRITE stamp), then ignoring it entirely (so a
  WRITE host's stricter label never reached the nested surface). It is a UNION:
  an override may only ever ADD a requirement,
* "exclude_fields" was filtered by the declaring host's "model_operations", so a
  prohibition was dropped from every operation that host does not serve,
* the nested pk scope check ran "get_queryset" for hosts that serve no write at
  all, refusing a nested update the child's own update accepts,
* the materialization record that refuses a late host was a process-global while
  the memo it shadows is per-registry, so a second registry's host was refused
  for a surface that registry never froze,
* a scope-hidden row that happens to have an owner was answered by the
  reverse-ownership guard -- disclosing that it exists -- instead of not-found,
* six of the seven "supported_kwargs" forwards had no test at all.
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
from django_graphex.permissions import BasePermission, DjangoModelPermissions
from django_graphex.registry import Registry, get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from tests.models import (
    NestedR5ExcKid,
    NestedR5ExcOwner,
    NestedR5HideKid,
    NestedR5HideOwner,
    NestedR5LateLabelKid,
    NestedR5LateLabelOwner,
    NestedR5LateOnlyKid,
    NestedR5LateOnlyOwner,
    NestedR5PolicyKid,
    NestedR5PolicyOwner,
    NestedR5RegKid,
    NestedR5RegOwner,
    NestedR5ScopeKid,
    NestedR5ScopeOwner,
    NestedR5StampKid,
    NestedR5StampOwner,
    NestedR5TwinKid,
    NestedR5TwinOwner,
)

#: The project-specific label the child's own write host declares. It is NOT a
#: verb the composite table ever produces, so its presence in the nested stamp
#: can only come from the host override.
_PUBLISH = "tests.publish_nestedr5stampkid"


# --------------------------------------------------------------------------- #
# The stamp UNIONS the host overrides onto the composite default.             #
# --------------------------------------------------------------------------- #
class NestedR5StampKidMutation(DjangoModelMutation):
    """The child's own write host, labelled with a project-specific verb.

    The label is not a verb the composite table ever produces, so finding it on the
    nested stamp can only mean the host override was read.
    """

    required_perms: ClassVar[tuple[str, ...]] = (_PUBLISH,)

    class Meta:
        """Bind the mutation to "NestedR5StampKid" for both write verbs.

        Serving create and update means both of this host's roots carry the label, so a
        caller missing it loses the front door and must lose the nested one too.
        """

        model = NestedR5StampKid
        model_operations = ("create", "update")


class NestedR5StampOwnerType(DjangoModelType):
    """The parent nesting the strictly-labelled child.

    Gated by model permissions so a caller can be handed the parent's grants exactly and
    still be measured on the child's label alone.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)

    class Meta:
        """Bind the type to "NestedR5StampOwner" with "kids" nested.

        "kids" is the entire surface under test: the pruner is asked about it three
        times below, with three different permission sets.
        """

        model = NestedR5StampOwner
        nested_fields = {"kids": NestedR5StampKid}


class _Query(ObjectType):
    """Root exposing the parent's read field."""

    r5_stamp_owner_retrieve = NestedR5StampOwnerType.RetrieveField()


class _Mutation(ObjectType):
    """Root exposing the parent whose input the pruner is asked about."""

    r5_stamp_owner_create = NestedR5StampOwnerType.CreateField()


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


class TestNestedStampUnionsHostOverrides:
    """An override may ADD a requirement to the nested field, never remove one.

    Three cases because this seam has already been swung twice: honouring the override
    alone widened the nested surface, ignoring it narrowed nothing, and only the union
    is both safe and satisfiable.
    """

    def test_a_write_hosts_stricter_label_reaches_the_nested_field(self) -> None:
        """The child's declared label must gate the parent's nested surface too.

        A caller holding every composite write verb, but not the label the
        project declared on the child's own write host, has both of that host's
        roots pruned away. This test breaks if the stamp stops consulting the
        hosts: the nested payload then writes child rows the child's own roots
        refuse -- front door pruned, back door open.
        """
        granted = _perms(NestedR5StampOwner, "view", "add") | _perms(
            NestedR5StampKid, "view", "add"
        )
        assert "kids" not in _input_fields(granted, "r5StampOwnerCreate")

    def test_the_composite_default_is_not_replaced_by_the_override(self) -> None:
        """The override is a union term, not a substitute.

        A caller holding the declared label but none of the child's composite
        write verbs must still lose the field. This test breaks if the host
        override REPLACES the default, which is how a read host's view label
        once collapsed the nested write stamp.
        """
        granted = _perms(NestedR5StampOwner, "view", "add") | {_PUBLISH}
        assert "kids" not in _input_fields(granted, "r5StampOwnerCreate")

    def test_a_caller_holding_both_halves_keeps_the_field(self) -> None:
        """The union stays satisfiable.

        This test breaks if the stamp is widened into something no caller can
        hold -- a self-inflicted outage rather than a fix.
        """
        granted = (
            _perms(NestedR5StampOwner, "view", "add")
            | _perms(NestedR5StampKid, "view", "add")
            | {_PUBLISH}
        )
        assert "kids" in _input_fields(granted, "r5StampOwnerCreate")


# --------------------------------------------------------------------------- #
# An allowance is operation-scoped; a prohibition is not.                     #
# --------------------------------------------------------------------------- #
class NestedR5ExcKidCreateMutation(DjangoModelMutation):
    """A create-only host declaring a column is never client-writable.

    It is the project's ONLY write mutation for this model, so a nested update accepting
    "role" writes a column no other surface would.
    """

    class Meta:
        """Bind the mutation to "NestedR5ExcKid" for "create" only.

        The narrow "model_operations" is the trap: filtering the exclusion by it drops
        the prohibition from every other operation's nested surface.
        """

        model = NestedR5ExcKid
        model_operations = ("create",)
        exclude_fields = ("role",)


class NestedR5ExcKidType(DjangoModelType):
    """An ordinary read host for the same child, declaring no projection.

    It supplies the update side of the merge, forbidding nothing, so anything missing
    from the nested update surface must have come from its create-only sibling.
    """

    class Meta:
        """Bind the type to "NestedR5ExcKid".

        No projection at all, so this host is a neutral contributor and can never be
        mistaken for the source of the prohibition.
        """

        model = NestedR5ExcKid


class NestedR5ExcOwnerType(DjangoModelType):
    """The parent nesting the partly-excluded child.

    Only its nested entry matters here; the assertions read the built child input
    directly instead of going through a schema.
    """

    class Meta:
        """Bind the type to "NestedR5ExcOwner" with "kids" nested.

        The nested child input is keyed by the nesting parent, so this declaration is
        what the test's direct build call scopes to.
        """

        model = NestedR5ExcOwner
        nested_fields = {"kids": NestedR5ExcKid}


class TestExclusionsAreNotOperationScoped:
    """An "exclude_fields" entry is a prohibition, not a per-operation opinion.

    Both halves are asserted: the column has to go, and nothing else may go with it. A
    fix that stripped the whole nested update input would satisfy the first on its own.
    """

    def test_a_create_hosts_exclusion_also_hides_the_column_on_update(self) -> None:
        """The nested UPDATE surface must honour every declared exclusion.

        Filtering "exclude_fields" by the declaring host's "model_operations"
        drops it from the nested surface of every other operation, so a client
        writes -- on an EXISTING row, through the parent -- a column the
        project's only write mutation for that model refuses.
        """
        built = nested_child_input(
            NestedR5ExcKid, "update", get_global_registry(), NestedR5ExcOwner
        )
        assert "role" not in built._meta.graphql_input_type.fields

    def test_the_rest_of_the_update_surface_survives(self) -> None:
        """Only the excluded column goes.

        This test breaks if the exclusion merge is widened into something that
        strips the whole nested update input.
        """
        built = nested_child_input(
            NestedR5ExcKid, "update", get_global_registry(), NestedR5ExcOwner
        )
        assert "headline" in built._meta.graphql_input_type.fields


# --------------------------------------------------------------------------- #
# The nested pk scope comes from the hosts that serve the WRITE.              #
# --------------------------------------------------------------------------- #
class NestedR5ScopeKidCreateMutation(DjangoModelMutation):
    """A create-only host whose scope hides every existing row.

    A create host has no rows to scope, so this is harmless -- right up until a nested
    UPDATE consults it and refuses a row the child's own update accepts.
    """

    class Meta:
        """Bind the mutation to "NestedR5ScopeKid" for "create" only.

        The declaration that should keep this host's scope out of the nested update path
        entirely.
        """

        model = NestedR5ScopeKid
        model_operations = ("create",)

    @classmethod
    def filter_queryset(cls, qs: Any, info: Any, **kwargs: Any) -> Any:
        """Hide every row from this host's own (create-only) surface.

        Args:
            qs: The queryset to scope.
            info: GraphQL resolve info for the current request.
            **kwargs: Extra arguments the caller forwarded.

        Returns:
            An empty queryset.
        """
        return qs.none()


class NestedR5ScopeKidUpdateMutation(DjangoModelMutation):
    """The host that actually serves "update", scoping nothing.

    Splitting a child into a create host and an update host is the library's own
    documented idiom, which is what makes an over-broad scope collateral damage on
    projects that were never exposed.
    """

    class Meta:
        """Bind the mutation to "NestedR5ScopeKid" for "update" only.

        No scoping hook of its own, so a nested update through this host is expected to
        see every row.
        """

        model = NestedR5ScopeKid
        model_operations = ("update",)


class NestedR5ScopeOwnerType(DjangoModelType):
    """The parent nesting the split-surface child.

    Its nested update payload is the exact call that used to land on the create host's
    empty queryset.
    """

    class Meta:
        """Bind the type to "NestedR5ScopeOwner" with "kids" nested.

        Serves every operation, so the nested update surface exists and can be exercised
        end to end rather than inspected.
        """

        model = NestedR5ScopeOwner
        nested_fields = {"kids": NestedR5ScopeKid}


# --------------------------------------------------------------------------- #
# A scope-hidden row is not disclosed by the reverse-ownership guard.         #
# --------------------------------------------------------------------------- #
class NestedR5HideKidType(DjangoModelType):
    """A tenant-scoped host: rows of any other tenant are invisible.

    Scoping through "Meta.queryset" keeps the fixture declarative, and the rows it hides
    are the ones the ownership guard used to disclose.
    """

    class Meta:
        """Bind the type to "NestedR5HideKid", scoped to one tenant.

        The queryset narrowing is the only thing hiding the row: this child declares no
        permission code at all, so nothing else can produce a denial.
        """

        model = NestedR5HideKid
        queryset = NestedR5HideKid.objects.filter(tenant="a")


class NestedR5HideOwnerType(DjangoModelType):
    """The parent nesting the tenant-scoped child.

    The tests create two parent rows so a hidden child can belong to the OTHER one --
    the case where the ownership guard answers first and says too much.
    """

    class Meta:
        """Bind the type to "NestedR5HideOwner" with "kids" nested.

        The nested entry through which a foreign primary key reaches the child's scope
        check.
        """

        model = NestedR5HideOwner
        nested_fields = {"kids": NestedR5HideKid}


def _info() -> SimpleNamespace:
    """Build a bare GraphQL resolve-info stand-in for direct resolver calls.

    Returns:
        An object shaped like a GraphQL resolve info, with a "context"
        carrying empty "META" and "FILES".
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


@pytest.mark.django_db()
class TestNestedScopeUsesTheWritingHosts:
    """A host that serves no write has no say over a nested update's scope.

    Over-scoping is an availability bug rather than a security one: it refuses a write
    the child's own update accepts, on a project that was never vulnerable.
    """

    def test_a_create_only_hosts_scope_does_not_gate_a_nested_update(self) -> None:
        """Only the hosts serving the operation may hide the row.

        A child split into a create host and an update host is the library's own
        idiom. Applying the create host's scope to a nested UPDATE refuses a row
        the child's OWN update accepts -- collateral damage on a project that
        was never vulnerable.
        """
        owner = NestedR5ScopeOwner.objects.create(name="o")
        kid = NestedR5ScopeKid.objects.create(owner=owner, headline="old")

        result = _update(
            NestedR5ScopeOwnerType,
            {"id": owner.pk, "kids": [{"id": kid.pk, "headline": "new"}]},
        )

        assert result.ok, getattr(result, "errors", None)
        kid.refresh_from_db()
        assert kid.headline == "new"


@pytest.mark.django_db()
class TestHiddenRowIsNotDisclosed:
    """Two scope-hidden rows must produce the SAME error shape.

    The difference IS the disclosure: one shape confirms the row exists and names the
    parent it belongs to, the other does not. The ownerless control is what makes the
    pair meaningful.
    """

    def test_a_hidden_row_owned_elsewhere_answers_not_found(self) -> None:
        """The scope decision must come before the ownership guard.

        The ownership guard resolves the pk against the bare model, so a row the
        child's scope hides answers "does not belong to this <Parent>" --
        confirming the row exists -- while an ownerless hidden row answers
        not-found. This test breaks if the two are reordered again.
        """
        mine = NestedR5HideOwner.objects.create(name="mine")
        theirs = NestedR5HideOwner.objects.create(name="theirs")
        hidden = NestedR5HideKid.objects.create(
            owner=theirs, headline="hidden", tenant="b"
        )

        result = _update(
            NestedR5HideOwnerType,
            {"id": mine.pk, "kids": [{"id": hidden.pk, "headline": "PWNED"}]},
        )

        assert not result.ok
        messages = [message for error in result.errors for message in error.messages]
        assert messages == [f"NestedR5HideKid with id {hidden.pk} does not exist."]
        hidden.refresh_from_db()
        assert hidden.headline == "hidden"

    def test_an_ownerless_hidden_row_answers_the_same_way(self) -> None:
        """The control: the shape both hidden rows must share.

        This test breaks if the not-found answer itself regresses.
        """
        mine = NestedR5HideOwner.objects.create(name="mine")
        hidden = NestedR5HideKid.objects.create(headline="hidden", tenant="b")

        result = _update(
            NestedR5HideOwnerType,
            {"id": mine.pk, "kids": [{"id": hidden.pk, "headline": "PWNED"}]},
        )

        assert not result.ok
        messages = [message for error in result.errors for message in error.messages]
        assert messages == [f"NestedR5HideKid with id {hidden.pk} does not exist."]
        hidden.refresh_from_db()
        assert hidden.headline == "hidden"


# --------------------------------------------------------------------------- #
# The materialization record dies with the registry that made it.             #
# --------------------------------------------------------------------------- #
class NestedR5TwinKidTypeA(DjangoModelType):
    """The early host whose projection the late twin repeats verbatim.

    It materializes the nested surface first, which is what makes the twin declared
    later a genuine no-op rather than a lost narrowing.
    """

    class Meta:
        """Bind the type to "NestedR5TwinKid", hiding "secret".

        The exclusion the late twin repeats; excludes are unioned, so repeating one
        cannot move the built surface by even a field.
        """

        model = NestedR5TwinKid
        exclude_fields = ("secret",)


class NestedR5TwinOwnerType(DjangoModelType):
    """The parent nesting the duplicate-projection child.

    Building through this parent is what freezes the child's nested input and arms the
    late-host guard the tests then poke.
    """

    class Meta:
        """Bind the type to "NestedR5TwinOwner" with "kids" nested.

        The materialization record is keyed by this nesting parent together with the
        child model and the registry, which is the whole point of the group.
        """

        model = NestedR5TwinOwner
        nested_fields = {"kids": NestedR5TwinKid}


class TestLateHostIsRefusedPerRegistry:
    """The guard fires for the registry that froze the surface, and no other.

    The record was a process global while the memo it shadows is per registry, so a
    second schema's host was refused for a surface that schema never built -- and the
    axes that genuinely DO narrow had no coverage at all.
    """

    def test_a_second_registrys_host_is_accepted_and_stays_there(self) -> None:
        """A registry whose memo is empty has frozen nothing -- and owns nothing.

        "Meta.registry" is the documented multi-schema option, so the
        declaration must be accepted: the second registry would happily build a
        fresh nested input honouring this host. Accepting it is only half the
        contract, though. The host list is per registry too, so the FIRST
        registry's nested input must not lose a column to a host that belongs to
        another schema entirely. This test breaks if either half regresses.
        """
        first = get_global_registry()
        built = nested_child_input(NestedR5RegKid, "create", first, NestedR5RegOwner)
        assert "secret" in built._meta.graphql_input_type.fields

        class NestedR5RegKidMutation(DjangoModelMutation):
            """A host bound to a registry that has materialized nothing."""

            class Meta:
                """Bind the mutation to "NestedR5RegKid" on a fresh registry."""

                model = NestedR5RegKid
                registry = Registry()
                exclude_fields = ("secret",)

        assert NestedR5RegKidMutation._meta.exclude_fields == ("secret",)
        rebuilt = nested_child_input(NestedR5RegKid, "update", first, NestedR5RegOwner)
        assert "secret" in rebuilt._meta.graphql_input_type.fields

    def test_a_late_twin_of_an_existing_host_is_accepted(self) -> None:
        """Refusing a no-op declaration buys nothing.

        The merge unions excludes, intersects "only_fields" and unions labels --
        all idempotent -- so a late host repeating a projection already
        contributing cannot change the built surface.
        """
        nested_child_input(
            NestedR5TwinKid, "create", get_global_registry(), NestedR5TwinOwner
        )

        class NestedR5TwinKidMutationB(DjangoModelMutation):
            """A host repeating the early host's projection exactly."""

            class Meta:
                """Bind the mutation to "NestedR5TwinKid", hiding "secret"."""

                model = NestedR5TwinKid
                exclude_fields = ("secret",)

        assert NestedR5TwinKidMutationB._meta.exclude_fields == ("secret",)

    def test_a_late_required_perms_override_is_refused(self) -> None:
        """ "required_perms" reaches the nested stamp, so a late one is fatal.

        The stamp unions every declared host's override, and graphql-core has
        already cached the parent input's field map -- so this label can never
        reach the nested surface. This test breaks if the clause is dropped from
        "_narrows_nested_input", which no test previously covered.
        """
        nested_child_input(
            NestedR5LateLabelKid,
            "create",
            get_global_registry(),
            NestedR5LateLabelOwner,
        )

        with pytest.raises(ImproperlyConfigured) as excinfo:

            class NestedR5LateLabelKidType(DjangoModelType):
                """A host arriving with nothing but a label, too late to matter."""

                required_perms: ClassVar[tuple[str, ...]] = (
                    "tests.publish_nestedr5latelabelkid",
                )

                class Meta:
                    """Bind the type to "NestedR5LateLabelKid"."""

                    model = NestedR5LateLabelKid

        message = str(excinfo.value)
        assert "NestedR5LateLabelKidType" in message
        assert "NestedR5LateLabelOwner" in message

    def test_a_late_only_fields_projection_is_refused(self) -> None:
        """The other narrowing axis, which also had no test.

        This test breaks if "_narrows_nested_input" stops treating
        "only_fields" as narrowing: the late host is then silently ignored and
        the WIDER surface stays baked in for the process lifetime.
        """
        nested_child_input(
            NestedR5LateOnlyKid,
            "create",
            get_global_registry(),
            NestedR5LateOnlyOwner,
        )

        with pytest.raises(ImproperlyConfigured) as excinfo:

            class NestedR5LateOnlyKidType(DjangoModelType):
                """A host arriving with nothing but "only_fields"."""

                class Meta:
                    """Bind the type to "NestedR5LateOnlyKid"."""

                    model = NestedR5LateOnlyKid
                    only_fields = ("headline",)

        message = str(excinfo.value)
        assert "NestedR5LateOnlyKidType" in message
        assert "NestedR5LateOnlyOwner" in message


# --------------------------------------------------------------------------- #
# Every "supported_kwargs" forward, not just the one the lot happened to hit. #
# --------------------------------------------------------------------------- #
class _ClosedHasPermission(BasePermission):
    """A policy overriding the DOCUMENTED primary hook with a closed signature.

    It GRANTS every action, so any failure at a forward is a crash, not a
    denial.
    """

    def has_permission(
        self, info: Any, action: str, model: Any, data: Any = None
    ) -> bool:
        """Allow every action.

        Args:
            info: GraphQL resolve info for the current request.
            action: The CRUD action being checked.
            model: The Django model the action targets.
            data: The payload under validation.

        Returns:
            Always True.
        """
        return True


class _ClosedModelPermissions(DjangoModelPermissions):
    """A "DjangoModelPermissions" subclass with a closed "has_permission"."""

    def has_permission(
        self, info: Any, action: str, model: Any, data: Any = None
    ) -> bool:
        """Allow every action.

        Args:
            info: GraphQL resolve info for the current request.
            action: The CRUD action being checked.
            model: The Django model the action targets.
            data: The payload under validation.

        Returns:
            Always True.
        """
        return True


def _authenticated_info() -> SimpleNamespace:
    """Build a resolve-info stand-in carrying an authenticated user.

    Returns:
        An object shaped like a GraphQL resolve info whose "context.user" is
        authenticated and holds nothing.
    """
    user = SimpleNamespace(
        is_authenticated=True,
        is_active=True,
        is_staff=False,
        is_superuser=False,
        has_perms=lambda perms: False,
    )
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}, user=user))


class TestEverySupportedKwargsForward:
    """Each per-action forward must narrow the extras to what lands on it.

    Only the create forward was pinned, so reverting any of the other six left the suite
    green while an override the guides document raised an uncaught "TypeError" for that
    action.
    """

    @pytest.mark.parametrize(
        "action", ["create", "update", "delete", "retrieve", "list", "subscribe"]
    )
    def test_a_closed_has_permission_survives_every_forward(self, action: str) -> None:
        """A policy without "**kwargs" must not turn a grant into a crash.

        Only the "create" forward was pinned, so reverting any of the other five
        left the whole suite green while an override the guides document raised
        an uncaught "TypeError" -- an HTTP 500 -- for that action.

        Args:
            action: The CRUD action whose forward is under test.
        """
        hook = getattr(_ClosedHasPermission(), f"has_{action}_permission")

        assert hook(
            _info(), NestedR5PolicyKid, data={"headline": "h"}, nested_parent=object()
        )

    def test_the_model_permissions_subscribe_fallback_narrows_too(self) -> None:
        """ "DjangoModelPermissions" has a second, separate forward.

        Its "has_subscribe_permission" falls back to "has_permission" when no
        subscription action-value was forwarded, and that call site carries the
        extras. This test breaks if that fallback stops narrowing them.
        """
        assert _ClosedModelPermissions().has_subscribe_permission(
            _authenticated_info(),
            NestedR5PolicyKid,
            data={"headline": "h"},
            nested_parent=object(),
        )


class NestedR5PolicyKidType(DjangoModelType):
    """The child whose policy cannot absorb an unknown keyword.

    The policy grants everything, so the nested update below can only fail one way: by
    crashing at the forward.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (_ClosedHasPermission,)

    class Meta:
        """Bind the type to "NestedR5PolicyKid".

        The policy above needs no projection or operation narrowing to do its job, so
        the binding stands alone.
        """

        model = NestedR5PolicyKid


class NestedR5PolicyOwnerType(DjangoModelType):
    """The parent driving the closed-"has_permission" child.

    Ungated itself, so the only permission code a nested write runs is the child's.
    """

    class Meta:
        """Bind the type to "NestedR5PolicyOwner" with "kids" nested.

        Serves update as well as create, which is the forward this whole fixture exists
        to cross.
        """

        model = NestedR5PolicyOwner
        nested_fields = {"kids": NestedR5PolicyKid}


@pytest.mark.django_db()
class TestNestedUpdateCrossesTheUpdateForward:
    """The seam the lot's own "nested_parent" extra actually crosses.

    Every earlier test of this contract drove a nested CREATE, so the update forward
    carried the new extra with nothing pinning it -- and a nested update is the one path
    that takes it.
    """

    def test_a_nested_update_still_grants_through_a_closed_policy(self) -> None:
        """The nested UPDATE lands on "has_update_permission", not "create".

        Every previous test of this contract went through a nested CREATE, so
        the update forward carried the new extra with nothing pinning it.
        """
        owner = NestedR5PolicyOwner.objects.create(name="o")
        kid = NestedR5PolicyKid.objects.create(owner=owner, headline="old")

        result = _update(
            NestedR5PolicyOwnerType,
            {"id": owner.pk, "kids": [{"id": kid.pk, "headline": "new"}]},
        )

        assert result.ok, getattr(result, "errors", None)
        kid.refresh_from_db()
        assert kid.headline == "new"
