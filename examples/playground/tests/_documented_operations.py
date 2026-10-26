"""Read literal GraphQL operations from the Playground walkthroughs."""

from pathlib import Path

README = Path(__file__).parents[1] / "README.md"
GUIDE = Path(__file__).parents[3] / "docs/usage/examples/playground.md"


def operation_under_heading(path: Path, heading: str, occurrence: int = 0) -> str:
    """Return a fenced GraphQL operation under an existing section heading.

    Args:
        path: The published Markdown file to read.
        heading: The exact heading line containing the operation.
        occurrence: Zero-based GraphQL fence number within the section.

    Returns:
        The literal GraphQL document inside the selected fence.
    """
    source = path.read_text(encoding="utf-8")
    level = len(heading) - len(heading.lstrip("#"))
    lines = source.splitlines()
    start = lines.index(heading) + 1
    section = []
    for line in lines[start:]:
        if line.startswith("#") and len(line) - len(line.lstrip("#")) <= level:
            break
        section.append(line)
    fences = []
    inside = False
    block = []
    for line in section:
        stripped = line.strip()
        if not inside and stripped == "```graphql":
            inside = True
            block = []
        elif inside and stripped == "```":
            fences.append("\n".join(block))
            inside = False
        elif inside:
            block.append(line)
    return fences[occurrence]
