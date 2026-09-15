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
    """Immutable extraction of a claim from a named source.

    Main fields: source identity, extracted claim, optional chapter/location
    anchors, and confidence used by promotion rules.
    """

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
        """Validate and freeze a new evidence record.

        Args:
            source_type: Origin category (``chapter``, ``author``, …).
            source_ref: Stable reference to the source document or actor.
            extracted_claim: Non-empty claim text.
            confidence: Confidence in ``[0, 1]``.
            chapter_ref: Optional chapter id when the claim came from a chapter.
            location: Optional in-source location string.
            source_revision: Optional revision of the source material.
            **metadata: Extra metadata stored on the record.

        Returns:
            A frozen ``Evidence`` instance with a generated id.

        Raises:
            ValueError: If the claim is empty/whitespace or confidence is outside
                ``[0, 1]``.
        """
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
    """In-memory store for evidence records (optional persistence hook later).

    Public interface: ``add``, ``get``, ``exists``, ``list_all``,
    ``list_by_source``.
    """

    def __init__(self) -> None:
        self._items: dict[str, Evidence] = {}

    def add(self, evidence: Evidence) -> Evidence:
        """Store evidence under its id.

        Args:
            evidence: Record to store (overwrites any prior record with the same id).

        Returns:
            The same evidence instance for chaining.
        """
        self._items[evidence.evidence_id] = evidence
        return evidence

    def get(self, evidence_id: str) -> Evidence | None:
        """Look up evidence by id.

        Args:
            evidence_id: Evidence identifier.

        Returns:
            The stored evidence, or ``None`` if missing.
        """
        return self._items.get(evidence_id)

    def exists(self, evidence_id: str) -> bool:
        """Check whether an evidence id is present.

        Args:
            evidence_id: Evidence identifier.

        Returns:
            ``True`` if the id is stored.
        """
        return evidence_id in self._items

    def list_all(self) -> list[Evidence]:
        """Return all stored evidence in insertion order.

        Returns:
            A list of every stored ``Evidence`` instance.
        """
        return list(self._items.values())

    def list_by_source(self, source_ref: str) -> list[Evidence]:
        """Return evidence captured from a given source reference.

        Args:
            source_ref: Source document or actor reference to filter on.

        Returns:
            Matching evidence records.
        """
        return [e for e in self._items.values() if e.source_ref == source_ref]
