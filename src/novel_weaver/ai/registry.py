# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Named provider lookup. Registration is process-local and replaceable."""

from __future__ import annotations

from collections.abc import Callable

from novel_weaver.ai.base import Provider
from novel_weaver.ai.failover import FailoverProvider
from novel_weaver.ai.fake import FakeProvider
from novel_weaver.ai.openai_compat import OpenAICompatibleProvider
from novel_weaver.ai.template import TemplateProvider

ProviderFactory = Callable[..., Provider]

_REGISTRY: dict[str, ProviderFactory] = {
    "fake": FakeProvider,
    "template": TemplateProvider,
    "openai": OpenAICompatibleProvider,
    "llm": OpenAICompatibleProvider,
    "failover": FailoverProvider,
}


class UnknownProviderError(KeyError):
    """Raised when a requested provider name is not registered."""

    def __init__(self, name: str) -> None:
        """Create the error for a missing provider name.

        Args:
            name: Provider name that was not found in the registry.
        """
        super().__init__(f"unknown provider: {name}")
        self.name = name


def register_provider(name: str, factory: ProviderFactory, *, replace: bool = False) -> None:
    """Register a provider factory under a process-local name.

    Args:
        name: Lookup key for ``get_provider``.
        factory: Callable that returns a ``Provider`` instance.
        replace: When ``True``, overwrite an existing registration.

    Returns:
        None.

    Raises:
        ValueError: If the name is already registered and ``replace`` is false.
    """
    if not replace and name in _REGISTRY:
        raise ValueError(f"provider already registered: {name}")
    _REGISTRY[name] = factory


def unregister_provider(name: str) -> None:
    """Remove a registration if present.

    Args:
        name: Provider name to drop; missing names are ignored.

    Returns:
        None.
    """
    _REGISTRY.pop(name, None)


def get_provider(name: str, **kwargs: object) -> Provider:
    """Instantiate a registered provider by name.

    Args:
        name: Registered provider name.
        **kwargs: Constructor keyword arguments for the factory.

    Returns:
        A constructed ``Provider`` instance.

    Raises:
        UnknownProviderError: If the name is not registered.
    """
    factory = _REGISTRY.get(name)
    if factory is None:
        raise UnknownProviderError(name)
    return factory(**kwargs)


def list_providers() -> list[str]:
    """List registered provider names in sorted order.

    Returns:
        Sorted list of registry keys.
    """
    return sorted(_REGISTRY)
