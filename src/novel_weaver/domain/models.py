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
    return f"{prefix}_{uuid4().hex[:12]}"


class FactStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    PROPOSED = "PROPOSED"
    REVIEWED = "REVIEWED"
    CANONICAL = "CANONICAL"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"
    PENDING = "PENDING"


class ProductionUnitStatus(str, Enum):
    PLANNED = "PLANNED"
    GENERATING = "GENERATING"
    CANDIDATE_READY = "CANDIDATE_READY"
    STALE = "STALE"
    COMMITTED = "COMMITTED"
    BLOCKED = "BLOCKED"


class CandidateStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    REVIEWED = "REVIEWED"
    ACCEPTED = "ACCEPTED"
    COMMITTED = "COMMITTED"
    REJECTED = "REJECTED"
    STALE = "STALE"


@dataclass
class Story:
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
        return cls(
            story_id=new_id("story"),
            title=title,
            premise=premise,
            creative_intent=creative_intent,
        )


@dataclass
class StoryRevision:
    story_id: str
    revision: int
    created_at: datetime = field(default_factory=_now)
    reason: str = ""
    checkpoint_ref: str | None = None


@dataclass
class Character:
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
        return cls(event_id=new_id("evt"), time_ref=time_ref, summary=summary, **kwargs)


@dataclass
class Chapter:
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
        return cls(
            chapter_id=new_id("ch"),
            number=number,
            title=title or f"Chapter {number}",
            plan=plan,
        )


@dataclass
class ThreadRecord:
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
        return cls(thread_id=new_id("thr"), name=name, introduced_at=introduced_at, **kwargs)


@dataclass
class FactProposalRecord:
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
        return cls(
            proposal_id=new_id("prop"),
            claim=claim,
            evidence_refs=list(evidence_refs),
            confidence=confidence,
            proposed_by=proposed_by,
            target_kind=target_kind,
            target_key=target_key or claim[:40],
        )
