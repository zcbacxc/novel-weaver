# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Provider contract: models execute tasks; they never write Canon."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from novel_weaver.production.fingerprint import context_fingerprint

DEFAULT_CAPABILITIES: frozenset[str] = frozenset(
    {
        "planning",
        "story_state_extraction",
        "chapter_generation",
        "continuity_review",
        "style_review",
        "revision",
    }
)


class ProviderError(Exception):
    """Provider-side failure. `retryable` marks transient faults (timeout, 429)."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def of(cls, prompt_tokens: int, completion_tokens: int) -> TokenUsage:
        return cls(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )


@dataclass
class GenerationRequest:
    """Single model call. Context is a materialized pack or any task payload."""

    task: str
    prompt: str
    context: dict[str, Any] = field(default_factory=dict)
    model: str = "default"
    temperature: float | None = None
    story_id: str = ""
    chapter_id: str = ""
    max_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        return context_fingerprint(
            {
                "task": self.task,
                "prompt": self.prompt,
                "context": self.context,
                "model": self.model,
                "temperature": self.temperature,
                "story_id": self.story_id,
                "chapter_id": self.chapter_id,
                "max_tokens": self.max_tokens,
            }
        )


@dataclass
class GenerationResult:
    text: str
    model: str
    provider: str
    usage: TokenUsage
    latency_ms: float
    task: str = ""
    story_id: str = ""
    chapter_id: str = ""
    fingerprint: str = ""
    raw: dict[str, Any] | None = None


class Provider(ABC):
    """Execution interface. Implementations must stay free of story state writes."""

    name: str = "provider"

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult:
        raise NotImplementedError

    def capabilities(self) -> frozenset[str]:
        return DEFAULT_CAPABILITIES


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)
