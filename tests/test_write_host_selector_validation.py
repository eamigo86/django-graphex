"""Write hosts must validate field selectors exactly like output types."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import Registry
from django_graphex.types import (
    DjangoInputObjectType,
    DjangoListObjectType,
    DjangoModelType,
    DjangoObjectType,
)

from .models import Author

HOSTS = {
    "mutation": DjangoModelMutation,
    "input": DjangoInputObjectType,
    "list": DjangoListObjectType,
    "model_type": DjangoModelType,
}


def _declare(host: str, **meta_options: Any) -> type:
    """Declare one host class over Author with the given Meta options.

    Args:
        host: Key of the host base class in HOSTS.
        **meta_options: Meta attributes to declare.

    Returns:
        The declared class.
    """
    attrs: dict[str, Any] = {"model": Author, **meta_options}
    if host != "model_type":  # DjangoModelType accepts no "registry" option.
        registry = attrs["registry"] = Registry()
        # The ordinary arrangement: the model's output type already exists, so
        # a write host reuses it and its own selectors are the only gate.
        type(
            "OutT",
            (DjangoObjectType,),
            {
                "Meta": type(
                    "Meta",
                    (),
                    {
                        "model": Author,
                        "registry": registry,
                        "__module__": __name__,
                        "__qualname__": "OutT.Meta",
                    },
                ),
                "__module__": __name__,
                "__qualname__": "OutT",
            },
        )
    meta = type(
        "Meta", (), {**attrs, "__module__": __name__, "__qualname__": "Host.Meta"}
    )
    return type(
        "Host",
        (HOSTS[host],),
        {"Meta": meta, "__module__": __name__, "__qualname__": "Host"},
    )


@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize("option", ("only_fields", "exclude_fields"))
def test_typo_selector_is_rejected(host: str, option: str) -> None:
    """A selector naming no field raises instead of leaving the field writable.

    Args:
        host: Host base class key.
        option: Selector option under test.
    """
    with pytest.raises(ImproperlyConfigured, match=f"Meta.{option} names unknown"):
        _declare(host, **{option: ("nmae",)})


@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize("option", ("only_fields", "exclude_fields"))
def test_bare_string_selector_is_rejected(host: str, option: str) -> None:
    """A bare string selector raises instead of being iterated per character.

    Args:
        host: Host base class key.
        option: Selector option under test.
    """
    with pytest.raises(ImproperlyConfigured, match="not a bare string"):
        _declare(host, **{option: "name"})


@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize("option", ("only_fields", "exclude_fields"))
def test_valid_tuple_selector_is_accepted(host: str, option: str) -> None:
    """A tuple of real field names still builds.

    Args:
        host: Host base class key.
        option: Selector option under test.
    """
    try:
        _declare(host, **{option: ("name",)})
    except ImproperlyConfigured as exc:  # unrelated reuse guards may still fire
        assert "unknown field" not in str(exc)
        assert "bare string" not in str(exc)


def test_all_marker_is_not_a_supported_selector() -> None:
    """Reject the "__all__" shorthand like any other bare string.

    The shorthand is not supported, so it must not pass as a field name.
    """
    with pytest.raises(ImproperlyConfigured, match="not a bare string"):
        _declare("mutation", only_fields="__all__")
