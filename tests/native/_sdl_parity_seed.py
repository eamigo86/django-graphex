"""Standalone seed-schema SDL printer for the cross-process parity gate (WU2/WU4).

Run as a subprocess with ``GDX_BACKEND`` set in the environment BEFORE this
module imports ``django_graphex`` (the backend flag is read at import/class-def
time, so it can only be flipped per-process — D7). Prints the SDL of a MINIMAL
seed schema to stdout.

Several seeds are exposed, selected by the ``GDX_SEED`` env var:

* ``GDX_SEED=node`` (default) — a Query with ONE ``DjangoObjectField`` on a real
  Django model (the WU2 ROOT-compiler parity seed).
* ``GDX_SEED=filter`` — the WU4 ``ArticleFilterInput`` parity seed: builds the
  native vs graphene ``<Model>FilterInput`` for a filter-bearing model and
  renders it as an argument so ``print_schema`` emits the full nested filter
  input shape (scalar lookups, choices enum, nested relation filter, and the
  recursive ``and`` / ``or`` / ``not`` combinators).
* ``GDX_SEED=node_scalars`` — the Slices B+C OUTPUT scalar NAME + nullability
  parity seed (Date/DateTime/Time -> Custom*, UUID, Decimal -> Float, JSONString;
  model scalars nullable, pk ``id: ID!``).
* ``GDX_SEED=relations`` — the Slices D+E + FK-relation-nullability OUTPUT
  field/relation parity seed: declared non-model fields, a required FK and a
  nullable FK (both nullable on output), M2M + reverse-FK to-many relations
  rendered as the ``<Model>ListType`` results/totalCount container.
* ``GDX_SEED=full`` — the WU10 BINDING gate: the ENTIRE ``tests/schema.py``
  schema (every query field, pagination containers, filter inputs, auto-derived
  list types, and the full ``all_directives`` directive block) built under each
  backend and printed. This is the Phase-5 closing full-schema SDL parity gate.
* ``GDX_SEED=types_unreferenced`` — the ``types=`` forwarding parity seed: a
  Query plus a plain ``graphene.ObjectType`` that is NOT reachable from Query,
  injected via ``DjangoGraphQLSchema(query=Query, types=[Unreferenced])``.
  graphene's ``graphene.Schema`` forwards ``types=`` to its graphql-core
  ``GraphQLSchema`` so the unreferenced type appears in the SDL; the native
  assembly must forward it too or the type is SILENTLY dropped (an SDL-parity
  divergence). After ``normalize_sdl`` the two SDLs MUST be byte-equal.

Usage::

    GDX_BACKEND=native  python -m tests.native._sdl_parity_seed
    GDX_BACKEND=graphene python -m tests.native._sdl_parity_seed
    GDX_SEED=filter GDX_BACKEND=native python -m tests.native._sdl_parity_seed

The two outputs, after ``normalize_sdl`` (ordering-only), MUST be byte-equal.
This is a GENUINE cross-process parity check: under native the seed assembles
via the native root compiler / native filter builder; under graphene via
graphene.Schema / the graphene filter builder.
"""
from __future__ import annotations

import os
import sys


def _configure_django() -> None:
    """Configure Django settings mirroring tests/conftest.py (minimal subset)."""
    import django
    from django.conf import settings

    if not settings.configured:
        settings.configure(
            ALLOWED_HOSTS=["*"],
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": ":memory:",
                }
            },
            SITE_ID=1,
            SECRET_KEY="not very secret in tests",
            USE_I18N=True,
            STATIC_URL="/static/",
            ROOT_URLCONF="tests.urls",
            INSTALLED_APPS=(
                "django.contrib.admin",
                "django.contrib.auth",
                "django.contrib.contenttypes",
                "django.contrib.sessions",
                "django.contrib.sites",
                "django.contrib.staticfiles",
                "tests",
            ),
            GRAPHEX={"SCHEMA": "tests.schema.schema"},
        )
    django.setup()


