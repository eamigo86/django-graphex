# -*- coding: utf-8 -*-
"""The pagination CONTAINER build path is graphene-free.

The pagination BUILD path is fully native: the ``<Model>ListType`` container
(``results``/``totalCount`` + cursor ``pageInfo``) is built UNCONDITIONALLY by
the native machinery.

STEP 0 ground truth (proven empirically; probes deleted):

* The native pagination container is assembled by
  ``types._make_list_fields_thunk_for`` from ``to_graphql_fields(native=True)``
  + ``NativePaginationField`` (``utils.py``) + ``get_native_page_info_field`` +
  ``NATIVE_CURSOR_PAGE_INFO`` (``pagination.py``). ZERO graphene dependency.
* Building a ``DjangoGraphQLSchema`` with a limit/offset AND a cursor paginated
  list field + ``print_schema`` fired graphene ZERO times even at HEAD (S-sub-6)
  — the graphene factories were already DEAD on the native path, only fired on
  the dead graphene path (the removed ``types.py`` else-branch + the graphene
  ``get_pagination_field``/``get_page_info_field`` methods it called).

The native container builds the full results/totalCount/pageInfo SDL without
graphene.

Run: .venv/bin/python -m pytest \
    tests/native/test_pagination_native_only.py -q -o addopts=""
"""
from __future__ import annotations

import re
import subprocess
import sys
import textwrap

import pytest


# --------------------------------------------------------------------------- #
# Shared seed: build a schema with a limit/offset AND a cursor paginated list   #
# field. Co-located inline (NOT render_native_sdl) to avoid the global-registry  #
# TagListType leak (#1611 item 3).                                              #
# --------------------------------------------------------------------------- #
def _build_paginated_schema() -> tuple[object, str]:
    """Build a DjangoGraphQLSchema with limit/offset + cursor list fields.

    Returns ``(schema, sdl)``. Uses unique container ``Meta.name`` values so it
    can be called from this module without colliding with other test schemas in
    the shared global output registry.
    """
    from graphql import print_schema

    from django_graphex import (
        CursorGraphqlPagination,
        DjangoListObjectField,
        DjangoListObjectType,
        LimitOffsetGraphqlPagination,
        ObjectType,
    )
    from django_graphex.schema import DjangoGraphQLSchema
    from tests.models import BasicModel

    class _S7LimitOffset(DjangoListObjectType):
        class Meta:
            model = BasicModel
            name = "S7LimitOffsetContainer"
            pagination = LimitOffsetGraphqlPagination(default_limit=5)

    class _S7Cursor(DjangoListObjectType):
        class Meta:
            model = BasicModel
            name = "S7CursorContainer"
            pagination = CursorGraphqlPagination(ordering="id")

    class _S7Query(ObjectType):
        limit_offset = DjangoListObjectField(_S7LimitOffset)
        cursor = DjangoListObjectField(_S7Cursor)

    schema = DjangoGraphQLSchema(query=_S7Query)
    return schema, print_schema(schema.graphql_schema)


# --------------------------------------------------------------------------- #
# (a) IMPORT-REMOVAL: the graphene pagination factories never fire on a native  #
#     pagination build.                                                         #
# --------------------------------------------------------------------------- #
def test_types_pagination_build_has_no_graphene_branch() -> None:
    """``types.py`` must not build a graphene pagination container at class-def
    time.

    The ``DjangoListObjectType`` metaclass sets ``_meta.fields = OrderedDict()``
    UNCONDITIONALLY — there is no graphene container factory to fire on a build.
    """
    import ast
    import inspect

    from django_graphex import types as types_mod

    source = inspect.getsource(types_mod.DjangoListObjectType.__init_subclass_with_meta__)
    tree = ast.parse(textwrap.dedent(source))

    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {
            "get_pagination_field",
            "get_page_info_field",
        }:
            offenders.append(node.attr)
    assert not offenders, (
        "DjangoListObjectType.__init_subclass_with_meta__ must NOT call the "
        f"graphene container factories on a build; still found: {offenders}"
    )


