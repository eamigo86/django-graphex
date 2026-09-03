"""Single Django settings module shared by all four benchmarked libraries.

The ONLY thing that varies per library is the value of the ``BENCH_LIB`` env var,
which selects:
  * which extra INSTALLED_APPS entry (if any) the library needs, via ``LIB_APPS``;
  * which ``libs/<BENCH_LIB>/bench_schema.py`` module ``config.urls`` mounts.

Everything else — database, DEBUG, models, seed — is identical across libraries.
Fairness rule: no per-library tuning of Django itself lives here. Each library's
idiomatic knobs (query optimizer, dataloaders, etc.) live in its own
``bench_schema.py``, never in this settings module.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Which library are we benchmarking this run? Set by harness.py / run_all.sh.
BENCH_LIB = os.environ.get("BENCH_LIB", "graphex")

SECRET_KEY = "benchmark-not-a-secret"
# DEBUG must be False: DEBUG=True installs query logging that skews timings and
# changes error handling. The benchmark measures production-shaped behavior.
DEBUG = False
ALLOWED_HOSTS = ["*", "testserver"]

# Extra INSTALLED_APPS each library needs, keyed by BENCH_LIB. django-graphex
# must be installed as an app (its AppConfig.ready() compiles the schema types).
# graphene-django registers "graphene_django". strawberry-django and ariadne do
# not require an app entry for this benchmark's feature set.
LIB_APPS = {
    "graphex": ["django_graphex"],
    "graphene": ["graphene_django"],
    "strawberry": [],
    "ariadne": [],
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "benchapp",
    *LIB_APPS.get(BENCH_LIB, []),
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("BENCH_DATABASE", BASE_DIR / "db.sqlite3"),
    }
}

USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- django-graphex schema pointer (ignored by the other libraries) ----------
# GraphQLView reads DJANGO_GRAPHEX["SCHEMA"] when no explicit schema is passed.
# bench_schema.py passes the schema explicitly, so this is a belt-and-suspenders
# entry that also lets `manage.py`-style tooling find the schema if needed.
DJANGO_GRAPHEX = {
    "SCHEMA": "libs.graphex.bench_schema.schema",
}

# --- graphene-django schema pointer (ignored by the other libraries) ---------
GRAPHENE = {
    "SCHEMA": "libs.graphene.bench_schema.schema",
}
