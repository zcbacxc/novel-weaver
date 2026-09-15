# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Quality system: deterministic checks, semantic review stub, revision manifest.

Quality must produce an actionable RevisionManifest, not just a score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from novel_weaver.domain.models import new_id
from novel_weaver.production.fake_gen import GeneratedCandidate


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    BLOCKER = "BLOCKER"


class ManifestStatus(str, Enum):
    OPEN = "OPEN"
    APPLIED = "APPLIED"
    DISCARDED = "DISCARDED"


class Decision(str, Enum):
    PASS = "PASS"
    REVISE = "REVISE"
    BLOCK = "BLOCK"


_PLACEHOLDER_PATTERNS = (
    re.compile(r"\[PLACEHOLDER\]", re.IGNORECASE),
    re.compile(r"\[TODO[^\]]*\]", re.IGNORECASE),
    re.compile(r"\bTBD\b"),
    re.compile(r"<placeholder>", re.IGNORECASE),
    re.compile(r"\{\{.*?\}\}"),
)


@dataclass
class QualityIssue:
    issue_id: str
    evidence: str
    severity: Severity
    affected_scope: str
    suggested_action: str
    acceptance_criteria: str


@dataclass
class RevisionManifest:
    manifest_id: str
    based_on_candidate_id: str
    issues: list[QualityIssue] = field(default_factory=list)
    ordering: list[str] = field(default_factory=list)
    status: ManifestStatus = ManifestStatus.OPEN

    @classmethod
    def build(
        cls,
        based_on_candidate_id: str,
        issues: list[QualityIssue],
    ) -> RevisionManifest:
        ordered = _order_issues(issues)
        return cls(
            manifest_id=new_id("rman"),
            based_on_candidate_id=based_on_candidate_id,
            issues=list(issues),
            ordering=[i.issue_id for i in ordered],
            status=ManifestStatus.OPEN,
        )


@dataclass
class QualityFeedback:
    issue: str
    evidence: str
    affected_scope: str
    recommended_action: str
    constraint_change: dict[str, Any] | None = None
    next_run_hints: list[str] = field(default_factory=list)


@dataclass
class QualityDecision:
    decision: Decision
    score: float
    issues: list[QualityIssue]
    feedback_for_next_run: QualityFeedback
    manifest: RevisionManifest


@dataclass
class SemanticReviewResult:
    decision: Decision
    issues: list[QualityIssue]


class SemanticReviewer(Protocol):
    def review(
        self,
        candidate: GeneratedCandidate,
        constraints: dict[str, Any],
    ) -> SemanticReviewResult: ...


def _order_issues(issues: list[QualityIssue]) -> list[QualityIssue]:
    rank = {Severity.BLOCKER: 0, Severity.WARN: 1, Severity.INFO: 2}
    return sorted(issues, key=lambda i: (rank[i.severity], i.issue_id))


def _word_count(text: str) -> int:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    non_cjk = re.sub(r"[\u4e00-\u9fff]", " ", text)
    tokens = len(re.findall(r"\S+", non_cjk))
    return cjk + tokens


class DeterministicChecker:
    """Code-verifiable gates: empty content, missing plan, constraint violations, placeholders."""

    def check(
        self,
        candidate: GeneratedCandidate,
        constraints: dict[str, Any] | None = None,
    ) -> list[QualityIssue]:
        constraints = constraints or {}
        issues: list[QualityIssue] = []
        content = candidate.content or ""
        stripped = content.strip()
        scope = f"candidate:{candidate.candidate_id}"

        if not stripped:
            issues.append(
                QualityIssue(
                    issue_id=new_id("qi"),
                    evidence="candidate content is empty or whitespace",
                    severity=Severity.BLOCKER,
                    affected_scope=scope,
                    suggested_action="regenerate chapter body",
                    acceptance_criteria="content.strip() is non-empty",
                )
            )

        plan = (candidate.validation or {}).get("plan") or constraints.get("plan")
        if plan is not None and not str(plan).strip():
            issues.append(
                QualityIssue(
                    issue_id=new_id("qi"),
                    evidence="production plan is missing or blank",
                    severity=Severity.WARN,
                    affected_scope=scope,
                    suggested_action="supply a non-empty plan before regeneration",
                    acceptance_criteria="plan is a non-empty string",
                )
            )

        forbidden = list(constraints.get("forbidden_keywords") or [])
        for kw in forbidden:
            if kw and kw in content:
                issues.append(
                    QualityIssue(
                        issue_id=new_id("qi"),
                        evidence=f"forbidden keyword present: {kw!r}",
                        severity=Severity.BLOCKER,
                        affected_scope=scope,
                        suggested_action=f"remove or rewrite passages containing {kw!r}",
                        acceptance_criteria=f"content does not contain {kw!r}",
                    )
                )

        required = list(constraints.get("required_keywords") or [])
        for kw in required:
            if kw and kw not in content:
                issues.append(
                    QualityIssue(
                        issue_id=new_id("qi"),
                        evidence=f"required keyword missing: {kw!r}",
                        severity=Severity.WARN,
                        affected_scope=scope,
                        suggested_action=f"ensure {kw!r} appears in the candidate",
                        acceptance_criteria=f"content contains {kw!r}",
                    )
                )

        min_words = constraints.get("min_words")
        if isinstance(min_words, int) and min_words > 0:
            wc = _word_count(stripped)
            if stripped and wc < min_words:
                issues.append(
                    QualityIssue(
                        issue_id=new_id("qi"),
                        evidence=f"word count {wc} below min_words {min_words}",
                        severity=Severity.WARN,
                        affected_scope=scope,
                        suggested_action="expand chapter body to meet min_words",
                        acceptance_criteria=f"word count >= {min_words}",
                    )
                )

        for pattern in _PLACEHOLDER_PATTERNS:
            match = pattern.search(content)
            if match:
                issues.append(
                    QualityIssue(
                        issue_id=new_id("qi"),
                        evidence=f"structure placeholder found: {match.group(0)!r}",
                        severity=Severity.WARN,
                        affected_scope=scope,
                        suggested_action="replace placeholder with real prose",
                        acceptance_criteria="no structural placeholders remain",
                    )
                )
                break

        return issues


