# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Runtime checkpoint model: Run / Step / Checkpoint.

Runtime State 仅描述执行状态（实现方案 §17），**不能**作为小说事实来源。
Canonical Story 只能通过 Commit 改变；本模块任何失败路径都不得改写
`stories.current_canonical_revision` 或任何 Canonical 实体。

Checkpoint 至少持久化：

- run_id / story_id / production_unit
- step name / status
- payload dict
- base_story_revision
- created_at

幂等约定：同一 (run_id, step) 对应稳定 checkpoint_id，重复保存为覆盖语义；
重复加载同一 checkpoint 结果一致、无副作用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StepStatus(str, Enum):
    """Lifecycle of a single production step inside a run."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class RunStatus(str, Enum):
    """Lifecycle of an entire production run."""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


@dataclass
class RunStep:
    """One named step in a RuntimeRun (plan / generate / validate / commit …)."""

    name: str
    status: StepStatus = StepStatus.PENDING
    payload: dict[str, Any] = field(default_factory=dict)
    retryable: bool = True
    error: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def mark_running(self) -> None:
        """Transition the step to RUNNING and clear prior error/finish time.

        Returns:
            None.
        """
        self.status = StepStatus.RUNNING
        self.started_at = _now()
        self.finished_at = None
        self.error = ""

    def mark_succeeded(self, payload: dict[str, Any] | None = None) -> None:
        """Mark the step SUCCEEDED and optionally merge payload fields.

        Args:
            payload: Extra payload keys to merge into the step.

        Returns:
            None.
        """
        self.status = StepStatus.SUCCEEDED
        if payload:
            self.payload = {**self.payload, **payload}
        self.finished_at = _now()
        self.error = ""

    def mark_failed(self, error: str, *, retryable: bool = True) -> None:
        """Mark the step FAILED with an error and retryability flag.

        Args:
            error: Failure message.
            retryable: Whether a later resume may retry this step.

        Returns:
            None.
        """
        self.status = StepStatus.FAILED
        self.error = error
        self.retryable = retryable
        self.finished_at = _now()


@dataclass
class RuntimeRun:
    """Execution-only run for one production unit. Never a story-fact source."""

    run_id: str
    story_id: str
    production_unit: str
    base_story_revision: int
    steps: list[RunStep] = field(default_factory=list)
    status: RunStatus = RunStatus.CREATED
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def step(self, name: str) -> RunStep | None:
        """Look up a step by name.

        Args:
            name: Step name.

        Returns:
            The matching RunStep, or None.
        """
        for s in self.steps:
            if s.name == name:
                return s
        return None

    def last_step(self) -> RunStep | None:
        """Return the most recently added step.

        Returns:
            The last RunStep, or None when the run has no steps.
        """
        return self.steps[-1] if self.steps else None

    def upsert_step(self, step: RunStep) -> RunStep:
        """Insert or replace a step by name; keeps step order stable on replace.

        Args:
            step: Step to insert or use as replacement.

        Returns:
            The step that is now stored.
        """
        for i, existing in enumerate(self.steps):
            if existing.name == step.name:
                self.steps[i] = step
                self.updated_at = _now()
                return step
        self.steps.append(step)
        self.updated_at = _now()
        return step

    def next_pending_step(self) -> RunStep | None:
        """Return the first PENDING step in run order.

        Returns:
            The next pending RunStep, or None when none remain.
        """
        for s in self.steps:
            if s.status is StepStatus.PENDING:
                return s
        return None


def stable_checkpoint_id(run_id: str, step: str) -> str:
    """Stable id so the same production intent maps to one checkpoint row.

    Args:
        run_id: Runtime run identity.
        step: Step name.

    Returns:
        Checkpoint id string ``ckpt_<run_id>_<step>``.
    """
    return f"ckpt_{run_id}_{step}"


@dataclass
class Checkpoint:
    """Durable snapshot of one step boundary for resume/recovery."""

    checkpoint_id: str
    run_id: str
    story_id: str
    production_unit: str
    step: str
    status: StepStatus
    payload: dict[str, Any] = field(default_factory=dict)
    base_story_revision: int = 0
    created_at: datetime = field(default_factory=_now)

    @classmethod
    def for_step(
        cls,
        run: RuntimeRun,
        step: RunStep,
        *,
        checkpoint_id: str | None = None,
    ) -> Checkpoint:
        """Build a checkpoint from a run + step. Does not mutate Canonical state.

        Args:
            run: Runtime run providing story/unit/base revision.
            step: Step whose status/payload to snapshot.
            checkpoint_id: Optional override; defaults to a stable id.

        Returns:
            A Checkpoint ready for persistence.
        """
        return cls(
            checkpoint_id=checkpoint_id or stable_checkpoint_id(run.run_id, step.name),
            run_id=run.run_id,
            story_id=run.story_id,
            production_unit=run.production_unit,
            step=step.name,
            status=step.status,
            payload=dict(step.payload),
            base_story_revision=run.base_story_revision,
            created_at=_now(),
        )

    def to_payload_envelope(self) -> dict[str, Any]:
        """Serialize fields that do not fit the narrow checkpoints table columns.

        Returns:
            Dict envelope with run_id, step, status, revision, and payload.
        """
        return {
            "run_id": self.run_id,
            "production_unit": self.production_unit,
            "step": self.step,
            "status": self.status.value,
            "base_story_revision": self.base_story_revision,
            "payload": self.payload,
        }

    @classmethod
    def from_row(
        cls,
        *,
        checkpoint_id: str,
        story_id: str,
        revision: int,
        payload_json: dict[str, Any],
        created_at: datetime,
    ) -> Checkpoint:
        """Rebuild from a storage row. Safe to call multiple times (idempotent).

        Args:
            checkpoint_id: Stored checkpoint identity.
            story_id: Story identity from the row.
            revision: Fallback base story revision.
            payload_json: Envelope dict previously written by to_payload_envelope.
            created_at: Row creation timestamp.

        Returns:
            A reconstructed Checkpoint.
        """
        envelope = payload_json or {}
        status_raw = envelope.get("status", StepStatus.PENDING.value)
        try:
            status = StepStatus(status_raw)
        except ValueError:
            status = StepStatus.PENDING
        return cls(
            checkpoint_id=checkpoint_id,
            run_id=str(envelope.get("run_id", "")),
            story_id=story_id,
            production_unit=str(envelope.get("production_unit", "")),
            step=str(envelope.get("step", "")),
            status=status,
            payload=dict(envelope.get("payload") or {}),
            base_story_revision=int(
                envelope.get("base_story_revision", revision)
            ),
            created_at=created_at,
        )


def run_from_checkpoints(
    run_id: str,
    checkpoints: list[Checkpoint],
) -> RuntimeRun | None:
    """Rebuild a RuntimeRun from ordered checkpoints of the same run.

    Loading is pure: no Canonical writes.

    Args:
        run_id: Expected run identity (must match all checkpoints).
        checkpoints: Ordered checkpoint snapshots for one run.

    Returns:
        Reconstructed RuntimeRun, or None when the list is empty.

    Raises:
        ValueError: If checkpoints belong to mixed runs.
    """
    if not checkpoints:
        return None
    first = checkpoints[0]
    if any(c.run_id != first.run_id for c in checkpoints):
        raise ValueError("checkpoints belong to mixed runs")
    run = RuntimeRun(
        run_id=first.run_id,
        story_id=first.story_id,
        production_unit=first.production_unit,
        base_story_revision=first.base_story_revision,
    )
    for c in checkpoints:
        run.upsert_step(
            RunStep(
                name=c.step,
                status=c.status,
                payload=dict(c.payload),
            )
        )
    last = run.last_step()
    if last is not None:
        if last.status is StepStatus.SUCCEEDED:
            run.status = RunStatus.SUCCEEDED
        elif last.status is StepStatus.FAILED:
            run.status = RunStatus.FAILED
        elif last.status is StepStatus.RUNNING:
            run.status = RunStatus.RUNNING
        else:
            run.status = RunStatus.RUNNING
    return run
