"""An AttributeError raised while computing a class descriptor must surface."""

from __future__ import annotations

import functools
from typing import Any

import pytest
from django.utils.functional import cached_property as django_cached_property

from django_graphex.core.descriptors import _source_resolver


class _RaisingDescriptor:
    """A non-data descriptor whose lookup fails with an AttributeError."""

    def __get__(self, instance: Any, owner: type | None = None) -> str:
        """Fail while computing the value.

        Args:
            instance: Object being resolved.
            owner: Class holding the descriptor.

        Raises:
            AttributeError: Always, as the lookup itself failed.
        """
        raise AttributeError("descriptor failed")


class _Root:
    """Expose every descriptor kind next to healthy members."""

    healthy = "visible"
    descriptor = _RaisingDescriptor()

    @property
    def plain_property(self) -> str:
        """Fail on a typo inside the getter.

        Returns:
            Never returns.
        """
        return self.nonexistent  # type: ignore[attr-defined,no-any-return]

    @functools.cached_property
    def std_cached(self) -> str:
        """Fail on a typo inside a functools cached_property.

        Returns:
            Never returns.
        """
        return self.nonexistent  # type: ignore[attr-defined,no-any-return]

    @django_cached_property
    def django_cached(self) -> str:
        """Fail on a typo inside Django's cached_property.

        Returns:
            Never returns.
        """
        return self.nonexistent  # type: ignore[attr-defined,no-any-return]

    @functools.cached_property
    def std_cached_ok(self) -> str:
        """Compute normally.

        Returns:
            A value.
        """
        return "computed"


@pytest.mark.parametrize(
    "name", ["plain_property", "std_cached", "django_cached", "descriptor"]
)
def test_attribute_error_inside_a_descriptor_surfaces(name: str) -> None:
    """The original AttributeError reaches the caller instead of null.

    Args:
        name: Source name of the failing descriptor.
    """
    with pytest.raises(AttributeError):
        _source_resolver(name, _Root(), None)


def test_healthy_and_missing_members_are_unchanged() -> None:
    """Healthy descriptors resolve and a truly missing attribute stays null.

    Only a failing descriptor changes behavior.
    """
    root = _Root()
    assert _source_resolver("healthy", root, None) == "visible"
    assert _source_resolver("std_cached_ok", root, None) == "computed"
    assert _source_resolver("missing", root, None) is None


def test_class_with_getattr_keeps_null() -> None:
    """A __getattr__ class cannot tell missing from failing, so it stays null.

    Python discards the descriptor's error before calling __getattr__, so the
    library cannot recover it; the limitation is documented.

    Raises:
        AttributeError: Raised by the test stubs; none escapes the resolver.
    """

    class WithGetattr:
        """Define a failing property and a __getattr__ that re-raises."""

        @property
        def broken(self) -> str:
            """Fail on a typo inside the getter.

            Returns:
                Never returns.
            """
            return self.nonexistent  # type: ignore[attr-defined,no-any-return]

        def __getattr__(self, name: str) -> Any:
            """Report every unknown name as absent.

            Args:
                name: Attribute requested by Python lookup.

            Raises:
                AttributeError: Always.
            """
            raise AttributeError(name)

    assert _source_resolver("broken", WithGetattr(), None) is None
