# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""§25.3 long-run benchmark: continuous production + repair + recovery metrics."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from novel_weaver.ai.base import GenerationRequest, GenerationResult, Provider, ProviderError
from novel_weaver.domain.errors import DomainError
from novel_weaver.domain.models import FactStatus, ProductionUnitStatus
from novel_weaver.production.engine import ProductionEngine
from novel_weaver.production.fingerprint import content_fingerprint
from novel_weaver.storage.db import Database
from novel_weaver.storage.repositories import StoryRepository


class FlakyProvider(Provider):
    """Fails a fixed number of times on designated chapter markers, then delegates."""

    name = "flaky"

    def __init__(self, inner: Provider, *, fail_plan_numbers: set[int]) -> None:
        self.inner = inner
        self.fail_plan_numbers = set(fail_plan_numbers)
        self._remaining = {n: 1 for n in fail_plan_numbers}

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Fail once on designated chapter markers, then delegate to the inner provider.

        Args:
            request: Generation request whose plan may contain fail markers.

        Returns:
            Inner provider GenerationResult when no failure is scheduled.

        Raises:
            ProviderError: Simulated transient failure for a marked chapter.
        """
        marker = request.context.get("current_plan") or ""
        for num in list(self._remaining):
            if f"#{num}#" in marker and self._remaining[num] > 0:
                self._remaining[num] -= 1
                raise ProviderError(
                    f"simulated transient failure for chapter {num}", retryable=True
                )
        return self.inner.generate(request)


@dataclass
class ChapterOutcome:
    """Result of producing one chapter in the long-run benchmark.

    Attributes:
        number: Chapter number.
        chapter_id: Production unit identity.
        ok: Whether the chapter committed successfully.
        stage: Pipeline stage of the final attempt.
        message: Human-readable outcome message.
        run_id: Runtime run identity of the successful/last attempt.
        new_revision: Canonical revision after commit, if any.
        latency_ms: Wall time of the final attempt.
        attempt: 1-based attempt number that produced this outcome.
    """

    number: int
    chapter_id: str
    ok: bool
    stage: str
    message: str
    run_id: str = ""
    new_revision: int | None = None
    latency_ms: float = 0.0
    attempt: int = 1


@dataclass
class RepairOutcome:
    """Result of one scheduled author-edit + reconcile repair drill.

    Attributes:
        at_chapter: Chapter number when the drill ran.
        changed_key: Fact key changed by the drill.
        reconcile_id: Reconcile ticket identity.
        stale_chapter_ids: Chapters invalidated by reconcile.
        still_valid_chapter_ids: Chapters left valid.
        invalidated_plan_ids: Plan nodes marked stale.
        total_chapters: Chapter count at drill time.
        true_dependents: Ground-truth dependent chapter ids.
        regenerations: Planned units re-opened after reconcile.
        production_blocked_before_complete: Blocked state while ticket open.
        production_blocked_after_complete: Blocked state after completion.
        invalidation_precision: Precision vs true dependents.
        invalidation_recall: Recall vs true dependents.
    """

    at_chapter: int
    changed_key: str
    reconcile_id: str
    stale_chapter_ids: list[str]
    still_valid_chapter_ids: list[str]
    invalidated_plan_ids: list[str]
    total_chapters: int
    true_dependents: list[str]
    regenerations: int = 0
    production_blocked_before_complete: bool = True
    production_blocked_after_complete: bool = True
    invalidation_precision: float = 1.0
    invalidation_recall: float = 1.0


@dataclass
class RecoveryOutcome:
    """Result of one scheduled provider-failure recovery drill.

    Attributes:
        chapter_number: Chapter number of the drill.
        failed_runs: Failed attempts before success (attempt - 1).
        recovered: Whether the chapter eventually committed.
        resume_action: ResumeAction value from the engine, if known.
        double_commit: True if any chapter id appears twice in successes.
    """

    chapter_number: int
    failed_runs: int
    recovered: bool
    resume_action: str = ""
    double_commit: bool = False


@dataclass
class ContinuityAudit:
    """End-of-benchmark Canonical continuity audit.

    Attributes:
        committed_chapters: Count of committed chapters.
        missing_fingerprint: Chapters with missing/mismatched fingerprints.
        double_status_chapters: Duplicate committed chapter numbers.
        unresolved_canonical_conflicts: Same-key Canonical value conflicts.
        superseded_still_treated_as_canonical: Keys without live Canonical successor.
        orphan_pending_reconciles: Reconcile tickets still PENDING.
        sequential_numbers: Whether committed numbers are 1..N.
        final_revision: Final Canonical story revision.
        canonical_fact_count: Count of CANONICAL facts.
        event_count: Count of events.
        violations: Human-readable violation summary lines.
    """

    committed_chapters: int
    missing_fingerprint: list[str]
    double_status_chapters: list[str]
    unresolved_canonical_conflicts: list[str]
    superseded_still_treated_as_canonical: list[str]
    orphan_pending_reconciles: list[str]
    sequential_numbers: bool
    final_revision: int
    canonical_fact_count: int
    event_count: int
    violations: list[str]

    @property
    def violation_count(self) -> int:
        """Number of continuity violations recorded.

        Returns:
            Length of the violations list.
        """
        return len(self.violations)


@dataclass
class BenchmarkReport:
    """Aggregated long-run benchmark metrics and drill outcomes.

    Attributes:
        target_chapters: Requested chapter count.
        provider_name: Provider used for generation.
        produced_chapters: Successfully committed chapters.
        failed_attempts: Failed produce attempts.
        total_attempts: Total produce attempts.
        regenerations: Extra attempts that later succeeded.
        repairs: Scheduled repair drill outcomes.
        recoveries: Scheduled recovery drill outcomes.
        continuity: End-of-run continuity audit.
        token_cost: Aggregated token/cost totals.
        diagnostics: Engine diagnostics summary.
        quality_feedback_events: Count of quality feedback entries.
        quality_feedback_present_in_later_context: Feedback seen later.
        wall_clock_ms: Total benchmark wall time.
        chapter_outcomes: Per-chapter outcome list.
        notes: Free-form operator notes.
    """

    target_chapters: int
    provider_name: str
    produced_chapters: int
    failed_attempts: int
    total_attempts: int
    regenerations: int
    repairs: list[RepairOutcome] = field(default_factory=list)
    recoveries: list[RecoveryOutcome] = field(default_factory=list)
    continuity: ContinuityAudit | None = None
    token_cost: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    quality_feedback_events: int = 0
    quality_feedback_present_in_later_context: int = 0
    wall_clock_ms: float = 0.0
    chapter_outcomes: list[ChapterOutcome] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def execution_failure_rate(self) -> float:
        """Failed attempts over total attempts.

        Returns:
            Failure rate in [0, 1] (0 when no attempts).
        """
        if self.total_attempts == 0:
            return 0.0
        return self.failed_attempts / self.total_attempts

    @property
    def recovery_success_rate(self) -> float:
        """Share of recovery drills that eventually committed.

        Returns:
            Success rate in [0, 1] (1 when no drills).
        """
        if not self.recoveries:
            return 1.0
        return sum(1 for r in self.recoveries if r.recovered) / len(self.recoveries)

    @property
    def mean_invalidation_precision(self) -> float:
        """Mean invalidation precision across repair drills.

        Returns:
            Mean precision in [0, 1] (1 when no drills).
        """
        if not self.repairs:
            return 1.0
        return sum(r.invalidation_precision for r in self.repairs) / len(self.repairs)

    @property
    def mean_invalidation_recall(self) -> float:
        """Mean invalidation recall across repair drills.

        Returns:
            Mean recall in [0, 1] (1 when no drills).
        """
        if not self.repairs:
            return 1.0
        return sum(r.invalidation_recall for r in self.repairs) / len(self.repairs)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full report for JSON output.

        Returns:
            Nested dict of metrics, drills, continuity, and cost.
        """
        return {
            "target_chapters": self.target_chapters,
            "provider_name": self.provider_name,
            "produced_chapters": self.produced_chapters,
            "failed_attempts": self.failed_attempts,
            "total_attempts": self.total_attempts,
            "execution_failure_rate": round(self.execution_failure_rate, 4),
            "regenerations": self.regenerations,
            "repairs": [asdict(r) for r in self.repairs],
            "recoveries": [asdict(r) for r in self.recoveries],
            "continuity_violations": (
                self.continuity.violation_count if self.continuity else None
            ),
            "continuity": asdict(self.continuity) if self.continuity else None,
            "contradiction_count": (
                len(self.continuity.unresolved_canonical_conflicts) if self.continuity else 0
            ),
            "recovery_success_rate": round(self.recovery_success_rate, 4),
            "mean_invalidation_precision": round(self.mean_invalidation_precision, 4),
            "mean_invalidation_recall": round(self.mean_invalidation_recall, 4),
            "token_cost": self.token_cost,
            "diagnostics": self.diagnostics,
            "quality_feedback_events": self.quality_feedback_events,
            "quality_feedback_present_in_later_context": (
                self.quality_feedback_present_in_later_context
            ),
            "wall_clock_ms": round(self.wall_clock_ms, 2),
            "notes": self.notes,
        }

    def summary_lines(self) -> list[str]:
        """Render a short multi-line human summary of key metrics.

        Returns:
            List of summary strings suitable for CLI printing.
        """
        c = self.continuity
        lines = [
            f"target_chapters={self.target_chapters}",
            f"produced_chapters={self.produced_chapters}",
            f"execution_failure_rate={self.execution_failure_rate:.3f} "
            f"({self.failed_attempts}/{self.total_attempts})",
            f"regenerations={self.regenerations}",
            f"repairs={len(self.repairs)} mean_precision={self.mean_invalidation_precision:.3f} "
            f"mean_recall={self.mean_invalidation_recall:.3f}",
            f"recovery_success_rate={self.recovery_success_rate:.3f}",
            f"continuity_violations={c.violation_count if c else 'n/a'}",
            f"contradictions={len(c.unresolved_canonical_conflicts) if c else 'n/a'}",
            f"tokens={self.token_cost.get('prompt_tokens', 0)}+"
            f"{self.token_cost.get('completion_tokens', 0)} "
            f"cost_usd={self.token_cost.get('cost_usd', 0)}",
            f"wall_clock_ms={self.wall_clock_ms:.1f}",
        ]
        if c and c.violations:
            lines.append("violations: " + "; ".join(c.violations[:10]))
        return lines


