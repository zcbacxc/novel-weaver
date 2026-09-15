# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

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
    ReconcileRecord,
    ReconcileStatus,
    StateItem,
    Story,
    StoryRevision,
    ThreadRecord,
)
from novel_weaver.runtime.checkpoint import Checkpoint
from novel_weaver.storage.db import Database
from novel_weaver.truth.evidence import Evidence


def _j(value: Any) -> str:
    """Serialize a value to a compact JSON string for storage columns."""
    return json.dumps(value, ensure_ascii=False, default=str)


def _jl(text: str | None, default: Any) -> Any:
    """Deserialize a stored JSON column; return ``default`` when empty/None."""
    if not text:
        return default
    return json.loads(text)


class StoryRepository:
    """Persistence facade for one SQLite database.

    Owns all reads/writes of Canonical story entities (stories, state items,
    events, chapters, evidence, proposals, audit log, reconcile records,
    runtime checkpoints, and narrative threads). Callers never issue SQL
    directly; every public method accepts/returns domain objects.

    Main interface:
        Story: ``save_story``, ``get_story``, ``append_revision``,
        ``bump_story_revision``.
        State: ``upsert_state_item``, ``get_state_item``,
        ``list_state_items``, ``find_state_by_key``.
        Events/Chapters: ``save_event``, ``list_events``, ``save_chapter``,
        ``get_chapter``, ``list_chapters``.
        Evidence/Proposals/Audit: ``save_evidence``, ``get_evidence``,
        ``save_proposal``, ``save_audit``.
        Reconcile: ``save_reconcile``, ``get_reconcile``, ``list_reconciles``.
        Checkpoints: ``save_checkpoint``, ``load_checkpoint``,
        ``list_checkpoints_for_story``.
        Threads: ``save_thread``, ``get_thread``, ``list_threads``,
        ``find_thread_by_name``.
    """

    def __init__(self, db: Database) -> None:
        """Bind the repository to an open database.

        Args:
            db: Database facade providing ``execute`` and ``commit``.
        """
        self.db = db

    # --- Story ---
    def save_story(self, story: Story) -> None:
        """Insert or update the story row (upsert on ``story_id``).

        Args:
            story: Story entity whose fields replace any existing row.

        Returns:
            None
        """
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
        """Load one story by id.

        Args:
            story_id: Stable story identity.

        Returns:
            The story, or ``None`` when no row matches.
        """
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
        """Record an immutable story-revision entry (replace on conflict).

        Args:
            story_id: Story the revision belongs to.
            revision: Canonical revision number being logged.
            reason: Human-readable reason for the revision.

        Returns:
            The created ``StoryRevision`` (includes ``created_at`` and
            ``checkpoint_ref``).
        """
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
        """Insert or update one canonical fact slot.

        Args:
            story_id: Owning story identity.
            item: State item to persist; conflicts on ``item_id`` update all fields.

        Returns:
            None
        """
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
        """Load one state item by primary key.

        Args:
            item_id: State item identity.

        Returns:
            The item, or ``None`` when no row matches.
        """
        row = self.db.execute(
            "SELECT * FROM state_items WHERE item_id = ?", (item_id,)
        ).fetchone()
        return self._row_to_state(row) if row else None

    def list_state_items(
        self, story_id: str, *, status: FactStatus | None = None, kind: str | None = None
    ) -> list[StateItem]:
        """List state items for a story, optionally filtered.

        Args:
            story_id: Owning story identity.
            status: Restrict to this ``FactStatus`` when provided.
            kind: Restrict to this fact kind (e.g. ``character``) when provided.

        Returns:
            Matching state items in insertion/row order.
        """
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
        """Find all state items sharing a fact key, newest revision first.

        Args:
            story_id: Owning story identity.
            key: Namespaced fact key to look up.

        Returns:
            Matching items ordered by ``revision`` descending.
        """
        rows = self.db.execute(
            "SELECT * FROM state_items WHERE story_id = ? AND key = ? ORDER BY revision DESC",
            (story_id, key),
        ).fetchall()
        return [self._row_to_state(r) for r in rows]

    def _row_to_state(self, row: Any) -> StateItem:
        """Map a ``state_items`` row to a ``StateItem``."""
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
        """Insert or update one narrative event.

        Args:
            story_id: Owning story identity.
            event: Event to persist; conflicts on ``event_id`` update all fields.

        Returns:
            None
        """
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
        """List all narrative events for a story in storage order.

        Args:
            story_id: Owning story identity.

        Returns:
            Events ordered by row insertion.
        """
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
        """Insert or update one chapter row.

        Args:
            story_id: Owning story identity.
            chapter: Chapter to persist; conflicts on ``chapter_id`` update all fields.

        Returns:
            None
        """
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
        """Load one chapter by identity.

        Args:
            chapter_id: Chapter primary key.

        Returns:
            The chapter, or ``None`` when no row matches.
        """
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
        """List all chapters of a story in chapter-number order.

        Args:
            story_id: Owning story identity.

        Returns:
            Chapters ordered by ``number`` ascending.
        """
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
        """Insert or replace one evidence row.

        Args:
            story_id: Owning story identity.
            evidence: Evidence record supporting fact proposals.

        Returns:
            None
        """
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
        """Load one evidence record by identity.

        Args:
            evidence_id: Evidence primary key.

        Returns:
            The evidence record, or ``None`` when no row matches.
        """
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
        """Insert or update a fact-proposal row.

        Args:
            story_id: Owning story identity.
            record: Proposal metadata (claim, evidence refs, status, etc.).
            claim_value: Proposed fact value to store as JSON.
            depends_on: Dependency keys for impact analysis.

        Returns:
            None
        """
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
        """Insert or replace one append-only audit entry.

        Args:
            story_id: Owning story identity.
            action: Action name (e.g. promote, commit, invalidate).
            actor: Who performed the action (author, orchestrator, system).
            base_revision: Canonical revision the action was based on.
            outcome: Result code (default ``OK`` at call site).
            payload: Structured details of the action.
            audit_id: Audit primary key.
            created_at: When the action occurred.

        Returns:
            None
        """
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
        """Increment the story's Canonical revision and log it.

        Args:
            story_id: Story to bump.
            reason: Why the revision is advanced.

        Returns:
            The new Canonical revision number.

        Raises:
            KeyError: If the story does not exist.
        """
        story = self.get_story(story_id)
        if story is None:
            raise KeyError(f"story not found: {story_id}")
        story.current_canonical_revision += 1
        story.updated_at = datetime.now(story.updated_at.tzinfo)
        self.save_story(story)
        self.append_revision(story_id, story.current_canonical_revision, reason)
        return story.current_canonical_revision

    # --- Reconcile ---
    def save_reconcile(self, record: ReconcileRecord) -> None:
        """Insert or update one external-edit reconcile record.

        Args:
            record: Reconcile record describing impact of an author edit.

        Returns:
            None
        """
        self.db.execute(
            """
            INSERT INTO reconcile_records (
                reconcile_id, story_id, chapter_id, previous_content_hash,
                current_content_hash, previous_story_revision, status, reason,
                fact_keys_changed_json, stale_chapter_ids_json,
                still_valid_chapter_ids_json, invalidated_plan_ids_json,
                extracted_fact_keys_json, created_at, completed_at, provenance_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(reconcile_id) DO UPDATE SET
                previous_content_hash=excluded.previous_content_hash,
                current_content_hash=excluded.current_content_hash,
                previous_story_revision=excluded.previous_story_revision,
                status=excluded.status,
                reason=excluded.reason,
                fact_keys_changed_json=excluded.fact_keys_changed_json,
                stale_chapter_ids_json=excluded.stale_chapter_ids_json,
                still_valid_chapter_ids_json=excluded.still_valid_chapter_ids_json,
                invalidated_plan_ids_json=excluded.invalidated_plan_ids_json,
                extracted_fact_keys_json=excluded.extracted_fact_keys_json,
                completed_at=excluded.completed_at,
                provenance_json=excluded.provenance_json
            """,
            (
                record.reconcile_id,
                record.story_id,
                record.chapter_id,
                record.previous_content_hash,
                record.current_content_hash,
                record.previous_story_revision,
                record.status.value,
                record.reason,
                _j(record.fact_keys_changed),
                _j(record.stale_chapter_ids),
                _j(record.still_valid_chapter_ids),
                _j(record.invalidated_plan_ids),
                _j(record.extracted_fact_keys),
                record.created_at.isoformat(),
                record.completed_at.isoformat() if record.completed_at else None,
                _j(record.provenance),
            ),
        )
        self.db.commit()

    def get_reconcile(self, reconcile_id: str) -> ReconcileRecord | None:
        """Load one reconcile record by identity.

        Args:
            reconcile_id: Reconcile primary key.

        Returns:
            The record, or ``None`` when no row matches.
        """
        row = self.db.execute(
            "SELECT * FROM reconcile_records WHERE reconcile_id = ?", (reconcile_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_reconcile(row)

    def list_reconciles(
        self, story_id: str, status: ReconcileStatus | None = None
    ) -> list[ReconcileRecord]:
        """List reconcile records for a story, oldest first.

        Args:
            story_id: Owning story identity.
            status: Restrict to this status when provided.

        Returns:
            Reconcile records ordered by ``created_at`` ascending.
        """
        if status is None:
            rows = self.db.execute(
                "SELECT * FROM reconcile_records WHERE story_id = ? ORDER BY created_at",
                (story_id,),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM reconcile_records WHERE story_id = ? AND status = ? ORDER BY created_at",
                (story_id, status.value),
            ).fetchall()
        return [self._row_to_reconcile(r) for r in rows]

    def _row_to_reconcile(self, row: Any) -> ReconcileRecord:
        """Map a ``reconcile_records`` row to a ``ReconcileRecord``."""
        return ReconcileRecord(
            reconcile_id=row["reconcile_id"],
            story_id=row["story_id"],
            chapter_id=row["chapter_id"],
            previous_content_hash=row["previous_content_hash"],
            current_content_hash=row["current_content_hash"],
            previous_story_revision=row["previous_story_revision"],
            status=ReconcileStatus(row["status"]),
            reason=row["reason"],
            fact_keys_changed=_jl(row["fact_keys_changed_json"], []),
            stale_chapter_ids=_jl(row["stale_chapter_ids_json"], []),
            still_valid_chapter_ids=_jl(row["still_valid_chapter_ids_json"], []),
            invalidated_plan_ids=_jl(row["invalidated_plan_ids_json"], []),
            extracted_fact_keys=_jl(row["extracted_fact_keys_json"], []),
            created_at=datetime.fromisoformat(row["created_at"]),
            completed_at=(
                datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
            ),
            provenance=_jl(row["provenance_json"], {}),
        )

    # --- Checkpoints (runtime only; never mutates Canonical revision) ---
    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Persist a runtime checkpoint. Idempotent on ``checkpoint_id``.

        Uses INSERT OR REPLACE so the same (run_id, step) can be saved again
        after a status change without creating duplicate rows. Does not touch
        stories / story_revisions.

        Args:
            checkpoint: Runtime checkpoint envelope to store.

        Returns:
            None
        """
        self.db.execute(
            """
            INSERT OR REPLACE INTO checkpoints (
                checkpoint_id, story_id, revision, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                checkpoint.checkpoint_id,
                checkpoint.story_id,
                checkpoint.base_story_revision,
                _j(checkpoint.to_payload_envelope()),
                checkpoint.created_at.isoformat(),
            ),
        )
        self.db.commit()

    def load_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        """Load one checkpoint by id. Safe to call repeatedly (idempotent).

        Args:
            checkpoint_id: Checkpoint primary key.

        Returns:
            The checkpoint, or ``None`` when no row matches.
        """
        row = self.db.execute(
            "SELECT * FROM checkpoints WHERE checkpoint_id = ?", (checkpoint_id,)
        ).fetchone()
        if row is None:
            return None
        return Checkpoint.from_row(
            checkpoint_id=row["checkpoint_id"],
            story_id=row["story_id"],
            revision=row["revision"],
            payload_json=_jl(row["payload_json"], {}),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_checkpoints_for_story(self, story_id: str) -> list[Checkpoint]:
        """List checkpoints for a story, oldest first (rowid order).

        Args:
            story_id: Owning story identity.

        Returns:
            Checkpoints ordered by insertion and ``created_at``.
        """
        rows = self.db.execute(
            "SELECT * FROM checkpoints WHERE story_id = ? ORDER BY rowid, created_at",
            (story_id,),
        ).fetchall()
        return [
            Checkpoint.from_row(
                checkpoint_id=row["checkpoint_id"],
                story_id=row["story_id"],
                revision=row["revision"],
                payload_json=_jl(row["payload_json"], {}),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    # --- Threads (throughline) ---
    def save_thread(self, story_id: str, thread: ThreadRecord) -> None:
        """Insert or update one narrative throughline thread.

        Args:
            story_id: Owning story identity.
            thread: Thread record to persist; conflicts on ``thread_id`` update all fields.

        Returns:
            None
        """
        self.db.execute(
            """
            INSERT INTO threads (
                thread_id, story_id, name, introduced_at, current_status,
                obligations_json, related_entities_json, expected_resolution,
                last_touched_at, revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                name=excluded.name,
                introduced_at=excluded.introduced_at,
                current_status=excluded.current_status,
                obligations_json=excluded.obligations_json,
                related_entities_json=excluded.related_entities_json,
                expected_resolution=excluded.expected_resolution,
                last_touched_at=excluded.last_touched_at,
                revision=excluded.revision
            """,
            (
                thread.thread_id,
                story_id,
                thread.name,
                thread.introduced_at,
                thread.current_status,
                _j(thread.obligations),
                _j(thread.related_entities),
                thread.expected_resolution,
                thread.last_touched_at,
                thread.revision,
            ),
        )
        self.db.commit()

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        """Load one thread by identity.

        Args:
            thread_id: Thread primary key.

        Returns:
            The thread record, or ``None`` when no row matches.
        """
        row = self.db.execute(
            "SELECT * FROM threads WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_thread(row)

    def list_threads(
        self, story_id: str, status: str | None = None
    ) -> list[ThreadRecord]:
        """List threads for a story, optionally by status.

        Args:
            story_id: Owning story identity.
            status: Restrict to this thread status (e.g. ``OPEN``) when provided.

        Returns:
            Threads ordered by introduction time then thread id.
        """
        if status is None:
            rows = self.db.execute(
                "SELECT * FROM threads WHERE story_id = ? ORDER BY introduced_at, thread_id",
                (story_id,),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM threads WHERE story_id = ? AND current_status = ? "
                "ORDER BY introduced_at, thread_id",
                (story_id, status),
            ).fetchall()
        return [self._row_to_thread(r) for r in rows]

    def find_thread_by_name(self, story_id: str, name: str) -> ThreadRecord | None:
        """Find the newest thread matching a display name.

        Args:
            story_id: Owning story identity.
            name: Thread display name.

        Returns:
            Highest-revision matching thread, or ``None``.
        """
        row = self.db.execute(
            "SELECT * FROM threads WHERE story_id = ? AND name = ? ORDER BY revision DESC LIMIT 1",
            (story_id, name),
        ).fetchone()
        return self._row_to_thread(row) if row else None

    @staticmethod
    def _row_to_thread(row: Any) -> ThreadRecord:
        """Map a ``threads`` row to a ``ThreadRecord``."""
        return ThreadRecord(
            thread_id=row["thread_id"],
            name=row["name"],
            introduced_at=row["introduced_at"],
            current_status=row["current_status"],
            obligations=_jl(row["obligations_json"], []),
            related_entities=_jl(row["related_entities_json"], []),
            expected_resolution=row["expected_resolution"],
            last_touched_at=row["last_touched_at"],
            revision=row["revision"],
        )
