"""Permission-hook keyword filtering at Python callable boundaries."""

from django_graphex.permissions import supported_kwargs


def test_permission_hook_excludes_positional_only_and_varargs_names() -> None:
    """Forward only keywords the hook can accept by name.

    A positional-only context parameter and variadic positional arguments
    must not be mistaken for supported policy keywords.
    """

    def policy(context: object, /, *args: object, action: str) -> str:
        """Return the named action after positional context processing.

        Args:
            context: The positional request context.
            *args: Extra positional values.
            action: The named permission action.

        Returns:
            The accepted action.
        """
        return action

    narrowed = supported_kwargs(
        policy,
        {"context": "not positional", "args": "not positional", "action": "list"},
    )

    assert narrowed == {"action": "list"}
    assert policy(object(), action=narrowed["action"]) == "list"
