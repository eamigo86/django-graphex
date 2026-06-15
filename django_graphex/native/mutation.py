"""Native ``Mutation`` base for hand-written GraphQL mutations (S-ROOTS-h).

``Mutation`` is the graphene-free public base for HAND-WRITTEN mutations under the
native backend — the 2.0 replacement for ``graphene.Mutation``.  Usage (the public
2.0 form)::

    from django_graphex import Mutation, field
    from graphql import GraphQLBoolean, GraphQLString
    import graphene  # only for the transitional argument declaration form

    class CreateCategory(Mutation):
        class args:                              # input arguments
            name = graphene.Argument(graphene.String, required=True)

        ok = field(GraphQLBoolean)               # output payload fields
        category = field(CategoryType)
        error = field(GraphQLString)

        @classmethod
        def mutate(cls, root, info, **args):
            obj = Category.objects.create(name=args["name"])
            return cls(ok=True, category=obj, error=None)

    # On a native ``django_graphex.ObjectType`` root:
    class RootMutation(ObjectType):
        create_category = CreateCategory.Field()

Design (reuses the ``DjangoModelMutation`` machinery — mutation.py):

1. ``Mutation`` subclasses the NATIVE ``ObjectType`` base, so the class-body
   output ``field()`` descriptors land in ``_meta.fields`` (the native terminal's
   descriptor merge) and the ``cls(ok=..., obj=..., error=...)`` VALUE-OBJECT
   payload round-trips through the native ObjectType ``__init__`` (the S6c
   silent-null fix stashes the descriptor-named kwargs as instance attributes).

2. ``class args`` is converted to a ``{name: GraphQLArgument}`` dict exactly like
   ``DjangoModelMutation`` builds its arguments — via
   ``graphene_arg_to_graphql_argument`` (accepts the native arg form).

3. ``Field()`` compiles the OUTPUT PAYLOAD by running THIS class through
   ``_compile_plain_object_type`` (the same plain-object compiler
   ``DjangoModelMutation`` uses for its payload), builds the args, wraps the
   ``mutate`` resolver, and returns a graphql-core ``GraphQLField`` whose type IS
   that compiled payload — NOT the old Phase-4 ``GraphQLString`` placeholder.  It
   registers the field's identity in ``_NATIVE_FIELD_IDENTITIES`` so the native
   root compiler's ``_collect_root_attrs`` recovers it (never silently dropping it).

Graphene import policy: zero top-level ``import graphene``.  graphene is touched
only lazily inside ``_compile_args`` when converting an argument declaration that
is still a ``graphene.Argument`` (the transitional argument form).
"""

from __future__ import annotations

from typing import Any

from graphql import GraphQLField

from django_graphex._strconv import props
from django_graphex.native._args import graphene_arg_to_graphql_argument
from django_graphex.native._compat import _adapt_self
from django_graphex.native.base import ObjectType as NativeObjectType

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compile_args(args_cls: type) -> dict[str, Any]:
    """Convert a ``class args`` inner class to a ``dict[str, GraphQLArgument]``.

    Reads every non-underscore attribute of *args_cls*.  Attributes that are
    ``graphene.Argument`` instances are converted via
    ``graphene_arg_to_graphql_argument`` (the same converter ``DjangoModelMutation``
    uses); other attribute types are skipped.

    Args:
        args_cls: The ``class args`` inner class of a ``Mutation`` subclass.

    Returns:
        ``dict[str, GraphQLArgument]`` ready for ``GraphQLField(args=…)``.
    """
    result: dict[str, Any] = {}
    for attr_name, value in props(args_cls).items():
        # Lazy check: is this a graphene Argument? (transitional arg form)
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


