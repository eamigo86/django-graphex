"""S8f RED -> GREEN — ``paginations/{pagination,utils}.py`` are graphene-free at
the top level.

S8f takes the pagination modules off graphene at the MODULE level. The two
TOP-LEVEL graphene imports BLOCK the graphene uninstall (S8i), so they must go::

    # paginations/pagination.py
    from graphene import Boolean, Field, Int, ObjectType, String
    # paginations/utils.py
    import graphene

Construct analysis (consumer-proven; the graphene pagination machinery is built
SEPARATELY from the native pagination container — see #1565 / S-ROOTS-e):

* The NATIVE pagination container is assembled by the native compiler from
  ``NativePaginationField`` + ``to_graphql_fields(native=True)`` +
  ``get_native_page_info_field`` + ``NATIVE_CURSOR_PAGE_INFO``. These have ZERO
  graphene dependency and stay byte-identical.

* The GRAPHENE pagination descriptors are GENUINELY CONSUMED by the
  native-default test contract (a bare ``pytest tests/`` runs ``GDX_BACKEND=
  native`` per ``tests/conftest.py``): ~115 tests across
  ``tests/test_pagination_internals.py``, ``tests/test_pagination_edges.py``,
  ``tests/test_paginations.py`` and ``tests/test_optimizer_phase_c.py`` directly
  reference ``GenericPaginationField`` (graphene ``Field`` subclass),
  ``CursorPageInfo`` (graphene ``ObjectType``) via ``get_page_info_field`` (a
  graphene ``Field``), and the ``to_graphql_fields(native=False)`` graphene-scalar
  else-branches via ``_graphene_paginator_args``. Removing them breaks the
  protected contract.

So S8f is a LAZY-DEFER slice (same strategy as S8e for ``converter.py``): every
graphene construct keeps producing the EXACT same graphene object (test contract
+ SDL byte-parity preserved); only the uninstall-blocking TOP-LEVEL graphene
imports move to a lazy, gated accessor.

Run: GDX_BACKEND=native .venv/bin/python -m pytest \
    tests/native/test_s8f_paginations_graphene_free.py -q -o addopts=""
"""
from __future__ import annotations

import ast
import inspect

import pytest

pytestmark = pytest.mark.native_only


# --------------------------------------------------------------------------- #
# 1. Top-level graphene imports are GONE                                       #
# --------------------------------------------------------------------------- #
def _module_imports(module: object) -> list[ast.stmt]:
    source = inspect.getsource(module)
    tree = ast.parse(source)
    return [
        node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]


def _assert_module_body_graphene_free(module: object, module_name: str) -> None:
    """Assert the module body contains no top-level graphene import."""
    source = inspect.getsource(module)
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in tree.body:  # MODULE-LEVEL statements only
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "graphene" or alias.name.startswith("graphene."):
                    offenders.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and (
                node.module == "graphene" or node.module.startswith("graphene.")
            ):
                offenders.append(f"from {node.module}")
    assert not offenders, (
        f"{module_name} module body must be graphene-free; found: {offenders}"
    )


def test_pagination_module_has_no_top_level_graphene_import() -> None:
    """``paginations/pagination.py`` must not import graphene at the top level."""
    from django_graphex.paginations import pagination

    imports = _module_imports(pagination)

    bare_graphene = [
        node
        for node in imports
        if isinstance(node, ast.Import)
        and any(
            alias.name == "graphene" or alias.name.startswith("graphene.")
            for alias in node.names
        )
    ]
    assert not bare_graphene, (
        "pagination.py must NOT contain a top-level `import graphene` — it "
        "blocks the graphene uninstall (S8i)."
    )

    from_graphene = [
        node
        for node in imports
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and (node.module == "graphene" or node.module.startswith("graphene."))
    ]
    assert not from_graphene, (
        "pagination.py must NOT contain any top-level `from graphene...` import "
        f"— still found: {[n.module for n in from_graphene]}"
    )


