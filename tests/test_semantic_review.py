# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""LLM semantic reviewer unit tests (mocked provider, no live key)."""

from __future__ import annotations

import json

from novel_weaver.ai.base import (
    GenerationRequest,
    GenerationResult,
    Provider,
    ProviderError,
    TokenUsage,
)
from novel_weaver.domain.models import CandidateStatus
from novel_weaver.production.fake_gen import GeneratedCandidate
from novel_weaver.production.quality import Decision, Severity, decide
from novel_weaver.production.semantic_review import (
    CompositeSemanticReviewer,
    LLMSemanticReviewer,
    _extract_json,
)


class _ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, reply: str, *, fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        if self.fail:
            raise ProviderError("review down", retryable=False)
        return GenerationResult(
            text=self.reply,
            model="scripted-1",
            provider=self.name,
            usage=TokenUsage.of(10, 10),
            latency_ms=1.0,
            task=request.task,
        )


def _cand(text: str = "顾言走进码头。雨很大。") -> GeneratedCandidate:
    return GeneratedCandidate(
        candidate_id="cand_x",
        chapter_id="ch_x",
        content=text,
        session_id="s",
        base_story_revision=1,
        plan_revision=1,
        context_fingerprint="fp",
        status=CandidateStatus.DRAFT,
    )


def test_extract_json_from_fence_and_bare() -> None:
    assert _extract_json('```json\n{"a":1}\n```') == {"a": 1}
    assert _extract_json('noise {"decision":"PASS","issues":[]} tail')["decision"] == "PASS"
    assert _extract_json("not json") is None


def test_llm_reviewer_parses_issues_and_forces_block() -> None:
    reply = json.dumps(
        {
            "decision": "REVISE",
            "issues": [
                {
                    "severity": "BLOCKER",
                    "evidence": "顾言左手受伤却用左手开门",
                    "suggested_action": "改写为右手或交代伤势",
                    "affected_scope": "fact:character.gu.injury",
                    "acceptance_criteria": "与伤势一致",
                },
                {
                    "severity": "WARN",
                    "evidence": "场景略空",
                    "suggested_action": "补环境细节",
                },
            ],
        },
        ensure_ascii=False,
    )
    provider = _ScriptedProvider(reply)
    reviewer = LLMSemanticReviewer(provider)
    result = reviewer.review(
        _cand(),
        {},
        review_context={"selected_facts": [{"key": "character.gu.injury", "value": "left"}]},
    )
    assert reviewer.last_used_llm is True
    assert result.decision is Decision.BLOCK  # BLOCKER overrides model REVISE
    assert len(result.issues) == 2
    assert provider.calls[0].task == "continuity_review"
    assert "正式事实" in provider.calls[0].prompt


def test_llm_reviewer_falls_back_on_provider_error() -> None:
    provider = _ScriptedProvider("", fail=True)
    notes: list[str] = []
    reviewer = LLMSemanticReviewer(provider, on_fallback=notes.append)
    result = reviewer.review(_cand(), {})
    assert reviewer.last_used_llm is False
    assert notes and "review down" in notes[0]
    # Stub path on clean short text → PASS or INFO-only
    assert result.decision in (Decision.PASS, Decision.REVISE)


def test_composite_merges_stub_and_llm() -> None:
    # Stub will WARN on 3+ repeated lines.
    body = "重复行\n重复行\n重复行\n其他段落"
    reply = json.dumps(
        {
            "decision": "PASS",
            "issues": [
                {"severity": "INFO", "evidence": "节奏偏快", "suggested_action": "放慢"}
            ],
        }
    )
    provider = _ScriptedProvider(reply)
    composite = CompositeSemanticReviewer(LLMSemanticReviewer(provider))
    result = composite.review(_cand(body), {})
    assert result.decision is Decision.REVISE  # stub WARN
    assert any("repeated" in i.evidence for i in result.issues)
    assert any("节奏" in i.evidence for i in result.issues)


def test_decide_uses_injected_reviewer() -> None:
    reply = json.dumps(
        {
            "decision": "BLOCK",
            "issues": [
                {
                    "severity": "BLOCKER",
                    "evidence": "与正式事实冲突：港口名错误",
                    "suggested_action": "改写地点",
                }
            ],
        }
    )
    provider = _ScriptedProvider(reply)
    reviewer = CompositeSemanticReviewer(LLMSemanticReviewer(provider))
    qd = decide(_cand(), {}, reviewer=reviewer, review_context={"current_plan": "调查"})
    assert qd.decision is Decision.BLOCK
    assert any("港口" in i.evidence for i in qd.issues)
    assert qd.manifest.issues
