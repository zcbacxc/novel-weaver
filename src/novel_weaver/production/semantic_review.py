# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""LLM-backed semantic review (continuity / style) behind the SemanticReviewer protocol."""

from __future__ import annotations

import json
import re
from typing import Any

from novel_weaver.ai.base import GenerationRequest, Provider, ProviderError
from novel_weaver.domain.models import new_id
from novel_weaver.production.fake_gen import GeneratedCandidate
from novel_weaver.production.quality import (
    Decision,
    QualityIssue,
    SemanticReviewResult,
    SemanticReviewStub,
    Severity,
)

_SEVERITY_MAP = {
    "BLOCKER": Severity.BLOCKER,
    "BLOCK": Severity.BLOCKER,
    "WARN": Severity.WARN,
    "WARNING": Severity.WARN,
    "INFO": Severity.INFO,
}

_DECISION_MAP = {
    "PASS": Decision.PASS,
    "REVISE": Decision.REVISE,
    "BLOCK": Decision.BLOCK,
}

_SYSTEM = """你是长篇小说引擎的审校员（Reviewer），只做语义检查，不改写正文。
检查维度：
1) 连续性：是否违背「正式事实」；人物状态/时间线/地点是否与事实冲突。
2) 计划遵循：是否明显偏离本章计划。
3) 风格与结构：空洞重复、明显占位符、结构崩溃。

只输出 JSON，不要 Markdown 代码块，格式：
{
  "decision": "PASS" | "REVISE" | "BLOCK",
  "issues": [
    {
      "severity": "INFO" | "WARN" | "BLOCKER",
      "evidence": "原文短摘录或明确依据",
      "suggested_action": "可执行修复动作",
      "affected_scope": "chapter|fact:<key>|style",
      "acceptance_criteria": "通过标准"
    }
  ]
}
决策规则：有致命矛盾 → BLOCK；有可修复问题 → REVISE；否则 PASS。
issues 可为空数组。"""


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    # Strip markdown fences if present.
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


