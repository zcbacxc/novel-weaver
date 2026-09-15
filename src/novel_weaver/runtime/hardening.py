# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Cost accounting and runtime diagnostics (Phase 5 foundation)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class UsageRecord:
    """One provider usage sample for cost accounting.

    Attributes:
        story_id: Story that incurred the usage.
        run_id: Runtime run identity.
        provider: Provider name.
        model: Model name used for pricing.
        prompt_tokens: Input token count.
        completion_tokens: Output token count.
        latency_ms: Request latency in milliseconds.
        cost_usd: Computed USD cost.
        created_at: Record timestamp.
    """

    story_id: str
    run_id: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    cost_usd: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# Simple default price table (USD per 1M tokens); overridable
DEFAULT_PRICE = {
    "fake": {"input": 0.0, "output": 0.0},
    "template": {"input": 0.0, "output": 0.0},
    "deepseek-flash": {"input": 0.0, "output": 0.0},
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek-v4-pro": {"input": 0.50, "output": 2.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "default": {"input": 0.5, "output": 1.5},
}


class CostAccountant:
    """Accumulate provider usage and estimate USD cost per story/run."""

    def __init__(self, price_table: dict[str, dict[str, float]] | None = None) -> None:
        self.prices = price_table or DEFAULT_PRICE
        self.records: list[UsageRecord] = []

    def price_for(self, model: str) -> dict[str, float]:
        """Return input/output USD-per-million-token prices for a model.

        Args:
            model: Model name key in the price table.

        Returns:
            Dict with input and output rates (falls back to "default").
        """
        return self.prices.get(model, self.prices["default"])

    def record(
        self,
        *,
        story_id: str,
        run_id: str,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
    ) -> UsageRecord:
        """Record one usage sample and compute its USD cost.

        Args:
            story_id: Story that incurred the usage.
            run_id: Runtime run identity.
            provider: Provider name.
            model: Model name used for pricing.
            prompt_tokens: Input token count.
            completion_tokens: Output token count.
            latency_ms: Request latency in milliseconds.

        Returns:
            The stored UsageRecord including computed cost_usd.
        """
        p = self.price_for(model)
        cost = (prompt_tokens * p["input"] + completion_tokens * p["output"]) / 1_000_000
        rec = UsageRecord(
            story_id=story_id,
            run_id=run_id,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            cost_usd=cost,
        )
        self.records.append(rec)
        return rec

    def total_for_story(self, story_id: str) -> dict[str, Any]:
        """Aggregate usage and cost for one story.

        Args:
            story_id: Story to summarize.

        Returns:
            Dict with calls, token totals, cost_usd, and avg_latency_ms.
        """
        rows = [r for r in self.records if r.story_id == story_id]
        return {
            "calls": len(rows),
            "prompt_tokens": sum(r.prompt_tokens for r in rows),
            "completion_tokens": sum(r.completion_tokens for r in rows),
            "cost_usd": sum(r.cost_usd for r in rows),
            "avg_latency_ms": (sum(r.latency_ms for r in rows) / len(rows)) if rows else 0.0,
        }


@dataclass
class DiagnosticEvent:
    """One runtime diagnostic event.

    Attributes:
        level: INFO | WARN | ERROR.
        code: Stable machine-readable event code.
        message: Human-readable message.
        context: Structured event context.
        created_at: Event timestamp.
    """

    level: str  # INFO | WARN | ERROR
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class Diagnostics:
    """In-memory diagnostic event log for engine runs."""

    def __init__(self) -> None:
        self.events: list[DiagnosticEvent] = []

    def emit(self, level: str, code: str, message: str, **context: Any) -> DiagnosticEvent:
        """Append a diagnostic event.

        Args:
            level: INFO | WARN | ERROR.
            code: Stable machine-readable event code.
            message: Human-readable message.
            **context: Structured event context fields.

        Returns:
            The stored DiagnosticEvent.
        """
        ev = DiagnosticEvent(level=level, code=code, message=message, context=context)
        self.events.append(ev)
        return ev

    def errors(self) -> list[DiagnosticEvent]:
        """List ERROR-level events.

        Returns:
            ERROR DiagnosticEvent list.
        """
        return [e for e in self.events if e.level == "ERROR"]

    def summary(self) -> dict[str, int]:
        """Count events by level.

        Returns:
            Dict mapping INFO/WARN/ERROR to counts.
        """
        out = {"INFO": 0, "WARN": 0, "ERROR": 0}
        for e in self.events:
            out[e.level] = out.get(e.level, 0) + 1
        return out