class SemanticReviewStub:
    """Rule-based semantic review; interface matches a future LLM reviewer."""

    def review(
        self,
        candidate: GeneratedCandidate,
        constraints: dict[str, Any] | None = None,
    ) -> SemanticReviewResult:
        constraints = constraints or {}
        issues: list[QualityIssue] = []
        content = candidate.content or ""
        stripped = content.strip()
        scope = f"candidate:{candidate.candidate_id}"

        if not stripped:
            return SemanticReviewResult(decision=Decision.BLOCK, issues=issues)

        lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
        if len(lines) >= 3:
            counts: dict[str, int] = {}
            for ln in lines:
                counts[ln] = counts.get(ln, 0) + 1
            repeated = [ln for ln, c in counts.items() if c >= 3]
            if repeated:
                issues.append(
                    QualityIssue(
                        issue_id=new_id("qi"),
                        evidence=f"line repeated >=3 times: {repeated[0][:60]!r}",
                        severity=Severity.WARN,
                        affected_scope=scope,
                        suggested_action="vary repeated narrative lines",
                        acceptance_criteria="no line repeats three or more times",
                    )
                )

        soft_min = constraints.get("semantic_min_paragraphs", 2)
        paragraphs = [p for p in re.split(r"\n\s*\n", stripped) if p.strip()]
        if isinstance(soft_min, int) and soft_min > 0 and len(paragraphs) < soft_min:
            issues.append(
                QualityIssue(
                    issue_id=new_id("qi"),
                    evidence=f"paragraph count {len(paragraphs)} below {soft_min}",
                    severity=Severity.INFO,
                    affected_scope=scope,
                    suggested_action="split body into more scene paragraphs",
                    acceptance_criteria=f"at least {soft_min} paragraphs",
                )
            )

        if any(i.severity is Severity.BLOCKER for i in issues):
            decision = Decision.BLOCK
        elif any(i.severity is Severity.WARN for i in issues):
            decision = Decision.REVISE
        else:
            decision = Decision.PASS

        return SemanticReviewResult(decision=decision, issues=issues)


def decide(
    candidate: GeneratedCandidate,
    constraints: dict[str, Any] | None = None,
    *,
    checker: DeterministicChecker | None = None,
    reviewer: SemanticReviewer | None = None,
) -> QualityDecision:
    """Run dual-layer quality and return decision + revision manifest + feedback."""
    constraints = constraints or {}
    checker = checker or DeterministicChecker()
    reviewer = reviewer or SemanticReviewStub()

    det_issues = checker.check(candidate, constraints)
    sem_result = reviewer.review(candidate, constraints)
    all_issues = det_issues + list(sem_result.issues)

    if any(i.severity is Severity.BLOCKER for i in all_issues):
        decision = Decision.BLOCK
    elif any(i.severity is Severity.WARN for i in all_issues):
        decision = Decision.REVISE
    else:
        decision = Decision.PASS

    score = _score(all_issues)
    manifest = RevisionManifest.build(candidate.candidate_id, all_issues)
    feedback = _build_feedback(candidate, constraints, all_issues, decision)

    return QualityDecision(
        decision=decision,
        score=score,
        issues=all_issues,
        feedback_for_next_run=feedback,
        manifest=manifest,
    )


def _score(issues: list[QualityIssue]) -> float:
    score = 1.0
    for issue in issues:
        if issue.severity is Severity.BLOCKER:
            score -= 0.4
        elif issue.severity is Severity.WARN:
            score -= 0.15
        else:
            score -= 0.05
    return max(0.0, round(score, 4))


def _build_feedback(
    candidate: GeneratedCandidate,
    constraints: dict[str, Any],
    issues: list[QualityIssue],
    decision: Decision,
) -> QualityFeedback:
    ordered = _order_issues(issues)
    if not ordered:
        return QualityFeedback(
            issue="no quality issues",
            evidence="deterministic checks and semantic review passed",
            affected_scope=f"candidate:{candidate.candidate_id}",
            recommended_action="accept candidate for commit path",
            constraint_change=None,
            next_run_hints=["keep current constraints"],
        )

    top = ordered[0]
    hints = [i.suggested_action for i in ordered[:5]]
    constraint_change: dict[str, Any] | None = None

    forbidden_hits = [
        i for i in issues if "forbidden keyword present" in i.evidence
    ]
    if forbidden_hits and decision is Decision.BLOCK:
        constraint_change = {
            "note": "reinforce forbidden keywords in next generation prompt",
            "forbidden_keywords": list(constraints.get("forbidden_keywords") or []),
        }

    missing_required = [
        i for i in issues if "required keyword missing" in i.evidence
    ]
    if missing_required and constraint_change is None:
        constraint_change = {
            "note": "surface required keywords more explicitly in plan/context",
            "required_keywords": list(constraints.get("required_keywords") or []),
        }

    return QualityFeedback(
        issue=top.suggested_action,
        evidence=top.evidence,
        affected_scope=top.affected_scope,
        recommended_action=top.suggested_action,
        constraint_change=constraint_change,
        next_run_hints=hints,
    )
