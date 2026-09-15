"""Build a selective, traceable Context Pack for generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from novel_weaver.domain.models import Chapter, FactStatus, StateItem, Story
from novel_weaver.production.fingerprint import context_fingerprint


@dataclass
class ContextPack:
    story_id: str
    creative_intent: str
    current_plan: str
    production_unit: str
    state_snapshot: list[dict[str, Any]] = field(default_factory=list)
    active_threads: list[dict[str, Any]] = field(default_factory=list)
    selected_facts: list[dict[str, Any]] = field(default_factory=list)
    quality_feedback: list[dict[str, Any]] = field(default_factory=list)
    generation_task: str = ""
    fingerprint: str = ""

    def materialize(self) -> dict[str, Any]:
        return {
            "story_id": self.story_id,
            "creative_intent": self.creative_intent,
            "current_plan": self.current_plan,
            "production_unit": self.production_unit,
            "state_snapshot": self.state_snapshot,
            "active_threads": self.active_threads,
            "selected_facts": self.selected_facts,
            "quality_feedback": self.quality_feedback,
            "generation_task": self.generation_task,
        }

    def finalize_fingerprint(self) -> str:
        self.fingerprint = context_fingerprint(self.materialize())
        return self.fingerprint


def build_context_pack(
    story: Story,
    chapter: Chapter,
    state_items: list[StateItem],
    *,
    quality_feedback: list[dict[str, Any]] | None = None,
) -> ContextPack:
    canonical = [i for i in state_items if i.status == FactStatus.CANONICAL]
    pending = [i for i in state_items if i.status in (FactStatus.PENDING, FactStatus.PROPOSED)]

    used_keys = set(chapter.fact_keys_used)
    selected = [i for i in canonical if i.key in used_keys or not used_keys]

    pack = ContextPack(
        story_id=story.story_id,
        creative_intent=story.creative_intent,
        current_plan=chapter.plan,
        production_unit=chapter.chapter_id,
        state_snapshot=[
            {
                "key": i.key,
                "value": i.value,
                "kind": i.kind,
                "status": i.status.value,
                "revision": i.revision,
            }
            for i in canonical
        ],
        active_threads=[
            {
                "key": i.key,
                "value": i.value,
                "status": i.status.value,
            }
            for i in pending
            if i.kind == "thread"
        ],
        selected_facts=[
            {
                "key": i.key,
                "value": i.value,
                "kind": i.kind,
                "source": i.source,
            }
            for i in selected
        ],
        quality_feedback=list(quality_feedback or []),
        generation_task=f"Write chapter {chapter.number}: {chapter.title}. Plan: {chapter.plan}",
    )
    pack.finalize_fingerprint()
    return pack
