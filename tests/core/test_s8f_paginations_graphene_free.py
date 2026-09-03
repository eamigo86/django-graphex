"""S8f RED -> GREEN — "paginations/{pagination,utils}.py" are graphene-free at
the top level.

S8f takes the pagination modules off graphene at the MODULE level. The two
TOP-LEVEL graphene imports BLOCK the graphene uninstall (S8i), so they must go:
"paginations/pagination.py" pulled the graphene
"Boolean"/"Field"/"Int"/"ObjectType"/"String" names and
"paginations/utils.py" did a bare "graphene" import.

Construct analysis (consumer-proven; the graphene pagination machinery is built
SEPARATELY from the native pagination container — see #1565 / S-ROOTS-e):

* The NATIVE pagination container is assembled by the native compiler from
  "NativePaginationField" + "to_graphql_fields(native=True)" +
  "get_native_page_info_field" + "NATIVE_CURSOR_PAGE_INFO". These have ZERO
  graphene dependency and stay byte-identical.

* The GRAPHENE pagination descriptors "GenericPaginationField" (graphene
  "Field" subclass) + "CursorPageInfo" (graphene "ObjectType") are still
  built lazily and referenced by graphene-backend-only tests
  ("tests/test_pagination_internals.py", "tests/test_optimizer_phase_c.py",
  "tests/test_pagination_edges.py") that construct them via "__new__" to
  exercise "list_resolver"/"wrap_resolve". They are RETIRED in
  S-del-backend-11.

So S8f is a LAZY-DEFER slice (same strategy as S8e for "converter.py"): the
uninstall-blocking TOP-LEVEL graphene imports move to a lazy, gated accessor.

S-page-7 UPDATE: the pagination CONTAINER BUILD path was then migrated off
graphene entirely (the dead graphene branch in "types.py" that allocated the
graphene container via "get_pagination_field"/"get_page_info_field" is
removed, and "to_graphql_fields" is native-only). "_graphene_paginator_args"
was RETIRED. See "tests/core/test_pagination_native_only.py". The graphene
"GenericPaginationField"/"CursorPageInfo" factories survive as dead-but-defined
for the "__new__"-based graphene-backend tests only; they never fire on a build.

Run: .venv/bin/python -m pytest \
    tests/core/test_s8f_paginations_graphene_free.py -q --no-cov
"""

from __future__ import annotations

import ast
import inspect


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
    """Ships broken if "paginations/pagination.py" reintroduces a top-level
    graphene import, blocking the graphene uninstall (S8i).
    """
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
    """Ships broken if "paginations/utils.py" reintroduces a top-level
    graphene import, blocking the graphene uninstall (S8i).
    """
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
    """Ships broken if a top-level graphene import reappears at pagination.py
    module level.
    """
    from django_graphex.paginations import pagination

    _assert_module_body_graphene_free(pagination, "pagination.py")


def test_utils_module_body_is_graphene_token_free() -> None:
    """No top-level graphene import survives at utils.py module level.

    Ships broken if a top-level graphene import reappears at "utils.py"
    module level, re-blocking the graphene uninstall (S8i).
    """
    from django_graphex.paginations import utils

    _assert_module_body_graphene_free(utils, "utils.py")


# --------------------------------------------------------------------------- #
# 2. The graphene pagination descriptors are DELETED (S-del-backend-11)        #
# --------------------------------------------------------------------------- #
def test_generic_pagination_field_is_deleted() -> None:
    """S-del-backend-11: the graphene "GenericPaginationField" factory + class
    are deleted with the graphene backend. The backend-neutral slicing logic now
    lives on the native "NativePaginationField" (tested in
    "test_pagination_internals.py" / "test_optimizer_phase_c.py").
    """
    from django_graphex.paginations import utils

    assert not hasattr(utils, "GenericPaginationField"), (
        "GenericPaginationField (graphene Field subclass) must be deleted."
    )
    assert not hasattr(utils, "_build_generic_pagination_field")
    assert not hasattr(utils, "_g")
    # The native replacement is present.
    assert hasattr(utils, "NativePaginationField")


def test_cursor_page_info_graphene_descriptors_are_deleted() -> None:
    """S-del-backend-11: the graphene "CursorPageInfo" "ObjectType" + the
    graphene-bodied "CursorGraphqlPagination.get_page_info_field" are deleted.

    The native cursor pageInfo is the graphql-core "NATIVE_CURSOR_PAGE_INFO" +
    "get_native_page_info_field" (tested below + in "test_pagination_edges.py").
    """
    from django_graphex.paginations import pagination as ppag
    from django_graphex.paginations.pagination import CursorGraphqlPagination

    assert not hasattr(ppag, "CursorPageInfo"), (
        "the graphene CursorPageInfo ObjectType must be deleted."
    )
    assert not hasattr(ppag, "_build_cursor_page_info")
    assert not hasattr(ppag, "_g")

    # The base get_page_info_field is graphene-free (returns None); the Cursor
    # graphene override is gone — the native pageInfo is get_native_page_info_field.
    p = CursorGraphqlPagination(ordering="name")
    assert p.get_page_info_field(None) is None
    native_field = p.get_native_page_info_field(None)
    assert native_field.resolve("not-a-base", None) is None


def test_graphene_paginator_args_helper_is_retired() -> None:
    """S-page-7: "_graphene_paginator_args" is RETIRED.

    S8f kept "_graphene_paginator_args" (forcing "to_graphql_fields(native=
    False)" graphene scalars) so the graphene "GenericPaginationField" could
    order its args. S-page-7 migrated the pagination CONTAINER build off graphene
    entirely (the dead graphene branch in "types.py" is removed), so the
    graphene-shape arg helper has no consumer and is gone. "to_graphql_fields"
    is now native-only (asserted in "test_pagination_native_only.py").
    """
    from django_graphex.paginations import utils

    assert not hasattr(utils, "_graphene_paginator_args"), (
        "_graphene_paginator_args must be retired in S-page-7 (no consumer "
        "after the dead graphene container branch was removed)."
    )


# --------------------------------------------------------------------------- #
# 3. The NATIVE pagination machinery is intact + graphql-core-typed            #
# --------------------------------------------------------------------------- #
def test_native_cursor_page_info_is_graphql_core_object_type() -> None:
    """Assert that "NATIVE_CURSOR_PAGE_INFO" is a graphql-core "GraphQLObjectType".

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
    """Assert that "get_native_page_info_field" returns a graphql-core "GraphQLField".

    Its type is the shared "NATIVE_CURSOR_PAGE_INFO" and it carries native
    first/cursor "GraphQLArgument" instances. The resolver returns "None" off
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
    """Assert that "to_graphql_fields(native=True)" returns graphql-core args.

    The values are "GraphQLArgument" instances — this is the native arg shape
    the native compiler wires onto the container's "results" field. It must
    stay graphql-core-typed and graphene-free.
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
        assert all(isinstance(a, GraphQLArgument) for a in native_args.values()), (
            f"{type(paginator).__name__} native args must be GraphQLArgument"
        )


def test_native_pagination_field_has_no_graphene_dependency() -> None:
    """Assert that "NativePaginationField" resolves a page WITHOUT touching graphene.

    It is a plain dataclass; its slicing is delegated to "_paginate_list_base".
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
    assert hasattr(utils, "_paginate_list_base")
    # S-del-backend-11: the graphene GenericPaginationField was deleted.
    assert not hasattr(utils, "GenericPaginationField")
