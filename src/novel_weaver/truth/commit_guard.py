# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Commit Guard: stale sessions must not overwrite Canonical."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from novel_weaver.domain.errors import GuardRejectError


class RejectReason(str, Enum):
    """Why Commit Guard refused a commit request."""

    STORY_REVISION_MISMATCH = "STORY_REVISION_MISMATCH"
    PLAN_REVISION_MISMATCH = "PLAN_REVISION_MISMATCH"
    PRODUCTION_UNIT_MISMATCH = "PRODUCTION_UNIT_MISMATCH"
    CONTEXT_FINGERPRINT_MISMATCH = "CONTEXT_FINGERPRINT_MISMATCH"
    UNIT_LOCKED = "UNIT_LOCKED"
    ALREADY_COMMITTED = "ALREADY_COMMITTED"


@dataclass(frozen=True)
class ProductionSession:
    """Immutable snapshot of the world a generation session was prepared against."""

    session_id: str
    story_id: str
    base_story_revision: int
    plan_revision: int
    production_unit: str
    context_fingerprint: str
    generation_spec_fingerprint: str = ""


@dataclass
class CommitRequest:
    """Candidate commit payload submitted to Commit Guard."""

    session: ProductionSession
    candidate_id: str
    target_unit: str
    state_delta: list[dict[str, Any]] = field(default_factory=list)
    event_delta: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommitResult:
    """Acceptance or rejection of a commit request, with optional new revision."""

    accepted: bool
    reason: RejectReason | None = None
    message: str = ""
    new_revision: int | None = None
    audit_ref: str | None = None

    @classmethod
    def ok(cls, new_revision: int = 0, audit_ref: str | None = None) -> CommitResult:
        """Build an accepted result.

        Args:
            new_revision: Revision after a successful commit, if known.
            audit_ref: Optional audit entry reference.

        Returns:
            An accepted ``CommitResult``.
        """
        return cls(accepted=True, new_revision=new_revision, audit_ref=audit_ref)

    @classmethod
    def reject(cls, reason: RejectReason, message: str) -> CommitResult:
        """Build a rejected result.

        Args:
            reason: Structured reject reason.
            message: Human-readable explanation.

        Returns:
            A rejected ``CommitResult``.
        """
        return cls(accepted=False, reason=reason, message=message)


class CommitGuard:
    """Validates that a commit still targets the current Canonical world.

    Public interface: ``lock_unit``, ``unlock_unit``, ``is_unit_committed``,
    ``validate``, ``mark_committed``, ``raise_if_rejected``.
    """

    def __init__(self) -> None:
        self._committed_units: set[str] = set()
        self._locked_units: dict[str, str] = {}  # unit -> session_id

    def lock_unit(self, unit: str, session_id: str = "") -> None:
        """Lock a production unit so only the given session may commit.

        Args:
            unit: Production unit identifier (typically a chapter id).
            session_id: Session that owns the lock; empty means anonymous owner.

        Returns:
            None.
        """
        self._locked_units[unit] = session_id

    def unlock_unit(self, unit: str) -> None:
        """Release any lock on a production unit.

        Args:
            unit: Production unit identifier to unlock.

        Returns:
            None.
        """
        self._locked_units.pop(unit, None)

    def is_unit_committed(self, unit: str) -> bool:
        """Check whether a unit has already been committed in this guard lifetime.

        Args:
            unit: Production unit identifier.

        Returns:
            ``True`` if the unit is marked committed.
        """
        return unit in self._committed_units

    def validate(
        self,
        request: CommitRequest,
        *,
        current_story_revision: int,
        current_plan_revision: int,
        current_context_fingerprint: str | None = None,
    ) -> CommitResult:
        """Check unit lock, prior commit, revisions, and context fingerprint.

        Args:
            request: Commit request under validation.
            current_story_revision: Live story revision at commit time.
            current_plan_revision: Live plan revision at commit time.
            current_context_fingerprint: Optional live context fingerprint; when
                provided and the session fingerprint differs, the commit is rejected.

        Returns:
            An accepted result, or a rejected result with a ``RejectReason``.
        """
        session = request.session

        if request.target_unit != session.production_unit:
            return CommitResult.reject(
                RejectReason.PRODUCTION_UNIT_MISMATCH,
                f"session targets {session.production_unit}, commit targets {request.target_unit}",
            )

        if self.is_unit_committed(request.target_unit):
            return CommitResult.reject(
                RejectReason.ALREADY_COMMITTED,
                f"production unit {request.target_unit} already committed",
            )

        lock_owner = self._locked_units.get(request.target_unit)
        if lock_owner is not None and lock_owner != session.session_id:
            return CommitResult.reject(
                RejectReason.UNIT_LOCKED,
                f"production unit {request.target_unit} is locked by session {lock_owner}",
            )

        if session.base_story_revision != current_story_revision:
            return CommitResult.reject(
                RejectReason.STORY_REVISION_MISMATCH,
                (
                    f"session story revision {session.base_story_revision} != "
                    f"current {current_story_revision}"
                ),
            )

        if session.plan_revision != current_plan_revision:
            return CommitResult.reject(
                RejectReason.PLAN_REVISION_MISMATCH,
                (
                    f"session plan revision {session.plan_revision} != "
                    f"current {current_plan_revision}"
                ),
            )

        if (
            current_context_fingerprint is not None
            and session.context_fingerprint
            and session.context_fingerprint != current_context_fingerprint
        ):
            return CommitResult.reject(
                RejectReason.CONTEXT_FINGERPRINT_MISMATCH,
                "context fingerprint changed; rebuild context and regenerate",
            )

        return CommitResult.ok()

    def mark_committed(self, unit: str) -> None:
        """Record a successful commit and clear any lock on the unit.

        Args:
            unit: Production unit that was committed.

        Returns:
            None.
        """
        self._committed_units.add(unit)
        self._locked_units.pop(unit, None)

    def raise_if_rejected(self, result: CommitResult) -> None:
        """Raise when a commit result was rejected.

        Args:
            result: Result returned by ``validate``.

        Returns:
            None.

        Raises:
            GuardRejectError: If ``result.accepted`` is false.
        """
        if not result.accepted:
            raise GuardRejectError(result.message or str(result.reason))
