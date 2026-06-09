import os
import sys

import django
from django.core import management


def pytest_addoption(parser):
    parser.addoption(
        "--no-pkgroot",
        action="store_true",
        default=False,
        help="Remove package root directory from sys.path, ensuring that "
        "django_graphex is imported from the installed site-packages. "
        "Used for testing the distribution.",
    )
    parser.addoption(
        "--staticfiles",
        action="store_true",
        default=False,
        help="Run tests with static files collection, using manifest "
        "staticfiles storage. Used for testing the distribution.",
    )


try:
    import channels  # noqa: F401

    HAS_CHANNELS = True
except ImportError:
    HAS_CHANNELS = False


def pytest_configure(config):
    from django.conf import settings

    # Subscriptions are an optional extra: only wire channels when it is present
    # so the base-install CI job (no extra) can still configure and run.
    channels_apps = ("channels",) if HAS_CHANNELS else ()
    channel_layers = (
        {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
        if HAS_CHANNELS
        else {}
    )

    settings.configure(
        CHANNEL_LAYERS=channel_layers,
        ALLOWED_HOSTS=["*"],
        DEBUG_PROPAGATE_EXCEPTIONS=True,
        DATABASES={
            "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
        },
        SITE_ID=1,
        SECRET_KEY="not very secret in tests",
        USE_I18N=True,
        STATIC_URL="/static/",
        ROOT_URLCONF="tests.urls",
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
                "OPTIONS": {"debug": True},  # We want template errors to raise
            }
        ],
        MIDDLEWARE=(
            "django.middleware.common.CommonMiddleware",
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            "django.contrib.messages.middleware.MessageMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
        ),
        INSTALLED_APPS=(
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.sites",
            "django.contrib.staticfiles",
            *channels_apps,
            "tests",
        ),
        PASSWORD_HASHERS=("django.contrib.auth.hashers.MD5PasswordHasher",),
        GRAPHENE={
            "SCHEMA": "tests.schema.schema",
            "MIDDLEWARE": ["django_graphex.ExtraGraphQLDirectiveMiddleware"],
        },
        AUTHENTICATION_BACKENDS=(
            "django.contrib.auth.backends.ModelBackend",
            "guardian.backends.ObjectPermissionBackend",
        ),
    )

    # FIXME(eclar): necessary ?
    if config.getoption("--no-pkgroot"):
        sys.path.pop(0)

        # import the package before pytest re-adds the package root directory.
        import django_graphex

        package_dir = os.path.join(os.getcwd(), "django_graphex")
        assert not django_graphex.__file__.startswith(package_dir)

    # Manifest storage will raise an exception if static files are not present (ie, a packaging failure).
    if config.getoption("--staticfiles"):
        import django_graphex

        settings.STATIC_ROOT = os.path.join(
            os.path.dirname(django_graphex.__file__), "static-root"
        )
        settings.STATICFILES_STORAGE = (
            "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
        )

    django.setup()

    if config.getoption("--staticfiles"):
        management.call_command("collectstatic", verbosity=0, interactive=False)
