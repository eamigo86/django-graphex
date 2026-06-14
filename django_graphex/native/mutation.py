"""Native Mutation base for hand-written GraphQL mutations.

Provides ``Mutation``, a drop-in replacement for ``graphene.Mutation`` under
``GDX_BACKEND=native``.  Usage::

    import graphene
    from django_graphex.native.mutation import Mutation

    class CreateUser(Mutation):
        class args:
            name = graphene.Argument(graphene.String, required=True)

        @staticmethod
        def mutate(root, info, name):
            user = User.objects.create(name=name)
            return user

    # In your schema:
    field = CreateUser.Field()  # → GraphQLField

Design:
- ``class args`` inner class declares arguments as ``graphene.Argument``
  instances (class-level attrs).  ``Field()`` reads them via
  ``django_graphex._strconv.props`` and converts each one with
  ``graphene_arg_to_graphql_argument``.
- ``Field()`` returns ``GraphQLField(type_=GraphQLString, resolve=..., args=…)``.
  The ``type_`` placeholder is ``GraphQLString`` — Phase 5 wires real output
  types; for Phase 4 isolation testing the type value is irrelevant.
- The resolver is ``_adapt_self(cls.mutate, cls)``:
  - ``staticmethod``/bare ``(root, info, ...)`` functions → passthrough.
  - ``def mutate(self, ...)`` → shimmed with ``DeprecationWarning``.

Zero graphene imports at module level (graphene is only accessed inside
``_compile_args`` when actually converting arguments).
"""

from __future__ import annotations

from typing import Any

from graphql import GraphQLField, GraphQLString

from django_graphex._strconv import props
from django_graphex.native._args import graphene_arg_to_graphql_argument
from django_graphex.native._compat import _adapt_self


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compile_args(args_cls: type) -> dict[str, Any]:
    """Convert a ``class args`` inner class to a ``dict[str, GraphQLArgument]``.

    Reads every non-underscore attribute of *args_cls*.  Attributes that are
    ``graphene.Argument`` instances are converted via
    ``graphene_arg_to_graphql_argument``; other attribute types are skipped.

    Args:
        args_cls: The ``class args`` inner class of a ``Mutation`` subclass.

    Returns:
        ``dict[str, GraphQLArgument]`` ready for ``GraphQLField(args=…)``.
    """
    result: dict[str, Any] = {}
    for attr_name, value in props(args_cls).items():
        # Lazy check: is this a graphene Argument?
        try:
            from graphene import Argument as GArgument  # noqa: PLC0415
        except ImportError:  # pragma: no cover — graphene absent
            break
        if isinstance(value, GArgument):
            result[attr_name] = graphene_arg_to_graphql_argument(value, name=attr_name)
    return result


# ---------------------------------------------------------------------------
# Mutation base
# ---------------------------------------------------------------------------


class Mutation:
    """Base class for hand-written GraphQL mutations under the native backend.

    Subclass and define:

    - ``class args``: inner class with ``graphene.Argument`` class attributes.
    - ``def mutate(root, info, **kwargs)`` (or ``mutate(self, info, ...)``):
      the resolver function.  ``self``-first callables are automatically
      adapted via ``_adapt_self``.

    Example::

        class MyMutation(Mutation):
            class args:
                name = graphene.Argument(graphene.String, required=True)

            @staticmethod
            def mutate(root, info, name):
                return do_something(name)

        field = MyMutation.Field()  # → GraphQLField
    """

    class args:
        """Default empty args inner class.

        Subclasses override this to declare mutation arguments.
        """

    @classmethod
    def Field(cls) -> GraphQLField:
        """Build and return a ``GraphQLField`` for this mutation.

        The field's ``resolve`` is ``_adapt_self(cls.mutate, cls)`` and its
        ``args`` are compiled from the ``class args`` inner class.

        Returns:
            A ``GraphQLField`` whose ``.resolve`` and ``.args`` are ready for
            direct inspection and (in Phase 5) schema wiring.
        """
        # Retrieve the args inner class from the subclass (or the default empty one)
        args_cls = cls.__dict__.get("args", cls.args)

        # Compile arguments
        compiled_args = _compile_args(args_cls)

        # Adapt the mutate resolver
        mutate_fn = cls.__dict__.get("mutate", None)
        if mutate_fn is None:
            # Walk MRO to find mutate (but not our own default placeholder)
            for klass in cls.__mro__[1:]:
                if "mutate" in klass.__dict__:
                    mutate_fn = klass.__dict__["mutate"]
                    break

        if mutate_fn is None:
            raise AttributeError(
                f"{cls.__name__} must define a 'mutate' method or staticmethod."
            )

        # Unwrap staticmethod descriptor if needed
        if isinstance(mutate_fn, staticmethod):
            mutate_fn = mutate_fn.__func__

        resolver = _adapt_self(mutate_fn, owner=cls)

        # Phase 4: type_ placeholder — Phase 5 wires the real output type.
        # Using GraphQLString as a non-None placeholder satisfies GraphQLField
        # construction without schema assembly.
        return GraphQLField(
            GraphQLString,
            args=compiled_args,
            resolve=resolver,
        )