class Mutation(NativeObjectType):
    """Base class for hand-written GraphQL mutations under the native backend.

    Subclass and define:

    - ``class args``: inner class with ``graphene.Argument`` class attributes
      (the transitional argument form; converted to native ``GraphQLArgument``).
    - Output payload fields declared via ``field()``
      (``ok = field(GraphQLBoolean)``, ``category = field(CategoryType)`` …).
    - ``mutate``: a ``@classmethod`` (or ``@staticmethod`` / bare function) that
      returns ``cls(ok=..., <obj>=..., error=...)`` — a value-object instance of
      this class.  ``self``-first callables are adapted via ``_adapt_self``.

    Example::

        class CreateCategory(Mutation):
            class args:
                name = graphene.Argument(graphene.String, required=True)

            ok = field(GraphQLBoolean)
            category = field(CategoryType)
            error = field(GraphQLString)

            @classmethod
            def mutate(cls, root, info, **args):
                obj = Category.objects.create(name=args["name"])
                return cls(ok=True, category=obj, error=None)

        # In your schema root:
        create_category = CreateCategory.Field()  # → GraphQLField
    """

    class Meta:
        """Marks the ``Mutation`` BASE itself as abstract.

        The native ``ObjectType.__init_subclass__`` driver skips a base whose
        ``Meta.abstract`` is True, so the bare ``Mutation`` class does not build a
        payload ``_meta``; concrete user subclasses do.
        """

        abstract = True

    class args:
        """Default empty args inner class.

        Subclasses override this to declare mutation arguments.  Declared as a
        plain nested class (a ``type``), which Pydantic's ``ModelMetaclass``
        ignores — it is not a model field.
        """

    @classmethod
    def _resolve_mutate(cls) -> Any:
        """Locate and adapt the ``mutate`` callable for this subclass.

        Walks the MRO to find ``mutate`` (skipping the bare ``Mutation`` base,
        which defines none), unwraps ``staticmethod``, and adapts a ``self``-first
        callable to the ``(root, info, **kw)`` protocol via ``_adapt_self``.

        Returns:
            The resolver callable ready for ``GraphQLField(resolve=…)``.

        Raises:
            AttributeError: When no ``mutate`` is defined anywhere in the MRO.
        """
        mutate_fn = cls.__dict__.get("mutate", None)
        if mutate_fn is None:
            # Walk MRO to find mutate (but not our own — Mutation defines none).
            for klass in cls.__mro__[1:]:
                if "mutate" in klass.__dict__:
                    mutate_fn = klass.__dict__["mutate"]
                    break

        if mutate_fn is None:
            raise AttributeError(
                f"{cls.__name__} must define a 'mutate' method or staticmethod."
            )

        # Unwrap descriptors so ``_adapt_self`` inspects the real function.
        if isinstance(mutate_fn, staticmethod):
            mutate_fn = mutate_fn.__func__
        elif isinstance(mutate_fn, classmethod):
            # Bind the classmethod to ``cls`` so it is called as
            # ``(root, info, **kw)`` by graphql-core (``cls`` is already bound).
            mutate_fn = mutate_fn.__get__(None, cls)

        return _adapt_self(mutate_fn, owner=cls)

    @classmethod
    def Field(cls) -> GraphQLField:
        """Build and return a ``GraphQLField`` for this mutation.

        The field's ``type`` is the compiled OUTPUT PAYLOAD ``GraphQLObjectType``
        (the declared ``field()`` output descriptors compiled via
        ``_compile_plain_object_type`` — the SAME plain-object compiler
        ``DjangoModelMutation`` uses for its ``ok``/``errors`` payload).  Its
        ``args`` are compiled from the ``class args`` inner class and its
        ``resolve`` is the adapted ``mutate`` callable.

        The returned field's identity is registered in ``_NATIVE_FIELD_IDENTITIES``
        so the native root compiler (``_collect_root_attrs``) recovers it when
        mounted on a root — the silent-drop guard.

        Returns:
            A graphql-core ``GraphQLField`` ready for direct mounting on a native
            ``ObjectType`` root (or inspection).
        """
        # Lazy imports to avoid an import cycle at module load (schema_compiler
        # imports from this module's siblings).
        from django_graphex.mutation import _NATIVE_FIELD_IDENTITIES
        from django_graphex.native.schema_compiler import _compile_plain_object_type

        # 1) Output payload type — compile THIS class (its field() output
        #    descriptors live in _meta.fields). The inner field types are lazy
        #    thunks, so object-reference fields resolve at schema-build time
        #    (after compile_all_outputs), not here.
        payload_type = _compile_plain_object_type(cls)

        # 2) Arguments from ``class args``.
        args_cls = cls.__dict__.get("args", cls.args)
        compiled_args = _compile_args(args_cls)

        # 3) Resolver — the adapted ``mutate`` callable.
        resolver = cls._resolve_mutate()

        gql_field = GraphQLField(
            payload_type,
            args=compiled_args,
            resolve=resolver,
            description=cls.__doc__,
        )
        # Register identity so ``_collect_root_attrs`` recovers it on a root —
        # parity with the DjangoModelMutation registration (silent-drop guard).
        _NATIVE_FIELD_IDENTITIES.add(id(gql_field))
        return gql_field
