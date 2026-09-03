# -*- coding: utf-8 -*-
"""S8g + S-sub-6 (graphene-removal): subscription build path is graphene-free.

S8g removed subscription.py's TOP-LEVEL graphene imports (lazy-defer). S-sub-6
goes further and MIGRATES the subscription BUILD path off graphene entirely —
defining + mounting a "Subscription" subclass no longer fires graphene at all
(S8g only deferred the import; the firing still happened at subclass-def + mount,
pinning graphene for the process lifetime):

  * "_meta.arguments" is now a NATIVE graphql-core "{action, id, filters}"
    dict ("GraphQLArgument" + a graphql-core action "GraphQLEnumType"), NOT
    graphene "Argument(ActionSubscriptionEnum)"/"ID"/"GenericScalar". The
    "_g()" accessor + "_generic_scalar" factory are RETIRED.
  * "SubscriptionField" is now a NATIVE marker class subclassing
    "NativeMountedField" (no graphene "Field" base). The native root compiler
    recovers it off a graphene root via "_collect_dropped_native_fields" and
    detects it by class NAME ("schema_compiler._is_subscription_field").
  * "ActionSubscriptionEnum" (the graphene "Enum") survives ONLY as a lazily
    built public re-export for the graphene-backend-only test contract
    ("test_unit"/"test_isolation"); it is RETIRED in S-del-tests-10. Nothing
    on the native build path references it.

The NATIVE delivery path ("_build_native_field", the serialize-once event type)
stays graphene-free (asserted here + in
"tests/subscriptions/test_subscription_base_native.py").
"""

import ast
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path

import pytest

_SUB_MODULE = "django_graphex.subscriptions.subscription"
sub_mod = import_module(_SUB_MODULE) if find_spec("channels") else None

# Collect the module even in the channels-free base-install environment.
pytestmark = pytest.mark.skipif(sub_mod is None, reason="requires subscriptions extra")

_SUB_PATH = Path(sub_mod.__file__ or "") if sub_mod is not None else Path()


def _toplevel_graphene_imports(path: Path) -> list[str]:
    """Return the source lines of any TOP-LEVEL graphene import in *path*."""
    tree = ast.parse(path.read_text())
    hits: list[str] = []
    for node in tree.body:  # module body only -> top-level statements
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "graphene" or alias.name.startswith("graphene."):
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "graphene" or mod.startswith("graphene."):
                names = ", ".join(a.name for a in node.names)
                hits.append(f"from {mod} import {names}")
    return hits


def test_no_toplevel_graphene_import_in_subscription_module() -> None:
    """Assert that subscription.py has ZERO top-level graphene imports.

    Verified via an AST probe over the module body.
    """
    hits = _toplevel_graphene_imports(_SUB_PATH)
    assert hits == [], (
        "subscriptions/subscription.py still has top-level graphene imports "
        f"(uninstall-blocking): {hits}"
    )


