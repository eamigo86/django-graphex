"""Django settings for the django-graphex playground."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "playground-not-secret"  # noqa: S105 - local playground only
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    # `daphne` first so `manage.py runserver` serves ASGI (http + websocket).
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "channels",
    "django_graphex",
    # Local
    "blog",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# In-memory channel layer: fine for a single-process local playground.
# Use channels-redis in production.
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# ---------------------------------------------------------------------------
# django-graphex
# ---------------------------------------------------------------------------
# 2.0 BREAKING CHANGE: every django-graphex setting is read from the SINGLE
# ``DJANGO_GRAPHEX`` namespace (schema/middleware/subscription keys included);
# the legacy ``GRAPHENE`` namespace is no longer consulted.
DJANGO_GRAPHEX = {
    "SCHEMA": "blog.schema.schema",
    "MIDDLEWARE": [
        # Block schema introspection unless allowed (see ALLOW_INTROSPECTION).
        "django_graphex.security.DisableIntrospectionMiddleware",
        # Require an authenticated user on the schema's private fields.
        "django_graphex.security.AuthenticatedFieldsMiddleware",
        # Process @directives.
        "django_graphex.middleware.GraphQLDirectiveMiddleware",
    ],
    "DEFAULT_PAGE_SIZE": 10,
    "MAX_PAGE_SIZE": 100,
    # Keep introspection ON so GraphiQL works. Flip to False to see the
    # DisableIntrospectionMiddleware block it (superusers still bypass).
    "ALLOW_INTROSPECTION": True,
    # Subscriptions: serialize the full instance in notifications (the default is
    # id-only). Per-subscription Meta.payload_mode can override this.
    "SUBSCRIPTION_PAYLOAD_MODE": "full",
    # ---------------------------------------------------------------------------
    # Permission-scoped schema (2.2.0). Every request to AuthenticatedGraphQLView
    # (/graphql/secure/) validates against a schema PRUNED to the caller's Django
    # model permissions: a field they may not use does not exist for them, so
    # selecting it is a plain "Cannot query field" — a not-found, never an
    # authorization error that would confirm it is there. An active superuser (the
    # seeded `demo` user) always gets the full schema, so the flag is invisible
    # until you log in as an ordinary user; the public /graphql/ endpoint is never
    # pruned, which is why the runtime gate (permission_classes) is the half that
    # must not be skipped. Flip to False to watch the pruned fields come back.
    #
    # The subscription transports are NOT pruned here: this playground wires both
    # of them with `schema=` (config/urls.py for SSE, blog/consumers.py for WS),
    # and pruning only happens through `schema_provider=`. To scope them too,
    # pass `schema_provider=lambda user: pruned_schema_for(user, full)` from
    # django_graphex.core.permission_signature_cache — see
    # docs/usage/subscriptions.md.
    "PERMISSION_SCOPED_SCHEMA": True,
    # ---------------------------------------------------------------------------
    # TWO SETTINGS THIS FILE DELIBERATELY DOES NOT SET. Both ship ON, so pinning
    # them here would only restate a default — but a default is exactly the thing
    # a project forgets it depends on, and both of these are walls you would
    # otherwise meet for the first time in production. They are named here so a
    # reader copying this file meets them at their desk instead. Uncomment either
    # line to change it; the values shown ARE the defaults.
    #
    # REQUIRE_CSRF_HEADER (default True). This endpoint is `csrf_exempt` and
    # accepts form-encoded and multipart bodies, and both are CORS-SIMPLE content
    # types: a `<form>` on any origin posts them with NO preflight and the browser
    # attaches the victim's session cookie — a plain CSRF hole on every mutation,
    # and on the SSE endpoint too. The guard demands the `X-Requested-With`
    # header, which is not CORS-safelisted, so requiring it forces back the
    # preflight a forged request cannot pass. The value is never inspected, and
    # the refusal (HTTP 403) happens before the body is read.
    #   Who pays: form-encoded clients, and the multipart upload host
    #   (`documentCreate` in blog/schema.py) — see the curl invocation there.
    #   Who does not: `application/json` and `application/graphql` clients, which
    #   already required a preflight. That is why GraphiQL needs nothing.
    #   "REQUIRE_CSRF_HEADER": True,
    #
    # MAX_SUBSCRIPTIONS_PER_CONNECTION (default 50). Every live
    # `graphql-transport-ws` operation joins its own channel-layer group, so one
    # socket with no ceiling turns a single connection into hundreds of
    # subscribers — the HTTP side has bounded its analogous surface with
    # MAX_BATCH_SIZE since 1.2.1. A `subscribe` past the cap gets the transport's
    # own `error` frame naming the limit; the socket and every subscription
    # already running on it survive, and a slot frees itself when its operation
    # ends (client `complete`, stream end, or disconnect). SSE is unaffected — one
    # request carries exactly one subscription. `None` restores the old unbounded
    # behaviour.
    #   "MAX_SUBSCRIPTIONS_PER_CONNECTION": 50,
    # ---------------------------------------------------------------------------
    # Base64 file uploads (v1.3.0, opt-in via Base64FileInput).
    #
    # MAX_UPLOAD_SIZE — maximum decoded size (bytes) of a single upload field.
    # REQUIRED when Base64FileInput is used; raises ImproperlyConfigured if
    # absent and no per-field override is given in the resolver.
    # 5 MB is a reasonable default for the playground demo.
    "MAX_UPLOAD_SIZE": 5 * 1024 * 1024,  # 5 MB per file
    #
    # MAX_REQUEST_BODY_SIZE — total HTTP body limit (bytes), enforced in
    # BaseGraphQLView.dispatch BEFORE JSON parsing. This is the primary memory
    # cap: the entire base64 payload is already in the body before any field
    # resolver runs, so rejecting here prevents full-body allocation above the
    # limit. None = disabled (not recommended for public APIs).
    # 20 MB allows a single 5 MB file (base64 overhead ~4/3 × 5 MB ≈ 6.7 MB)
    # plus JSON scaffolding, with margin for a batch of smaller files.
    # NOTE: this cap only bites AFTER Django's own DATA_UPLOAD_MAX_MEMORY_SIZE
    # has let the JSON body through — see the Django-level setting below.
    "MAX_REQUEST_BODY_SIZE": 20 * 1024 * 1024,  # 20 MB total body
    # ---------------------------------------------------------------------------
    # Query depth limiting (DepthLimitValidationRule — wired in GraphQLView).
    # Reject queries that nest objects more than N levels deep.
    # None = no global limit; per-type max_depth still applies on top.
    # Active here so the playground rejects an over-nested query out of the box:
    "MAX_QUERY_DEPTH": 6,
    # ---------------------------------------------------------------------------
    # Query cost analysis (CostLimitValidationRule — wired in GraphQLView).
    # Reject queries whose estimated cost exceeds the budget; report cost in
    # extensions.cost so clients can see the estimate. None = no budget.
    # Uncomment these to see cost analysis in action:
    #   "MAX_QUERY_COST": 200,
    #   "EXPOSE_QUERY_COST": True,
    # ---------------------------------------------------------------------------
    # Queryset optimization (N+1 avoidance). All five default to the values shown
    # below, so the optimizer is fully ON out of the box. They are listed here
    # (commented) so you can flip any of them and feel the difference — e.g. set
    # OPTIMIZE_QUERYSET=False and watch the SQL panel / assertNumQueries explode.
    #   "OPTIMIZE_QUERYSET": True,           # master switch: select_related /
    #                                        # prefetch_related from the selection.
    #   "OPTIMIZE_ONLY_FIELDS": True,        # .only() column narrowing (root span
    #                                        # + inside each Prefetch child).
    #   "OPTIMIZE_NESTED_PAGINATION": True,  # DB-side ROW_NUMBER() window slicing
    #                                        # of paginated nested lists.
    #   "OPTIMIZE_ANNOTATED_FIELDS": True,   # selection-driven AnnotatedField
    #                                        # .alias()/.annotate() injection.
    #   "OPTIMIZER_SAFE_MODE": False,        # False = fail loud (default); True =
    #                                        # degrade to the un-optimized base on
    #                                        # any optimizer exception and log a WARNING.
    # ---------------------------------------------------------------------------
    # Response caching. Flip CACHE_ACTIVE to True to enable query-result caching:
    #   "CACHE_ACTIVE": True,
    #   "CACHE_TIMEOUT": 60,  # seconds
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files. Under `daphne` (ASGI) they are served by the ASGIStaticFilesHandler
# in asgi.py while DEBUG is True; for production run `collectstatic` and serve
# STATIC_ROOT with a real web server / whitenoise.
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # collectstatic target
STATICFILES_DIRS = [BASE_DIR / "static"]  # project-level static sources

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Media files (uploaded by Base64FileInput demo mutations).
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# A base64 upload travels inside the JSON body, so Django has to hold the whole
# body in memory to parse it — and Django's own default ceiling for that is
# 2.5 MB, well under the 5 MB file the UploadDocument demo advertises. Without
# this, a 5 MB upload is refused by Django with an opaque HTML 400 long before
# MAX_REQUEST_BODY_SIZE (20 MB) or MAX_UPLOAD_SIZE (5 MB) ever sees it. Keep the
# two in step: this value must clear MAX_REQUEST_BODY_SIZE for base64 uploads.
# Multipart uploads do NOT need it — they never land in memory whole. They are
# still capped by MAX_REQUEST_BODY_SIZE, which under ASGI measures the spooled
# body itself and under WSGI compares the declared Content-Length, so that cap
# must clear the largest multipart upload this project accepts on either server.
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024  # 20 MB, matches the body cap