def build_seed_sdl() -> str:
    """Build the seed schema for the current backend and return its SDL.

    The backend is determined by ``GDX_BACKEND`` (already set in os.environ
    before django_graphex is imported).
    """
    _configure_django()

    import graphene
    from graphql.utilities import print_schema

    from django_graphex.fields import DjangoObjectField
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    backend = os.environ.get("GDX_BACKEND", "graphene")

    class SeedCategoryType(DjangoObjectType):
        class Meta:
            model = Category
            # id-only node: ``id: ID!`` renders byte-identical on both backends.
            # (graphene-django renders CharField as nullable ``String`` while the
            # native compiler renders the non-null DB column as ``String!`` — a
            # WU1-level node divergence, out of scope for the WU2 ROOT-compiler
            # parity seed. WU10's full-schema parity covers node-field parity.)
            only_fields = ("id",)

    class SeedQuery(graphene.ObjectType):
        category = DjangoObjectField(SeedCategoryType)

    if backend == "native":
        # Compile outputs (app-ready normally does this; the seed app config
        # does not auto-run it here, so do it explicitly before assembly).
        from django_graphex.native.registry_compiler import compile_all_outputs
        from django_graphex.schema import DjangoGraphQLSchema

        compile_all_outputs()
        schema = DjangoGraphQLSchema(query=SeedQuery)
        # Anti-tautology sentinel: prove the native assembly path was taken and
        # the query field type IS the native canonical instance (gdx-bearing),
        # NOT a graphene-built type. Emitted to stderr to keep stdout = pure SDL.
        if os.environ.get("GDX_SEED_TRACE"):
            from django_graphex.native.base import get_shared_output_registry

            query_type = schema.graphql_schema.query_type
            field_type = query_type.fields["category"].type
            canonical = get_shared_output_registry().get_compiled(Category)
            is_native = field_type is canonical and "gdx" in (
                field_type.extensions or {}
            )
            sys.stderr.write(
                "GDX_SEED_PATH=native\n"
                if is_native
                else "GDX_SEED_PATH=graphene-fallback\n"
            )
        return print_schema(schema.graphql_schema)

    # Graphene path: build via graphene.Schema and print its graphql_schema.
    graphene_schema = graphene.Schema(query=SeedQuery)
    if os.environ.get("GDX_SEED_TRACE"):
        sys.stderr.write("GDX_SEED_PATH=graphene\n")
    return print_schema(graphene_schema.graphql_schema)


def build_scalar_node_seed_sdl() -> str:
    """Build the Slice-B/C OUTPUT scalar+nullability parity seed SDL.

    This is the deliverable that PROVES the native output compiler matches the
    graphene v1 contract for the FULL scalar surface (#1494 nullability + the
    scalar-NAME parity sibling). It builds a node OUTPUT type carrying:

    * ``title`` — a NON-NULL ``CharField`` (proves the #1494 nullability fix:
      graphene renders ``String`` nullable; native must NOT emit ``String!``).
    * ``when_date`` / ``when_dt`` / ``when_time`` — Date/DateTime/Time fields
      (proves the date scalar NAMES: graphene-django uses the ``CustomDate`` /
      ``CustomDateTime`` / ``CustomTime`` subclasses, NOT bare ``Date`` etc.).
    * ``ext_id`` — ``UUIDField`` -> ``UUID``.
    * ``amount`` — ``DecimalField``: graphene-django COLLAPSES Decimal to
      ``Float`` on output (converter.py registers DecimalField on
      ``convert_field_to_float``), so native must emit ``Float`` here too.
    * ``payload`` — ``JSONField`` -> ``JSONString``.

    The whole node type must be byte-identical (names + nullability) between the
    two backends after ``normalize_sdl`` (ordering/description only).
    """
    _configure_django()

    import graphene
    from django.db import models
    from graphql.utilities import print_schema

    from django_graphex.fields import DjangoObjectField
    from django_graphex.types import DjangoObjectType

    backend = os.environ.get("GDX_BACKEND", "graphene")

    class SeedScalarModel(models.Model):
        title = models.CharField(max_length=100)  # NON-NULL CharField (#1494)
        when_date = models.DateField()
        when_dt = models.DateTimeField()
        when_time = models.TimeField()
        ext_id = models.UUIDField()
        amount = models.DecimalField(max_digits=10, decimal_places=2)
        payload = models.JSONField()

        class Meta:
            app_label = "tests"

    _OUTPUT_FIELDS = (
        "id",
        "title",
        "when_date",
        "when_dt",
        "when_time",
        "ext_id",
        "amount",
        "payload",
    )

    class SeedScalarType(DjangoObjectType):
        class Meta:
            model = SeedScalarModel
            only_fields = _OUTPUT_FIELDS

    class SeedQuery(graphene.ObjectType):
        scalar_node = DjangoObjectField(SeedScalarType)

    if backend == "native":
        from django_graphex.native.base import get_shared_output_registry
        from django_graphex.native.registry_compiler import compile_all_outputs
        from django_graphex.schema import DjangoGraphQLSchema

        compile_all_outputs()
        schema = DjangoGraphQLSchema(query=SeedQuery)
        if os.environ.get("GDX_SEED_TRACE"):
            query_type = schema.graphql_schema.query_type
            field_type = query_type.fields["scalarNode"].type
            canonical = get_shared_output_registry().get_compiled(SeedScalarModel)
            is_native = field_type is canonical and "gdx" in (
                field_type.extensions or {}
            )
            sys.stderr.write(
                "GDX_SEED_PATH=native\n"
                if is_native
                else "GDX_SEED_PATH=graphene-fallback\n"
            )
        return print_schema(schema.graphql_schema)

    graphene_schema = graphene.Schema(query=SeedQuery)
    if os.environ.get("GDX_SEED_TRACE"):
        sys.stderr.write("GDX_SEED_PATH=graphene\n")
    return print_schema(graphene_schema.graphql_schema)


