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
GRAPHENE = {
    "SCHEMA": "blog.schema.schema",
    "MIDDLEWARE": [
        # Block schema introspection unless allowed (see DJANGO_GRAPHEX).
        "django_graphex.DisableIntrospectionMiddleware",
        # Require an authenticated user on the schema's private fields.
        "django_graphex.AuthenticatedFieldsMiddleware",
        # Process @directives.
        "django_graphex.GraphQLDirectiveMiddleware",
    ],
}

DJANGO_GRAPHEX = {
    "DEFAULT_PAGE_SIZE": 10,
    "MAX_PAGE_SIZE": 100,
    # Keep introspection ON so GraphiQL works. Flip to False to see the
    # DisableIntrospectionMiddleware block it (superusers still bypass).
    "ALLOW_INTROSPECTION": True,
    # Subscriptions: serialize the full instance in notifications (the default is
    # id-only). Per-subscription Meta.serialize_data can override this.
    "SUBSCRIPTION_SERIALIZE_DATA": True,
    # ---------------------------------------------------------------------------
    # Query depth limiting (DepthLimitValidationRule — wired in GraphQLView).
    # Reject queries that nest objects more than N levels deep.
    # None = no global limit; per-type max_deep still applies on top.
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
