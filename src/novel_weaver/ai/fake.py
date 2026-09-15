# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Deterministic offline provider: same request fingerprint → same text."""

from __future__ import annotations

import hashlib
import time

from novel_weaver.ai.base import (
    GenerationRequest,
    GenerationResult,
    Provider,
    ProviderError,
    TokenUsage,
    estimate_tokens,
)


class FakeProvider(Provider):
    """Offline deterministic ``Provider`` for tests and dry-run production.

    Generates text derived only from the request fingerprint and context.
    Can simulate transient failures via ``fail_times``.
    """

    name = "fake"

    def __init__(self, *, model: str = "fake-deterministic-v1", fail_times: int = 0) -> None:
        """Create a fake provider.

        Args:
            model: Model label reported on results when the request uses default.
            fail_times: Number of leading ``generate`` calls that raise a
                retryable ``ProviderError``.
        """
        self.model = model
        self._remaining_failures = fail_times

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Return deterministic draft text for the request.

        Args:
            request: Generation inputs used for fingerprint and rendering.

        Returns:
            A ``GenerationResult`` with estimated usage and latency.

        Raises:
            ProviderError: While simulated failures remain (``fail_times``).
        """
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise ProviderError("simulated transient provider failure", retryable=True)

        started = time.perf_counter()
        fingerprint = request.fingerprint()
        text = self._render(request, fingerprint)
        latency_ms = (time.perf_counter() - started) * 1000.0
        prompt_tokens = estimate_tokens(request.prompt) + estimate_tokens(str(request.context))
        completion_tokens = estimate_tokens(text)
        return GenerationResult(
            text=text,
            model=request.model if request.model != "default" else self.model,
            provider=self.name,
            usage=TokenUsage.of(prompt_tokens, completion_tokens),
            latency_ms=latency_ms,
            task=request.task,
            story_id=request.story_id,
            chapter_id=request.chapter_id,
            fingerprint=fingerprint,
            raw={"seed": fingerprint[:8], "task": request.task},
        )

    def _render(self, request: GenerationRequest, fingerprint: str) -> str:
        ctx = request.context
        seed = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:8]
        facts = ctx.get("selected_facts") or []
        fact_lines = [f"- {f.get('key')}: {f.get('value')}" for f in facts if isinstance(f, dict)]
        if not fact_lines:
            fact_lines = ["- (no canonical facts selected)"]
        chapter_label = request.chapter_id or ctx.get("production_unit") or "unknown"
        plan = ctx.get("current_plan") or request.prompt or "n/a"
        intent = ctx.get("creative_intent") or "n/a"
        return (
            f"[FAKE:{seed}] task={request.task} unit={chapter_label}\n"
            f"Intent: {intent}\n"
            f"Plan: {plan}\n"
            f"Canonical facts in play:\n" + "\n".join(fact_lines) + "\n"
            f"Scene: Deterministic draft body for fingerprint {fingerprint}."
        )
