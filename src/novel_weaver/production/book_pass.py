# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Full-book Consistency Pass (Phase 4): audit every committed unit against Canon.

Produces a book-scoped RevisionManifest. Deterministic checks always run;
optional LLM pass deepens semantic book-wide review without becoming the
sole source of truth.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from novel_weaver.ai.base import GenerationRequest, Provider, ProviderError
from novel_weaver.domain.models import (
    Chapter,
    FactStatus,
    ProductionUnitStatus,
    StateItem,
)
from novel_weaver.domain.models import new_id
from novel_weaver.production.fingerprint import content_fingerprint
from novel_weaver.production.quality import (
    Decision,
    QualityIssue,
    RevisionManifest,
    Severity,
)
from novel_weaver.storage.repositories import StoryRepository

_LLM_SYSTEM = """你是长篇小说全书审校员。输入为：正式事实摘要 + 各章标题/摘要/节选。
只输出 JSON：
{
  "decision": "PASS" | "REVISE" | "BLOCK",
  "issues": [
    {
      "severity": "INFO" | "WARN" | "BLOCKER",
      "evidence": "哪一章/哪条事实冲突或断裂",
      "suggested_action": "可执行修复",
      "affected_scope": "chapter:<id>|thread:<key>|fact:<key>",
      "acceptance_criteria": "通过标准"
    }
  ]
}
关注：跨章矛盾、人物状态无来源漂移、开放伏笔被遗忘、时间线倒错。
不要复述情节；只报问题。"""


