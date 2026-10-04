"""Default filter lookup behavior for non-text and custom configurations."""

from django.test import override_settings

from django_graphex.filtering.lookups import DEFAULT_LOOKUPS, default_lookups_for


def test_nontext_unordered_field_uses_only_common_lookups() -> None:
    """A JSON field does not inherit text or ordered comparison lookups.

    Its exposed filter surface must stay limited to the common defaults.
    """
    assert default_lookups_for("JSONField") == tuple(DEFAULT_LOOKUPS)


@override_settings(
    DJANGO_GRAPHEX={"COMMON_FILTER_LOOKUPS": ("exact", "exact", "isnull")}
)
def test_custom_common_lookups_keep_first_occurrence_order() -> None:
    """Configured repeated lookup names appear only once on the input surface.

    Deduplication retains the declared ordering rather than sorting names.
    """
    assert default_lookups_for("JSONField") == ("exact", "isnull")
