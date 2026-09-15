# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unified production engine wiring Phase 0–5 building blocks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from novel_weaver.ai.base import GenerationRequest, Provider, ProviderError
from novel_weaver.ai.failover import FailoverProvider
from novel_weaver.ai.registry import get_provider
from novel_weaver.ai.retry import retry_with_backoff
from novel_weaver.domain.errors import DomainError, ReconcilePendingError
from novel_weaver.domain.models import (
    CandidateStatus,
    Chapter,
    ProductionUnitStatus,
    Story,
)
from novel_weaver.production.context import build_context_pack
from novel_weaver.production.dependency import (
    DependencyGraph,
    DepNode,
    NodeKind,
    RepairLevel,
    escalate_repair,
)
from novel_weaver.production.fake_gen import GeneratedCandidate
from novel_weaver.production.orchestrator import ProductionOrchestrator
from novel_weaver.production.planning import RollingPlanner
from novel_weaver.production.quality import Decision, decide
from novel_weaver.production.reconcile import DetectedEdit, ReconcileRecord, ReconcileResult
from novel_weaver.production.semantic_review import (
    CompositeSemanticReviewer,
    LLMSemanticReviewer,
)
from novel_weaver.runtime.checkpoint import Checkpoint, RunStep, RuntimeRun, StepStatus
from novel_weaver.runtime.hardening import CostAccountant, Diagnostics
from novel_weaver.runtime.resume import ResumeAction, decide_resume_action
from novel_weaver.storage.repositories import StoryRepository


@dataclass
class EngineRunResult:
    """Outcome of one ProductionEngine.produce_chapter attempt.

    Attributes:
        ok: Whether the chapter reached a successful commit.
        stage: Pipeline stage that produced this result.
        message: Human-readable summary of the outcome.
        data: Stage-specific payload (run_id, revision, cost, errors, ...).
    """

    ok: bool
    stage: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