def build_relation_node_seed_sdl() -> str:
    """Build the Slice-D/E OUTPUT field/relation parity seed SDL.

    This is the deliverable that PROVES the native output compiler matches the
    graphene v1 contract for the FULL field/relation surface (Slices D + E +
    the FK-relation-output-nullability divergence). It builds an output node
    type carrying:

    * ``extra`` — a DECLARED ``graphene.String()`` non-model field (Slice D:
      graphene captures it via ``_meta.fields``; native must emit it too,
      matching name + type + nullability).
    * ``computed`` — a DECLARED ``graphene.Int(description=...)`` non-model
      field (Slice D).
    * ``author`` — a REQUIRED (non-null DB) ``ForeignKey``. graphene renders
      OUTPUT FK ALWAYS NULLABLE (``author: AuthorType``); native must NOT wrap
      it in ``GraphQLNonNull`` (the FK-relation-output-nullability fix).
    * ``category`` — a NULLABLE ``ForeignKey`` (``category: CategoryType``).
    * ``tags`` / ``co_authors`` — ``ManyToManyField`` (Slice E: graphene renders
      the auto-derived ``<Model>ListType`` results/totalCount container, NOT a
      plain ``[Node]`` list).
    * ``comments`` — a REVERSE FK (``ManyToOneRel``) (Slice E: ``CommentListType``
      container via the reverse accessor).
    * ``author_profile`` (on ``SeedAuthorType``) — a REVERSE O2O
      (``OneToOneRel``, the reverse side of ``AuthorProfile.author``). graphene
      renders this as a SINGLE nullable Field (``authorProfile:
      SeedAuthorProfileType``) via ``convert_onetoone_field_to_djangomodel``, NOT
      a ``<Model>ListType`` container. ``OneToOneRel`` subclasses
      ``ManyToOneRel``, so the native ``_is_many_relation`` check must EXCLUDE it
      or it would wrongly render as ``authorProfile: AuthorProfileListType`` — a
      reverse-O2O parity regression this seed pins.

    Uses the REAL ``tests`` models so the auto-derived list-type NAMES
    (``AuthorListType`` / ``CommentListType`` / ``TagListType``) and FK target
    type names are identical between the two backends. The whole reachable graph
    must be byte-identical (names + nullability + args) after ``normalize_sdl``.
    """
    _configure_django()

    import graphene
    from graphql.utilities import print_schema

    from django_graphex.fields import DjangoObjectField
    from django_graphex.registry import Registry
    from django_graphex.types import DjangoObjectType
    from tests.models import Author, AuthorProfile, Category, Comment, Post, Tag

    backend = os.environ.get("GDX_BACKEND", "graphene")

    # Isolated registry so this seed's types never collide with other seeds'
    # types registered in the global registry within the same process.
    seed_registry = Registry()

    class SeedAuthorProfileType(DjangoObjectType):
        class Meta:
            model = AuthorProfile
            registry = seed_registry
            only_fields = ("id", "bio")

    class SeedAuthorType(DjangoObjectType):
        class Meta:
            model = Author
            registry = seed_registry
            # ``author_profile`` is a reverse O2O (OneToOneRel): graphene renders
            # it as a SINGLE nullable Field, NOT a list container. Pins the
            # OneToOneRel-misclassification fix in ``_is_many_relation``.
            only_fields = ("id", "name", "author_profile")

    class SeedCategoryType(DjangoObjectType):
        class Meta:
            model = Category
            registry = seed_registry
            only_fields = ("id", "title")

    class SeedTagType(DjangoObjectType):
        class Meta:
            model = Tag
            registry = seed_registry
            only_fields = ("id", "label")

    class SeedCommentType(DjangoObjectType):
        class Meta:
            model = Comment
            registry = seed_registry
            only_fields = ("id", "body")

    class SeedPostType(DjangoObjectType):
        # Slice D: DECLARED non-model fields (never enter model._meta).
        extra = graphene.String()
        computed = graphene.Int(description="declared int")

        class Meta:
            model = Post
            registry = seed_registry
            only_fields = (
                "id",
                "title",
                "author",  # required FK -> nullable on output
                "category",  # nullable FK
                "tags",  # M2M -> TagListType container
                "co_authors",  # M2M -> AuthorListType container
                "comments",  # reverse FK -> CommentListType container
            )

        def resolve_extra(self, info: object) -> str:
            return "x"

    class SeedQuery(graphene.ObjectType):
        post = DjangoObjectField(SeedPostType)

    if backend == "native":
        from django_graphex.native.base import get_shared_output_registry
        from django_graphex.native.registry_compiler import compile_all_outputs
        from django_graphex.schema import DjangoGraphQLSchema

        compile_all_outputs()
        schema = DjangoGraphQLSchema(query=SeedQuery)
        if os.environ.get("GDX_SEED_TRACE"):
            query_type = schema.graphql_schema.query_type
            field_type = query_type.fields["post"].type
            canonical = get_shared_output_registry().get_compiled(Post)
            is_native = field_type is canonical and "gdx" in (
                field_type.extensions or {}
            )
            sys.stderr.write(
                "GDX_SEED_PATH=native\n"
                if is_native
                else "GDX_SEED_PATH=graphene-fallback\n"
            )
        return print_schema(schema.graphql_schema)

    graphene_schema = graphene.Schema(query=SeedQuery)
    if os.environ.get("GDX_SEED_TRACE"):
        sys.stderr.write("GDX_SEED_PATH=graphene\n")
    return print_schema(graphene_schema.graphql_schema)


