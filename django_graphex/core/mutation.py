"""Native "Mutation" base for hand-written GraphQL mutations (S-ROOTS-h).

"Mutation" is the graphene-free public base for HAND-WRITTEN mutations under the
native backend — the 2.0 replacement for "graphene.Mutation". Usage (the public
2.0 form):

    from django_graphex.core import Mutation, field
    from graphql import GraphQLArgument, GraphQLBoolean, GraphQLNonNull, GraphQLString

    class CreateCategory(Mutation):
        class Arguments:                         # input arguments (native form)
            name = GraphQLArgument(GraphQLNonNull(GraphQLString))

        ok = field(GraphQLBoolean)               # output payload fields
        category = field(CategoryType)
        error = field(GraphQLString)

        @classmethod
        def mutate(cls, root, info, **args):
            obj = Category.objects.create(name=args["name"])
            return cls(ok=True, category=obj, error=None)

    # On a native "django_graphex.ObjectType" root:
    class RootMutation(ObjectType):
        create_category = CreateCategory.Field()

Design (reuses the "DjangoModelMutation" machinery — mutation.py):

1. "Mutation" subclasses the NATIVE "ObjectType" base, so the class-body
   output "field()" descriptors land in "_meta.fields" (the native terminal's
   descriptor merge) and the "cls(ok=..., obj=..., error=...)" VALUE-OBJECT
   payload round-trips through the native ObjectType "__init__" (the S6c
   silent-null fix stashes the descriptor-named kwargs as instance attributes).

2. "class Arguments" is converted to a "{name: GraphQLArgument}" dict via the
   NATIVE arg API "native_arg" ("core/_args.py"): a graphql-core
   "GraphQLArgument" is accepted verbatim ("out_name" filled from the declared
   key), a bare graphql-core type is wrapped. No graphene.

3. "Field()" compiles the OUTPUT PAYLOAD by running THIS class through
   "_compile_plain_object_type" (the same plain-object compiler
   "DjangoModelMutation" uses for its payload), builds the args, wraps the
   "mutate" resolver, and returns a graphql-core "GraphQLField" whose type IS
   that compiled payload — NOT the old Phase-4 "GraphQLString" placeholder. It
   registers the field's identity in "_NATIVE_FIELD_IDENTITIES" so the native
   root compiler's "_collect_root_attrs" recovers it (never silently dropping it).

Graphene import policy: ZERO graphene anywhere (S-args-8, decision #1603 — CLEAN
BREAK). The argument path uses the graphene-free "native_arg" normaliser; the
transitional "graphene.Argument" form is no longer accepted.
"""

from __future__ import annotations

from typing import Any

from graphql import GraphQLField

from django_graphex._strconv import props
from django_graphex.core._args import native_arg
from django_graphex.core._compat import _adapt_self
from django_graphex.core.base import ObjectType as NativeObjectType

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compile_args(args_cls: type) -> dict[str, Any]:
    """Convert a ``class Arguments`` inner class to a ``dict[str, GraphQLArgument]``.

    Reads every non-underscore attribute of *args_cls* and normalises EACH through
    the NATIVE arg API ``native_arg`` (S-args-8, decision #1603 — CLEAN BREAK off
    graphene).  ``native_arg`` accepts three declaration currencies:

    - a graphql-core ``GraphQLArgument`` (``name = GraphQLArgument(GraphQLNonNull(
      GraphQLString))``) — accepted VERBATIM, with ``out_name`` set to the
      snake_case form of the declared (possibly camelCase) key when the user did
      not already supply one;
    - a bare graphql-core type (``age = GraphQLInt``, ``tags = GraphQLList(...)``)
      — wrapped in a ``GraphQLArgument`` for ergonomics;
    - a zero-arg callable THUNK (``data = lambda: GraphQLArgument(GraphQLNonNull(
      MyInput._meta.graphql_input_type))``) — called to resolve a deferred type
      (the native lazy form for an input-object arg whose compiled
      ``GraphQLInputObjectType`` is not available at class-definition time; the
      thunk fires here, at ``Field()`` build time, AFTER ``compile_all_inputs``).

    CLEAN BREAK (no silent drops): every public attribute is routed through
    ``native_arg``, which raises a clear ``TypeError`` naming the offending value
    when it is not a native arg currency (e.g. a leftover ``graphene.Argument``).
    Pre-S-args-8 the loop FILTERED to ``(GraphQLArgument, GraphQLType)`` and
    SILENTLY SKIPPED anything else — so a stray ``graphene.Argument`` dropped the
    arg with no error and the advertised clean break (= ``TypeError``) was
    unreachable.  ``props`` already strips dunders / underscore helpers, so a
    private helper constant is never seen here; a genuine public arg declaration
    must be a native currency or it fails loudly.  graphene is NEVER imported.

    Args:
        args_cls: The ``class Arguments`` inner class of a ``Mutation`` subclass.

    Returns:
        ``dict[str, GraphQLArgument]`` ready for ``GraphQLField(args=…)``.

    Raises:
        TypeError: When any public attribute of *args_cls* is not a native arg
            currency (the CLEAN BREAK — silent drops are impossible).
    """
    result: dict[str, Any] = {}
    for attr_name, value in props(args_cls).items():
        result[attr_name] = native_arg(value, name=attr_name)
    return result


