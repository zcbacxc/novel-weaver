"""Deterministic fake generator for Phase 0 (no real LLM)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from novel_weaver.domain.models import CandidateStatus, Chapter
from novel_weaver.production.context import ContextPack


@dataclass
class GeneratedCandidate:
    candidate_id: str
    chapter_id: str
    content: str
    session_id: str
    base_story_revision: int
    plan_revision: int
    context_fingerprint: str
    status: CandidateStatus = CandidateStatus.DRAFT
    extracted_facts: list[dict[str, Any]] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)


class FakeGenerator:
    """Produces deterministic chapter text from the context pack."""

    def generate(
        self,
        chapter: Chapter,
        pack: ContextPack,
        *,
        session_id: str,
        base_story_revision: int,
        plan_revision: int,
    ) -> GeneratedCandidate:
        facts_lines = []
        for fact in pack.selected_facts:
            facts_lines.append(f"- {fact['key']}: {fact['value']}")
        if not facts_lines:
            facts_lines.append("- (no canonical facts selected)")

        body = (
            f"[FAKE GEN] Chapter {chapter.number}: {chapter.title}\n"
            f"Intent: {pack.creative_intent or 'n/a'}\n"
            f"Plan: {pack.current_plan}\n"
            f"Canonical facts in play:\n" + "\n".join(facts_lines) + "\n"
            f"Scene: The story continues under revision {base_story_revision}."
        )

        # Extract one trivial proposal from generation for evidence-backed path demos
        extracted = [
            {
                "claim": f"chapter_{chapter.number}_produced",
                "target_kind": "world",
                "target_key": f"chapter.{chapter.number}.produced",
                "value": True,
            }
        ]

        return GeneratedCandidate(
            candidate_id=f"cand_{uuid4().hex[:12]}",
            chapter_id=chapter.chapter_id,
            content=body,
            session_id=session_id,
            base_story_revision=base_story_revision,
            plan_revision=plan_revision,
            context_fingerprint=pack.fingerprint,
            extracted_facts=extracted,
        )

    def validate(self, candidate: GeneratedCandidate) -> dict[str, Any]:
        ok = bool(candidate.content.strip()) and candidate.context_fingerprint != ""
        result = {
            "passed": ok,
            "checks": {
                "non_empty": bool(candidate.content.strip()),
                "has_fingerprint": candidate.context_fingerprint != "",
            },
            "issues": [] if ok else ["empty content or missing fingerprint"],
        }
        candidate.validation = result
        if ok:
            candidate.status = CandidateStatus.VALIDATED
        return result

    def review(self, candidate: GeneratedCandidate) -> dict[str, Any]:
        result = {
            "decision": "PASS" if candidate.validation.get("passed") else "BLOCK",
            "score": 1.0 if candidate.validation.get("passed") else 0.0,
            "issues": candidate.validation.get("issues", []),
        }
        candidate.quality = result
        if result["decision"] == "PASS":
            candidate.status = CandidateStatus.REVIEWED
        return result