def build_filter_seed_sdl() -> str:
    """Build the WU4 ``ArticleFilterInput`` filter-input seed SDL for the backend.

    Builds the ``<Model>FilterInput`` for a filter-bearing model under the active
    backend's filter builder and renders it as a query-field argument so
    ``print_schema`` emits the full nested input shape — including the recursive
    ``and`` / ``or`` / ``not`` combinators, the per-field ``<Field>Lookups``
    inputs, the choices enum, and the nested relation filter input.

    The model carries a ``CharField`` (``title``, text lookups), a choices field
    (``status`` -> shared GraphQLEnumType), an ordered ``IntegerField`` (``views``,
    range/in list lookups), and a forward FK (``author``) with a nested relation
    declaration. This exercises the FULL filtering surface (A1 scalar map, A2
    and/or/not recursion, A3 thunk, A4 out_name, choices enum, nested relation).

    Filter input fields are ALL nullable on both backends, so the native-vs-
    graphene OUTPUT-scalar nullability divergence (#1494) does NOT surface here —
    the seed renders only the INPUT surface, never the output node type with its
    non-null scalars.

    WU10 EXTENSION (#1509 filter-input date scalars): the seed now ALSO carries
    Date/DateTime/Time lookup fields. graphene-django is internally inconsistent
    on date scalar names — its OUTPUT converter uses ``CustomDate`` /
    ``CustomDateTime`` / ``CustomTime`` while its FILTER-INPUT map uses PLAIN
    ``Date`` / ``DateTime`` / ``Time``. Native must match graphene PER-PATH: the
    native filter-input map references plain-named filter date scalars (distinct
    from the CustomDate-named output singletons). This seed pins that per-path
    reconciliation; the OUTPUT scalar names are covered by the ``node_scalars``
    seed (Slices B + C, #1494 + #1508). The native ``Decimal`` scalar singleton
    (name ``Decimal``) matches graphene's filter-input ``Decimal`` for
    DecimalField lookups.
    """
    _configure_django()

    from django.db import models
    from graphql.utilities import print_schema

    from django_graphex.registry import Registry
    from tests.models import Author

    backend = os.environ.get("GDX_BACKEND", "graphene")

    class SeedArticle(models.Model):
        STATUS = (("draft", "Draft"), ("published", "Published"))
        title = models.CharField(max_length=200)
        status = models.CharField(max_length=20, choices=STATUS, default="draft")
        views = models.IntegerField(default=0)
        # Date/DateTime/Time lookups exercise the filter-input date scalar names
        # (#1509): graphene renders PLAIN ``Date`` / ``DateTime`` / ``Time`` on
        # the filter-input path (NOT the CustomDate output names), so native must
        # too. Pins the per-path date-scalar reconciliation.
        published_on = models.DateField(null=True)
        published_at = models.DateTimeField(null=True)
        published_time = models.TimeField(null=True)
        author = models.ForeignKey(
            Author, related_name="seed_articles", on_delete=models.CASCADE
        )

        class Meta:
            app_label = "tests"

    filter_fields = {
        "title": ("exact", "icontains"),
        "status": ("exact", "in"),
        "views": ("exact", "gt", "gte", "lt", "lte", "range", "in", "isnull"),
        "published_on": ("exact", "gt", "lt", "range", "isnull"),
        "published_at": ("exact", "gt", "lt", "range"),
        "published_time": ("exact", "gt", "lt"),
        "author__name": ("exact", "icontains"),
    }

    registry = Registry()

    # Register the ``status`` choices enum FIRST, mirroring how a real schema's
    # OUTPUT node type registers it before the filter input is built. Without
    # this, the graphene filter builder falls back to ``String`` (it only REUSES
    # a pre-registered enum) while the native builder self-builds one — a false
    # divergence. In a real schema both reuse the converter-registered enum.
    status_field = SeedArticle._meta.get_field("status")

    if backend == "native":
        from graphql import (
            GraphQLArgument,
            GraphQLField,
            GraphQLList,
            GraphQLObjectType,
            GraphQLSchema,
            GraphQLString,
        )

        from django_graphex.filtering.native_schema import (
            _choices_enum as native_choices_enum,
        )
        from django_graphex.filtering.native_schema import (
            build_filter_input_type as native_build,
        )

        # Build + register the native GraphQLEnumType (idempotent, memoized).
        native_choices_enum(status_field, registry)
        filter_input = native_build(SeedArticle, filter_fields, registry=registry)

        query_type = GraphQLObjectType(
            "SeedQuery",
            lambda: {
                "articles": GraphQLField(
                    GraphQLList(GraphQLString),
                    args={"filter": GraphQLArgument(filter_input)},
                )
            },
        )
        schema = GraphQLSchema(query=query_type)
        if os.environ.get("GDX_SEED_TRACE"):
            # Anti-tautology sentinel: prove the printed filter input is the
            # NATIVE graphql-core builder's output (gdx-bearing), not a graphene
            # type smuggled in. Emitted to stderr so stdout stays pure SDL.
            from graphql import GraphQLInputObjectType

            printed = schema.type_map.get("SeedArticleFilterinput")
            is_native = isinstance(printed, GraphQLInputObjectType) and "gdx" in (
                (printed.extensions or {})
            )
            sys.stderr.write(
                "GDX_SEED_PATH=native\n"
                if is_native
                else "GDX_SEED_PATH=graphene-fallback\n"
            )
        return print_schema(schema)

    # Graphene path.
    import graphene
    from graphql import GraphQLInputObjectType as _GqlInput

    from django_graphex.converter import convert_django_field_with_choices
    from django_graphex.filtering.schema import (
        build_filter_input_type as graphene_build,
    )

    # Register the graphene choices enum FIRST (the OUTPUT converter would do
    # this in a real schema) so the graphene filter builder REUSES it instead of
    # degrading to ``String``. Same registry key as the native path.
    convert_django_field_with_choices(status_field, registry)
    filter_input = graphene_build(SeedArticle, filter_fields, registry=registry)

    class SeedQuery(graphene.ObjectType):
        articles = graphene.List(
            graphene.String, filter=graphene.Argument(filter_input)
        )

    graphene_schema = graphene.Schema(query=SeedQuery)
    if os.environ.get("GDX_SEED_TRACE"):
        printed = graphene_schema.graphql_schema.type_map.get("SeedArticleFilterinput")
        # Graphene builds graphql-core input types WITHOUT the gdx extension.
        is_graphene = isinstance(printed, _GqlInput) and "gdx" not in (
            (printed.extensions or {})
        )
        sys.stderr.write(
            "GDX_SEED_PATH=graphene\n"
            if is_graphene
            else "GDX_SEED_PATH=unexpected\n"
        )
    return print_schema(graphene_schema.graphql_schema)