def test_utils_module_has_no_top_level_graphene_import() -> None:
    """``paginations/utils.py`` must not import graphene at the top level."""
    from django_graphex.paginations import utils

    imports = _module_imports(utils)

    bare_graphene = [
        node
        for node in imports
        if isinstance(node, ast.Import)
        and any(
            alias.name == "graphene" or alias.name.startswith("graphene.")
            for alias in node.names
        )
    ]
    assert not bare_graphene, (
        "utils.py must NOT contain a top-level `import graphene` — it blocks "
        "the graphene uninstall (S8i)."
    )

    from_graphene = [
        node
        for node in imports
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and (node.module == "graphene" or node.module.startswith("graphene."))
    ]
    assert not from_graphene, (
        "utils.py must NOT contain any top-level `from graphene...` import "
        f"— still found: {[n.module for n in from_graphene]}"
    )


def test_pagination_module_body_is_graphene_token_free() -> None:
    """No top-level graphene import survives at pagination.py module level."""
    from django_graphex.paginations import pagination

    _assert_module_body_graphene_free(pagination, "pagination.py")


def test_utils_module_body_is_graphene_token_free() -> None:
    """No top-level graphene import survives at utils.py module level."""
    from django_graphex.paginations import utils

    _assert_module_body_graphene_free(utils, "utils.py")


# --------------------------------------------------------------------------- #
# 2. The graphene pagination descriptors stay graphene (test contract)         #
# --------------------------------------------------------------------------- #
def test_generic_pagination_field_is_graphene_field_subclass() -> None:
    """``GenericPaginationField`` must still subclass graphene ``Field``.

    The optimizer + pagination-internals tests build it via ``__new__`` and read
    ``paginator_instance`` / ``list_resolver``; the class identity (a graphene
    ``Field`` subclass) is part of the protected native-default test contract.
    """
    import graphene  # graphene is still installed (uninstall is S8i)

    from django_graphex.paginations.utils import GenericPaginationField

    assert issubclass(GenericPaginationField, graphene.Field), (
        "GenericPaginationField must remain a graphene.Field subclass."
    )


def test_cursor_page_info_field_is_graphene_field() -> None:
    """``CursorGraphqlPagination.get_page_info_field`` returns a graphene Field.

    The field wraps the graphene ``CursorPageInfo`` ``ObjectType`` and exposes a
    ``.resolver`` attribute (read by ``tests/test_pagination_edges.py``). The
    lazy-defer must keep this byte-identical.
    """
    import graphene

    from django_graphex.paginations.pagination import (
        CursorGraphqlPagination,
        CursorPageInfo,
    )

    assert issubclass(CursorPageInfo, graphene.ObjectType), (
        "CursorPageInfo must remain a graphene.ObjectType subclass."
    )

    p = CursorGraphqlPagination(ordering="name")
    field = p.get_page_info_field(None)
    assert isinstance(field, graphene.Field)
    # The graphene field exposes a `.resolver` that returns None off a non-base.
    assert field.resolver("not-a-base", None) is None


def test_graphene_paginator_args_are_graphene_scalars() -> None:
    """``to_graphql_fields(native=False)`` still returns graphene scalar instances.

    ``_graphene_paginator_args`` forces the graphene shape so the graphene
    ``GenericPaginationField`` can order them. The lazy-defer must keep the
    graphene scalar identity (``graphene.Int`` / ``graphene.String``).
    """
    import graphene

    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
    from django_graphex.paginations.utils import _graphene_paginator_args

    p = LimitOffsetGraphqlPagination(default_limit=5)
    args = _graphene_paginator_args(p)
    assert isinstance(args["limit"], graphene.Int)
    assert isinstance(args["offset"], graphene.Int)
    assert isinstance(args["ordering"], graphene.String)


# --------------------------------------------------------------------------- #
# 3. The NATIVE pagination machinery is intact + graphql-core-typed            #
# --------------------------------------------------------------------------- #
def test_native_cursor_page_info_is_graphql_core_object_type() -> None:
    """``NATIVE_CURSOR_PAGE_INFO`` must be a graphql-core ``GraphQLObjectType``.

    The native pagination container reads this singleton; it must survive S8f
    byte-identical (name + fields).
    """
    from graphql import GraphQLObjectType

    from django_graphex.paginations.pagination import NATIVE_CURSOR_PAGE_INFO

    assert isinstance(NATIVE_CURSOR_PAGE_INFO, GraphQLObjectType)
    assert NATIVE_CURSOR_PAGE_INFO.name == "CursorPageInfo"
    field_names = set(NATIVE_CURSOR_PAGE_INFO.fields)
    assert field_names == {
        "hasNextPage",
        "hasPreviousPage",
        "startCursor",
        "endCursor",
    }