class LLMSemanticReviewer:
    """Semantic review via a replaceable Provider. Falls back to rule stub on failure."""

    def __init__(
        self,
        provider: Provider,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 800,
        fallback: SemanticReviewStub | None = None,
        on_fallback: Any = None,  # callable[[str], None] | None
    ) -> None:
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.fallback = fallback or SemanticReviewStub()
        self.on_fallback = on_fallback
        self.last_raw: str = ""
        self.last_used_llm: bool = False

    def review(
        self,
        candidate: GeneratedCandidate,
        constraints: dict[str, Any] | None = None,
        *,
        review_context: dict[str, Any] | None = None,
    ) -> SemanticReviewResult:
        """Review via the LLM provider; fall back to the rule stub on failure.

        Args:
            candidate: Candidate under review.
            constraints: Production constraints for the prompt and rules.
            review_context: Context pack fields (facts, plan, intent, story_id).

        Returns:
            SemanticReviewResult from the LLM path or the fallback stub.
        """
        constraints = constraints or {}
        try:
            result = self._review_via_llm(candidate, constraints, review_context or {})
            self.last_used_llm = True
            return result
        except (ProviderError, ValueError, KeyError) as exc:
            self.last_used_llm = False
            if self.on_fallback is not None:
                try:
                    self.on_fallback(str(exc))
                except Exception:
                    pass
            return self.fallback.review(candidate, constraints)

    def _review_via_llm(
        self,
        candidate: GeneratedCandidate,
        constraints: dict[str, Any],
        review_context: dict[str, Any],
    ) -> SemanticReviewResult:
        request = self._build_request(candidate, constraints, review_context)
        gen = self.provider.generate(request)
        self.last_raw = gen.text or ""
        payload = _extract_json(self.last_raw)
        if payload is None:
            raise ValueError("semantic review returned non-JSON body")

        decision = _DECISION_MAP.get(str(payload.get("decision", "PASS")).upper(), Decision.PASS)
        issues: list[QualityIssue] = []
        raw_issues = payload.get("issues") or []
        if not isinstance(raw_issues, list):
            raw_issues = []
        scope_default = f"candidate:{candidate.candidate_id}"
        for item in raw_issues:
            if not isinstance(item, dict):
                continue
            severity = _SEVERITY_MAP.get(
                str(item.get("severity", "INFO")).upper(), Severity.INFO
            )
            evidence = str(item.get("evidence") or item.get("detail") or "").strip()
            action = str(item.get("suggested_action") or item.get("action") or "revise passage").strip()
            if not evidence and not action:
                continue
            issues.append(
                QualityIssue(
                    issue_id=new_id("qi"),
                    evidence=evidence or action,
                    severity=severity,
                    affected_scope=str(item.get("affected_scope") or scope_default),
                    suggested_action=action or "revise passage",
                    acceptance_criteria=str(
                        item.get("acceptance_criteria") or "issue resolved in next draft"
                    ),
                )
            )

        # Reconcile decision with issue severities (don't trust model to under-block).
        if any(i.severity is Severity.BLOCKER for i in issues):
            decision = Decision.BLOCK
        elif issues and decision is Decision.PASS:
            decision = Decision.REVISE

        return SemanticReviewResult(decision=decision, issues=issues)

    def _build_request(
        self,
        candidate: GeneratedCandidate,
        constraints: dict[str, Any],
        review_context: dict[str, Any],
    ) -> GenerationRequest:
        facts = review_context.get("selected_facts") or review_context.get("state_snapshot") or []
        plan = str(review_context.get("current_plan") or candidate.validation.get("plan") or "")
        intent = str(review_context.get("creative_intent") or "")
        fact_lines = [
            f"- {f.get('key')}: {f.get('value')}" if isinstance(f, dict) else f"- {f}"
            for f in facts
        ] or ["- (无)"]
        forbidden = list(constraints.get("forbidden_keywords") or [])
        required = list(constraints.get("required_keywords") or [])

        user = "\n\n".join(
            [
                f"本章计划：{plan or '(未提供)'}",
                f"创作意图：{intent or '(未提供)'}",
                "正式事实（Canonical）：\n" + "\n".join(fact_lines),
                (
                    "额外约束：forbidden="
                    + repr(forbidden)
                    + " required="
                    + repr(required)
                    if forbidden or required
                    else "额外约束：(无)"
                ),
                "待审正文：\n" + (candidate.content or "")[:12000],
                "请输出 JSON 审校结果。",
            ]
        )
        return GenerationRequest(
            task="continuity_review",
            prompt=user,
            context={
                "candidate_id": candidate.candidate_id,
                "chapter_id": candidate.chapter_id,
                "selected_facts": facts,
                "current_plan": plan,
            },
            model=self.model or "default",
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            story_id=str(review_context.get("story_id") or ""),
            chapter_id=candidate.chapter_id,
        )


class CompositeSemanticReviewer:
    """Run rule stub + LLM reviewer and merge issues (LLM failure still yields stub)."""

    def __init__(
        self,
        llm: LLMSemanticReviewer,
        *,
        stub: SemanticReviewStub | None = None,
    ) -> None:
        self.llm = llm
        self.stub = stub or SemanticReviewStub()

    def review(
        self,
        candidate: GeneratedCandidate,
        constraints: dict[str, Any] | None = None,
        *,
        review_context: dict[str, Any] | None = None,
    ) -> SemanticReviewResult:
        """Merge rule-stub and LLM issues; blockers always win the decision.

        Args:
            candidate: Candidate under review.
            constraints: Production constraints for both reviewers.
            review_context: Context pack fields for the LLM reviewer.

        Returns:
            SemanticReviewResult with combined issues and final decision.
        """
        stub_result = self.stub.review(candidate, constraints)
        llm_result = self.llm.review(
            candidate, constraints, review_context=review_context
        )
        issues = list(stub_result.issues) + list(llm_result.issues)
        if any(i.severity is Severity.BLOCKER for i in issues):
            decision = Decision.BLOCK
        elif any(i.severity is Severity.WARN for i in issues):
            decision = Decision.REVISE
        elif llm_result.decision is Decision.BLOCK:
            decision = Decision.BLOCK
        elif llm_result.decision is Decision.REVISE:
            decision = Decision.REVISE
        else:
            decision = Decision.PASS
        return SemanticReviewResult(decision=decision, issues=issues)
