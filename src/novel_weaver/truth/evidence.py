# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Evidence-backed facts: nothing enters Canon without a traceable source."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_type: str  # chapter | author | research | generated
    source_ref: str
    extracted_claim: str
    source_revision: int | None = None
    chapter_ref: str | None = None
    location: str = ""
    confidence: float = 1.0
    captured_at: datetime = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def capture(
        cls,
        source_type: str,
        source_ref: str,
        extracted_claim: str,
        *,
        confidence: float = 1.0,
        chapter_ref: str | None = None,
        location: str = "",
        source_revision: int | None = None,
        **metadata: Any,
    ) -> Evidence:
        if not extracted_claim.strip():
            raise ValueError("Evidence must carry a non-empty claim")
        if confidence < 0 or confidence > 1:
            raise ValueError("confidence must be in [0, 1]")
        return cls(
            evidence_id=f"ev_{uuid4().hex[:12]}",
            source_type=source_type,
            source_ref=source_ref,
            extracted_claim=extracted_claim.strip(),
            confidence=confidence,
            chapter_ref=chapter_ref,
            location=location,
            source_revision=source_revision,
            metadata=metadata,
        )


class EvidenceStore:
    """In-memory + optional persistence hook for evidence records."""

    def __init__(self) -> None:
        self._items: dict[str, Evidence] = {}

    def add(self, evidence: Evidence) -> Evidence:
        self._items[evidence.evidence_id] = evidence
        return evidence

    def get(self, evidence_id: str) -> Evidence | None:
        return self._items.get(evidence_id)

    def exists(self, evidence_id: str) -> bool:
        return evidence_id in self._items

    def list_all(self) -> list[Evidence]:
        return list(self._items.values())

    def list_by_source(self, source_ref: str) -> list[Evidence]:
        return [e for e in self._items.values() if e.source_ref == source_ref]
