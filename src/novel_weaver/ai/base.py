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
    """Provider-side failure. `retryable` marks transient faults (timeout, 429).

    Args:
        message: Human-readable error text.
        retryable: Whether callers may safely retry the same request.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class TokenUsage:
    """Token accounting for a single model call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def of(cls, prompt_tokens: int, completion_tokens: int) -> TokenUsage:
        """Build usage with total tokens derived from the two parts.

        Args:
            prompt_tokens: Tokens counted on the prompt/input side.
            completion_tokens: Tokens counted on the completion/output side.

        Returns:
            A ``TokenUsage`` with ``total_tokens`` set to the sum.
        """
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
        """Stable hash of the generation inputs (not metadata).

        Returns:
            Fingerprint string used for caching, diagnostics, and commit checks.
        """
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
    """Model output plus usage, latency, and request identity fields."""

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
    """Execution interface. Implementations must stay free of story state writes.

    Contract: ``generate`` returns a ``GenerationResult`` or raises
    ``ProviderError``; ``capabilities`` advertises task names the provider
    supports. Subclasses must implement ``generate``.
    """

    name: str = "provider"

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Execute one generation request.

        Args:
            request: Task, prompt, and materialized context for this call.

        Returns:
            Generated text with usage and latency metadata.

        Raises:
            ProviderError: On provider-side failure; ``retryable`` marks
                whether the call may be retried safely.
        """
        raise NotImplementedError

    def capabilities(self) -> frozenset[str]:
        """Task-name capabilities this provider claims to support.

        Returns:
            Frozen set of capability labels; defaults to ``DEFAULT_CAPABILITIES``.
        """
        return DEFAULT_CAPABILITIES


def estimate_tokens(text: str) -> int:
    """Approximate token count when the gateway omits usage.

    Args:
        text: Input text to estimate.

    Returns:
        Approximate token count (empty text yields 0).
    """
    if not text:
        return 0
    return max(1, len(text) // 4)
