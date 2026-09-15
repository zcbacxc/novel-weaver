# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Production orchestrator: plan 鈫?generate 鈫?validate 鈫?review 鈫?commit."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from novel_weaver.domain.errors import DomainError, GuardRejectError
from novel_weaver.domain.models import (
    CandidateStatus,
    Chapter,
    Event,
    FactProposalRecord,
    FactStatus,
    ProductionUnitStatus,
    StateItem,
    Story,
)
from novel_weaver.production.context import ContextPack, build_context_pack
from novel_weaver.production.fake_gen import FakeGenerator, GeneratedCandidate
from novel_weaver.production.invalidation import ImpactAnalyzer, ImpactReport, mark_stale
from novel_weaver.storage.repositories import StoryRepository
from novel_weaver.truth.audit import AuditLog
from novel_weaver.truth.commit_guard import (
    CommitGuard,
    CommitRequest,
    CommitResult,
    ProductionSession,
)
from novel_weaver.truth.evidence import Evidence, EvidenceStore
from novel_weaver.truth.proposal import FactProposal, PromotionError, promote_proposal


@dataclass
class OrchestrationResult:
    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)


class ProductionOrchestrator:
    def __init__(
        self,
        repo: StoryRepository,
        *,
        evidence_store: EvidenceStore | None = None,
        audit: AuditLog | None = None,
        guard: CommitGuard | None = None,
        generator: FakeGenerator | None = None,
        actor: str = "orchestrator",
    ) -> None:
        self.repo = repo
        self.evidence_store = evidence_store or EvidenceStore()
        self.audit = audit or AuditLog()
        self.guard = guard or CommitGuard()
        self.generator = generator or FakeGenerator()
        self.actor = actor
        self.analyzer = ImpactAnalyzer()
        self._plan_revisions: dict[str, int] = {}
        self._sessions: dict[str, ProductionSession] = {}
        self._candidates: dict[str, GeneratedCandidate] = {}
        self._quality_feedback: dict[str, list[dict[str, Any]]] = {}

    # ------------------------------------------------------------------ setup
    def create_story(
        self,
        title: str,
        premise: str = "",
        creative_intent: str = "",
        *,
        initial_state: list[dict[str, Any]] | None = None,
    ) -> Story:
        story = Story.create(title=title, premise=premise, creative_intent=creative_intent)
        self.repo.save_story(story)
        self._plan_revisions[story.story_id] = 0
        self._quality_feedback[story.story_id] = []

        for spec in initial_state or []:
            item = StateItem.create(
                key=spec["key"],
                value=spec.get("value"),
                kind=spec.get("kind", "world"),
                status=FactStatus(spec.get("status", "CANONICAL")),
                source=spec.get("source", "author"),
                depends_on=spec.get("depends_on"),
            )
            item.effective_from = 0
            item.provenance = {"origin": "initial_state"}
            self.repo.upsert_state_item(story.story_id, item)

        if initial_state:
            rev = self.repo.bump_story_revision(story.story_id, "initial canonical state")
            story.current_canonical_revision = rev

        self.audit.record(
            "CREATE_STORY",
            actor=self.actor,
            story_id=story.story_id,
            base_revision=story.current_canonical_revision,
            title=title,
        )
        return story

    def plan_chapter(self, story_id: str, number: int, title: str = "", plan: str = "") -> Chapter:
        story = self._require_story(story_id)
        chapter = Chapter.create(number=number, title=title, plan=plan)
        self.repo.save_chapter(story_id, chapter)
        self._bump_plan(story_id)
        self.audit.record(
            "PLAN_CHAPTER",
            actor=self.actor,
            story_id=story_id,
            base_revision=story.current_canonical_revision,
            chapter_id=chapter.chapter_id,
            number=number,
        )
        return chapter

    def capture_evidence(
        self,
        story_id: str,
        *,
        source_type: str,
        source_ref: str,
        claim: str,
        confidence: float = 1.0,
        chapter_ref: str | None = None,
        location: str = "",
    ) -> Evidence:
        self._require_story(story_id)
        ev = Evidence.capture(
            source_type=source_type,
            source_ref=source_ref,
            extracted_claim=claim,
            confidence=confidence,
            chapter_ref=chapter_ref,
            location=location,
        )
        self.evidence_store.add(ev)
        self.repo.save_evidence(story_id, ev)
        self.audit.record(
            "CAPTURE_EVIDENCE",
            actor=self.actor,
            story_id=story_id,
            base_revision=self._revision(story_id),
            evidence_id=ev.evidence_id,
            claim=claim,
        )
        return ev

    def propose_fact(
        self,
        story_id: str,
        claim: str,
        evidence_refs: list[str],
        *,
        claim_value: Any = None,
        target_kind: str = "world",
        target_key: str = "",
        confidence: float = 0.8,
        depends_on: list[str] | None = None,
        proposed_by: str | None = None,
    ) -> FactProposal:
        self._require_story(story_id)
        rec = FactProposalRecord.create(
            claim=claim,
            evidence_refs=evidence_refs,
            confidence=confidence,
            proposed_by=proposed_by or self.actor,
            target_kind=target_kind,
            target_key=target_key,
        )
        proposal = FactProposal(record=rec, claim_value=claim_value, depends_on=list(depends_on or []))
        self.repo.save_proposal(story_id, rec, claim_value, proposal.depends_on)
        self.audit.record(
            "PROPOSE_FACT",
            actor=self.actor,
            story_id=story_id,
            base_revision=self._revision(story_id),
            proposal_id=rec.proposal_id,
            claim=claim,
            evidence_refs=evidence_refs,
        )
        return proposal

    def promote_to_canonical(self, story_id: str, proposal: FactProposal) -> StateItem:
        story = self._require_story(story_id)
        try:
            item = promote_proposal(
                proposal,
                self.evidence_store,
                story_revision=story.current_canonical_revision,
            )
        except PromotionError as exc:
            self.audit.record(
                "PROMOTE_REJECTED",
                actor=self.actor,
                story_id=story_id,
                base_revision=story.current_canonical_revision,
                outcome="REJECT",
                proposal_id=proposal.proposal_id,
                error=str(exc),
            )
            raise

        item.revision = story.current_canonical_revision + 1
        self.repo.upsert_state_item(story_id, item)
        self.repo.save_proposal(story_id, proposal.record, proposal.claim_value, proposal.depends_on)
        new_rev = self.repo.bump_story_revision(story_id, f"promote:{item.key}")
        self.audit.record(
            "PROMOTE_CANONICAL",
            actor=self.actor,
            story_id=story_id,
            base_revision=story.current_canonical_revision,
            item_id=item.item_id,
            key=item.key,
            new_revision=new_rev,
        )
        return item

    def author_set_fact(
        self,
        story_id: str,
        key: str,
        value: Any,
        *,
        kind: str = "world",
        reason: str = "author edit",
    ) -> tuple[StateItem, ImpactReport]:
        """Author-level canonical write (bypasses proposal; still audited)."""
        story = self._require_story(story_id)
        existing = [i for i in self.repo.find_state_by_key(story_id, key) if i.status == FactStatus.CANONICAL]

        if existing:
            old = existing[0]
            old.status = FactStatus.SUPERSEDED
            old.superseded_by = f"edit:{key}:{story.current_canonical_revision + 1}"
            old.effective_to = story.current_canonical_revision
            self.repo.upsert_state_item(story_id, old)

        item = StateItem.create(key=key, value=value, kind=kind, status=FactStatus.CANONICAL, source="author")
        item.effective_from = story.current_canonical_revision + 1
        item.provenance = {"origin": "author_edit", "reason": reason, "at": datetime.now(timezone.utc).isoformat()}
        self.repo.upsert_state_item(story_id, item)
        new_rev = self.repo.bump_story_revision(story_id, reason)

        report = self.invalidate_dependents(story_id, {key}, reason=reason)
        self.audit.record(
            "AUTHOR_EDIT_STATE",
            actor=self.actor,
            story_id=story_id,
            base_revision=story.current_canonical_revision,
            key=key,
            new_revision=new_rev,
            stale_chapters=report.stale_chapter_ids,
        )
        return item, report

    def invalidate_dependents(self, story_id: str, changed_keys: set[str], reason: str = "change") -> ImpactReport:
        chapters = self.repo.list_chapters(story_id)
        items = self.repo.list_state_items(story_id)
        report = self.analyzer.analyze(chapters, items, changed_keys)
        updated = mark_stale(chapters, report.stale_chapter_ids, reason)
        for ch in updated:
            self.repo.save_chapter(story_id, ch)
        return report

    # -------------------------------------------------------------- production
    def begin_session(self, story_id: str, chapter_id: str) -> ProductionSession:
        story = self._require_story(story_id)
        chapter = self.repo.get_chapter(chapter_id)
        if chapter is None:
            raise DomainError(f"chapter not found: {chapter_id}")
        if chapter.status == ProductionUnitStatus.COMMITTED:
            raise DomainError(f"chapter already committed: {chapter_id}")

        pack = build_context_pack(
            story, chapter, self.repo.list_state_items(story_id),
            quality_feedback=self._quality_feedback.get(story_id, []),
        )
        session = ProductionSession(
            session_id=f"sess_{uuid4().hex[:12]}",
            story_id=story_id,
            base_story_revision=story.current_canonical_revision,
            plan_revision=self._plan_revisions.get(story_id, 0),
            production_unit=chapter_id,
            context_fingerprint=pack.fingerprint,
        )
        self._sessions[session.session_id] = session
        chapter.status = ProductionUnitStatus.GENERATING
        self.repo.save_chapter(story_id, chapter)
        self.guard.lock_unit(chapter_id, session.session_id)
        self.audit.record(
            "BEGIN_SESSION",
            actor=self.actor,
            story_id=story_id,
            base_revision=session.base_story_revision,
            session_id=session.session_id,
            chapter_id=chapter_id,
            context_fingerprint=pack.fingerprint,
        )
        return session

    def generate_candidate(self, session_id: str) -> GeneratedCandidate:
        session = self._sessions.get(session_id)
        if session is None:
            raise DomainError(f"session not found: {session_id}")
        story = self._require_story(session.story_id)
        chapter = self.repo.get_chapter(session.production_unit)
        if chapter is None:
            raise DomainError("chapter missing")

        pack = build_context_pack(
            story,
            chapter,
            self.repo.list_state_items(session.story_id),
            quality_feedback=self._quality_feedback.get(session.story_id, []),
        )
        # Context must still match session fingerprint for fair commit
        if pack.fingerprint != session.context_fingerprint:
            raise DomainError(
                "context fingerprint drifted since session start; begin a new session"
            )

        candidate = self.generator.generate(
            chapter,
            pack,
            session_id=session.session_id,
            base_story_revision=session.base_story_revision,
            plan_revision=session.plan_revision,
        )
        self._candidates[candidate.candidate_id] = candidate
        chapter.status = ProductionUnitStatus.CANDIDATE_READY
        self.repo.save_chapter(session.story_id, chapter)
        self.audit.record(
            "GENERATE_CANDIDATE",
            actor=self.actor,
            story_id=session.story_id,
            base_revision=session.base_story_revision,
            candidate_id=candidate.candidate_id,
            session_id=session_id,
        )
        return candidate

    def validate_and_review(self, candidate_id: str) -> GeneratedCandidate:
        candidate = self._require_candidate(candidate_id)
        self.generator.validate(candidate)
        self.generator.review(candidate)
        if candidate.quality.get("decision") != "PASS":
            candidate.status = CandidateStatus.REJECTED
        self.audit.record(
            "VALIDATE_REVIEW",
            actor=self.actor,
            story_id=self._sessions[candidate.session_id].story_id,
            base_revision=candidate.base_story_revision,
            candidate_id=candidate_id,
            decision=candidate.quality.get("decision"),
        )
        return candidate

    def commit_candidate(self, candidate_id: str) -> OrchestrationResult:
        candidate = self._require_candidate(candidate_id)
        session = self._sessions.get(candidate.session_id)
        if session is None:
            raise DomainError("session missing for candidate")
        story = self._require_story(session.story_id)

        if candidate.status not in (CandidateStatus.REVIEWED, CandidateStatus.VALIDATED, CandidateStatus.ACCEPTED):
            return OrchestrationResult(
                ok=False,
                message=f"candidate status {candidate.status} not committable",
                data={"candidate_id": candidate_id},
            )

        if candidate.quality.get("decision") not in ("PASS", None):
            self.guard.unlock_unit(session.production_unit)
            return OrchestrationResult(ok=False, message="quality blocked commit")

        chapter = self.repo.get_chapter(session.production_unit)
        if chapter is None:
            return OrchestrationResult(ok=False, message="chapter missing")

        request = CommitRequest(
            session=session,
            candidate_id=candidate_id,
            target_unit=session.production_unit,
            state_delta=[],
            event_delta=[],
        )
        result = self.guard.validate(
            request,
            current_story_revision=story.current_canonical_revision,
            current_plan_revision=self._plan_revisions.get(story.story_id, 0),
            current_context_fingerprint=None,  # fingerprint checked at generate time
        )
        audit = self.audit.record(
            "COMMIT_ATTEMPT",
            actor=self.actor,
            story_id=story.story_id,
            base_revision=session.base_story_revision,
            candidate_id=candidate_id,
            outcome="OK" if result.accepted else "REJECT",
            reason=str(result.reason) if result.reason else "",
        )
        if not result.accepted:
            self.guard.unlock_unit(session.production_unit)
            return OrchestrationResult(
                ok=False,
                message=result.message,
                data={
                    "reason": result.reason.value if result.reason else "",
                    "audit_id": audit.audit_id,
                    "current_revision": story.current_canonical_revision,
                    "session_revision": session.base_story_revision,
                },
            )

        # Atomic-ish commit body
        chapter.content = candidate.content
        chapter.status = ProductionUnitStatus.COMMITTED
        chapter.revision = story.current_canonical_revision + 1
        if not chapter.fact_keys_used:
            chapter.fact_keys_used = [
                f["key"] for f in build_context_pack(
                    story, chapter, self.repo.list_state_items(story.story_id)
                ).selected_facts
            ]
        chapter.provenance = {
            **chapter.provenance,
            "candidate_id": candidate_id,
            "session_id": session.session_id,
            "context_fingerprint": session.context_fingerprint,
            "base_story_revision": session.base_story_revision,
            "committed_at": datetime.now(timezone.utc).isoformat(),
        }
        self.repo.save_chapter(story.story_id, chapter)

        event = Event.create(
            time_ref=f"ch{chapter.number}",
            summary=f"Committed chapter {chapter.number}: {chapter.title}",
            source_chapter=chapter.chapter_id,
            provenance={"candidate_id": candidate_id},
        )
        self.repo.save_event(story.story_id, event)

        # Materialize extracted facts as canonical via evidence path
        for spec in candidate.extracted_facts:
            ev = Evidence.capture(
                source_type="generated",
                source_ref=chapter.chapter_id,
                extracted_claim=str(spec.get("claim")),
                chapter_ref=chapter.chapter_id,
                source_revision=session.base_story_revision,
            )
            self.evidence_store.add(ev)
            self.repo.save_evidence(story.story_id, ev)
            rec = FactProposalRecord.create(
                claim=str(spec.get("claim")),
                evidence_refs=[ev.evidence_id],
                confidence=0.9,
                proposed_by="fake_generator",
                target_kind=str(spec.get("target_kind", "world")),
                target_key=str(spec.get("target_key", spec.get("claim"))),
            )
            proposal = FactProposal(record=rec, claim_value=spec.get("value"))
            self.repo.save_proposal(story.story_id, rec, spec.get("value"), [])
            try:
                item = promote_proposal(
                    proposal,
                    self.evidence_store,
                    story_revision=story.current_canonical_revision,
                )
                item.provenance["chapter"] = chapter.chapter_id
                self.repo.upsert_state_item(story.story_id, item)
                self.repo.save_proposal(story.story_id, rec, spec.get("value"), [])
            except PromotionError:
                # Keep as PROPOSED; never auto-force Canon
                pass

        new_rev = self.repo.bump_story_revision(story.story_id, f"commit:{chapter.chapter_id}")
        self.guard.mark_committed(session.production_unit)
        candidate.status = CandidateStatus.COMMITTED
        self.audit.record(
            "COMMIT_OK",
            actor=self.actor,
            story_id=story.story_id,
            base_revision=session.base_story_revision,
            candidate_id=candidate_id,
            chapter_id=chapter.chapter_id,
            new_revision=new_rev,
        )

        # Capture trivial quality feedback for next run
        self._quality_feedback.setdefault(story.story_id, []).append(
            {
                "issue": "none",
                "chapter_id": chapter.chapter_id,
                "recommended_action": "continue",
            }
        )

        return OrchestrationResult(
            ok=True,
            message="committed",
            data={
                "chapter_id": chapter.chapter_id,
                "new_revision": new_rev,
                "event_id": event.event_id,
            },
        )

    def try_commit_with_stale_session(self, candidate_id: str, force_old_revision: int | None = None) -> OrchestrationResult:
        """Demonstrate Commit Guard rejection against a mutated world."""
        candidate = self._require_candidate(candidate_id)
        session = self._sessions[candidate.session_id]
        story = self._require_story(session.story_id)

        if force_old_revision is not None:
            # Simulate a world that moved on
            self.repo.bump_story_revision(story.story_id, "external mutation")

        return self.commit_candidate(candidate_id)

    # ---------------------------------------------------------------- helpers
    def get_plan_revision(self, story_id: str) -> int:
        return self._plan_revisions.get(story_id, 0)

    def list_audit(self, story_id: str) -> list[dict[str, Any]]:
        return [
            {
                "audit_id": e.audit_id,
                "action": e.action,
                "outcome": e.outcome,
                "base_revision": e.base_revision,
                "payload": e.payload,
                "created_at": e.created_at.isoformat(),
            }
            for e in self.audit.list_for_story(story_id)
        ]

    def _bump_plan(self, story_id: str) -> int:
        self._plan_revisions[story_id] = self._plan_revisions.get(story_id, 0) + 1
        return self._plan_revisions[story_id]

    def _revision(self, story_id: str) -> int:
        story = self.repo.get_story(story_id)
        return story.current_canonical_revision if story else -1

    def _require_story(self, story_id: str) -> Story:
        story = self.repo.get_story(story_id)
        if story is None:
            raise DomainError(f"story not found: {story_id}")
        return story

    def _require_candidate(self, candidate_id: str) -> GeneratedCandidate:
        candidate = self._candidates.get(candidate_id)
        if candidate is None:
            raise DomainError(f"candidate not found: {candidate_id}")
        return candidate
