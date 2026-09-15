# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Rolling planning: long-horizon low certainty, near-horizon high certainty."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class Horizon(str, Enum):
    BOOK = "BOOK"
    ARC = "ARC"
    CHAPTER = "CHAPTER"
    SCENE = "SCENE"


class Certainty(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


HORIZON_CERTAINTY = {
    Horizon.BOOK: Certainty.LOW,
    Horizon.ARC: Certainty.MEDIUM,
    Horizon.CHAPTER: Certainty.HIGH,
    Horizon.SCENE: Certainty.HIGH,
}


@dataclass
class PlanNode:
    plan_id: str
    horizon: Horizon
    title: str
    summary: str
    certainty: Certainty
    status: str = "ACTIVE"  # ACTIVE | SUPERSEDED | STALE | DONE
    parent_id: str | None = None
    revision: int = 0
    constraints: list[str] = field(default_factory=list)
    depends_on_fact_keys: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def create(
        cls,
        horizon: Horizon,
        title: str,
        summary: str = "",
        *,
        parent_id: str | None = None,
        depends_on_fact_keys: list[str] | None = None,
        constraints: list[str] | None = None,
    ) -> PlanNode:
        return cls(
            plan_id=f"plan_{uuid4().hex[:12]}",
            horizon=horizon,
            title=title,
            summary=summary,
            certainty=HORIZON_CERTAINTY[horizon],
            parent_id=parent_id,
            depends_on_fact_keys=list(depends_on_fact_keys or []),
            constraints=list(constraints or []),
        )


class RollingPlanner:
    """Keeps book/arc plans soft and chapter/scene plans precise."""

    def __init__(self) -> None:
        self._nodes: dict[str, PlanNode] = {}
        self._by_story: dict[str, list[str]] = {}

    def add(self, story_id: str, node: PlanNode) -> PlanNode:
        self._nodes[node.plan_id] = node
        self._by_story.setdefault(story_id, []).append(node.plan_id)
        return node

    def get(self, plan_id: str) -> PlanNode | None:
        return self._nodes.get(plan_id)

    def list_story(self, story_id: str) -> list[PlanNode]:
        return [self._nodes[i] for i in self._by_story.get(story_id, []) if i in self._nodes]

    def active_by_horizon(self, story_id: str, horizon: Horizon) -> list[PlanNode]:
        return [
            n for n in self.list_story(story_id)
            if n.horizon is horizon and n.status == "ACTIVE"
        ]

    def next_chapter_slot(self, story_id: str) -> int:
        chapters = [
            n for n in self.list_story(story_id) if n.horizon is Horizon.CHAPTER
        ]
        if not chapters:
            return 1
        return max(int(n.metadata.get("number", i + 1)) for i, n in enumerate(chapters)) + 1

    def after_commit(
        self,
        story_id: str,
        *,
        committed_plan_id: str | None,
        changed_fact_keys: set[str] | None = None,
        reason: str = "canonical commit",
    ) -> list[PlanNode]:
        """Re-evaluate plans after a Canonical commit (§8.2)."""
        changed = changed_fact_keys or set()
        marked: list[PlanNode] = []
        for node in self.list_story(story_id):
            if node.plan_id == committed_plan_id:
                node.status = "DONE"
                node.revision += 1
                marked.append(node)
                continue
            if node.horizon is Horizon.BOOK:
                # Soft: keep active unless explicitly abandoned
                continue
            if changed and (set(node.depends_on_fact_keys) & changed):
                node.status = "STALE"
                node.revision += 1
                marked.append(node)
        return marked

    def after_quality_feedback(
        self,
        story_id: str,
        *,
        decision: str,
        issue_actions: list[str] | None = None,
        constraint_change: dict[str, Any] | None = None,
        reason: str = "quality feedback",
    ) -> list[PlanNode]:
        """Quality-driven planning adjustments (§3.7 / Phase 4).

        - BLOCK/REVISE on near-horizon plans: lower certainty, add constraint hints.
        - Attach recommended actions to the newest ACTIVE chapter plan.
        """
        adjusted: list[PlanNode] = []
        actions = list(issue_actions or [])
        chapter_plans = [
            n
            for n in self.list_story(story_id)
            if n.horizon is Horizon.CHAPTER and n.status == "ACTIVE"
        ]
        if not chapter_plans:
            return adjusted
        # Prefer the latest chapter plan (next to produce / just planned).
        target = max(chapter_plans, key=lambda n: int(n.metadata.get("number", 0)))
        if decision in ("BLOCK", "REVISE"):
            if target.certainty is Certainty.HIGH:
                target.certainty = Certainty.MEDIUM
            target.revision += 1
            for action in actions[:5]:
                if action and action not in target.constraints:
                    target.constraints.append(action)
            if constraint_change:
                target.metadata["last_constraint_change"] = constraint_change
            target.metadata["last_quality_decision"] = decision
            target.metadata["last_quality_reason"] = reason
            adjusted.append(target)
        elif decision == "PASS" and target.certainty is Certainty.MEDIUM:
            # Recover certainty after a clean pass.
            target.certainty = Certainty.HIGH
            target.revision += 1
            target.metadata["last_quality_decision"] = decision
            adjusted.append(target)
        return adjusted

    def plan_next_chapter(
        self,
        story_id: str,
        title: str,
        summary: str,
        *,
        parent_arc_id: str | None = None,
        depends_on_fact_keys: list[str] | None = None,
    ) -> PlanNode:
        number = self.next_chapter_slot(story_id)
        node = PlanNode.create(
            Horizon.CHAPTER,
            title=title,
            summary=summary,
            parent_id=parent_arc_id,
            depends_on_fact_keys=depends_on_fact_keys,
        )
        node.metadata["number"] = number
        return self.add(story_id, node)
