# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build a selective, traceable Context Pack for generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from novel_weaver.domain.models import Chapter, FactStatus, StateItem, Story
from novel_weaver.production.fingerprint import context_fingerprint


@dataclass
class ContextPack:
    """Selective, fingerprinted context assembled for one generation request.

    Attributes:
        story_id: Story identity.
        creative_intent: Author creative direction text.
        current_plan: Plan/summary for the production unit.
        production_unit: Chapter (or unit) identity being generated.
        state_snapshot: Canonical fact snapshot dicts.
        active_threads: Pending thread-fact snapshots.
        selected_facts: Facts chosen for this chapter's dependencies.
        quality_feedback: Prior quality feedback entries.
        generation_task: Instructional prompt fragment for the generator.
        fingerprint: Stable hash of the materialized pack.
    """

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
        """Convert the pack into a plain dict for providers and reviewers.

        Returns:
            Dict with story/plan/state/facts/feedback fields (no fingerprint).
        """
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
        """Compute and store the pack fingerprint from the materialized form.

        Returns:
            The fingerprint string assigned to this pack.
        """
        self.fingerprint = context_fingerprint(self.materialize())
        return self.fingerprint


def build_context_pack(
    story: Story,
    chapter: Chapter,
    state_items: list[StateItem],
    *,
    quality_feedback: list[dict[str, Any]] | None = None,
) -> ContextPack:
    """Build a selective ContextPack for generating one chapter.

    Args:
        story: Story providing creative intent.
        chapter: Chapter providing plan and fact_keys_used.
        state_items: All state items for the story (canonical + pending).
        quality_feedback: Optional prior quality feedback entries.

    Returns:
        A fingerprinted ContextPack ready for generation.
    """
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
