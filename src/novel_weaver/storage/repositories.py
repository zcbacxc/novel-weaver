"""Repository layer: maps domain entities to SQLite rows."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from novel_weaver.domain.models import (
    Chapter,
    Event,
    FactStatus,
    FactProposalRecord,
    ProductionUnitStatus,
    StateItem,
    Story,
    StoryRevision,
)
from novel_weaver.storage.db import Database
from novel_weaver.truth.evidence import Evidence


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _jl(text: str | None, default: Any) -> Any:
    if not text:
        return default
    return json.loads(text)


class StoryRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # --- Story ---
    def save_story(self, story: Story) -> None:
        self.db.execute(
            """
            INSERT INTO stories (
                story_id, title, premise, creative_intent, constraints_json,
                current_canonical_revision, lifecycle_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id) DO UPDATE SET
                title=excluded.title,
                premise=excluded.premise,
                creative_intent=excluded.creative_intent,
                constraints_json=excluded.constraints_json,
                current_canonical_revision=excluded.current_canonical_revision,
                lifecycle_status=excluded.lifecycle_status,
                updated_at=excluded.updated_at
            """,
            (
                story.story_id,
                story.title,
                story.premise,
                story.creative_intent,
                _j(story.constraints),
                story.current_canonical_revision,
                story.lifecycle_status,
                story.created_at.isoformat(),
                story.updated_at.isoformat(),
            ),
        )
        self.db.commit()

    def get_story(self, story_id: str) -> Story | None:
        row = self.db.execute(
            "SELECT * FROM stories WHERE story_id = ?", (story_id,)
        ).fetchone()
        if row is None:
            return None
        return Story(
            story_id=row["story_id"],
            title=row["title"],
            premise=row["premise"],
            creative_intent=row["creative_intent"],
            constraints=_jl(row["constraints_json"], {}),
            current_canonical_revision=row["current_canonical_revision"],
            lifecycle_status=row["lifecycle_status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def append_revision(self, story_id: str, revision: int, reason: str = "") -> StoryRevision:
        rev = StoryRevision(story_id=story_id, revision=revision, reason=reason)
        self.db.execute(
            """
            INSERT OR REPLACE INTO story_revisions (story_id, revision, created_at, reason, checkpoint_ref)
            VALUES (?, ?, ?, ?, ?)
            """,
            (story_id, revision, rev.created_at.isoformat(), reason, rev.checkpoint_ref),
        )
        self.db.commit()
        return rev

    # --- State ---
    def upsert_state_item(self, story_id: str, item: StateItem) -> None:
        self.db.execute(
            """
            INSERT INTO state_items (
                item_id, story_id, key, value_json, kind, status, revision, source,
                confidence, effective_from, effective_to, provenance_json,
                superseded_by, invalidated_by, depends_on_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_id) DO UPDATE SET
                key=excluded.key,
                value_json=excluded.value_json,
                kind=excluded.kind,
                status=excluded.status,
                revision=excluded.revision,
                source=excluded.source,
                confidence=excluded.confidence,
                effective_from=excluded.effective_from,
                effective_to=excluded.effective_to,
                provenance_json=excluded.provenance_json,
                superseded_by=excluded.superseded_by,
                invalidated_by=excluded.invalidated_by,
                depends_on_json=excluded.depends_on_json
            """,
            (
                item.item_id,
                story_id,
                item.key,
                _j(item.value),
                item.kind,
                item.status.value,
                item.revision,
                item.source,
                item.confidence,
                item.effective_from,
                item.effective_to,
                _j(item.provenance),
                item.superseded_by,
                item.invalidated_by,
                _j(item.depends_on),
            ),
        )
        self.db.commit()

    def get_state_item(self, item_id: str) -> StateItem | None:
        row = self.db.execute(
            "SELECT * FROM state_items WHERE item_id = ?", (item_id,)
        ).fetchone()
        return self._row_to_state(row) if row else None

    def list_state_items(
        self, story_id: str, *, status: FactStatus | None = None, kind: str | None = None
    ) -> list[StateItem]:
        sql = "SELECT * FROM state_items WHERE story_id = ?"
        params: list[Any] = [story_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value)
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        rows = self.db.execute(sql, params).fetchall()
        return [self._row_to_state(r) for r in rows]

    def find_state_by_key(self, story_id: str, key: str) -> list[StateItem]:
        rows = self.db.execute(
            "SELECT * FROM state_items WHERE story_id = ? AND key = ? ORDER BY revision DESC",
            (story_id, key),
        ).fetchall()
        return [self._row_to_state(r) for r in rows]

    def _row_to_state(self, row: Any) -> StateItem:
        return StateItem(
            item_id=row["item_id"],
            key=row["key"],
            value=_jl(row["value_json"], None),
            kind=row["kind"],
            status=FactStatus(row["status"]),
            revision=row["revision"],
            source=row["source"],
            confidence=row["confidence"],
            effective_from=row["effective_from"],
            effective_to=row["effective_to"],
            provenance=_jl(row["provenance_json"], {}),
            superseded_by=row["superseded_by"],
            invalidated_by=row["invalidated_by"],
            depends_on=_jl(row["depends_on_json"], []),
        )

    # --- Events ---
    def save_event(self, story_id: str, event: Event) -> None:
        self.db.execute(
            """
            INSERT INTO events (
                event_id, story_id, time_ref, summary, participants_json, location,
                claims_json, source_chapter, status, revision, provenance_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                time_ref=excluded.time_ref,
                summary=excluded.summary,
                participants_json=excluded.participants_json,
                location=excluded.location,
                claims_json=excluded.claims_json,
                source_chapter=excluded.source_chapter,
                status=excluded.status,
                revision=excluded.revision,
                provenance_json=excluded.provenance_json
            """,
            (
                event.event_id,
                story_id,
                event.time_ref,
                event.summary,
                _j(event.participants),
                event.location,
                _j(event.claims),
                event.source_chapter,
                event.status,
                event.revision,
                _j(event.provenance),
            ),
        )
        self.db.commit()

    def list_events(self, story_id: str) -> list[Event]:
        rows = self.db.execute(
            "SELECT * FROM events WHERE story_id = ? ORDER BY rowid", (story_id,)
        ).fetchall()
        return [
            Event(
                event_id=r["event_id"],
                time_ref=r["time_ref"],
                summary=r["summary"],
                participants=_jl(r["participants_json"], []),
                location=r["location"],
                claims=_jl(r["claims_json"], {}),
                source_chapter=r["source_chapter"],
                status=r["status"],
                revision=r["revision"],
                provenance=_jl(r["provenance_json"], {}),
            )
            for r in rows
        ]

    # --- Chapters ---
    def save_chapter(self, story_id: str, chapter: Chapter) -> None:
        self.db.execute(
            """
            INSERT INTO chapters (
                chapter_id, story_id, number, title, plan, content, status, revision,
                depends_on_json, fact_keys_used_json, provenance_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chapter_id) DO UPDATE SET
                title=excluded.title,
                plan=excluded.plan,
                content=excluded.content,
                status=excluded.status,
                revision=excluded.revision,
                depends_on_json=excluded.depends_on_json,
                fact_keys_used_json=excluded.fact_keys_used_json,
                provenance_json=excluded.provenance_json
            """,
            (
                chapter.chapter_id,
                story_id,
                chapter.number,
                chapter.title,
                chapter.plan,
                chapter.content,
                chapter.status.value,
                chapter.revision,
                _j(chapter.depends_on),
                _j(chapter.fact_keys_used),
                _j(chapter.provenance),
            ),
        )
        self.db.commit()

    def get_chapter(self, chapter_id: str) -> Chapter | None:
        row = self.db.execute(
            "SELECT * FROM chapters WHERE chapter_id = ?", (chapter_id,)
        ).fetchone()
        if row is None:
            return None
        return Chapter(
            chapter_id=row["chapter_id"],
            number=row["number"],
            title=row["title"],
            plan=row["plan"],
            content=row["content"],
            status=ProductionUnitStatus(row["status"]),
            revision=row["revision"],
            depends_on=_jl(row["depends_on_json"], []),
            fact_keys_used=_jl(row["fact_keys_used_json"], []),
            provenance=_jl(row["provenance_json"], {}),
        )

    def list_chapters(self, story_id: str) -> list[Chapter]:
        rows = self.db.execute(
            "SELECT * FROM chapters WHERE story_id = ? ORDER BY number", (story_id,)
        ).fetchall()
        out: list[Chapter] = []
        for row in rows:
            out.append(
                Chapter(
                    chapter_id=row["chapter_id"],
                    number=row["number"],
                    title=row["title"],
                    plan=row["plan"],
                    content=row["content"],
                    status=ProductionUnitStatus(row["status"]),
                    revision=row["revision"],
                    depends_on=_jl(row["depends_on_json"], []),
                    fact_keys_used=_jl(row["fact_keys_used_json"], []),
                    provenance=_jl(row["provenance_json"], {}),
                )
            )
        return out

    # --- Evidence ---
    def save_evidence(self, story_id: str, evidence: Evidence) -> None:
        self.db.execute(
            """
            INSERT OR REPLACE INTO evidence (
                evidence_id, story_id, source_type, source_ref, source_revision,
                chapter_ref, location, extracted_claim, confidence, captured_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence.evidence_id,
                story_id,
                evidence.source_type,
                evidence.source_ref,
                evidence.source_revision,
                evidence.chapter_ref,
                evidence.location,
                evidence.extracted_claim,
                evidence.confidence,
                evidence.captured_at.isoformat(),
                _j(evidence.metadata),
            ),
        )
        self.db.commit()

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        row = self.db.execute(
            "SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()
        if row is None:
            return None
        return Evidence(
            evidence_id=row["evidence_id"],
            source_type=row["source_type"],
            source_ref=row["source_ref"],
            extracted_claim=row["extracted_claim"],
            source_revision=row["source_revision"],
            chapter_ref=row["chapter_ref"],
            location=row["location"],
            confidence=row["confidence"],
            captured_at=datetime.fromisoformat(row["captured_at"]),
            metadata=_jl(row["metadata_json"], {}),
        )

    # --- Proposals ---
    def save_proposal(self, story_id: str, record: FactProposalRecord, claim_value: Any, depends_on: list[str]) -> None:
        self.db.execute(
            """
            INSERT INTO proposals (
                proposal_id, story_id, claim, evidence_refs_json, confidence, status,
                conflicts_json, proposed_by, target_kind, target_key, created_at,
                promoted_item_id, claim_value_json, depends_on_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(proposal_id) DO UPDATE SET
                status=excluded.status,
                conflicts_json=excluded.conflicts_json,
                promoted_item_id=excluded.promoted_item_id
            """,
            (
                record.proposal_id,
                story_id,
                record.claim,
                _j(record.evidence_refs),
                record.confidence,
                record.status.value,
                _j(record.conflicts),
                record.proposed_by,
                record.target_kind,
                record.target_key,
                record.created_at.isoformat(),
                record.promoted_item_id,
                _j(claim_value),
                _j(depends_on),
            ),
        )
        self.db.commit()

    # --- Audit ---
    def save_audit(
        self,
        story_id: str,
        action: str,
        actor: str,
        base_revision: int,
        outcome: str,
        payload: dict[str, Any],
        audit_id: str,
        created_at: datetime,
    ) -> None:
        self.db.execute(
            """
            INSERT OR REPLACE INTO audit_log (
                audit_id, story_id, action, actor, base_revision, outcome, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                story_id,
                action,
                actor,
                base_revision,
                outcome,
                _j(payload),
                created_at.isoformat(),
            ),
        )
        self.db.commit()

    def bump_story_revision(self, story_id: str, reason: str = "") -> int:
        story = self.get_story(story_id)
        if story is None:
            raise KeyError(f"story not found: {story_id}")
        story.current_canonical_revision += 1
        story.updated_at = datetime.now(story.updated_at.tzinfo)
        self.save_story(story)
        self.append_revision(story_id, story.current_canonical_revision, reason)
        return story.current_canonical_revision
