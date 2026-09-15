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
    def __init__(self, name: str) -> None:
        super().__init__(f"unknown provider: {name}")
        self.name = name


def register_provider(name: str, factory: ProviderFactory, *, replace: bool = False) -> None:
    if not replace and name in _REGISTRY:
        raise ValueError(f"provider already registered: {name}")
    _REGISTRY[name] = factory


def unregister_provider(name: str) -> None:
    _REGISTRY.pop(name, None)


def get_provider(name: str, **kwargs: object) -> Provider:
    factory = _REGISTRY.get(name)
    if factory is None:
        raise UnknownProviderError(name)
    return factory(**kwargs)  # type: ignore[arg-type]


def list_providers() -> list[str]:
    return sorted(_REGISTRY)
