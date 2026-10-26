"""Bounded structural cycle checks for named GraphQL fragment references."""

from __future__ import annotations

from collections import deque

from graphql.language import (
    DocumentNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    SelectionSetNode,
)


def find_fragment_cycle(document: DocumentNode) -> FragmentDefinitionNode | None:
    """Return a fragment left in a cyclic reference graph, if one exists.

    The AST and fragment graph are traversed iteratively. Kahn's topological
    reduction visits each distinct reference once, avoiding both exponential
    spread expansion and Python recursion limits for long fragment chains.
    An unknown spread contributes no graph edge; normal validation reports it.

    Args:
        document: The parsed GraphQL document to inspect structurally.

    Returns:
        A fragment in the unreduced graph, or None when acyclic.
    """
    fragments = {
        definition.name.value: definition
        for definition in document.definitions
        if isinstance(definition, FragmentDefinitionNode)
    }
    edges: dict[str, set[str]] = {name: set() for name in fragments}
    incoming = dict.fromkeys(fragments, 0)

    for name, fragment in fragments.items():
        pending: list[SelectionSetNode] = [fragment.selection_set]
        while pending:
            selection_set = pending.pop()
            for selection in selection_set.selections:
                if isinstance(selection, FragmentSpreadNode):
                    target = selection.name.value
                    if target in fragments and target not in edges[name]:
                        edges[name].add(target)
                        incoming[target] += 1
                else:
                    if selection.selection_set is not None:
                        pending.append(selection.selection_set)

    ready = deque(name for name, degree in incoming.items() if degree == 0)
    while ready:
        for target in edges[ready.popleft()]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)

    return next((fragments[name] for name, degree in incoming.items() if degree), None)
