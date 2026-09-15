"""Quality system tests: deterministic checks, semantic stub, manifest, feedback."""

from __future__ import annotations

from novel_weaver.domain.models import CandidateStatus
from novel_weaver.production.fake_gen import GeneratedCandidate
from novel_weaver.production.quality import (
    Decision,
    DeterministicChecker,
    ManifestStatus,
    QualityIssue,
    RevisionManifest,
    SemanticReviewStub,
    Severity,
    decide,
)


def _candidate(
    content: str,
    *,
    candidate_id: str = "cand_test",
    plan: str | None = None,
) -> GeneratedCandidate:
    validation: dict = {}
    if plan is not None:
        validation["plan"] = plan
    return GeneratedCandidate(
        candidate_id=candidate_id,
        chapter_id="ch1",
        content=content,
        session_id="s1",
        base_story_revision=0,
        plan_revision=0,
        context_fingerprint="fp",
        status=CandidateStatus.DRAFT,
        validation=validation,
    )


def test_empty_content_is_blocker() -> None:
    issues = DeterministicChecker().check(_candidate("   "), {})
    assert any(i.severity is Severity.BLOCKER for i in issues)
    assert any("empty" in i.evidence for i in issues)


def test_forbidden_keyword_is_blocker() -> None:
    cand = _candidate("主角走进了禁地。")
    issues = DeterministicChecker().check(
        cand, {"forbidden_keywords": ["禁地"]}
    )
    assert any(
        i.severity is Severity.BLOCKER and "禁地" in i.evidence for i in issues
    )


def test_required_keyword_missing_is_warn() -> None:
    cand = _candidate("夜色笼罩小镇。")
    issues = DeterministicChecker().check(
        cand, {"required_keywords": ["顾言"]}
    )
    assert any(
        i.severity is Severity.WARN and "顾言" in i.evidence for i in issues
    )


def test_min_words_violation() -> None:
    cand = _candidate("短。")
    issues = DeterministicChecker().check(cand, {"min_words": 10})
    assert any("min_words" in i.evidence for i in issues)


def test_placeholder_detected() -> None:
    cand = _candidate("正文…… [PLACEHOLDER] 后文。")
    issues = DeterministicChecker().check(cand, {})
    assert any("placeholder" in i.evidence.lower() for i in issues)


def test_missing_plan_when_explicitly_blank() -> None:
    cand = _candidate("足够的正文内容在这里。", plan="  ")
    issues = DeterministicChecker().check(cand, {"plan": "  "})
    assert any("plan" in i.evidence for i in issues)


def test_semantic_stub_pass_on_clean_text() -> None:
    cand = _candidate("第一段落。\n\n第二段落展开情节。\n\n第三段落收束。")
    result = SemanticReviewStub().review(cand, {})
    assert result.decision is Decision.PASS
    assert result.issues == []


def test_semantic_stub_revise_on_repeated_lines() -> None:
    body = "同一句话。\n" * 3 + "另一句。"
    cand = _candidate(body)
    result = SemanticReviewStub().review(cand, {})
    assert result.decision is Decision.REVISE
    assert any(i.severity is Severity.WARN for i in result.issues)


def test_decide_pass_with_manifest_open() -> None:
    cand = _candidate(
        "顾言推开木门，雨声灌进来。\n\n他望向长街尽头，灯火未熄。\n\n这一夜不会平静。",
    )
    result = decide(cand, {"required_keywords": ["顾言"], "min_words": 5})
    assert result.decision is Decision.PASS
    assert result.score == 1.0
    assert result.issues == []
    assert result.manifest.status is ManifestStatus.OPEN
    assert result.manifest.based_on_candidate_id == "cand_test"
    assert result.manifest.ordering == []
    assert result.feedback_for_next_run.recommended_action
    assert result.feedback_for_next_run.next_run_hints


def test_decide_block_builds_ordered_manifest_and_feedback() -> None:
    cand = _candidate("他使用了禁术。 [TODO: expand]", candidate_id="cand_bad")
    constraints = {
        "forbidden_keywords": ["禁术"],
        "required_keywords": ["顾言"],
        "min_words": 20,
    }
    result = decide(cand, constraints)
    assert result.decision is Decision.BLOCK
    assert result.score < 1.0
    assert result.manifest.based_on_candidate_id == "cand_bad"
    assert len(result.manifest.ordering) == len(result.manifest.issues)
    ordered_ids = result.manifest.ordering
    severities = {
        i.issue_id: i.severity for i in result.manifest.issues
    }
    first_sev = severities[ordered_ids[0]]
    assert first_sev is Severity.BLOCKER

    fb = result.feedback_for_next_run
    assert fb.recommended_action
    assert fb.constraint_change is not None
    assert fb.next_run_hints
    assert all(isinstance(h, str) and h for h in fb.next_run_hints)


def test_decide_revise_on_soft_issues() -> None:
    cand = _candidate("只有短短一句。")
    result = decide(cand, {"min_words": 10})
    assert result.decision is Decision.REVISE
    assert any(i.severity is Severity.WARN for i in result.issues)
    assert result.manifest.status is ManifestStatus.OPEN


def test_revision_manifest_ordering_prefers_blockers() -> None:
    blocker = QualityIssue(
        issue_id="b1",
        evidence="e",
        severity=Severity.BLOCKER,
        affected_scope="s",
        suggested_action="fix blocker",
        acceptance_criteria="ok",
    )
    warn = QualityIssue(
        issue_id="w1",
        evidence="e",
        severity=Severity.WARN,
        affected_scope="s",
        suggested_action="fix warn",
        acceptance_criteria="ok",
    )
    info = QualityIssue(
        issue_id="i1",
        evidence="e",
        severity=Severity.INFO,
        affected_scope="s",
        suggested_action="note",
        acceptance_criteria="ok",
    )
    manifest = RevisionManifest.build("c1", [info, warn, blocker])
    assert manifest.ordering == ["b1", "w1", "i1"]
