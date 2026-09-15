# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""External Edit Sync / Reconcile (§3.14 / §10.4 / §23.7).

External change → detect (hash) → open reconcile → extract facts/events →
rebuild projections → impact → invalidate plans/results → resume production.
While any PENDING reconcile exists for a story, forward production is blocked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from novel_weaver.domain.errors import DomainError, ReconcilePendingError
from novel_weaver.domain.models import (
    Chapter,
    Event,
    FactProposalRecord,
    FactStatus,
    ProductionUnitStatus,
    ReconcileRecord,
    ReconcileStatus,
    StateItem,
)
from novel_weaver.production.fingerprint import content_fingerprint
from novel_weaver.production.invalidation import ImpactAnalyzer
from novel_weaver.production.planning import RollingPlanner
from novel_weaver.storage.repositories import StoryRepository
from novel_weaver.truth.audit import AuditLog
from novel_weaver.truth.evidence import Evidence, EvidenceStore
from novel_weaver.truth.proposal import FactProposal, PromotionError, promote_proposal


@dataclass
class DetectedEdit:
    """One chapter whose live content differs from the commit-time fingerprint.

    Attributes:
        chapter_id: Chapter identity.
        number: Chapter number.
        title: Chapter title at detection time.
        committed_hash: Fingerprint recorded at commit (or baseline).
        current_hash: Fingerprint of live content.
        has_drift: True when hashes differ.
        reason: Detection reason code.
    """

    chapter_id: str
    number: int
    title: str
    committed_hash: str
    current_hash: str
    has_drift: bool
    reason: str


