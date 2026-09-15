# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""AI execution layer: replaceable providers, never owns story truth."""

from novel_weaver.ai.base import (
    GenerationRequest,
    GenerationResult,
    Provider,
    ProviderError,
    TokenUsage,
)
from novel_weaver.ai.fake import FakeProvider
from novel_weaver.ai.registry import get_provider, list_providers, register_provider
from novel_weaver.ai.retry import retry_with_backoff
from novel_weaver.ai.template import TemplateProvider

__all__ = [
    "FakeProvider",
    "GenerationRequest",
    "GenerationResult",
    "Provider",
    "ProviderError",
    "TemplateProvider",
    "TokenUsage",
    "get_provider",
    "list_providers",
    "register_provider",
    "retry_with_backoff",
]