def test_to_graphql_fields_is_native_only() -> None:
    """RED->GREEN: ``to_graphql_fields`` is collapsed to native-only.

    At HEAD each paginator's ``to_graphql_fields`` carried a ``native`` switch
    whose ``else`` branch built graphene scalars via ``_g()``. S-page-7 collapses
    these to graphql-core ``GraphQLArgument`` UNCONDITIONALLY — no graphene
    branch, so a paginator's args can never pull graphene. Asserted by source
    inspection (no ``_g()`` call in the method bodies) AND behaviorally.
    """
    import inspect

    from graphql import GraphQLArgument

    from django_graphex.paginations import utils as putils
    from django_graphex.paginations.pagination import (
        CursorGraphqlPagination,
        LimitOffsetGraphqlPagination,
        PageGraphqlPagination,
    )

    # The graphene-shape arg helper is RETIRED (its only consumer was the dead
    # graphene container branch removed from types.py).
    assert not hasattr(putils, "_graphene_paginator_args"), (
        "_graphene_paginator_args must be retired in S-page-7."
    )

    for paginator in (
        LimitOffsetGraphqlPagination(default_limit=5),
        PageGraphqlPagination(page_size_query_param="page_size"),
        CursorGraphqlPagination(ordering="id"),
    ):
        method = type(paginator).to_graphql_fields
        src = inspect.getsource(method)
        assert "_g()" not in src, (
            f"{type(paginator).__name__}.to_graphql_fields must not call the lazy "
            "graphene accessor _g() — it must be native-only."
        )
        # Behaviorally: returns graphql-core arguments regardless of how called.
        args = paginator.to_graphql_fields()
        assert args, "to_graphql_fields must return non-empty args"
        assert all(isinstance(a, GraphQLArgument) for a in args.values()), (
            f"{type(paginator).__name__}.to_graphql_fields must return "
            "GraphQLArgument instances (native-only)."
        )


def test_pagination_factories_are_native_and_graphene_free() -> None:
    """Build a schema with limit/offset AND cursor paginated list fields; the
    container SDL is assembled natively.

    S-del-backend-11: the graphene pagination factories (``_g`` accessors,
    ``_build_generic_pagination_field``, ``_build_cursor_page_info``, the graphene
    ``get_pagination_field`` / graphene-bodied ``get_page_info_field``) were all
    DELETED with the graphene backend, so the native container path is structurally
    graphene-free. This asserts the native containers + cursor pageInfo render in
    the compiled SDL, and that the deleted graphene factories are truly gone.
    """
    from django_graphex.paginations import pagination as ppag
    from django_graphex.paginations import utils as putils

    # The graphene pagination factories were deleted (not merely dormant).
    assert not hasattr(putils, "_g")
    assert not hasattr(ppag, "_g")
    assert not hasattr(putils, "_build_generic_pagination_field")
    assert not hasattr(ppag, "_build_cursor_page_info")
    assert not hasattr(ppag, "CursorPageInfo")
    assert not hasattr(putils, "GenericPaginationField")

    schema, sdl = _build_paginated_schema()

    # The container SDL was built natively.
    assert "type S7LimitOffsetContainer" in sdl
    assert "type S7CursorContainer" in sdl
    assert "type CursorPageInfo" in sdl