# ---------------------------------------------------------------------------
# Mutation base
# ---------------------------------------------------------------------------


class Mutation(NativeObjectType):
    """Base class for hand-written GraphQL mutations under the native backend.

    Subclass and define:

    - "class Arguments": inner class with graphql-core "GraphQLArgument" (or
      bare graphql-core type) class attributes — the native arg form (S-args-8).
    - Output payload fields declared via "field()"
      ("ok = field(GraphQLBoolean)", "category = field(CategoryType)" and so on).
    - "mutate": a "@classmethod" (or "@staticmethod" / bare function) that
      returns "cls(ok=..., <obj>=..., error=...)" — a value-object instance of
      this class. "self"-first callables are adapted via "_adapt_self".

    Example:
        class CreateCategory(Mutation):
            class Arguments:
                name = GraphQLArgument(GraphQLNonNull(GraphQLString))

            ok = field(GraphQLBoolean)
            category = field(CategoryType)
            error = field(GraphQLString)

            @classmethod
            def mutate(cls, root, info, **args):
                obj = Category.objects.create(name=args["name"])
                return cls(ok=True, category=obj, error=None)

        # In your schema root:
        create_category = CreateCategory.Field()  # -> GraphQLField
    """

    class Meta:
        """Marks the "Mutation" BASE itself as abstract.

        The native "ObjectType.__init_subclass__" driver skips a base whose
        "Meta.abstract" is True, so the bare "Mutation" class does not build a
        payload "_meta"; concrete user subclasses do.
        """

        abstract = True

    class Arguments:
        """Default empty arguments inner class.

        Subclasses override this to declare mutation arguments via the native
        arg form (graphql-core "GraphQLArgument" / types). Declared as a plain
        nested class (a "type"), which Pydantic's "ModelMetaclass" ignores —
        it is not a model field.
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
        """Build and return a "GraphQLField" for this mutation.

        The field's "type" is the compiled OUTPUT PAYLOAD "GraphQLObjectType"
        (the declared "field()" output descriptors compiled via
        "_compile_plain_object_type" — the SAME plain-object compiler
        "DjangoModelMutation" uses for its "ok"/"errors" payload). Its
        "args" are compiled from the "class Arguments" inner class and its
        "resolve" is the adapted "mutate" callable.

        The returned field's identity is registered in "_NATIVE_FIELD_IDENTITIES"
        so the native root compiler ("_collect_root_attrs") recovers it when
        mounted on a root — the silent-drop guard.

        Returns:
            A graphql-core "GraphQLField" ready for direct mounting on a native
            "ObjectType" root (or inspection).

        Raises:
            TypeError: When the subclass still declares the legacy "class args"
                inner class without an "Arguments" — the v2.0 rename guard fails
                loudly instead of silently compiling zero arguments.
        """
        # Lazy imports to avoid an import cycle at module load (schema_compiler
        # imports from this module's siblings).
        from django_graphex.core.schema_compiler import _compile_plain_object_type
        from django_graphex.mutation import _NATIVE_FIELD_IDENTITIES

        # 1) Output payload type — compile THIS class (its field() output
        #    descriptors live in _meta.fields). The inner field types are lazy
        #    thunks, so object-reference fields resolve at schema-build time
        #    (after compile_all_outputs), not here.
        payload_type = _compile_plain_object_type(cls)

        # 2) Arguments from ``class Arguments``.  HARD rename guard (v2.0): a
        #    subclass that still declares the legacy ``class args`` inner class and
        #    NO ``Arguments`` would silently compile zero args — fail loudly instead.
        if "args" in cls.__dict__ and "Arguments" not in cls.__dict__:
            raise TypeError(
                f"{cls.__name__}: the mutation argument container `class args` was "
                "renamed to `class Arguments` in v2.0 — rename the inner class."
            )
        args_cls = cls.__dict__.get("Arguments", cls.Arguments)
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
