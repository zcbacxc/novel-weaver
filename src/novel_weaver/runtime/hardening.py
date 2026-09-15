# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Cost accounting and runtime diagnostics (Phase 5 foundation)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class UsageRecord:
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
    def __init__(self, price_table: dict[str, dict[str, float]] | None = None) -> None:
        self.prices = price_table or DEFAULT_PRICE
        self.records: list[UsageRecord] = []

    def price_for(self, model: str) -> dict[str, float]:
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
    level: str  # INFO | WARN | ERROR
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class Diagnostics:
    def __init__(self) -> None:
        self.events: list[DiagnosticEvent] = []

    def emit(self, level: str, code: str, message: str, **context: Any) -> DiagnosticEvent:
        ev = DiagnosticEvent(level=level, code=code, message=message, context=context)
        self.events.append(ev)
        return ev

    def errors(self) -> list[DiagnosticEvent]:
        return [e for e in self.events if e.level == "ERROR"]

    def summary(self) -> dict[str, int]:
        out = {"INFO": 0, "WARN": 0, "ERROR": 0}
        for e in self.events:
            out[e.level] = out.get(e.level, 0) + 1
        return out
