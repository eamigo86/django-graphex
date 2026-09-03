"""Configure the shared Django benchmark application.

The application contains the library-independent models used by every adapter.
"""

from django.apps import AppConfig


class BenchappConfig(AppConfig):
    """Register the shared benchmark models with Django.

    The configuration keeps model discovery identical for every adapter.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "benchapp"
