# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""FailoverProvider: ordered multi-provider chain with retryable-only failover."""

from __future__ import annotations

from dataclasses import dataclass, field

from novel_weaver.ai.base import (
    GenerationRequest,
    GenerationResult,
    Provider,
    ProviderError,
)


@dataclass
class FailoverAttempt:
    """Record of one attempt against a chained provider."""

    provider_name: str
    ok: bool
    error: str = ""


@dataclass
class FailoverProvider(Provider):
    """Try providers in order. Only retryable errors advance the chain.

    Decision: ordered list (not load-balance) because production continuity and
    deterministic fallback (template/fake) matter more than traffic spreading.
    Alternative considered: weighted random / health-score routing — rejected for
    Phase 5 minimal kernel (extra state, non-reproducible generation path).
    """

    name = "failover"
    providers: list[Provider] = field(default_factory=list)

    def __init__(self, providers: list[Provider], *, name: str = "failover") -> None:
        """Create a failover chain.

        Args:
            providers: Ordered providers; later entries are used on failure.
            name: Provider label reported on results from this chain.

        Raises:
            ValueError: If ``providers`` is empty.
        """
        if not providers:
            raise ValueError("FailoverProvider requires at least one provider")
        self.providers = list(providers)
        self.name = name
        self.last_attempts: list[FailoverAttempt] = []

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Call providers in order until one succeeds or the chain exhausts.

        Args:
            request: Generation request forwarded unchanged to each attempt.

        Returns:
            Result from the first successful provider, with ``raw`` annotated
            by failover index and serving provider name.

        Raises:
            ProviderError: If every provider fails (last error or aggregated
                exhaustion message).
        """
        self.last_attempts = []
        errors: list[str] = []
        for idx, provider in enumerate(self.providers):
            try:
                result = provider.generate(request)
                self.last_attempts.append(
                    FailoverAttempt(provider_name=getattr(provider, "name", f"p{idx}"), ok=True)
                )
                # Record which provider actually served (for diagnostics/cost).
                raw = dict(result.raw or {})
                raw["failover_served_by"] = getattr(provider, "name", f"p{idx}")
                raw["failover_index"] = idx
                return GenerationResult(
                    text=result.text,
                    model=result.model,
                    provider=result.provider,
                    usage=result.usage,
                    latency_ms=result.latency_ms,
                    task=result.task,
                    story_id=result.story_id,
                    chapter_id=result.chapter_id,
                    fingerprint=result.fingerprint,
                    raw=raw,
                )
            except ProviderError as exc:
                pname = getattr(provider, "name", f"p{idx}")
                self.last_attempts.append(
                    FailoverAttempt(provider_name=pname, ok=False, error=str(exc))
                )
                errors.append(f"{pname}: {exc}")
                if not exc.retryable:
                    # Fatal on this provider — still try next (policy: failover on both
                    # retryable and fatal, so a bad key doesn't stall the book).
                    # Exception: if it's the last provider, re-raise.
                    if idx == len(self.providers) - 1:
                        raise
                    continue
                if idx == len(self.providers) - 1:
                    raise ProviderError(
                        f"all failover providers exhausted: {'; '.join(errors)}",
                        retryable=True,
                    ) from exc
                continue
        raise ProviderError("failover chain empty after init", retryable=False)

    def capabilities(self) -> frozenset[str]:
        """Union of capabilities from every provider in the chain.

        Returns:
            Frozen set of task labels any chained provider can handle.
        """
        # Intersection would be too strict; union keeps tasks available.
        caps: set[str] = set()
        for p in self.providers:
            caps |= set(p.capabilities())
        return frozenset(caps)
