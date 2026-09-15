# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Canonical domain entities for Phase 0.

These types are the single source of truth for story facts. Runtime and
derived projections must never be the only holders of these values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Create a short unique identifier with the given prefix.

    Args:
        prefix: Short label such as ``story`` or ``ch``.

    Returns:
        A string of the form ``{prefix}_{12 hex chars}``.
    """
    return f"{prefix}_{uuid4().hex[:12]}"


class FactStatus(str, Enum):
    """Lifecycle of a canonical fact.

    ``PENDING`` is not the same as false; model guesses must not skip the
    proposal/review path into ``CANONICAL``.
    """

    UNKNOWN = "UNKNOWN"
    PROPOSED = "PROPOSED"
    REVIEWED = "REVIEWED"
    CANONICAL = "CANONICAL"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"
    PENDING = "PENDING"


class ProductionUnitStatus(str, Enum):
    """Production lifecycle of a chapter (or other unit)."""

    PLANNED = "PLANNED"
    GENERATING = "GENERATING"
    CANDIDATE_READY = "CANDIDATE_READY"
    STALE = "STALE"
    COMMITTED = "COMMITTED"
    BLOCKED = "BLOCKED"


class CandidateStatus(str, Enum):
    """Lifecycle of generated text before it becomes committed content."""

    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    REVIEWED = "REVIEWED"
    ACCEPTED = "ACCEPTED"
    COMMITTED = "COMMITTED"
    REJECTED = "REJECTED"
    STALE = "STALE"


class ReconcileStatus(str, Enum):
    """Status of an external-edit reconcile ticket."""

    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass
class Story:
    """Root aggregate for one novel.

    Fields cover identity, creative intent, constraints, and the current
    canonical revision used by Commit Guard.
    """

    story_id: str
    title: str
    premise: str = ""
    creative_intent: str = ""
    constraints: dict[str, Any] = field(default_factory=dict)
    current_canonical_revision: int = 0
    lifecycle_status: str = "ACTIVE"
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @classmethod
    def create(cls, title: str, premise: str = "", creative_intent: str = "") -> Story:
        """Create a new story with a generated id.

        Args:
            title: Human-readable story title.
            premise: Optional one-paragraph premise.
            creative_intent: Optional creative intent for downstream planning.

        Returns:
            A new ``Story`` instance at revision 0.
        """
        return cls(
            story_id=new_id("story"),
            title=title,
            premise=premise,
            creative_intent=creative_intent,
        )


@dataclass
class StoryRevision:
    """Marker that the story's canonical revision advanced.

    Used for audit/history; ``checkpoint_ref`` may point at a recovery snapshot.
    """

    story_id: str
    revision: int
    created_at: datetime = field(default_factory=_now)
    reason: str = ""
    checkpoint_ref: str | None = None


@dataclass
class Character:
    """Character fact record with status, revision, and provenance."""

    character_id: str
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    status: FactStatus = FactStatus.CANONICAL
    revision: int = 0
    source: str = ""
    effective_from: int | None = None
    effective_to: int | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, name: str, **attributes: Any) -> Character:
        """Create a character with a generated id.

        Args:
            name: Character display name.
            **attributes: Free-form attribute map stored on the character.

        Returns:
            A new ``Character`` with ``CANONICAL`` status by default.
        """
        return cls(character_id=new_id("chr"), name=name, attributes=attributes)


@dataclass
class StateItem:
    """A single canonical fact slot (character/world/timeline/thread/etc.)."""

    item_id: str
    key: str
    value: Any
    kind: str  # character | world | location | timeline | conflict | thread | constraint
    status: FactStatus = FactStatus.PENDING
    revision: int = 0
    source: str = ""
    confidence: float = 1.0
    effective_from: int | None = None
    effective_to: int | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    superseded_by: str | None = None
    invalidated_by: str | None = None
    depends_on: list[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        key: str,
        value: Any,
        kind: str,
        *,
        status: FactStatus = FactStatus.PENDING,
        source: str = "",
        confidence: float = 1.0,
        depends_on: list[str] | None = None,
    ) -> StateItem:
        """Create a state item with a generated id.

        Args:
            key: Stable fact key (for example character trait or world rule).
            value: Fact payload.
            kind: Fact category such as ``character`` or ``timeline``.
            status: Initial fact status; defaults to ``PENDING``.
            source: Origin label (chapter, proposal, author, …).
            confidence: Confidence in ``[0, 1]``.
            depends_on: Optional list of other item ids this fact depends on.

        Returns:
            A new ``StateItem`` instance.
        """
        return cls(
            item_id=new_id("st"),
            key=key,
            value=value,
            kind=kind,
            status=status,
            source=source,
            confidence=confidence,
            depends_on=list(depends_on or []),
        )


@dataclass
class Event:
    """Timeline event extracted from or committed into the story."""

    event_id: str
    time_ref: str
    summary: str
    participants: list[str] = field(default_factory=list)
    location: str = ""
    claims: dict[str, Any] = field(default_factory=dict)
    source_chapter: str | None = None
    status: str = "ACTIVE"  # ACTIVE | RESOLVED | INVALIDATED
    revision: int = 0
    provenance: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, time_ref: str, summary: str, **kwargs: Any) -> Event:
        """Create an event with a generated id.

        Args:
            time_ref: Story-time reference string.
            summary: Short event summary.
            **kwargs: Remaining ``Event`` field values.

        Returns:
            A new ``Event`` instance.
        """
        return cls(event_id=new_id("evt"), time_ref=time_ref, summary=summary, **kwargs)


@dataclass
class Chapter:
    """Production unit representing one chapter of the novel."""

    chapter_id: str
    number: int
    title: str = ""
    plan: str = ""
    content: str = ""
    status: ProductionUnitStatus = ProductionUnitStatus.PLANNED
    revision: int = 0
    depends_on: list[str] = field(default_factory=list)
    fact_keys_used: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, number: int, title: str = "", plan: str = "") -> Chapter:
        """Create a planned chapter with a generated id.

        Args:
            number: 1-based chapter number.
            title: Optional title; defaults to ``Chapter {number}``.
            plan: Optional plan text for generation.

        Returns:
            A new ``Chapter`` in ``PLANNED`` status.
        """
        return cls(
            chapter_id=new_id("ch"),
            number=number,
            title=title or f"Chapter {number}",
            plan=plan,
        )


@dataclass
class ThreadRecord:
    """Open narrative thread tracked across chapters."""

    thread_id: str
    name: str
    introduced_at: str
    current_status: str = "OPEN"  # OPEN | TOUCHED | RESOLVED | ABANDONED
    obligations: list[str] = field(default_factory=list)
    related_entities: list[str] = field(default_factory=list)
    expected_resolution: str = ""
    last_touched_at: str | None = None
    revision: int = 0

    @classmethod
    def create(cls, name: str, introduced_at: str, **kwargs: Any) -> ThreadRecord:
        """Create a thread record with a generated id.

        Args:
            name: Thread display name.
            introduced_at: Story-time or chapter ref where the thread opened.
            **kwargs: Remaining ``ThreadRecord`` field values.

        Returns:
            A new ``ThreadRecord`` instance.
        """
        return cls(thread_id=new_id("thr"), name=name, introduced_at=introduced_at, **kwargs)


@dataclass
class ReconcileRecord:
    """External-edit reconcile ticket. Pending blocks forward production."""

    reconcile_id: str
    story_id: str
    chapter_id: str
    previous_content_hash: str
    current_content_hash: str
    previous_story_revision: int
    status: ReconcileStatus = ReconcileStatus.PENDING
    reason: str = ""
    fact_keys_changed: list[str] = field(default_factory=list)
    stale_chapter_ids: list[str] = field(default_factory=list)
    still_valid_chapter_ids: list[str] = field(default_factory=list)
    invalidated_plan_ids: list[str] = field(default_factory=list)
    extracted_fact_keys: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)
    completed_at: datetime | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        story_id: str,
        chapter_id: str,
        previous_content_hash: str,
        current_content_hash: str,
        previous_story_revision: int,
        *,
        reason: str = "",
        provenance: dict[str, Any] | None = None,
    ) -> ReconcileRecord:
        """Create a pending reconcile ticket for an externally edited chapter.

        Args:
            story_id: Story that owns the edited chapter.
            chapter_id: Chapter whose content hash changed outside the engine.
            previous_content_hash: Content hash before the external edit.
            current_content_hash: Content hash after the external edit.
            previous_story_revision: Story revision observed before reconcile.
            reason: Optional human-readable reason for the ticket.
            provenance: Optional extra provenance metadata.

        Returns:
            A new ``ReconcileRecord`` in ``PENDING`` status.
        """
        return cls(
            reconcile_id=new_id("rec"),
            story_id=story_id,
            chapter_id=chapter_id,
            previous_content_hash=previous_content_hash,
            current_content_hash=current_content_hash,
            previous_story_revision=previous_story_revision,
            reason=reason,
            provenance=dict(provenance or {}),
        )


@dataclass
class FactProposalRecord:
    """Persisted proposal awaiting promotion into Canonical state."""

    proposal_id: str
    claim: str
    evidence_refs: list[str]
    confidence: float
    status: FactStatus = FactStatus.PROPOSED
    conflicts: list[str] = field(default_factory=list)
    proposed_by: str = "system"
    target_kind: str = "world"
    target_key: str = ""
    created_at: datetime = field(default_factory=_now)
    promoted_item_id: str | None = None

    @classmethod
    def create(
        cls,
        claim: str,
        evidence_refs: list[str],
        *,
        confidence: float = 0.5,
        proposed_by: str = "system",
        target_kind: str = "world",
        target_key: str = "",
    ) -> FactProposalRecord:
        """Create a proposal record with a generated id.

        Args:
            claim: Natural-language claim or fact value summary.
            evidence_refs: Evidence ids that support the claim.
            confidence: Proposal confidence in ``[0, 1]``.
            proposed_by: Actor or system that proposed the fact.
            target_kind: Destination fact kind (default ``world``).
            target_key: Destination key; defaults to a truncated claim.

        Returns:
            A new ``FactProposalRecord`` in ``PROPOSED`` status.
        """
        return cls(
            proposal_id=new_id("prop"),
            claim=claim,
            evidence_refs=list(evidence_refs),
            confidence=confidence,
            proposed_by=proposed_by,
            target_kind=target_kind,
            target_key=target_key or claim[:40],
        )