def build_full_schema_sdl() -> str:
    """Build the ENTIRE ``tests/schema.py`` schema SDL for the active backend.

    This is the WU10 BINDING Phase-5 closing gate (D7): the full production test
    schema — every query field (``all_users`` / ``all_users1..4`` / ``user`` /
    ``user1`` / ``user2`` / ``users`` / the explicit-name ``datetime`` / ``date``
    / ``time`` scalar fields), the ``LimitOffset`` pagination containers, the
    ``UserType`` filter inputs, the auto-derived list-object types, AND the full
    ``all_directives`` directive block — assembled under each backend in a
    SEPARATE process and printed via ``print_schema``.

    Under ``native`` the schema assembles through ``DjangoGraphQLSchema`` (the
    native root compiler + native output registry + native filter builder +
    forwarded directives), bypassing ``graphene.Schema`` entirely. Under
    ``graphene`` it uses the already-built ``tests.schema.schema``. After
    ``normalize_sdl`` (ordering only) the two MUST be byte-identical.

    The native path passes ``directives=all_directives`` exactly as
    ``tests/schema.py`` does for the graphene schema, so the directive block
    matches; and it honors each field's explicit ``name=`` kwarg (e.g.
    ``CustomDate(name="date")``) so ``date`` / ``datetime`` / ``time`` render
    identically (not ``date_`` / ``datetime_`` / ``time_``).
    """
    _configure_django()

    from graphql.utilities import print_schema

    backend = os.environ.get("GDX_BACKEND", "graphene")

    if backend == "native":
        from django_graphex import all_directives
        from django_graphex.native.registry_compiler import compile_all_outputs
        from django_graphex.schema import DjangoGraphQLSchema
        from tests.schema import Query

        # Compile every registered output type (app-ready normally does this;
        # the seed process must do it explicitly before native assembly).
        compile_all_outputs()
        schema = DjangoGraphQLSchema(query=Query, directives=all_directives)
        if os.environ.get("GDX_SEED_TRACE"):
            # Anti-tautology sentinel: prove the native query root is a
            # graphql-core GraphQLObjectType carrying extensions['gdx'] (the
            # native assembly path), NOT a graphene-built root smuggled in.
            from graphql import GraphQLObjectType

            qt = schema.graphql_schema.query_type
            is_native = (
                isinstance(qt, GraphQLObjectType)
                and not hasattr(qt, "_meta")
                and "gdx" in (qt.extensions or {})
            )
            sys.stderr.write(
                "GDX_SEED_PATH=native\n"
                if is_native
                else "GDX_SEED_PATH=graphene-fallback\n"
            )
        return print_schema(schema.graphql_schema)

    # Graphene path: the real production test schema, built with all_directives.
    from tests.schema import schema as graphene_schema

    if os.environ.get("GDX_SEED_TRACE"):
        sys.stderr.write("GDX_SEED_PATH=graphene\n")
    return print_schema(graphene_schema.graphql_schema)