class LongRunBenchmark:
    """Produce N chapters with scheduled repair/recovery drills and audit §25.3 metrics."""

    # Fact key rotation so impact analysis stays selective.
    _FACT_CYCLE = (
        "character.hero.name",
        "character.hero.injury",
        "world.port",
        "world.faction",
        "thread.missing_cargo",
    )

    def __init__(
        self,
        *,
        chapters: int = 30,
        provider_name: str = "template",
        workspace: Path | str | None = None,
        repair_at: tuple[int, ...] | None = None,
        recover_at: tuple[int, ...] | None = None,
        chapter_delay_s: float = 0.0,
        max_provider_retries: int = 0,
        provider: Provider | None = None,
    ) -> None:
        self.chapters = chapters
        self.provider_name = provider_name
        self.workspace = Path(workspace) if workspace else None
        default_repair, default_recover = self._default_drills(chapters)
        self.repair_at = set(repair_at if repair_at is not None else default_repair)
        self.recover_at = set(recover_at if recover_at is not None else default_recover)
        self.chapter_delay_s = chapter_delay_s
        # Live gateways need provider-side retries; offline fakes don't.
        if max_provider_retries or provider_name in ("openai", "llm"):
            self.max_provider_retries = max_provider_retries or 3
            if chapter_delay_s == 0.0 and provider_name in ("openai", "llm"):
                self.chapter_delay_s = 2.0
        else:
            self.max_provider_retries = 0
        self._provider = provider

    @staticmethod
    def _default_drills(chapters: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
        """Scale repair/recovery drills with run length (keep them in-range)."""
        if chapters < 8:
            return (), ()
        if chapters < 20:
            return (max(4, chapters // 2),), (max(3, chapters // 3),)
        # ~every third of the book, plus an early drill once a few chapters exist.
        repairs = tuple(
            sorted({max(5, chapters // 5), max(8, chapters // 2), max(10, (chapters * 4) // 5)})
        )
        recoveries = tuple(
            sorted({max(6, chapters // 3), max(12, (chapters * 2) // 3)})
        )
        # Drop any drill that would land after the final chapter.
        repairs = tuple(n for n in repairs if n < chapters)
        recoveries = tuple(n for n in recoveries if n < chapters)
        return repairs, recoveries

    def run(self) -> BenchmarkReport:
        """Produce N chapters with scheduled repair/recovery drills and audit metrics.

        Returns:
            BenchmarkReport with chapter outcomes, drills, continuity, and cost.
        """
        started = time.perf_counter()
        db = self._open_db()
        try:
            return self._run_with_db(db, started)
        finally:
            db.close()

    def _open_db(self) -> Database:
        if self.workspace is None:
            return Database(":memory:")
        self.workspace.mkdir(parents=True, exist_ok=True)
        return Database(self.workspace / "bench.sqlite3")

    def _run_with_db(self, db: Database, started: float) -> BenchmarkReport:
        repo = StoryRepository(db)
        inner = self._provider or self._make_inner_provider()
        flaky = FlakyProvider(inner, fail_plan_numbers=set(self.recover_at))
        eng = ProductionEngine(repo, provider=flaky, provider_name=self.provider_name)
        # Expose real model name when wrapping OpenAI-compatible providers.
        if hasattr(inner, "model"):
            eng.provider_name = self.provider_name
            try:
                eng.provider = flaky
            except Exception:
                pass

        report = BenchmarkReport(
            target_chapters=self.chapters,
            provider_name=self.provider_name,
            produced_chapters=0,
            failed_attempts=0,
            total_attempts=0,
            regenerations=0,
        )

        story = eng.create_story(
            "长程基准小说",
            premise="港口侦探连续追查失踪货轮，强连续性。",
            creative_intent="连续性优先；禁止无来源改写关键事实",
            initial_state=[
                {
                    "key": "character.hero.name",
                    "value": "顾言",
                    "kind": "character",
                    "status": "CANONICAL",
                },
                {
                    "key": "world.port",
                    "value": "雾港",
                    "kind": "world",
                    "status": "CANONICAL",
                },
                {
                    "key": "thread.missing_cargo",
                    "value": "OPEN",
                    "kind": "thread",
                    "status": "PENDING",
                },
            ],
        )
        story_id = story.story_id
        produced_ids: dict[int, str] = {}
        chapter_ids_by_key: dict[str, list[str]] = {}
        # Track which committed chapters claim each fact key.
        key_usage: dict[str, set[str]] = {}

        # Pre-plan + rolling produce loop.
        for n in range(1, self.chapters + 1):
            fact_keys = self._facts_for_chapter(n)
            for k in fact_keys:
                key_usage.setdefault(k, set())

            # After repair, previously STALE planned chapters may need re-plan.
            existing_planned = [
                c
                for c in repo.list_chapters(story_id)
                if c.number == n and c.status is not ProductionUnitStatus.COMMITTED
            ]
            if existing_planned:
                chapter = existing_planned[0]
                if chapter.status is ProductionUnitStatus.STALE:
                    chapter.status = ProductionUnitStatus.PLANNED
                    repo.save_chapter(story_id, chapter)
            else:
                chapter, _ = eng.plan_with_rolling(
                    story_id,
                    number=n,
                    title=f"第{n}章",
                    summary=f"#{n}# 推进主线：{n}",
                    depends_on_fact_keys=fact_keys,
                )

            if n in self.repair_at and report.produced_chapters >= 2:
                self._run_repair(
                    eng, repo, report, story_id, chapter_id_hint=None, at_chapter=n
                )
                # After repair, this slot may have been STALE→PLANNED; refresh handle.
                chapter = repo.get_chapter(chapter.chapter_id) or chapter

            outcome = self._produce_with_retries(
                eng,
                report,
                story_id,
                chapter,
                max_attempts=3,
                max_provider_retries=self.max_provider_retries,
            )
            report.chapter_outcomes.append(outcome)
            if not outcome.ok:
                report.notes.append(
                    f"chapter {n} failed at {outcome.stage}: {outcome.message}"
                )
                continue

            report.produced_chapters += 1
            produced_ids[n] = outcome.chapter_id
            stored = repo.get_chapter(outcome.chapter_id)
            if stored is not None:
                for key in stored.fact_keys_used or fact_keys:
                    key_usage[key].add(outcome.chapter_id)
                    chapter_ids_by_key.setdefault(key, []).append(outcome.chapter_id)

            if n in self.recover_at:
                self._record_recovery(eng, report, outcome)

            if self.chapter_delay_s > 0 and n < self.chapters:
                time.sleep(self.chapter_delay_s)

        # Final audit
        report.continuity = self._audit_continuity(repo, story_id, produced_ids)
        report.token_cost = eng.cost.total_for_story(story_id)
        report.diagnostics = eng.diagnostics_summary()
        report.wall_clock_ms = (time.perf_counter() - started) * 1000.0
        report.notes.append(
            f"key_usage_sizes={ {k: len(v) for k, v in key_usage.items()} }"
        )
        return report

    def _facts_for_chapter(self, n: int) -> list[str]:
        # 2 rotating keys per chapter → selective dependency for invalidation precision.
        a = self._FACT_CYCLE[(n - 1) % len(self._FACT_CYCLE)]
        b = self._FACT_CYCLE[n % len(self._FACT_CYCLE)]
        keys = [a, b]
        # Always keep hero name early for grounding.
        if n <= 3:
            keys.append("character.hero.name")
        return list(dict.fromkeys(keys))

    def _produce_with_retries(
        self,
        eng: ProductionEngine,
        report: BenchmarkReport,
        story_id: str,
        chapter: Any,
        *,
        max_attempts: int = 3,
        max_provider_retries: int = 0,
    ) -> ChapterOutcome:
        last: ChapterOutcome | None = None
        for attempt in range(1, max_attempts + 1):
            report.total_attempts += 1
            t0 = time.perf_counter()
            result = eng.produce_chapter(
                story_id,
                chapter.chapter_id,
                max_provider_retries=max_provider_retries,
            )
            elapsed = (time.perf_counter() - t0) * 1000.0
            if result.ok:
                if attempt > 1:
                    report.regenerations += 1
                return ChapterOutcome(
                    number=chapter.number,
                    chapter_id=chapter.chapter_id,
                    ok=True,
                    stage=result.stage,
                    message=result.message,
                    run_id=str(result.data.get("run_id", "")),
                    new_revision=result.data.get("new_revision"),
                    latency_ms=elapsed,
                    attempt=attempt,
                )
            report.failed_attempts += 1
            last = ChapterOutcome(
                number=chapter.number,
                chapter_id=chapter.chapter_id,
                ok=False,
                stage=result.stage,
                message=result.message,
                run_id=str(result.data.get("run_id", "")),
                latency_ms=elapsed,
                attempt=attempt,
            )
            try:
                eng.orch.guard.unlock_unit(chapter.chapter_id)
            except Exception:
                pass
            if attempt < max_attempts:
                # Outer retry pause (rate limits / flaky gateways).
                time.sleep(min(8.0, 1.5 * attempt))
        assert last is not None
        return last

    def _run_repair(
        self,
        eng: ProductionEngine,
        repo: StoryRepository,
        report: BenchmarkReport,
        story_id: str,
        *,
        chapter_id_hint: str | None,
        at_chapter: int,
    ) -> RepairOutcome:
        chapters = repo.list_chapters(story_id)
        committed = [c for c in chapters if c.status is ProductionUnitStatus.COMMITTED]
        if not committed:
            raise DomainError("repair drill requires at least one committed chapter")

        # Pick an early committed chapter and a fact key that some chapters actually use.
        target = min(committed, key=lambda c: c.number)
        used_keys: dict[str, list[str]] = {}
        for c in committed:
            for k in c.fact_keys_used or []:
                used_keys.setdefault(k, []).append(c.chapter_id)
        # Prefer a non-name key with real dependents for a non-trivial precision measurement.
        changed_key = next(
            (k for k, ids in used_keys.items() if k != "character.hero.name" and len(ids) >= 1),
            next(iter(used_keys), "character.hero.name"),
        )
        true_dependents = set(used_keys.get(changed_key, []))
        # Forward planned chapters are also "true" impact for narrative continuity.
        for c in chapters:
            if c.number > target.number and c.status is not ProductionUnitStatus.COMMITTED:
                true_dependents.add(c.chapter_id)

        new_value = f"rewritten@{at_chapter}"
        original_content = target.content
        edited = original_content + f"\n\n【基准改稿 ch{at_chapter}】关键设定变更：{changed_key}={new_value}。"

        record = eng.apply_author_chapter_edit(
            story_id,
            target.chapter_id,
            new_content=edited,
            reason=f"bench repair at {at_chapter}",
        )
        blocked_open = eng.is_production_blocked(story_id)

        result = eng.complete_reconcile(
            story_id,
            record.reconcile_id,
            fact_deltas=[
                {
                    "key": changed_key,
                    "value": new_value,
                    "kind": "world" if changed_key.startswith("world") else "character",
                    "claim": f"benchmark set {changed_key}={new_value}",
                }
            ],
        )
        if not result.ok:
            report.notes.append(f"repair@{at_chapter} failed: {result.message}")

        predicted = set(result.stale_chapter_ids)
        # Precision/recall against chapters that used the key or were forward planned.
        tp = predicted & true_dependents
        precision = len(tp) / len(predicted) if predicted else 1.0
        recall = len(tp) / len(true_dependents) if true_dependents else 1.0

        blocked_after = eng.is_production_blocked(story_id)

        # Count how many planned units were regenerated after this repair.
        regen = 0
        for c in repo.list_chapters(story_id):
            if c.provenance.get("replanned_after_reconcile") == record.reconcile_id:
                regen += 1

        outcome = RepairOutcome(
            at_chapter=at_chapter,
            changed_key=changed_key,
            reconcile_id=record.reconcile_id,
            stale_chapter_ids=sorted(predicted),
            still_valid_chapter_ids=result.still_valid_chapter_ids,
            invalidated_plan_ids=result.invalidated_plan_ids,
            total_chapters=len(chapters),
            true_dependents=sorted(true_dependents),
            regenerations=regen,
            production_blocked_before_complete=blocked_open,
            production_blocked_after_complete=blocked_after,
            invalidation_precision=precision,
            invalidation_recall=recall,
        )
        report.repairs.append(outcome)
        report.regenerations += regen
        return outcome

    def _record_recovery(
        self, eng: ProductionEngine, report: BenchmarkReport, outcome: ChapterOutcome
    ) -> None:
        failed = outcome.attempt - 1
        run_id = outcome.run_id
        action = ""
        double = False
        recovered = outcome.ok
        if run_id:
            try:
                action = eng.resume_decision(run_id).value
            except DomainError:
                action = "UNKNOWN"
        # Double-commit check: same chapter must not appear twice in successful commits.
        ids = [o.chapter_id for o in report.chapter_outcomes if o.ok]
        double = len(ids) != len(set(ids))
        report.recoveries.append(
            RecoveryOutcome(
                chapter_number=outcome.number,
                failed_runs=failed,
                recovered=recovered,
                resume_action=action,
                double_commit=double,
            )
        )

    def _audit_continuity(
        self,
        repo: StoryRepository,
        story_id: str,
        produced_ids: dict[int, str],
    ) -> ContinuityAudit:
        chapters = repo.list_chapters(story_id)
        items = repo.list_state_items(story_id)
        events = repo.list_events(story_id)
        committed = [c for c in chapters if c.status is ProductionUnitStatus.COMMITTED]

        missing_fp = [
            c.chapter_id
            for c in committed
            if c.provenance.get("content_fingerprint") != content_fingerprint(c.content)
        ]

        by_number: dict[int, int] = {}
        for c in committed:
            by_number[c.number] = by_number.get(c.number, 0) + 1
        multi = [cid for cid, n in ((f"#{num}", cnt) for num, cnt in by_number.items()) if n > 1]

        # Contradictions: two CANONICAL items with the same key and different values.
        canonical = [i for i in items if i.status is FactStatus.CANONICAL]
        by_key: dict[str, list[Any]] = {}
        for i in canonical:
            by_key.setdefault(i.key, []).append(i.value)
        conflicts = [
            f"{k}={vals}"
            for k, vals in by_key.items()
            if len({json.dumps(v, sort_keys=True, default=str) for v in vals}) > 1
        ]

        # Broken truth: key has SUPERSEDED/INVALIDATED history but no live CANONICAL successor.
        canon_keys = {i.key for i in canonical}
        historical = {
            i.key
            for i in items
            if i.status in (FactStatus.SUPERSEDED, FactStatus.INVALIDATED)
        }
        broken_truth = sorted(historical - canon_keys)

        # Planned-but-not-yet-canonical keys are allowed (forward deps); note only.
        plan_only: list[str] = []
        for c in committed:
            for k in c.fact_keys_used or []:
                if k.startswith("chapter."):
                    continue
                if k not in canon_keys and k not in historical:
                    plan_only.append(f"{c.chapter_id}:{k}")

        pending = repo.list_reconciles(story_id)
        open_recs = [r.reconcile_id for r in pending if r.status.value == "PENDING"]

        numbers = sorted(c.number for c in committed)
        sequential = numbers == list(range(1, len(numbers) + 1)) if numbers else True

        violations: list[str] = []
        if missing_fp:
            violations.append(f"missing_or_mismatched_fingerprint={len(missing_fp)}")
        if multi:
            violations.append(f"duplicate_committed_numbers={multi}")
        if conflicts:
            violations.append(f"canonical_contradictions={len(conflicts)}")
        if broken_truth:
            violations.append(f"superseded_without_canonical={broken_truth}")
        if open_recs:
            violations.append(f"pending_reconciles={open_recs}")
        if not sequential:
            violations.append(f"non_sequential_numbers={numbers}")

        story = repo.get_story(story_id)
        audit = ContinuityAudit(
            committed_chapters=len(committed),
            missing_fingerprint=missing_fp,
            double_status_chapters=multi,
            unresolved_canonical_conflicts=conflicts,
            superseded_still_treated_as_canonical=broken_truth,
            orphan_pending_reconciles=open_recs,
            sequential_numbers=sequential,
            final_revision=story.current_canonical_revision if story else -1,
            canonical_fact_count=len(canonical),
            event_count=len(events),
            violations=violations,
        )
        if plan_only:
            # Informational only: rolling plans may declare keys filled later.
            pass
        return audit

    def _make_inner_provider(self) -> Provider:
        if self.provider_name == "fake":
            from novel_weaver.ai.fake import FakeProvider

            return FakeProvider()
        if self.provider_name in ("openai", "llm"):
            from novel_weaver.ai.registry import get_provider

            return get_provider(self.provider_name)
        from novel_weaver.ai.template import TemplateProvider

        return TemplateProvider()


def run_benchmark(
    *,
    chapters: int = 30,
    provider_name: str = "template",
    workspace: Path | str | None = None,
    output: Path | str | None = None,
    repair_at: tuple[int, ...] | None = None,
    recover_at: tuple[int, ...] | None = None,
    chapter_delay_s: float = 0.0,
    max_provider_retries: int = 0,
) -> BenchmarkReport:
    """Run a LongRunBenchmark and optionally write a JSON report file.

    Args:
        chapters: Target chapter count.
        provider_name: Provider key (fake/template/openai/llm).
        workspace: Optional workspace directory for the SQLite database.
        output: Optional JSON report path.
        repair_at: Explicit repair drill chapter numbers.
        recover_at: Explicit recovery drill chapter numbers.
        chapter_delay_s: Sleep between chapters (live gateways).
        max_provider_retries: Provider retries per chapter attempt.

    Returns:
        BenchmarkReport from the completed run.
    """
    bench = LongRunBenchmark(
        chapters=chapters,
        provider_name=provider_name,
        workspace=workspace,
        repair_at=repair_at,
        recover_at=recover_at,
        chapter_delay_s=chapter_delay_s,
        max_provider_retries=max_provider_retries,
    )
    report = bench.run()
    if output is not None:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report