@dataclass
class ReconcileResult:
    """Outcome of completing one reconcile ticket.

    Attributes:
        ok: Whether reconcile completed successfully.
        message: Human-readable summary.
        reconcile_id: Reconcile ticket identity.
        chapter_id: Edited chapter identity.
        fact_keys_changed: Fact keys written or superseded.
        stale_chapter_ids: Chapters invalidated by the edit.
        still_valid_chapter_ids: Chapters unaffected by the edit.
        invalidated_plan_ids: Plan nodes marked stale.
        extracted_fact_keys: Fact keys extracted from the edit.
        new_story_revision: Canonical revision after reconcile.
        production_blocked: Whether other pending reconciles remain.
        data: Extra payload (event_id, remaining_pending).
    """

    ok: bool
    message: str
    reconcile_id: str
    chapter_id: str
    fact_keys_changed: list[str] = field(default_factory=list)
    stale_chapter_ids: list[str] = field(default_factory=list)
    still_valid_chapter_ids: list[str] = field(default_factory=list)
    invalidated_plan_ids: list[str] = field(default_factory=list)
    extracted_fact_keys: list[str] = field(default_factory=list)
    new_story_revision: int | None = None
    production_blocked: bool = False
    data: dict[str, Any] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReconcileService:
    """Detect external chapter-content edits and run the reconcile pipeline."""

    def __init__(
        self,
        repo: StoryRepository,
        *,
        evidence_store: EvidenceStore | None = None,
        audit: AuditLog | None = None,
        planner: RollingPlanner | None = None,
        actor: str = "author",
    ) -> None:
        self.repo = repo
        self.evidence_store = evidence_store or EvidenceStore()
        self.audit = audit or AuditLog()
        self.planner = planner or RollingPlanner()
        self.actor = actor
        self.analyzer = ImpactAnalyzer()

    # ---------------------------------------------------------------- detect
    def detect_edits(self, story_id: str) -> list[DetectedEdit]:
        """Compare live chapter content against the fingerprint recorded at commit.

        Also baselines missing fingerprints on committed chapters.

        Args:
            story_id: Story to scan.

        Returns:
            DetectedEdit records (drift or baseline) for committed chapters.

        Raises:
            DomainError: If the story does not exist.
        """
        self._require_story(story_id)
        out: list[DetectedEdit] = []
        for chapter in self.repo.list_chapters(story_id):
            if chapter.status is not ProductionUnitStatus.COMMITTED:
                continue
            recorded = chapter.provenance.get("content_fingerprint")
            current = content_fingerprint(chapter.content)
            if recorded is None:
                # No baseline yet: treat current content as the baseline.
                chapter.provenance = {**chapter.provenance, "content_fingerprint": current}
                self.repo.save_chapter(story_id, chapter)
                out.append(
                    DetectedEdit(
                        chapter_id=chapter.chapter_id,
                        number=chapter.number,
                        title=chapter.title,
                        committed_hash=current,
                        current_hash=current,
                        has_drift=False,
                        reason="baseline_fingerprint_recorded",
                    )
                )
                continue
            if recorded != current:
                out.append(
                    DetectedEdit(
                        chapter_id=chapter.chapter_id,
                        number=chapter.number,
                        title=chapter.title,
                        committed_hash=recorded,
                        current_hash=current,
                        has_drift=True,
                        reason="content_hash_mismatch",
                    )
                )
        return out

    def pending_reconciles(self, story_id: str) -> list[ReconcileRecord]:
        """List PENDING reconcile tickets for a story.

        Args:
            story_id: Story to inspect.

        Returns:
            Pending ReconcileRecord list.
        """
        return self.repo.list_reconciles(story_id, status=ReconcileStatus.PENDING)

    def is_production_blocked(self, story_id: str) -> bool:
        """Whether any pending reconcile blocks forward production.

        Args:
            story_id: Story to inspect.

        Returns:
            True when at least one PENDING reconcile exists.
        """
        return bool(self.pending_reconciles(story_id))

    def assert_production_allowed(self, story_id: str) -> None:
        """Raise if production must wait for reconcile completion.

        Args:
            story_id: Story to check.

        Returns:
            None.

        Raises:
            ReconcilePendingError: When PENDING reconciles exist.
        """
        pending = self.pending_reconciles(story_id)
        if pending:
            ids = ", ".join(r.reconcile_id for r in pending)
            chapters = ", ".join(r.chapter_id for r in pending)
            raise ReconcilePendingError(
                f"story {story_id} has pending reconcile ({ids}); "
                f"chapters awaiting sync: {chapters}. Complete reconcile before production."
            )

    # ------------------------------------------------------------------ open
    def apply_author_chapter_edit(
        self,
        story_id: str,
        chapter_id: str,
        new_content: str,
        *,
        reason: str = "author external edit",
    ) -> ReconcileRecord:
        """Author writes new official chapter text; opens (or refreshes) a PENDING reconcile.

        Args:
            story_id: Story that owns the chapter.
            chapter_id: Chapter being rewritten.
            new_content: Replacement official chapter text.
            reason: Audit reason for the edit.

        Returns:
            The open (or refreshed) ReconcileRecord.

        Raises:
            DomainError: If story or chapter is missing.
        """
        self._require_story(story_id)
        chapter = self._require_chapter(story_id, chapter_id)

        previous_hash = chapter.provenance.get("content_fingerprint") or content_fingerprint(
            chapter.content
        )
        new_hash = content_fingerprint(new_content)
        if previous_hash == new_hash and chapter.content == new_content:
            # Idempotent no-op re-apply of identical content.
            existing = self._open_for_chapter(story_id, chapter_id)
            if existing is not None:
                return existing

        chapter.content = new_content
        chapter.provenance = {
            **chapter.provenance,
            "content_fingerprint": new_hash,
            "external_edit": True,
            "external_edit_reason": reason,
            "external_edit_at": _now().isoformat(),
            "needs_reconcile": True,
        }
        if chapter.status is ProductionUnitStatus.COMMITTED:
            chapter.provenance["needs_reconcile"] = True
        else:
            chapter.status = ProductionUnitStatus.STALE
        self.repo.save_chapter(story_id, chapter)

        record = self._open_record(
            story_id=story_id,
            chapter=chapter,
            previous_hash=previous_hash,
            current_hash=new_hash,
            reason=reason,
        )
        self.audit.record(
            "EXTERNAL_EDIT_OPENED",
            actor=self.actor,
            story_id=story_id,
            base_revision=self._revision(story_id),
            reconcile_id=record.reconcile_id,
            chapter_id=chapter_id,
            previous_hash=previous_hash,
            current_hash=new_hash,
            reason=reason,
        )
        return record

    def open_from_detected_drift(
        self,
        story_id: str,
        chapter_id: str,
        *,
        reason: str = "detected external drift",
    ) -> ReconcileRecord:
        """Open a reconcile for content that was already changed outside the engine.

        Args:
            story_id: Story that owns the chapter.
            chapter_id: Chapter with drifted content.
            reason: Audit reason for opening the ticket.

        Returns:
            The newly opened ReconcileRecord.

        Raises:
            DomainError: If story/chapter is missing or no drift is present.
        """
        self._require_story(story_id)
        chapter = self._require_chapter(story_id, chapter_id)
        recorded = chapter.provenance.get("content_fingerprint") or ""
        current = content_fingerprint(chapter.content)
        if recorded and recorded == current:
            raise DomainError(
                f"no content drift for chapter {chapter_id}; apply an edit first"
            )
        previous_hash = recorded or current
        chapter.provenance = {
            **chapter.provenance,
            "content_fingerprint": current,
            "external_edit": True,
            "needs_reconcile": True,
            "drift_detected_at": _now().isoformat(),
        }
        self.repo.save_chapter(story_id, chapter)
        record = self._open_record(
            story_id=story_id,
            chapter=chapter,
            previous_hash=previous_hash,
            current_hash=current,
            reason=reason,
        )
        self.audit.record(
            "EXTERNAL_DRIFT_OPENED",
            actor=self.actor,
            story_id=story_id,
            base_revision=self._revision(story_id),
            reconcile_id=record.reconcile_id,
            chapter_id=chapter_id,
            previous_hash=previous_hash,
            current_hash=current,
        )
        return record

    # -------------------------------------------------------------- complete
    def complete_reconcile(
        self,
        story_id: str,
        reconcile_id: str,
        *,
        fact_deltas: list[dict[str, Any]] | None = None,
        event_summary: str | None = None,
        force_author_promote: bool = True,
    ) -> ReconcileResult:
        """Extract facts/events, rebuild projections, impact-invalidate, unblock production.

        Args:
            story_id: Story that owns the reconcile ticket.
            reconcile_id: Pending reconcile identity.
            fact_deltas: Fact extractions with key/value/kind/claim/confidence.
            event_summary: Optional rebuilt event summary text.
            force_author_promote: When True, author-upsert Canonical facts
                directly; otherwise promote via evidence path when allowed.

        Returns:
            ReconcileResult with stale chapters, plans, and new revision.

        Raises:
            DomainError: If story/reconcile/chapter is missing or a fact
                delta lacks a key.
        """
        self._require_story(story_id)
        record = self.repo.get_reconcile(reconcile_id)
        if record is None or record.story_id != story_id:
            raise DomainError(f"reconcile not found: {reconcile_id}")
        if record.status is not ReconcileStatus.PENDING:
            return ReconcileResult(
                ok=False,
                message=f"reconcile {reconcile_id} already {record.status.value}",
                reconcile_id=reconcile_id,
                chapter_id=record.chapter_id,
                production_blocked=self.is_production_blocked(story_id),
            )

        chapter = self._require_chapter(story_id, record.chapter_id)
        changed_keys: set[str] = set()
        extracted_keys: list[str] = []

        # 1) Extract affected facts → Evidence → (author) promote / supersede.
        for delta in fact_deltas or []:
            key = str(delta.get("key") or "").strip()
            if not key:
                raise DomainError("fact_delta requires 'key'")
            claim = str(delta.get("claim") or f"external edit set {key}")
            value = delta.get("value")
            kind = str(delta.get("kind") or "world")
            confidence = float(delta.get("confidence", 0.99))

            ev = Evidence.capture(
                source_type="external_edit",
                source_ref=record.chapter_id,
                extracted_claim=claim,
                confidence=confidence,
                chapter_ref=record.chapter_id,
                source_revision=self._revision(story_id),
            )
            self.evidence_store.add(ev)
            self.repo.save_evidence(story_id, ev)

            rec = FactProposalRecord.create(
                claim=claim,
                evidence_refs=[ev.evidence_id],
                confidence=confidence,
                proposed_by=self.actor,
                target_kind=kind,
                target_key=key,
            )
            proposal = FactProposal(
                record=rec, claim_value=value, depends_on=list(delta.get("depends_on") or [])
            )
            self.repo.save_proposal(story_id, rec, value, proposal.depends_on)

            if force_author_promote:
                # Author-level external edit is a direct Canonical write (still evidence-backed).
                item = self._author_upsert_fact(
                    story_id, key, value, kind=kind, reason=record.reason or "external reconcile"
                )
                extracted_keys.append(key)
                changed_keys.add(key)
            else:
                try:
                    item = promote_proposal(
                        proposal,
                        self.evidence_store,
                        story_revision=self._revision(story_id),
                    )
                    item.provenance["chapter"] = record.chapter_id
                    item.provenance["reconcile_id"] = reconcile_id
                    self._supersede_prior_canonical(story_id, item)
                    self.repo.upsert_state_item(story_id, item)
                    self.repo.bump_story_revision(story_id, f"reconcile-promote:{key}")
                    extracted_keys.append(key)
                    changed_keys.add(key)
                except PromotionError:
                    # Stay PROPOSED — never auto-force Canon without acceptance path.
                    pass

        # 2) Rebuild chapter event projection from edited content.
        summary = event_summary or (
            f"Reconciled chapter {chapter.number}: {chapter.title} after external edit"
        )
        event = Event.create(
            time_ref=f"ch{chapter.number}",
            summary=summary,
            source_chapter=chapter.chapter_id,
            provenance={
                "reconcile_id": reconcile_id,
                "content_fingerprint": record.current_content_hash,
                "rebuilt": True,
            },
        )
        self.repo.save_event(story_id, event)
        self._invalidate_prior_chapter_events(story_id, chapter.chapter_id, keep=event.event_id)

        # 3) Impact analysis on explicit fact keys.
        chapters = self.repo.list_chapters(story_id)
        items = self.repo.list_state_items(story_id)
        impact = self.analyzer.analyze(chapters, items, changed_keys)

        stale_ids = set(impact.stale_chapter_ids)
        # 4) Forward invalidation: later planned units after the edited chapter.
        for ch in chapters:
            if ch.chapter_id == chapter.chapter_id:
                continue
            if ch.number <= chapter.number:
                continue
            if ch.status in (
                ProductionUnitStatus.PLANNED,
                ProductionUnitStatus.GENERATING,
                ProductionUnitStatus.CANDIDATE_READY,
                ProductionUnitStatus.STALE,
            ):
                ch.status = ProductionUnitStatus.STALE
                ch.provenance = {
                    **ch.provenance,
                    "stale_reason": f"forward_invalidate:reconcile:{reconcile_id}",
                    "upstream_edit": chapter.chapter_id,
                }
                stale_ids.add(ch.chapter_id)
                self.repo.save_chapter(story_id, ch)
            elif ch.status is ProductionUnitStatus.COMMITTED:
                ch.provenance = {
                    **ch.provenance,
                    "needs_reconcile": True,
                    "stale_reason": f"forward_review:reconcile:{reconcile_id}",
                }
                self.repo.save_chapter(story_id, ch)

        # 5) Persist impact for chapters already using changed keys (committed → flag only).
        for ch in chapters:
            if ch.chapter_id not in stale_ids:
                continue
            if ch.status is ProductionUnitStatus.COMMITTED:
                ch.provenance = {
                    **ch.provenance,
                    "needs_reconcile": True,
                    "stale_reason": f"reconcile:{reconcile_id}",
                }
            elif ch.status is not ProductionUnitStatus.COMMITTED:
                ch.status = ProductionUnitStatus.STALE
                ch.provenance = {
                    **ch.provenance,
                    "stale_reason": f"reconcile:{reconcile_id}",
                }
            self.repo.save_chapter(story_id, ch)

        # 6) Invalidate plans that depend on changed fact keys (§3.14).
        invalidated_plans = self.planner.after_commit(
            story_id,
            committed_plan_id=None,
            changed_fact_keys=changed_keys or {f"chapter.{chapter.number}.content"},
            reason=f"external reconcile {reconcile_id}",
        )
        plan_ids = [p.plan_id for p in invalidated_plans]

        # 7) Finalize chapter fingerprint + clear needs_reconcile on the edited unit.
        chapter = self._require_chapter(story_id, record.chapter_id)
        chapter.provenance = {
            **chapter.provenance,
            "content_fingerprint": record.current_content_hash,
            "needs_reconcile": False,
            "reconcile_id": reconcile_id,
            "reconciled_at": _now().isoformat(),
        }
        self.repo.save_chapter(story_id, chapter)

        # Resume path: never-committed forward-invalidated units become PLANNED again.
        for ch in self.repo.list_chapters(story_id):
            if ch.status is not ProductionUnitStatus.STALE:
                continue
            if ch.provenance.get("upstream_edit") or ch.provenance.get("stale_reason", "").startswith(
                ("reconcile:", "forward_invalidate:")
            ):
                ch.status = ProductionUnitStatus.PLANNED
                ch.provenance = {
                    **ch.provenance,
                    "replanned_after_reconcile": reconcile_id,
                }
                self.repo.save_chapter(story_id, ch)

        still_valid = [c.chapter_id for c in chapters if c.chapter_id not in stale_ids]
        new_rev = self.repo.bump_story_revision(story_id, f"reconcile:{reconcile_id}")

        record.status = ReconcileStatus.COMPLETED
        record.completed_at = _now()
        record.fact_keys_changed = sorted(changed_keys)
        record.extracted_fact_keys = extracted_keys
        record.stale_chapter_ids = sorted(stale_ids)
        record.still_valid_chapter_ids = still_valid
        record.invalidated_plan_ids = plan_ids
        record.provenance = {
            **record.provenance,
            "event_id": event.event_id,
            "new_story_revision": new_rev,
        }
        self.repo.save_reconcile(record)

        self.audit.record(
            "RECONCILE_COMPLETED",
            actor=self.actor,
            story_id=story_id,
            base_revision=new_rev,
            reconcile_id=reconcile_id,
            chapter_id=record.chapter_id,
            fact_keys_changed=record.fact_keys_changed,
            stale_chapters=record.stale_chapter_ids,
            invalidated_plans=plan_ids,
        )

        blocked = self.is_production_blocked(story_id)
        return ReconcileResult(
            ok=True,
            message="reconcile completed",
            reconcile_id=reconcile_id,
            chapter_id=record.chapter_id,
            fact_keys_changed=record.fact_keys_changed,
            stale_chapter_ids=record.stale_chapter_ids,
            still_valid_chapter_ids=still_valid,
            invalidated_plan_ids=plan_ids,
            extracted_fact_keys=extracted_keys,
            new_story_revision=new_rev,
            production_blocked=blocked,
            data={"event_id": event.event_id, "remaining_pending": blocked},
        )

    def cancel_reconcile(
        self, story_id: str, reconcile_id: str, *, reason: str = "cancelled"
    ) -> ReconcileRecord:
        """Cancel a pending ticket without rebuilding projections (author aborts edit path).

        Args:
            story_id: Story that owns the ticket.
            reconcile_id: Pending reconcile identity.
            reason: Cancellation reason stored on the record.

        Returns:
            The ReconcileRecord (CANCELLED when it was still PENDING).

        Raises:
            DomainError: If story or reconcile is missing.
        """
        self._require_story(story_id)
        record = self.repo.get_reconcile(reconcile_id)
        if record is None or record.story_id != story_id:
            raise DomainError(f"reconcile not found: {reconcile_id}")
        if record.status is ReconcileStatus.PENDING:
            record.status = ReconcileStatus.CANCELLED
            record.completed_at = _now()
            record.reason = reason
            self.repo.save_reconcile(record)
            self.audit.record(
                "RECONCILE_CANCELLED",
                actor=self.actor,
                story_id=story_id,
                base_revision=self._revision(story_id),
                reconcile_id=reconcile_id,
                reason=reason,
            )
        return record

    # -------------------------------------------------------------- internals
    def _open_record(
        self,
        story_id: str,
        chapter: Chapter,
        *,
        previous_hash: str,
        current_hash: str,
        reason: str,
    ) -> ReconcileRecord:
        existing = self._open_for_chapter(story_id, chapter.chapter_id)
        if existing is not None:
            existing.previous_content_hash = previous_hash
            existing.current_content_hash = current_hash
            existing.reason = reason
            existing.previous_story_revision = self._revision(story_id)
            self.repo.save_reconcile(existing)
            return existing

        record = ReconcileRecord.create(
            story_id=story_id,
            chapter_id=chapter.chapter_id,
            previous_content_hash=previous_hash,
            current_content_hash=current_hash,
            previous_story_revision=self._revision(story_id),
            reason=reason,
            provenance={"chapter_number": chapter.number, "opened_by": self.actor},
        )
        self.repo.save_reconcile(record)
        return record

    def _open_for_chapter(self, story_id: str, chapter_id: str) -> ReconcileRecord | None:
        for rec in self.repo.list_reconciles(story_id, status=ReconcileStatus.PENDING):
            if rec.chapter_id == chapter_id:
                return rec
        return None

    def _author_upsert_fact(
        self, story_id: str, key: str, value: Any, *, kind: str, reason: str
    ) -> StateItem:
        story = self._require_story(story_id)
        existing = [
            i for i in self.repo.find_state_by_key(story_id, key) if i.status == FactStatus.CANONICAL
        ]
        if existing:
            old = existing[0]
            old.status = FactStatus.SUPERSEDED
            old.superseded_by = f"reconcile:{key}:{story.current_canonical_revision + 1}"
            old.effective_to = story.current_canonical_revision
            self.repo.upsert_state_item(story_id, old)

        item = StateItem.create(
            key=key, value=value, kind=kind, status=FactStatus.CANONICAL, source="external_edit"
        )
        item.effective_from = story.current_canonical_revision + 1
        item.provenance = {
            "origin": "external_reconcile",
            "reason": reason,
            "at": _now().isoformat(),
        }
        self.repo.upsert_state_item(story_id, item)
        self.repo.bump_story_revision(story_id, f"reconcile-fact:{key}")
        return item

    def _supersede_prior_canonical(self, story_id: str, item: StateItem) -> None:
        story = self._require_story(story_id)
        for prior in self.repo.find_state_by_key(story_id, item.key):
            if prior.item_id == item.item_id or prior.status != FactStatus.CANONICAL:
                continue
            prior.status = FactStatus.SUPERSEDED
            prior.superseded_by = item.item_id
            prior.effective_to = story.current_canonical_revision
            self.repo.upsert_state_item(story_id, prior)

    def _invalidate_prior_chapter_events(
        self, story_id: str, chapter_id: str, *, keep: str
    ) -> None:
        for ev in self.repo.list_events(story_id):
            if ev.source_chapter != chapter_id or ev.event_id == keep:
                continue
            ev.status = "INVALIDATED"
            ev.provenance = {**ev.provenance, "invalidated_by_reconcile": True}
            self.repo.save_event(story_id, ev)

    def _revision(self, story_id: str) -> int:
        story = self.repo.get_story(story_id)
        return story.current_canonical_revision if story else -1

    def _require_story(self, story_id: str) -> Any:
        story = self.repo.get_story(story_id)
        if story is None:
            raise DomainError(f"story not found: {story_id}")
        return story

    def _require_chapter(self, story_id: str, chapter_id: str) -> Chapter:
        chapter = self.repo.get_chapter(chapter_id)
        if chapter is None:
            raise DomainError(f"chapter not found: {chapter_id}")
        return chapter
