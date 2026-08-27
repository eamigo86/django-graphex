# -*- coding: utf-8 -*-
"""The types page must build for a reader who copies it TOP TO BOTTOM.

A sample that only works in isolation is not a sample, it is a trap. The
projection is a security boundary, so a "DjangoListObjectType" declaring
"only_fields" behind an already-registered node type raises
"ImproperlyConfigured" at class definition -- which means the page's own
earlier "UserType" decides whether a later container sample builds at all.
Fixing a container in isolation and leaving the node type it collides with two
hundred lines above is how the page ended up giving two opposite instructions.

So this module does not assert on prose. It EXTRACTS the page's Python samples,
RUNS each one paired with the very node type the page declares first, and then
BUILDS a schema out of what they declared. The build is not optional: only the
container projection refuses at class definition, while the filter axis refuses
during compilation, so stopping at "the class defined" would sail straight past
a "filter_fields" entry naming a column -- or a relation -- the node type does
not publish. If the docs and the boundary rule ever disagree again, this fails
with the sample's own line number.

Blocks are paired rather than concatenated wholesale because the page reuses
the name "UserType" as a running example across unrelated sections (a resolver
demo, a descriptor demo), which no reader copies all at once. The pairing is
the narrowest thing that still catches the real defect: a sample whose
declaration contradicts the node type the page registers for the same model.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth.models import User

import django_graphex.core.base as base_module
import django_graphex.registry as registry_module
from django_graphex.core import (
    BooleanField,
    CharField,
    Field,
    IntField,
    ObjectType,
)
from django_graphex.core.registry_compiler import NativeOutputRegistry
from django_graphex.fields import DjangoListObjectField, DjangoObjectField
from django_graphex.paginations import (
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import (
    DjangoInputObjectType,
    DjangoListObjectType,
    DjangoModelType,
    DjangoObjectType,
)

from ._schema_isolation import isolated_pair

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "usage" / "types.md"

# A fenced Python block, capturing its body. re.M so ^ anchors to line starts.
_BLOCK_RE = re.compile(r"^```python\n(.*?)^```$", re.M | re.S)

# The two class forms that REUSE a registered node type instead of minting one,
# and therefore cannot honour a projection of their own.
_CONTAINER_RE = re.compile(r"class \w+\((?:DjangoListObjectType|DjangoModelType)\)")

_NODE_RE = re.compile(r"class \w+\(DjangoObjectType\)")

# The imports the page tells the reader to assume. Samples below the first few
# sections stop repeating them, so the executed namespace supplies them.
_DOC_NAMESPACE: dict[str, Any] = {
    "User": User,
    "ObjectType": ObjectType,
    "DjangoObjectType": DjangoObjectType,
    "DjangoListObjectType": DjangoListObjectType,
    "DjangoInputObjectType": DjangoInputObjectType,
    "DjangoModelType": DjangoModelType,
    "DjangoListObjectField": DjangoListObjectField,
    "DjangoObjectField": DjangoObjectField,
    "LimitOffsetGraphqlPagination": LimitOffsetGraphqlPagination,
    "PageGraphqlPagination": PageGraphqlPagination,
    "BooleanField": BooleanField,
    "CharField": CharField,
    "Field": Field,
    "IntField": IntField,
}


def _samples() -> list[tuple[int, str]]:
    """Read every fenced Python block off the types page, in page order.

    Returns:
        One pair per block: the 1-based line the block's body starts on, and
        the block's source.
    """
    text = DOC_PATH.read_text(encoding="utf-8")
    out: list[tuple[int, str]] = []
    for match in _BLOCK_RE.finditer(text):
        line = text.count("\n", 0, match.start(1)) + 1
        out.append((line, match.group(1)))
    return out


def _user_samples() -> list[tuple[int, str]]:
    """Keep the blocks that declare a type over the page's running model.

    Returns:
        The blocks whose Meta binds the auth User model.
    """
    return [(line, src) for line, src in _samples() if "model = User" in src]


def _canonical_node() -> tuple[int, str]:
    """Find the node type the page registers for User FIRST.

    Everything after it in the page is read by someone who already ran it, so
    it is the declaration every later container sample has to live with.

    Returns:
        The line and source of that block.

    Raises:
        AssertionError: If the page stops declaring a User node type at all.
    """
    for line, src in _user_samples():
        if _NODE_RE.search(src):
            return line, src
    raise AssertionError(f"{DOC_PATH} declares no DjangoObjectType over User")


def _container_samples() -> list[tuple[int, str]]:
    """Select the samples whose container reuses that registered node type.

    Returns:
        Line and source for each container sample over User.
    """
    return [(line, src) for line, src in _user_samples() if _CONTAINER_RE.search(src)]


def _mount(namespace: dict[str, Any]) -> type:
    """Build a Query that mounts every output type the samples just declared.

    Defining the classes is not enough. Only one of the boundary's three axes
    refuses at class definition: the container projection. The FILTER axis is
    enforced while the schema compiles, so a "filter_fields" entry naming a
    column the node type hides only raises once something actually builds --
    which is exactly the failure a reader hits and a test that stops at "class"
    would sail past.

    Args:
        namespace: The namespace the doc sources were executed in.

    Returns:
        A Query type mounting each declared node and list container.
    """
    attributes: dict[str, Any] = {}
    for name, value in namespace.items():
        if not isinstance(value, type) or name in _DOC_NAMESPACE:
            continue
        # A declared type carries a bound Meta; the library base classes, the
        # samples' own hand-written Query classes and stray helpers do not.
        if getattr(getattr(value, "_meta", None), "model", None) is None:
            continue
        if issubclass(value, DjangoListObjectType):
            attributes[f"{name}_list"] = DjangoListObjectField(value)
        elif issubclass(value, DjangoObjectType):
            attributes[f"{name}_one"] = DjangoObjectField(value)
    return type("Query", (ObjectType,), attributes)


def _run(sources: list[str]) -> None:
    """Execute doc sources, then COMPILE what they declared.

    The samples never spell a "Meta.registry", so they land in the process-wide
    registry -- which would leak the page's User types into every other test and
    make the outcome depend on collection order. Swapping the module-level
    singleton for the duration keeps the exec hermetic, and pairing it with a
    fresh output registry keeps the built schema out of the shared namespace.

    BOTH globals have to move together. A registry that IS the global one (and
    the swapped-in one is, for as long as it is installed) reports the
    process-wide shared "NativeOutputRegistry" as its companion, so every class
    definition would stamp the page's PROJECTED "UserType" into the shared
    model-keyed slot and hand it to whichever later test resolves a relation to
    User. Swapping the companion too is what makes the exec actually hermetic.

    Args:
        sources: Doc block bodies, executed in the given order in ONE namespace.
    """
    previous = registry_module.registry
    previous_output = base_module._gdx_shared_output_registry
    fresh = Registry()
    registry_module.registry = fresh
    base_module._gdx_shared_output_registry = NativeOutputRegistry()
    try:
        namespace = dict(_DOC_NAMESPACE)
        for source in sources:
            exec(compile(source, str(DOC_PATH), "exec"), namespace)
        query = _mount(namespace)
        if query._meta.fields:
            DjangoGraphQLSchema(query=query, registries=isolated_pair(fresh))
    finally:
        registry_module.registry = previous
        base_module._gdx_shared_output_registry = previous_output


@pytest.mark.parametrize(
    ("line", "source"),
    _user_samples(),
    ids=[f"L{line}" for line, _ in _user_samples()],
)
def test_sample_builds_behind_the_pages_own_node_type(line: int, source: str) -> None:
    """Every User sample must survive the node type the page declared first.

    If this fails, the page is telling the reader two different things about the
    same model: the sample at this line declares something the projection
    boundary refuses once the page's own UserType is on the registry. The
    containers are the sharp end -- they are the ones that reuse a registered
    node type and cannot honour a projection of their own -- but the whole
    running example is swept, because the next contradiction will not
    necessarily land on the same class.

    Args:
        line: The line the failing sample starts on, for the test id.
        source: The sample body.
    """
    _run([_canonical_node()[1], source])


def test_restating_the_nodes_own_projection_on_a_container_is_accepted() -> None:
    """The danger box promises a restatement builds. Hold it to that.

    The box tells the reader that repeating the node type's exact projection on
    the container is fine, because the guard compares the columns two
    projections SELECT rather than the options they spell. That is a promise
    about behaviour, so it is checked against the page's real projection --
    lifted out of the sample, not retyped here, so widening the node type cannot
    leave this passing against a stale copy.
    """
    node_source = _canonical_node()[1]
    only_fields = next(
        ast.get_source_segment(node_source, node.value)
        for node in ast.walk(ast.parse(node_source))
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "only_fields"
            for target in node.targets
        )
    )
    restated = (
        "class RestatingListType(DjangoListObjectType):\n"
        "    class Meta:\n"
        "        model = User\n"
        f"        only_fields = {only_fields}\n"
        '        exclude_fields = ("password",)\n'
    )
    _run([node_source, restated])


def test_running_a_sample_leaves_the_shared_output_registry_untouched() -> None:
    """Running the page must not repoint the process-wide User output type.

    The page's node type PROJECTS User down to a handful of columns. Every
    class definition stamps its compiled type into its registry's companion
    output registry, keyed by model, last-wins -- and for the GLOBAL registry
    that companion IS the process-wide singleton. So a run that only swaps the
    graphene registry still hands the whole process a User type serving four
    fields, and whichever later test resolves a relation to User fails
    depending on collection order. Pin the identity: after a run, the shared
    slot must hold exactly what it held before.
    """
    from django_graphex.core.base import get_shared_output_registry

    shared = get_shared_output_registry()
    before = shared.get_compiled(User)
    _run([_canonical_node()[1]])
    assert shared.get_compiled(User) is before


def test_the_page_still_has_container_samples_to_check() -> None:
    """Guard the guard: a parse that silently matches nothing proves nothing.

    A rewrite that renames the fences or the classes would leave the
    parametrized test with zero cases and a green run, so pin the shape.
    """
    assert len(_container_samples()) >= 4