@dataclass
class BookConsistencyReport:
    """Full-book consistency audit result.

    Attributes:
        story_id: Audited story identity.
        committed_chapters: Count of committed chapters inspected.
        canonical_facts: Count of CANONICAL facts inspected.
        decision: PASS / REVISE / BLOCK.
        score: Heuristic score in [0, 1].
        issues: All quality issues found.
        manifest_id: RevisionManifest identity for the issues.
        used_llm: Whether the optional LLM book review ran.
        llm_error: Error text when the LLM pass failed.
        stats: Structural counts (empty chapters, open threads, ...).
    """

    story_id: str
    committed_chapters: int
    canonical_facts: int
    decision: Decision
    score: float
    issues: list[QualityIssue] = field(default_factory=list)
    manifest_id: str = ""
    used_llm: bool = False
    llm_error: str = ""
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def blocker_count(self) -> int:
        """Number of BLOCKER-severity issues.

        Returns:
            Count of blocker issues.
        """
        return sum(1 for i in self.issues if i.severity is Severity.BLOCKER)

    @property
    def warn_count(self) -> int:
        """Number of WARN-severity issues.

        Returns:
            Count of warn issues.
        """
        return sum(1 for i in self.issues if i.severity is Severity.WARN)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report for JSON output.

        Returns:
            Dict with decision, score, counts, and issue details.
        """
        return {
            "story_id": self.story_id,
            "committed_chapters": self.committed_chapters,
            "canonical_facts": self.canonical_facts,
            "decision": self.decision.value,
            "score": self.score,
            "blocker_count": self.blocker_count,
            "warn_count": self.warn_count,
            "manifest_id": self.manifest_id,
            "used_llm": self.used_llm,
            "llm_error": self.llm_error,
            "stats": self.stats,
            "issues": [
                {
                    "severity": i.severity.value,
                    "evidence": i.evidence,
                    "suggested_action": i.suggested_action,
                    "affected_scope": i.affected_scope,
                    "acceptance_criteria": i.acceptance_criteria,
                }
                for i in self.issues
            ],
        }


class BookConsistencyPass:
    """Audit an entire story's committed chapters against Canonical state."""

    def __init__(
        self,
        repo: StoryRepository,
        *,
        llm_provider: Provider | None = None,
        llm_model: str | None = None,
        max_chapter_digest_chars: int = 240,
        max_llm_chapters: int = 40,
    ) -> None:
        self.repo = repo
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.max_chapter_digest_chars = max_chapter_digest_chars
        self.max_llm_chapters = max_llm_chapters

    def acknowledge_chapter(
        self,
        story_id: str,
        chapter_id: str,
        *,
        note: str = "book-pass accepted",
    ) -> Chapter | None:
        """Clear needs_reconcile on a committed chapter after human/book review.

        Args:
            story_id: Story that owns the chapter.
            chapter_id: Chapter to acknowledge.
            note: Acknowledgement note stored on provenance.

        Returns:
            The updated Chapter, or None when not found.
        """
        chapter = self.repo.get_chapter(chapter_id)
        if chapter is None:
            return None
        chapter.provenance = {
            **chapter.provenance,
            "needs_reconcile": False,
            "book_pass_ack": note,
        }
        self.repo.save_chapter(story_id, chapter)
        return chapter

    def acknowledge_all_flagged(self, story_id: str, *, note: str = "book-pass bulk ack") -> int:
        """Clear needs_reconcile on every flagged committed chapter.

        Args:
            story_id: Story to bulk-acknowledge.
            note: Acknowledgement note stored on provenance.

        Returns:
            Number of chapters acknowledged.
        """
        count = 0
        for ch in self.repo.list_chapters(story_id):
            if ch.status is ProductionUnitStatus.COMMITTED and ch.provenance.get(
                "needs_reconcile"
            ):
                self.acknowledge_chapter(story_id, ch.chapter_id, note=note)
                count += 1
        return count

    def run(self, story_id: str) -> BookConsistencyReport:
        """Run deterministic (and optional LLM) full-book consistency checks.

        Args:
            story_id: Story to audit.

        Returns:
            BookConsistencyReport with decision, score, issues, and stats.
        """
        chapters = self.repo.list_chapters(story_id)
        items = self.repo.list_state_items(story_id)
        committed = [c for c in chapters if c.status is ProductionUnitStatus.COMMITTED]
        canonical = [i for i in items if i.status is FactStatus.CANONICAL]

        issues: list[QualityIssue] = []
        issues.extend(self._check_structure(committed))
        issues.extend(self._check_fingerprints(committed))
        issues.extend(self._check_fact_refs(committed, items, canonical))
        issues.extend(self._check_reconcile_flags(committed))
        issues.extend(self._check_threads(chapters, items, committed))

        stats = {
            "total_chapters": len(chapters),
            "empty_committed": sum(1 for c in committed if not (c.content or "").strip()),
            "needs_reconcile": sum(1 for c in committed if c.provenance.get("needs_reconcile")),
            "open_thread_keys": [
                i.key
                for i in items
                if i.kind == "thread" and i.status in (FactStatus.PENDING, FactStatus.PROPOSED)
            ],
        }

        used_llm = False
        llm_error = ""
        if self.llm_provider is not None and committed:
            try:
                llm_issues = self._llm_book_review(story_id, committed, canonical, items)
                issues.extend(llm_issues)
                used_llm = True
            except (ProviderError, ValueError) as exc:
                llm_error = str(exc)

        decision = self._decide(issues)
        score = self._score(issues)
        # Manifest based on a synthetic candidate id scoped to the book.
        fake_basis = f"book:{story_id}"
        manifest = RevisionManifest.build(fake_basis, issues)
        return BookConsistencyReport(
            story_id=story_id,
            committed_chapters=len(committed),
            canonical_facts=len(canonical),
            decision=decision,
            score=score,
            issues=issues,
            manifest_id=manifest.manifest_id,
            used_llm=used_llm,
            llm_error=llm_error,
            stats=stats,
        )

    # ------------------------------------------------------------------ det
    def _check_structure(self, committed: list[Chapter]) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        if not committed:
            issues.append(
                QualityIssue(
                    issue_id=new_id("qi"),
                    evidence="no committed chapters in story",
                    severity=Severity.INFO,
                    affected_scope="book",
                    suggested_action="produce at least one chapter before full-book pass",
                    acceptance_criteria="committed_chapters >= 1",
                )
            )
            return issues

        numbers = sorted(c.number for c in committed)
        if numbers != list(range(1, len(numbers) + 1)):
            issues.append(
                QualityIssue(
                    issue_id=new_id("qi"),
                    evidence=f"non-sequential chapter numbers: {numbers}",
                    severity=Severity.WARN,
                    affected_scope="book",
                    suggested_action="re-plan missing numbers or archive gaps explicitly",
                    acceptance_criteria="committed numbers are 1..N without holes",
                )
            )

        for ch in committed:
            if not (ch.content or "").strip():
                issues.append(
                    QualityIssue(
                        issue_id=new_id("qi"),
                        evidence=f"committed chapter {ch.number} ({ch.chapter_id}) has empty content",
                        severity=Severity.BLOCKER,
                        affected_scope=f"chapter:{ch.chapter_id}",
                        suggested_action="regenerate or uncommit empty chapter",
                        acceptance_criteria="committed chapter content is non-empty",
                    )
                )
        return issues

    def _check_fingerprints(self, committed: list[Chapter]) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        for ch in committed:
            recorded = ch.provenance.get("content_fingerprint")
            current = content_fingerprint(ch.content)
            if recorded is None:
                issues.append(
                    QualityIssue(
                        issue_id=new_id("qi"),
                        evidence=f"chapter {ch.number} missing content_fingerprint",
                        severity=Severity.INFO,
                        affected_scope=f"chapter:{ch.chapter_id}",
                        suggested_action="re-commit or baseline fingerprint on next reconcile",
                        acceptance_criteria="provenance.content_fingerprint present",
                    )
                )
            elif recorded != current:
                issues.append(
                    QualityIssue(
                        issue_id=new_id("qi"),
                        evidence=(
                            f"chapter {ch.number} content hash drift "
                            f"(recorded={recorded}, current={current})"
                        ),
                        severity=Severity.BLOCKER,
                        affected_scope=f"chapter:{ch.chapter_id}",
                        suggested_action="open External Sync reconcile for this chapter",
                        acceptance_criteria="live content matches committed fingerprint",
                    )
                )
        return issues

    def _check_fact_refs(
        self,
        committed: list[Chapter],
        items: list[StateItem],
        canonical: list[StateItem],
    ) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        canon_keys = {i.key for i in canonical}
        historical = {
            i.key
            for i in items
            if i.status in (FactStatus.SUPERSEDED, FactStatus.INVALIDATED)
        }

        broken = sorted(historical - canon_keys)
        for key in broken:
            issues.append(
                QualityIssue(
                    issue_id=new_id("qi"),
                    evidence=f"fact key {key!r} was superseded/invalidated without live CANONICAL successor",
                    severity=Severity.WARN,
                    affected_scope=f"fact:{key}",
                    suggested_action="re-promote a canonical value or archive dependent chapters",
                    acceptance_criteria="exactly one live CANONICAL value per historical key",
                )
            )

        # Chapter-declared keys with no state history at all (forward dep only).
        unknown: dict[str, list[int]] = {}
        for ch in committed:
            for k in ch.fact_keys_used or []:
                if k.startswith("chapter."):
                    continue
                if k not in canon_keys and k not in historical:
                    unknown.setdefault(k, []).append(ch.number)
        for key, nums in sorted(unknown.items()):
            issues.append(
                QualityIssue(
                    issue_id=new_id("qi"),
                    evidence=f"chapters {nums} depend on fact key {key!r} with no state history",
                    severity=Severity.INFO,
                    affected_scope=f"fact:{key}",
                    suggested_action="declare initial state or stop depending on unfilled keys",
                    acceptance_criteria="key has CANONICAL/PENDING item or is removed from depends",
                )
            )
        return issues

    def _check_reconcile_flags(self, committed: list[Chapter]) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        for ch in committed:
            if ch.provenance.get("needs_reconcile"):
                issues.append(
                    QualityIssue(
                        issue_id=new_id("qi"),
                        evidence=(
                            f"chapter {ch.number} still flagged needs_reconcile "
                            f"(reason={ch.provenance.get('stale_reason')})"
                        ),
                        severity=Severity.WARN,
                        affected_scope=f"chapter:{ch.chapter_id}",
                        suggested_action="run reconcile/repair for this chapter before trusting continuity",
                        acceptance_criteria="needs_reconcile cleared after repair",
                    )
                )
        return issues

    def _check_threads(
        self,
        chapters: list[Chapter],
        items: list[StateItem],
        committed: list[Chapter],
    ) -> list[QualityIssue]:
        """Throughline: open thread keys should be touched by later production."""
        issues: list[QualityIssue] = []
        if not committed:
            return issues
        max_n = max(c.number for c in committed)
        open_threads = [
            i
            for i in items
            if i.kind == "thread"
            and i.status in (FactStatus.PENDING, FactStatus.PROPOSED, FactStatus.UNKNOWN)
        ]
        for thr in open_threads:
            # Which committed chapters declare this thread key?
            touching = [c.number for c in committed if thr.key in (c.fact_keys_used or [])]
            if not touching:
                issues.append(
                    QualityIssue(
                        issue_id=new_id("qi"),
                        evidence=f"open thread {thr.key!r} never appears in any chapter fact_keys",
                        severity=Severity.WARN,
                        affected_scope=f"thread:{thr.key}",
                        suggested_action="introduce/touch the thread in a plan or resolve/abandon it",
                        acceptance_criteria="thread is touched or status advanced",
                    )
                )
            elif max(touching) < max_n - 5 and max_n >= 8:
                # Untouched for a long stretch of later chapters.
                issues.append(
                    QualityIssue(
                        issue_id=new_id("qi"),
                        evidence=(
                            f"open thread {thr.key!r} last touched at ch{max(touching)} "
                            f"but book reaches ch{max_n}"
                        ),
                        severity=Severity.INFO,
                        affected_scope=f"thread:{thr.key}",
                        suggested_action="surface thread in near-horizon plan or mark ABANDONED",
                        acceptance_criteria="thread last_touched advances or status resolves",
                    )
                )
        return issues

    # ------------------------------------------------------------------ llm
    def _llm_book_review(
        self,
        story_id: str,
        committed: list[Chapter],
        canonical: list[StateItem],
        items: list[StateItem],
    ) -> list[QualityIssue]:
        assert self.llm_provider is not None
        fact_lines = [f"- {i.key} = {i.value!r} ({i.kind})" for i in canonical]
        sample = committed[: self.max_llm_chapters]
        chapter_lines: list[str] = []
        for ch in sample:
            body = (ch.content or "").strip().replace("\n", " ")
            digest = body[: self.max_chapter_digest_chars]
            if len(body) > self.max_chapter_digest_chars:
                digest += "…"
            chapter_lines.append(f"### 第{ch.number}章 {ch.title} [{ch.chapter_id}]\n{digest}")

        user = "\n\n".join(
            [
                "正式事实：\n" + ("\n".join(fact_lines) or "- (无)"),
                "章节摘要：\n" + "\n\n".join(chapter_lines),
                "请输出 JSON 全书一致性审校结果。",
            ]
        )
        request = GenerationRequest(
            task="continuity_review",
            prompt=user,
            context={"story_id": story_id, "scope": "full_book", "chapters": len(sample)},
            model=self.llm_model or "default",
            temperature=0.0,
            max_tokens=1200,
            story_id=story_id,
        )
        gen = self.llm_provider.generate(request)
        payload = self._extract_json(gen.text)
        if payload is None:
            raise ValueError("book review returned non-JSON")

        severity_map = {
            "BLOCKER": Severity.BLOCKER,
            "BLOCK": Severity.BLOCKER,
            "WARN": Severity.WARN,
            "WARNING": Severity.WARN,
            "INFO": Severity.INFO,
        }
        issues: list[QualityIssue] = []
        for item in payload.get("issues") or []:
            if not isinstance(item, dict):
                continue
            evidence = str(item.get("evidence") or "").strip()
            action = str(item.get("suggested_action") or item.get("action") or "inspect passage").strip()
            if not evidence and not action:
                continue
            issues.append(
                QualityIssue(
                    issue_id=new_id("qi"),
                    evidence=evidence or action,
                    severity=severity_map.get(str(item.get("severity", "INFO")).upper(), Severity.INFO),
                    affected_scope=str(item.get("affected_scope") or "book"),
                    suggested_action=action or "inspect passage",
                    acceptance_criteria=str(
                        item.get("acceptance_criteria") or "book-level issue resolved"
                    ),
                )
            )
        return issues

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        raw = (text or "").strip()
        if not raw:
            return None
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if fence:
            raw = fence.group(1)
        else:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                raw = raw[start : end + 1]
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _decide(issues: list[QualityIssue]) -> Decision:
        if any(i.severity is Severity.BLOCKER for i in issues):
            return Decision.BLOCK
        if any(i.severity is Severity.WARN for i in issues):
            return Decision.REVISE
        return Decision.PASS

    @staticmethod
    def _score(issues: list[QualityIssue]) -> float:
        score = 1.0
        for issue in issues:
            if issue.severity is Severity.BLOCKER:
                score -= 0.35
            elif issue.severity is Severity.WARN:
                score -= 0.12
            else:
                score -= 0.04
        return max(0.0, round(score, 4))