def test_module_import_leaves_own_lazy_graphene_cache_dormant() -> None:
    """A FRESH import of subscription.py leaves the lazy enum cache DORMANT.

    S-sub-6: the only surviving lazy graphene cache is
    "_ACTION_SUBSCRIPTION_ENUM" (kept for the graphene-backend-only public
    re-export contract; deleted in S-del-tests-10). Importing subscription.py must
    not materialize it — it stays "None" until first attribute access. The
    "_GRAPHENE" accessor cache and the "_SUBSCRIPTION_FIELD" cache are GONE
    ("SubscriptionField" is a native module-level class now). Asserted in a clean
    subprocess so an already-warmed cache in this process does not mask a
    load-time materialization.

    NOTE: "graphene" may still appear in "sys.modules" after the import via a
    TRANSITIVE dependency (other modules still import graphene at their own top
    level — out of S-sub-6 scope; retired in the deletion slices). S-sub-6 proves
    subscription.py's OWN build path never materializes the lazy enum.
    """
    import subprocess
    import sys
    import textwrap

    code = textwrap.dedent(
        """
        import django
        from django.conf import settings

        settings.configure(
            INSTALLED_APPS=(
                "django.contrib.contenttypes",
                "django.contrib.auth",
                "channels",
            ),
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": ":memory:",
                }
            },
            CHANNEL_LAYERS={
                "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
            },
        )
        django.setup()

        import django_graphex.subscriptions.subscription as m

        # The retired accessors are GONE from the module surface.
        assert not hasattr(m, "_GRAPHENE"), "_g()/_GRAPHENE must be retired"
        assert not hasattr(m, "_generic_scalar"), "_generic_scalar must be retired"
        assert not hasattr(m, "_SUBSCRIPTION_FIELD"), (
            "SubscriptionField is now a native class; its lazy cache is retired"
        )

        # S-del-backend-11: the lazy graphene ``ActionSubscriptionEnum`` (and its
        # cache + builder + __getattr__ seam) are DELETED with the graphene backend.
        assert not hasattr(m, "_ACTION_SUBSCRIPTION_ENUM")
        assert not hasattr(m, "_build_action_subscription_enum")
        assert not hasattr(m, "ActionSubscriptionEnum")

        # ``SubscriptionField`` is a real native module-level class (no lazy build).
        from django_graphex.core.descriptors import NativeMountedField
        assert isinstance(m.SubscriptionField, type)
        assert issubclass(m.SubscriptionField, NativeMountedField)
        assert m.SubscriptionField.__name__ == "SubscriptionField"
        print("DORMANT_OK")
        """
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "DORMANT_OK" in proc.stdout


def test_action_subscription_enum_is_deleted() -> None:
    """S-del-backend-11: the graphene "ActionSubscriptionEnum" (and its lazy
    builder / cache / module "__getattr__" seam) are DELETED with the graphene
    backend, and dropped from the public "subscriptions" surface.

    The subscription action enum is now the native graphql-core "GraphQLEnumType"
    built into "_meta.arguments['action']" (asserted in
    "test_meta_arguments_built_natively_graphene_free" +
    "tests/subscriptions/test_unit.py").
    """
    import django_graphex.subscriptions as subscriptions

    assert not hasattr(sub_mod, "ActionSubscriptionEnum"), (
        "the graphene ActionSubscriptionEnum must be deleted from subscription.py"
    )
    assert not hasattr(sub_mod, "_build_action_subscription_enum")
    assert not hasattr(sub_mod, "_ACTION_SUBSCRIPTION_ENUM")
    assert not hasattr(subscriptions, "ActionSubscriptionEnum"), (
        "ActionSubscriptionEnum must be dropped from the public subscriptions surface"
    )


def test_subscription_field_is_native_marker_with_mount_name() -> None:
    """S-sub-6: "SubscriptionField" is a NATIVE marker class (no graphene base).

    It now subclasses "NativeMountedField" (graphene-free) so the native schema
    compiler's "_collect_dropped_native_fields" recovers it off a graphene root.
    The class NAME ("SubscriptionField") is still the mount seam the native root
    compiler detects ("schema_compiler._is_subscription_field" gates on
    'type(field).__name__ == "SubscriptionField"').
    """
    from django_graphex.core.descriptors import NativeMountedField

    field_cls = sub_mod.SubscriptionField
    # Assert no graphene class in the MRO (by module name, never importing
    # graphene) — must hold with graphene ABSENT (v2.0).
    graphene_bases = [
        b.__qualname__
        for b in field_cls.__mro__
        if b.__module__.split(".")[0] == "graphene"
    ]
    assert not graphene_bases, (
        f"S-sub-6: SubscriptionField MRO must contain no graphene base; "
        f"found: {graphene_bases}"
    )
    assert issubclass(field_cls, NativeMountedField)
    assert field_cls.__name__ == "SubscriptionField"
    # Public re-export resolves to the same class.
    from django_graphex.subscriptions import SubscriptionField as reexport

    assert reexport is field_cls


def test_meta_arguments_built_natively_graphene_free(db: None) -> None:
    """S-sub-6: "_meta.arguments" is now a NATIVE graphql-core dict (no graphene).

    S8g lazy-deferred the graphene "Argument"/"ID"/"GenericScalar" build;
    S-sub-6 RETIRES it from the subclass-def path. "_meta.arguments" now holds
    graphql-core "GraphQLArgument" values: "action" -> "GraphQLNonNull" of a
    graphql-core action "GraphQLEnumType"; "id" -> "GraphQLID"; "filter"
    -> the generated "<Model>SubscriptionFilterInput" (2.1.0). The native compile
    path never read this dict — it is now a graphene-free presence/keys contract
    built from "_build_native_field_args".

    Args:
        db: The pytest-django fixture enabling database access for this test.
    """
    from django.contrib.auth.models import User
    from graphql import GraphQLID, GraphQLInputObjectType, GraphQLNonNull
    from graphql.type import GraphQLEnumType

    from django_graphex.subscriptions.subscription import Subscription

    class UserSubS8g(Subscription):
        class Meta:
            model = User
            stream = "users-s8g"

    args = UserSubS8g._meta.arguments
    assert set(args) == {"action", "id", "filter"}
    action_type = args["action"].type
    assert isinstance(action_type, GraphQLNonNull)
    assert isinstance(action_type.of_type, GraphQLEnumType)
    assert action_type.of_type.name == "UserSubscriptionAction"
    assert set(action_type.of_type.values) == {
        "CREATE",
        "UPDATE",
        "DELETE",
        "ALL_ACTIONS",
    }
    # id is a graphql-core ID scalar; filter is the generated input object.
    assert args["id"].type is GraphQLID
    filter_type = args["filter"].type
    assert isinstance(filter_type, GraphQLInputObjectType)
    assert filter_type.name == "UserSubscriptionFilterInput"


def test_mount_seam_field_is_named_subscription_field(db: None) -> None:
    """Mounting a Subscription yields a field whose class name is "SubscriptionField".

    This is what "schema_compiler._is_subscription_field" gates on; it must
    survive the lazy-defer so the native root compiler still mounts the field.

    Args:
        db: The pytest-django fixture enabling database access for this test.
    """
    from django.contrib.auth.models import User

    from django_graphex.subscriptions.subscription import Subscription

    class UserSubMount(Subscription):
        class Meta:
            model = User
            stream = "users-mount-s8g"

    # ``.Field()`` registers a post_save/post_delete signal binding on the model;
    # unregister it after so this subscription does not broadcast into other
    # tests creating ``auth.user`` rows (test isolation).
    try:
        mounted = UserSubMount.Field()
        assert type(mounted).__name__ == "SubscriptionField"
        assert isinstance(mounted, sub_mod.SubscriptionField)
    finally:
        UserSubMount.get_binding().unregister()


def test_native_delivery_path_stays_graphene_free(db: None) -> None:
    """Assert that "_build_native_field" builds a DIRECT graphql-core field.

    No graphene is involved.

    The native event type + reduced {action, id, filters} graphql-core args must
    not depend on the lazy graphene constructs (delivery path byte-identical).

    Args:
        db: The pytest-django fixture enabling database access for this test.
    """
    from django.contrib.auth.models import User
    from graphql import GraphQLField

    from django_graphex.subscriptions.subscription import Subscription

    class UserSubNative(Subscription):
        class Meta:
            model = User
            stream = "users-native-s8g"

    field = UserSubNative._build_native_field()
    assert isinstance(field, GraphQLField)
    assert set(field.args) == {"action", "id", "filter"}
