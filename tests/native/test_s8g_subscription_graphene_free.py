# -*- coding: utf-8 -*-
"""S8g (graphene-removal): subscriptions/subscription.py top-level graphene imports GONE.

The uninstall-blocking top-level imports

    from graphene import (ID, Argument, Enum, Field)
    from graphene.types.generic import GenericScalar

must NOT execute at module import time (they would block ``pip uninstall
graphene`` in S8i). The graphene constructs they build are GENUINELY consumed by
the native-default test contract:

  * ``ActionSubscriptionEnum`` (graphene ``Enum``) — iterated in
    ``tests/subscriptions/test_unit.py`` and pinned as
    ``NonNull(ActionSubscriptionEnum)`` on ``_meta.arguments['action']``;
  * ``SubscriptionField`` (graphene ``Field``) — the MOUNT SEAM the native root
    compiler detects by class name (``schema_compiler._is_subscription_field``);
  * ``Argument`` / ``ID`` / ``GenericScalar`` — build ``_meta.arguments``
    (``action``/``id``/``filters``).

So the strategy is LAZY-DEFER (same as S8e/S8f), NOT removal: the class bases
(``ActionSubscriptionEnum``/``SubscriptionField``) are built via a module-level
PEP 562 ``__getattr__`` + cached factory; the ``Argument``/``ID``/``GenericScalar``
calls go through an in-function ``_g()`` accessor. Every graphene construct stays
byte-identical; only the uninstall-blocking top-level import moves.

The NATIVE delivery path (``_build_native_field``, the serialize-once event type)
stays graphene-free and byte-identical (asserted separately in
``tests/subscriptions/test_subscription_base_native.py``).
"""

import ast
from pathlib import Path

import django_graphex.subscriptions.subscription as sub_mod

_SUB_PATH = Path(sub_mod.__file__)


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


def test_no_toplevel_graphene_import_in_subscription_module():
    """subscription.py must have ZERO top-level graphene imports (AST probe)."""
    hits = _toplevel_graphene_imports(_SUB_PATH)
    assert hits == [], (
        "subscriptions/subscription.py still has top-level graphene imports "
        f"(uninstall-blocking): {hits}"
    )


def test_module_import_leaves_own_lazy_graphene_caches_dormant():
    """A FRESH import of subscription.py leaves THIS module's lazy caches DORMANT.

    Importing subscription.py must not materialize this module's OWN graphene
    constructs: the ``_GRAPHENE`` accessor cache and the lazily built class caches
    (``ActionSubscriptionEnum``/``SubscriptionField``) stay ``None`` until first
    access. Asserted in a clean subprocess so an already-warmed cache in this
    process does not mask a load-time materialization.

    NOTE: ``graphene`` may still appear in ``sys.modules`` after the import via a
    TRANSITIVE dependency (``django_graphex.backends`` still imports graphene at
    its own top level — an S8h+ concern, OUT OF S8g scope). S8g only removes
    subscription.py's OWN top-level graphene import and proves its OWN lazy seam
    stays dormant; the transitive pull is asserted-against in a later slice.
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

        # Importing the module must NOT materialize THIS module's lazy graphene
        # caches (the accessor cache + the two lazily built class bases).
        assert m._GRAPHENE is None, m._GRAPHENE
        assert m._ACTION_SUBSCRIPTION_ENUM is None, m._ACTION_SUBSCRIPTION_ENUM
        assert m._SUBSCRIPTION_FIELD is None, m._SUBSCRIPTION_FIELD

        # First access materializes the cache; it then stays stable.
        enum_cls = m.ActionSubscriptionEnum
        assert m._ACTION_SUBSCRIPTION_ENUM is enum_cls
        field_cls = m.SubscriptionField
        assert m._SUBSCRIPTION_FIELD is field_cls
        assert m._GRAPHENE is not None
        print("DORMANT_OK")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert "DORMANT_OK" in proc.stdout


def test_action_subscription_enum_is_lazy_graphene_enum():
    """``ActionSubscriptionEnum`` resolves (lazily) to a graphene ``Enum`` subclass.

    Native-default contract (tests/subscriptions/test_unit.py iterates it and
    pins it on ``_meta.arguments``). Accessing it materializes the cache.
    """
    import graphene

    enum_cls = sub_mod.ActionSubscriptionEnum
    assert issubclass(enum_cls, graphene.Enum)
    assert {e.name: e.value for e in enum_cls} == {
        "CREATE": "create",
        "UPDATE": "update",
        "DELETE": "delete",
        "ALL_ACTIONS": "all_actions",
    }
    # Cache is stable (same class on a second access).
    assert sub_mod.ActionSubscriptionEnum is enum_cls
    # Public re-export resolves to the same class.
    from django_graphex.subscriptions import ActionSubscriptionEnum as reexport

    assert reexport is enum_cls


def test_subscription_field_is_lazy_graphene_field_with_mount_name():
    """``SubscriptionField`` resolves to a graphene ``Field`` subclass; name intact.

    The class NAME (``SubscriptionField``) is the mount seam the native root
    compiler detects (``schema_compiler._is_subscription_field`` gates on
    ``type(field).__name__ == 'SubscriptionField'``).
    """
    import graphene

    field_cls = sub_mod.SubscriptionField
    assert issubclass(field_cls, graphene.Field)
    assert field_cls.__name__ == "SubscriptionField"
    # Cache is stable.
    assert sub_mod.SubscriptionField is field_cls
    # Public re-export resolves to the same class.
    from django_graphex.subscriptions import SubscriptionField as reexport

    assert reexport is field_cls


def test_meta_arguments_built_via_lazy_graphene(db):
    """``_meta.arguments`` keep the graphene Argument shape (native-default contract).

    ``action`` -> ``NonNull(ActionSubscriptionEnum)``; ``id`` -> graphene ``ID``;
    ``filters`` -> graphene ``GenericScalar``. Built through the lazy graphene
    accessor, byte-identical to the eager build.
    """
    from django.contrib.auth.models import User
    from graphene import NonNull
    from graphene.types.generic import GenericScalar

    from django_graphex.subscriptions.subscription import Subscription

    class UserSubS8g(Subscription):
        class Meta:
            model = User
            stream = "users-s8g"

    args = UserSubS8g._meta.arguments
    assert set(args) == {"action", "id", "filters"}
    action_type = args["action"].type
    assert isinstance(action_type, NonNull)
    assert action_type.of_type is sub_mod.ActionSubscriptionEnum
    # id is graphene ID scalar; filters is graphene GenericScalar.
    from graphene import ID as GrapheneID

    assert args["id"].type is GrapheneID
    assert args["filters"].type is GenericScalar


def test_mount_seam_field_is_named_subscription_field(db):
    """Mounting a Subscription yields a field whose class name is ``SubscriptionField``.

    This is what ``schema_compiler._is_subscription_field`` gates on; it must
    survive the lazy-defer so the native root compiler still mounts the field.
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


def test_native_delivery_path_stays_graphene_free(db):
    """``_build_native_field`` builds a DIRECT graphql-core field (no graphene).

    The native event type + reduced {action, id, filters} graphql-core args must
    not depend on the lazy graphene constructs (delivery path byte-identical).
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
    assert set(field.args) == {"action", "id", "filters"}