def build_types_unreferenced_seed_sdl() -> str:
    """Build the ``types=`` forwarding parity seed SDL for the active backend.

    Renders a Query with a single scalar field plus an UNREFERENCED plain
    ``graphene.ObjectType`` (``SeedUnreferencedType``) that is NOT reachable from
    Query, injected via the ``types=`` kwarg.

    graphene's ``graphene.Schema`` forwards ``types=`` (a list of graphene type
    CLASSES of types to FORCE into the schema even when unreferenced) through its
    ``TypeMap`` into the underlying graphql-core ``GraphQLSchema(..., types=...)``,
    so the unreferenced type appears in BOTH the type_map and the printed SDL.
    The native ``DjangoGraphQLSchema`` assembly must forward ``types=`` identically
    (mapping each graphene class to its canonical native graphql-core type) or the
    unreferenced type is SILENTLY dropped — an SDL-parity divergence.

    After ``normalize_sdl`` (ordering only) the two backends MUST be byte-equal:
    ``SeedUnreferencedType`` appears in BOTH.
    """
    _configure_django()

    import graphene
    from graphql.utilities import print_schema

    backend = os.environ.get("GDX_BACKEND", "graphene")

    class SeedUnreferencedType(graphene.ObjectType):
        # A plain ObjectType NOT reachable from Query — only forced into the
        # schema via the ``types=`` kwarg. The whole point of ``types=``.
        secret = graphene.String()
        count = graphene.Int(description="an unreferenced count field")

    class SeedQuery(graphene.ObjectType):
        # Deliberately does NOT reference SeedUnreferencedType.
        hello = graphene.String()

    if backend == "native":
        from graphql import GraphQLObjectType

        from django_graphex.native.registry_compiler import compile_all_outputs
        from django_graphex.schema import DjangoGraphQLSchema

        compile_all_outputs()
        schema = DjangoGraphQLSchema(
            query=SeedQuery, types=[SeedUnreferencedType]
        )
        if os.environ.get("GDX_SEED_TRACE"):
            # Anti-tautology sentinel: prove (a) the native assembly path was
            # taken (query root is a gdx-bearing graphql-core type, no graphene
            # _meta) and (b) the forwarded ``types=`` entry is the native
            # compiled instance present in the type_map.
            qt = schema.graphql_schema.query_type
            forwarded = schema.graphql_schema.type_map.get("SeedUnreferencedType")
            is_native = (
                isinstance(qt, GraphQLObjectType)
                and not hasattr(qt, "_meta")
                and "gdx" in (qt.extensions or {})
                and isinstance(forwarded, GraphQLObjectType)
                and "gdx" in (forwarded.extensions or {})
            )
            sys.stderr.write(
                "GDX_SEED_PATH=native\n"
                if is_native
                else "GDX_SEED_PATH=graphene-fallback\n"
            )
        return print_schema(schema.graphql_schema)

    graphene_schema = graphene.Schema(query=SeedQuery, types=[SeedUnreferencedType])
    if os.environ.get("GDX_SEED_TRACE"):
        sys.stderr.write("GDX_SEED_PATH=graphene\n")
    return print_schema(graphene_schema.graphql_schema)


def main() -> int:
    seed = os.environ.get("GDX_SEED", "node")
    if seed == "filter":
        sys.stdout.write(build_filter_seed_sdl())
    elif seed == "node_scalars":
        sys.stdout.write(build_scalar_node_seed_sdl())
    elif seed == "relations":
        sys.stdout.write(build_relation_node_seed_sdl())
    elif seed == "full":
        sys.stdout.write(build_full_schema_sdl())
    elif seed == "types_unreferenced":
        sys.stdout.write(build_types_unreferenced_seed_sdl())
    else:
        sys.stdout.write(build_seed_sdl())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