def test_native_page_info_field_is_graphql_core_field() -> None:
    """``get_native_page_info_field`` returns a graphql-core ``GraphQLField``.

    Its type is the shared ``NATIVE_CURSOR_PAGE_INFO`` and it carries native
    first/cursor ``GraphQLArgument`` instances. The resolver returns ``None`` off
    a non-list root (parity with the graphene path).
    """
    from graphql import GraphQLArgument, GraphQLField

    from django_graphex.paginations.pagination import (
        NATIVE_CURSOR_PAGE_INFO,
        CursorGraphqlPagination,
    )

    p = CursorGraphqlPagination(ordering="name")
    field = p.get_native_page_info_field(None)
    assert isinstance(field, GraphQLField)
    assert field.type is NATIVE_CURSOR_PAGE_INFO
    assert set(field.args) == {"first", "cursor"}
    assert all(isinstance(a, GraphQLArgument) for a in field.args.values())
    # The native resolver returns None for a non-list-base root.
    assert field.resolve("not-a-base", None) is None


def test_native_to_graphql_fields_are_graphql_core_arguments() -> None:
    """``to_graphql_fields(native=True)`` returns graphql-core ``GraphQLArgument``.

    This is the native arg shape the native compiler wires onto the container's
    ``results`` field — it must stay graphql-core-typed and graphene-free.
    """
    from graphql import GraphQLArgument

    from django_graphex.paginations.pagination import (
        CursorGraphqlPagination,
        LimitOffsetGraphqlPagination,
        PageGraphqlPagination,
    )

    for paginator in (
        LimitOffsetGraphqlPagination(default_limit=5),
        PageGraphqlPagination(page_size_query_param="page_size"),
        CursorGraphqlPagination(ordering="id"),
    ):
        native_args = paginator.to_graphql_fields(native=True)
        assert native_args, "native args must be non-empty"
        assert all(
            isinstance(a, GraphQLArgument) for a in native_args.values()
        ), f"{type(paginator).__name__} native args must be GraphQLArgument"


def test_native_pagination_field_has_no_graphene_dependency() -> None:
    """``NativePaginationField`` resolves a page WITHOUT touching graphene.

    It is a plain dataclass; its slicing is delegated to ``_paginate_list_base``.
    """
    from django_graphex.base_types import DjangoListObjectBase
    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
    from django_graphex.paginations.utils import NativePaginationField

    paginator = LimitOffsetGraphqlPagination(default_limit=2, max_limit=10)
    field = NativePaginationField(type=None, paginator=paginator)
    base = DjangoListObjectBase(
        results=list(range(5)), count=5, results_field_name="results"
    )
    resolve = field.wrap_resolve(None)
    assert resolve(base, None) == [0, 1]
    assert resolve.paginator_instance is paginator


# --------------------------------------------------------------------------- #
# 4. Modules import cleanly (lazy graphene does not fire at module load)        #
# --------------------------------------------------------------------------- #
def test_pagination_modules_import_and_expose_public_api() -> None:
    """Both pagination modules import and expose their public surface.

    The graphene imports are now lazy (inside functions / a gated accessor), so a
    bare import of the modules must succeed and the public classes/helpers must be
    present.
    """
    from django_graphex.paginations import pagination, utils

    assert hasattr(pagination, "LimitOffsetGraphqlPagination")
    assert hasattr(pagination, "PageGraphqlPagination")
    assert hasattr(pagination, "CursorGraphqlPagination")
    assert hasattr(pagination, "NATIVE_CURSOR_PAGE_INFO")
    assert hasattr(utils, "NativePaginationField")
    assert hasattr(utils, "GenericPaginationField")
    assert hasattr(utils, "_paginate_list_base")