def test_native_pagination_build_does_not_import_graphene_subprocess() -> None:
    """In a CLEAN subprocess with graphene BLOCKED via ``sys.meta_path``, building
    a schema with limit/offset AND cursor paginated list fields must NOT import
    graphene through the pagination machinery.

    NOTE: ``graphene`` may still enter ``sys.modules`` via a TRANSITIVE
    dependency at ``import django_graphex`` time (e.g. ``native/descriptors.py``
    pulls ``graphene.utils.orderedtype`` for the creation-counter parity — an
    out-of-S-page-7 concern, retired in the deletion slices). This test therefore
    asserts the PAGINATION build does not raise ``ModuleNotFoundError`` when
    graphene is blocked AFTER ``import django_graphex`` — i.e. the pagination
    container is assembled with graphene unavailable.
    """
    code = textwrap.dedent(
        """
        import django
        from django.conf import settings
        settings.configure(
            ALLOWED_HOSTS=["*"],
            DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
            SITE_ID=1, SECRET_KEY="x", USE_I18N=True, STATIC_URL="/static/",
            INSTALLED_APPS=(
                "django.contrib.admin", "django.contrib.auth",
                "django.contrib.contenttypes", "django.contrib.sessions",
                "django.contrib.sites", "django.contrib.staticfiles", "tests",
            ),
            DJANGO_GRAPHEX={"SCHEMA": "tests.schema.schema"},
        )
        django.setup()

        # Import django_graphex + the pagination machinery FIRST (the transitive
        # graphene pull at descriptors import is out of S-page-7 scope).
        import django_graphex  # noqa: F401
        from django_graphex import (
            CursorGraphqlPagination, DjangoListObjectField, DjangoListObjectType,
            LimitOffsetGraphqlPagination, ObjectType,
        )
        from django_graphex.schema import DjangoGraphQLSchema
        from tests.models import BasicModel
        from graphql import print_schema

        # NOW block any FURTHER graphene import. If the pagination build path
        # imports graphene (directly or via a lazy _g()/factory), this raises.
        import sys
        import importlib.abc

        class _BlockGraphene(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path, target=None):
                if fullname == "graphene" or fullname.startswith("graphene."):
                    raise ModuleNotFoundError(
                        f"graphene import BLOCKED during pagination build: {fullname}"
                    )
                return None

        sys.meta_path.insert(0, _BlockGraphene())
        # Drop any cached graphene submodules so a fresh import would re-trigger
        # the finder (the pagination lazy _g() caches are reset below).
        from django_graphex.paginations import utils as _u, pagination as _p
        _u._GRAPHENE = None
        _p._GRAPHENE = None

        class LO(DjangoListObjectType):
            class Meta:
                model = BasicModel; name = "SubLO"
                pagination = LimitOffsetGraphqlPagination(default_limit=5)

        class CU(DjangoListObjectType):
            class Meta:
                model = BasicModel; name = "SubCU"
                pagination = CursorGraphqlPagination(ordering="id")

        class Query(ObjectType):
            lo = DjangoListObjectField(LO)
            cu = DjangoListObjectField(CU)

        schema = DjangoGraphQLSchema(query=Query)
        sdl = print_schema(schema.graphql_schema)
        assert "type SubLO" in sdl, "limit/offset container missing"
        assert "type SubCU" in sdl, "cursor container missing"
        assert "type CursorPageInfo" in sdl, "cursor pageInfo missing"
        print("NATIVE_PAGINATION_BUILD_OK")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"native pagination build raised with graphene blocked:\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    assert "NATIVE_PAGINATION_BUILD_OK" in proc.stdout, proc.stdout


# --------------------------------------------------------------------------- #
# (b) SDL-NEUTRAL: the container SDL is byte-identical to the native baseline.  #
# --------------------------------------------------------------------------- #
def _container_block(sdl: str, type_name: str) -> str:
    m = re.search(r"type " + re.escape(type_name) + r" \{.*?\n\}", sdl, re.DOTALL)
    assert m is not None, f"{type_name} not found in SDL"
    return m.group(0)


def _normalize_results_element(block: str) -> str:
    """Replace the ``results(...): [<ElementType>]`` node-type name with a stable
    ``[NODE]`` placeholder.

    The element (node) type NAME is determined by the SHARED GLOBAL output
    registry's prior state (it may render as ``BasicModelGenericType``,
    ``LocalType``, etc. depending on which OTHER test registered ``BasicModel``'s
    node type first — the B5 / #1611-item-3 global-registry leak). S-page-7 does
    NOT change the element type; it controls the pagination CONTAINER shape
    (results ARGS + totalCount + pageInfo + CursorPageInfo). Normalizing the
    element name makes the byte-identical assertion robust to global state while
    still pinning everything S-page-7 owns.
    """
    return re.sub(r"\): \[[A-Za-z_][A-Za-z0-9_]*\]", "): [NODE]", block)


def test_limit_offset_container_sdl_byte_identical() -> None:
    """The limit/offset ``<Model>ListType`` container SDL block matches the
    expected native shape byte-for-byte (results with limit/offset/ordering args
    + totalCount, NO pageInfo). The element node type is normalized (see
    :func:`_normalize_results_element`)."""
    _schema, sdl = _build_paginated_schema()
    block = _normalize_results_element(_container_block(sdl, "S7LimitOffsetContainer"))
    expected = textwrap.dedent(
        """\
        type S7LimitOffsetContainer {
          results(
            \"\"\"
            Number of results to return per page. Default 'default_limit': 5, and 'max_limit': None
            \"\"\"
            limit: Int = 5

            \"\"\"The initial index from which to return the results. Default: 0\"\"\"
            offset: Int

            \"\"\"
            A string or comma delimited string value that indicates the default ordering when obtaining lists of objects.
            \"\"\"
            ordering: String
          ): [NODE]
          totalCount: Int
        }"""
    )
    assert block == expected, f"\n--- GOT ---\n{block}\n--- EXPECTED ---\n{expected}"


def test_cursor_container_sdl_byte_identical() -> None:
    """The cursor ``<Model>ListType`` container SDL block matches the expected
    native shape byte-for-byte (results with first/cursor args + totalCount +
    pageInfo{...}: CursorPageInfo) and the CursorPageInfo type matches. The
    element node type is normalized (see :func:`_normalize_results_element`)."""
    _schema, sdl = _build_paginated_schema()
    container = _normalize_results_element(_container_block(sdl, "S7CursorContainer"))
    expected_container = textwrap.dedent(
        """\
        type S7CursorContainer {
          results(
            \"\"\"Number of results to return per page.\"\"\"
            first: Int

            \"\"\"Opaque cursor; returns the results that come after it in the ordering.\"\"\"
            cursor: String
          ): [NODE]
          totalCount: Int

          \"\"\"Forward keyset pagination metadata.\"\"\"
          pageInfo(
            \"\"\"Number of results to return per page.\"\"\"
            first: Int

            \"\"\"Opaque cursor; returns the results that come after it in the ordering.\"\"\"
            cursor: String
          ): CursorPageInfo
        }"""
    )
    assert container == expected_container, (
        f"\n--- GOT ---\n{container}\n--- EXPECTED ---\n{expected_container}"
    )

    page_info = _container_block(sdl, "CursorPageInfo")
    expected_page_info = textwrap.dedent(
        """\
        type CursorPageInfo {
          \"\"\"True if at least one row exists after the last row of the page.\"\"\"
          hasNextPage: Boolean!

          \"\"\"True if at least one row exists before the first row of the page.\"\"\"
          hasPreviousPage: Boolean!

          \"\"\"Cursor of the first row of the page (null if the page is empty).\"\"\"
          startCursor: String

          \"\"\"Cursor of the last row of the page (null if the page is empty).\"\"\"
          endCursor: String
        }"""
    )
    assert page_info == expected_page_info, (
        f"\n--- GOT ---\n{page_info}\n--- EXPECTED ---\n{expected_page_info}"
    )


# --------------------------------------------------------------------------- #
# (c) RUNTIME: both pagination modes resolve correctly on the native container. #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_limit_offset_pagination_resolves_native() -> None:
    """A limit/offset paginated list field resolves correct results/totalCount."""
    from graphql import graphql_sync

    from tests.models import BasicModel

    for i in range(12):
        BasicModel.objects.create(text="M%02d" % i)

    schema, _sdl = _build_paginated_schema()
    result = graphql_sync(
        schema.graphql_schema,
        "{ limitOffset { totalCount results(limit: 3, offset: 2) { text } } }",
    )
    assert result.errors is None, result.errors
    data = result.data["limitOffset"]
    assert data["totalCount"] == 12
    assert [r["text"] for r in data["results"]] == ["M02", "M03", "M04"]


@pytest.mark.django_db
def test_cursor_pagination_resolves_native_with_page_info() -> None:
    """A cursor paginated list field resolves correct results AND pageInfo
    (hasNextPage/hasPreviousPage/start/end cursors), preserving cursor semantics.
    """
    from graphql import graphql_sync

    from django_graphex import CursorGraphqlPagination
    from tests.models import BasicModel

    for i in range(12):
        BasicModel.objects.create(text="M%02d" % i)

    schema, _sdl = _build_paginated_schema()

    # First page (first: 4) -> ids 1..4, hasNextPage True, hasPreviousPage False.
    q = (
        "{ cursor { totalCount "
        "results(first: 4) { id text } "
        "pageInfo(first: 4) { hasNextPage hasPreviousPage startCursor endCursor } } }"
    )
    result = graphql_sync(schema.graphql_schema, q)
    assert result.errors is None, result.errors
    data = result.data["cursor"]
    assert data["totalCount"] == 12
    assert [r["text"] for r in data["results"]] == ["M00", "M01", "M02", "M03"]
    page_info = data["pageInfo"]
    assert page_info["hasNextPage"] is True
    assert page_info["hasPreviousPage"] is False
    assert page_info["startCursor"] is not None
    assert page_info["endCursor"] is not None

    # Second page using endCursor -> ids 5..8, hasPreviousPage True.
    end_cursor = page_info["endCursor"]
    # Sanity: the end cursor decodes to the 4th row's ordering value (id=4).
    assert CursorGraphqlPagination.decode_cursor(end_cursor) == "4"
    q2 = (
        "{ cursor { "
        'results(first: 4, cursor: "%s") { text } '
        'pageInfo(first: 4, cursor: "%s") { hasNextPage hasPreviousPage } } }'
        % (end_cursor, end_cursor)
    )
    result2 = graphql_sync(schema.graphql_schema, q2)
    assert result2.errors is None, result2.errors
    data2 = result2.data["cursor"]
    assert [r["text"] for r in data2["results"]] == ["M04", "M05", "M06", "M07"]
    assert data2["pageInfo"]["hasNextPage"] is True
    assert data2["pageInfo"]["hasPreviousPage"] is True