class ProductionEngine:
    """High-level facade: plan → provider generate → quality → commit + runtime.

    Wires RollingPlanner, ProductionOrchestrator, providers, quality,
    reconcile, cost, and diagnostics into a single chapter-production entry
    point. Canonical writes still go through the orchestrator commit path.
    """

    def __init__(
        self,
        repo: StoryRepository,
        *,
        provider_name: str = "fake",
        provider: Provider | None = None,
        orchestrator: ProductionOrchestrator | None = None,
        constraints: dict[str, Any] | None = None,
        use_llm_review: bool | None = None,
        failover_names: list[str] | None = None,
        artifact_store: Any | None = None,
    ) -> None:
        self.repo = repo
        self.orch = orchestrator or ProductionOrchestrator(repo)
        if provider is not None:
            self.provider = provider
        elif failover_names:
            # Ordered chain: primary → fallback (e.g. openai,template).
            self.provider = FailoverProvider([get_provider(n) for n in failover_names])
            provider_name = "failover"
        elif provider_name == "failover":
            self.provider = FailoverProvider(
                [get_provider("openai"), get_provider("template")]
            )
        else:
            self.provider = get_provider(provider_name)
        self.provider_name = provider_name
        self.constraints = dict(constraints or {})
        self.planner = RollingPlanner()
        # Share planner so reconcile plan invalidation matches production planning.
        self.orch.reconcile.planner = self.planner
        self.deps = DependencyGraph()
        self.cost = CostAccountant()
        self.diagnostics = Diagnostics()
        self._runs: dict[str, RuntimeRun] = {}
        self._last_repair: dict[str, RepairLevel] = {}
        self.artifact_store = artifact_store
        self.semantic_reviewer = self._build_semantic_reviewer(use_llm_review)

    def _effective_provider_name(self) -> str:
        name = getattr(self.provider, "name", self.provider_name) or self.provider_name
        if name == "flaky":
            inner = getattr(self.provider, "inner", None)
            if inner is not None:
                return getattr(inner, "name", name) or name
        if name == "failover":
            # Prefer the provider that last served a request.
            attempts = getattr(self.provider, "last_attempts", None) or []
            for a in reversed(attempts):
                if getattr(a, "ok", False):
                    return str(getattr(a, "provider_name", name))
            chain = getattr(self.provider, "providers", None) or []
            if chain:
                return str(getattr(chain[0], "name", name))
        return str(name)

    def _build_semantic_reviewer(self, use_llm_review: bool | None):
        effective = self._effective_provider_name()
        enable = use_llm_review
        if enable is None:
            enable = effective in ("openai", "llm")
        if not enable:
            return None
        llm = LLMSemanticReviewer(
            self.provider,
            on_fallback=lambda msg: self.diagnostics.emit(
                "WARN", "SEMANTIC_REVIEW_FALLBACK", msg
            ),
        )
        return CompositeSemanticReviewer(llm)

    def create_story(self, title: str, **kwargs: Any) -> Story:
        """Create a story via the orchestrator and seed dependency nodes.

        Args:
            title: Story display title.
            **kwargs: Forwarded to ProductionOrchestrator.create_story
                (premise, creative_intent, initial_state, ...).

        Returns:
            The newly created Story.
        """
        story = self.orch.create_story(title, **kwargs)
        self.deps.add_node(DepNode(story.story_id, NodeKind.FACT, title))
        for item in self.repo.list_state_items(story.story_id):
            self.deps.add_node(DepNode(item.item_id, NodeKind.FACT, item.key))
            self.deps.add_edge(story.story_id, item.item_id)
        return story

    def plan_with_rolling(
        self,
        story_id: str,
        number: int | None = None,
        title: str = "",
        summary: str = "",
        *,
        depends_on_fact_keys: list[str] | None = None,
    ) -> tuple[Chapter, Any]:
        """Plan the next chapter slot and register plan/chapter dependency edges.

        Args:
            story_id: Target story identity.
            number: Explicit chapter number; None assigns the next rolling slot.
            title: Chapter title (auto-filled when empty).
            summary: Short plan summary for the chapter.
            depends_on_fact_keys: Fact keys this chapter will rely on.

        Returns:
            Tuple of (Chapter, PlanNode) created for the production unit.
        """
        plan_node = self.planner.plan_next_chapter(
            story_id,
            title=title or f"Chapter {number or self.planner.next_chapter_slot(story_id)}",
            summary=summary,
            depends_on_fact_keys=depends_on_fact_keys,
        )
        if number is None:
            number = int(plan_node.metadata["number"])
        chapter = self.orch.plan_chapter(story_id, number, plan_node.title, plan_node.summary)
        if depends_on_fact_keys:
            chapter.fact_keys_used = list(depends_on_fact_keys)
            self.repo.save_chapter(story_id, chapter)
        self.deps.add_node(DepNode(chapter.chapter_id, NodeKind.CHAPTER, chapter.title))
        self.deps.add_node(DepNode(plan_node.plan_id, NodeKind.PLAN, plan_node.title))
        self.deps.add_edge(plan_node.plan_id, chapter.chapter_id)
        for key in depends_on_fact_keys or []:
            key_id = f"key:{key}"
            self.deps.add_node(DepNode(key_id, NodeKind.FACT, key))
            self.deps.add_edge(key_id, chapter.chapter_id)
        return chapter, plan_node

    def produce_chapter(
        self,
        story_id: str,
        chapter_id: str,
        *,
        run_id: str | None = None,
        max_provider_retries: int = 2,
    ) -> EngineRunResult:
        """Produce one chapter: session → generate → quality → commit.

        Blocks when a pending reconcile exists for the story. Records runtime
        checkpoints, cost, and diagnostics along the way.

        Args:
            story_id: Story that owns the chapter.
            chapter_id: Production unit to generate and commit.
            run_id: Optional stable run identity; generated when omitted.
            max_provider_retries: Extra provider attempts after the first try.

        Returns:
            EngineRunResult describing success or the failing stage.
        """
        run_id = run_id or f"run_{uuid4().hex[:12]}"
        story = self.repo.get_story(story_id)
        if story is None:
            raise DomainError(f"story not found: {story_id}")
        chapter = self.repo.get_chapter(chapter_id)
        if chapter is None:
            raise DomainError(f"chapter not found: {chapter_id}")

        if self.orch.reconcile.is_production_blocked(story_id):
            pending = self.orch.reconcile.pending_reconciles(story_id)
            msg = (
                f"production blocked: pending reconcile "
                f"{', '.join(r.reconcile_id for r in pending)}"
            )
            self.diagnostics.emit("WARN", "RECONCILE_PENDING", msg, chapter_id=chapter_id)
            return EngineRunResult(
                False,
                "reconcile_gate",
                msg,
                {
                    "chapter_id": chapter_id,
                    "pending_reconciles": [r.reconcile_id for r in pending],
                },
            )

        run = RuntimeRun(
            run_id=run_id,
            story_id=story_id,
            production_unit=chapter_id,
            base_story_revision=story.current_canonical_revision,
        )
        for name in ("begin_session", "generate", "quality", "commit"):
            run.upsert_step(RunStep(name=name, status=StepStatus.PENDING))
        self._runs[run_id] = run

        def mark(step_name: str, status: StepStatus, **payload: Any) -> RunStep:
            step = run.step(step_name)
            assert step is not None
            step.status = status
            step.payload.update(payload)
            if status is StepStatus.SUCCEEDED:
                step.mark_succeeded(payload)
            elif status is StepStatus.FAILED:
                step.mark_failed(str(payload.get("error", "")), retryable=bool(payload.get("retryable", False)))
            else:
                step.status = status
            run.upsert_step(step)
            try:
                self.repo.save_checkpoint(Checkpoint.for_step(run, step))
            except Exception as exc:
                self.diagnostics.emit("WARN", "CKPT_SAVE_FAIL", str(exc), step=step_name)
            return step

        mark("begin_session", StepStatus.RUNNING)
        try:
            session = self.orch.begin_session(story_id, chapter_id)
            mark("begin_session", StepStatus.SUCCEEDED, session_id=session.session_id)
        except Exception as exc:
            mark("begin_session", StepStatus.FAILED, error=str(exc))
            self.diagnostics.emit("ERROR", "BEGIN_SESSION_FAIL", str(exc), chapter_id=chapter_id)
            return EngineRunResult(False, "begin_session", str(exc), {"run_id": run_id})

        mark("generate", StepStatus.RUNNING, session_id=session.session_id)
        pack = build_context_pack(
            story,
            chapter,
            self.repo.list_state_items(story_id),
            quality_feedback=self.orch._quality_feedback.get(story_id, []),
        )
        request = GenerationRequest(
            task="chapter_generation",
            prompt=pack.generation_task,
            context=pack.materialize(),
            model=self.provider_name,
            story_id=story_id,
            chapter_id=chapter_id,
        )

        @retry_with_backoff(max_attempts=max_provider_retries + 1, base_delay=1.0, max_delay=20.0)
        def _generate():
            return self.provider.generate(request)

        try:
            result = _generate()
        except ProviderError as exc:
            mark("generate", StepStatus.FAILED, error=str(exc), retryable=exc.retryable)
            self.diagnostics.emit("ERROR", "GENERATE_FAIL", str(exc), chapter_id=chapter_id)
            self.orch.guard.unlock_unit(chapter_id)
            return EngineRunResult(False, "generate", str(exc), {"run_id": run_id})

        self.cost.record(
            story_id=story_id,
            run_id=run_id,
            provider=result.provider,
            model=result.model,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            latency_ms=result.latency_ms,
        )

        candidate = GeneratedCandidate(
            candidate_id=f"cand_{uuid4().hex[:12]}",
            chapter_id=chapter_id,
            content=result.text,
            session_id=session.session_id,
            base_story_revision=session.base_story_revision,
            plan_revision=session.plan_revision,
            context_fingerprint=session.context_fingerprint,
            extracted_facts=[
                {
                    "claim": f"chapter_{chapter.number}_produced",
                    "target_kind": "world",
                    "target_key": f"chapter.{chapter.number}.produced",
                    "value": True,
                }
            ],
        )
        self.orch._candidates[candidate.candidate_id] = candidate
        self.orch.generator.validate(candidate)
        mark(
            "generate",
            StepStatus.SUCCEEDED,
            candidate_id=candidate.candidate_id,
            tokens=result.usage.total_tokens,
        )

        mark("quality", StepStatus.RUNNING, candidate_id=candidate.candidate_id)
        review_context = pack.materialize()
        review_context["story_id"] = story_id
        qd = decide(
            candidate,
            self.constraints,
            reviewer=self.semantic_reviewer,
            review_context=review_context,
        )
        # Account LLM review tokens if the reviewer used the live provider.
        llm_reviewer = getattr(self.semantic_reviewer, "llm", None)
        if llm_reviewer is not None and getattr(llm_reviewer, "last_used_llm", False):
            # Cheap estimate: review request + JSON reply.
            from novel_weaver.ai.base import estimate_tokens

            self.cost.record(
                story_id=story_id,
                run_id=run_id,
                provider=self._effective_provider_name(),
                model=getattr(self.provider, "model", self.provider_name),
                prompt_tokens=estimate_tokens(json.dumps(review_context, default=str))
                + estimate_tokens(candidate.content or ""),
                completion_tokens=estimate_tokens(getattr(llm_reviewer, "last_raw", "") or ""),
                latency_ms=0.0,
            )
        candidate.validation["passed"] = qd.decision is not Decision.BLOCK
        candidate.quality = {
            "decision": qd.decision.value,
            "score": qd.score,
            "issues": [i.evidence for i in qd.issues],
            "manifest_id": qd.manifest.manifest_id,
            "ordering": qd.manifest.ordering,
            "semantic_llm": bool(
                llm_reviewer is not None and getattr(llm_reviewer, "last_used_llm", False)
            ),
        }
        # Quality-driven planning adjustments (§3.7).
        try:
            self.planner.after_quality_feedback(
                story_id,
                decision=qd.decision.value,
                issue_actions=[i.suggested_action for i in qd.issues],
                constraint_change=qd.feedback_for_next_run.constraint_change,
            )
        except Exception:
            pass
        if self.artifact_store is not None:
            try:
                self.artifact_store.write_candidate(
                    story_id,
                    candidate_id=candidate.candidate_id,
                    chapter_id=chapter_id,
                    content=candidate.content,
                    quality=candidate.quality,
                    context_fingerprint=candidate.context_fingerprint,
                )
                self.artifact_store.write_review(
                    story_id,
                    review_id=qd.manifest.manifest_id,
                    decision=qd.decision.value,
                    issues=[
                        {
                            "severity": i.severity.value,
                            "evidence": i.evidence,
                            "suggested_action": i.suggested_action,
                        }
                        for i in qd.issues
                    ],
                    manifest_id=qd.manifest.manifest_id,
                )
            except Exception as exc:
                self.diagnostics.emit("WARN", "ARTIFACT_WRITE_FAIL", str(exc))
        if qd.decision is Decision.BLOCK:
            candidate.status = CandidateStatus.REJECTED
            mark("quality", StepStatus.FAILED, decision="BLOCK")
            self.orch.guard.unlock_unit(chapter_id)
            feedback = qd.feedback_for_next_run
            self.orch._quality_feedback.setdefault(story_id, []).append(
                {
                    "issue": feedback.issue,
                    "recommended_action": feedback.recommended_action,
                    "next_run_hints": feedback.next_run_hints,
                    "constraint_change": feedback.constraint_change,
                }
            )
            level = escalate_repair(
                self._last_repair.get(story_id, RepairLevel.NONE),
                issue_count=len(qd.issues),
                blocker_count=sum(1 for i in qd.issues if i.severity.value == "BLOCKER"),
            )
            self._last_repair[story_id] = level
            self.diagnostics.emit(
                "WARN",
                "QUALITY_BLOCK",
                feedback.recommended_action,
                chapter_id=chapter_id,
                repair_level=level.value,
            )
            return EngineRunResult(
                False,
                "quality",
                feedback.recommended_action,
                {
                    "run_id": run_id,
                    "candidate_id": candidate.candidate_id,
                    "manifest_id": qd.manifest.manifest_id,
                    "repair_level": level.value,
                    "hints": feedback.next_run_hints,
                },
            )

        candidate.status = (
            CandidateStatus.ACCEPTED if qd.decision is Decision.PASS else CandidateStatus.REVIEWED
        )
        mark("quality", StepStatus.SUCCEEDED, decision=qd.decision.value)

        mark("commit", StepStatus.RUNNING, candidate_id=candidate.candidate_id)
        commit = self.orch.commit_candidate(candidate.candidate_id)
        if not commit.ok:
            mark("commit", StepStatus.FAILED, error=commit.message)
            self.diagnostics.emit("ERROR", "COMMIT_FAIL", commit.message, chapter_id=chapter_id)
            return EngineRunResult(
                False, "commit", commit.message, {**commit.data, "run_id": run_id}
            )

        mark("commit", StepStatus.SUCCEEDED, **commit.data)
        self.planner.after_commit(
            story_id,
            committed_plan_id=None,
            changed_fact_keys={f"chapter.{chapter.number}.produced"},
        )
        self._last_repair[story_id] = RepairLevel.NONE

        return EngineRunResult(
            True,
            "commit",
            "chapter committed",
            {
                "run_id": run_id,
                "candidate_id": candidate.candidate_id,
                "chapter_id": chapter_id,
                "new_revision": commit.data.get("new_revision"),
                "cost": self.cost.total_for_story(story_id),
            },
        )

    def resume_decision(self, run_id: str, current_story_revision: int | None = None) -> ResumeAction:
        """Decide how to continue an interrupted engine run.

        Args:
            run_id: Runtime run identity previously produced by this engine.
            current_story_revision: Live Canonical revision, if known.

        Returns:
            ResumeAction from the runtime resume decision matrix.

        Raises:
            DomainError: If the run is unknown to this engine instance.
        """
        run = self._runs.get(run_id)
        if run is None:
            raise DomainError(f"run not found: {run_id}")
        return decide_resume_action(run, current_story_revision=current_story_revision)

    def detect_external_edits(self, story_id: str) -> list[DetectedEdit]:
        """Detect committed chapters whose live content drifted from the fingerprint.

        Args:
            story_id: Story to scan.

        Returns:
            Detected edits (and first-time baseline fingerprints).
        """
        return self.orch.detect_external_edits(story_id)

    def apply_author_chapter_edit(
        self, story_id: str, chapter_id: str, new_content: str, *, reason: str = "author external edit"
    ) -> ReconcileRecord:
        """Apply an author rewrite of official chapter text and open reconcile.

        Args:
            story_id: Story that owns the chapter.
            chapter_id: Committed (or planned) chapter being edited.
            new_content: Replacement chapter body.
            reason: Audit reason for the external edit.

        Returns:
            The open (or refreshed) ReconcileRecord.
        """
        record = self.orch.apply_author_chapter_edit(
            story_id, chapter_id, new_content, reason=reason
        )
        self.diagnostics.emit(
            "WARN",
            "EXTERNAL_EDIT_OPENED",
            f"reconcile {record.reconcile_id} opened for {chapter_id}",
            story_id=story_id,
        )
        return record

    def complete_reconcile(
        self,
        story_id: str,
        reconcile_id: str,
        *,
        fact_deltas: list[dict[str, Any]] | None = None,
        event_summary: str | None = None,
    ) -> ReconcileResult:
        """Complete reconcile and refresh dependency edges for changed facts.

        Args:
            story_id: Story that owns the reconcile ticket.
            reconcile_id: Pending reconcile identity.
            fact_deltas: Fact key/value extractions from the edited chapter.
            event_summary: Optional rebuilt event summary text.

        Returns:
            ReconcileResult with stale/valid chapters and plan invalidations.
        """
        result = self.orch.complete_reconcile(
            story_id, reconcile_id, fact_deltas=fact_deltas, event_summary=event_summary
        )
        if result.ok:
            for key in result.fact_keys_changed:
                key_id = f"key:{key}"
                self.deps.add_node(DepNode(key_id, NodeKind.FACT, key))
            for ch_id in result.stale_chapter_ids:
                self.deps.add_node(DepNode(ch_id, NodeKind.CHAPTER, ch_id))
                for key in result.fact_keys_changed:
                    self.deps.add_edge(f"key:{key}", ch_id)
        return result

    def is_production_blocked(self, story_id: str) -> bool:
        """Whether pending reconciles currently block forward production.

        Args:
            story_id: Story to inspect.

        Returns:
            True when at least one PENDING reconcile exists.
        """
        return self.orch.reconcile.is_production_blocked(story_id)

    def impact_after_author_edit(
        self, story_id: str, key: str, value: Any, *, kind: str = "world"
    ) -> dict[str, Any]:
        """Author-edit a fact and compute graph + report invalidation scope.

        Args:
            story_id: Story being edited.
            key: Canonical fact key to set.
            value: New fact value.
            kind: Fact kind (world/character/...).

        Returns:
            Dict with item_id, stale_chapters, still_valid, and graph_scope.
        """
        item, report = self.orch.author_set_fact(story_id, key, value, kind=kind)
        node_id = f"key:{key}"
        self.deps.add_node(DepNode(node_id, NodeKind.FACT, key))
        graph_scope = self.deps.impact_scope([node_id])
        chapter_ids = {n.node_id for n in self.deps.nodes_of_kind(NodeKind.CHAPTER, graph_scope)}
        chapter_ids |= set(report.stale_chapter_ids)
        for ch in self.repo.list_chapters(story_id):
            if ch.chapter_id in chapter_ids and ch.status is not ProductionUnitStatus.COMMITTED:
                ch.status = ProductionUnitStatus.STALE
                self.repo.save_chapter(story_id, ch)
        self.planner.after_commit(story_id, committed_plan_id=None, changed_fact_keys={key})
        return {
            "item_id": item.item_id,
            "stale_chapters": sorted(chapter_ids),
            "still_valid": report.still_valid_chapter_ids,
            "graph_scope": sorted(graph_scope),
        }

    def diagnostics_summary(self) -> dict[str, Any]:
        """Summarize runtime diagnostic events and error messages.

        Returns:
            Dict with event counts by level and error message list.
        """
        return {
            "events": self.diagnostics.summary(),
            "errors": [e.message for e in self.diagnostics.errors()],
        }
