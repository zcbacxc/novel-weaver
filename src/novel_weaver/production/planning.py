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
    """Planning horizon: longer horizons stay soft, shorter stay precise."""

    BOOK = "BOOK"
    ARC = "ARC"
    CHAPTER = "CHAPTER"
    SCENE = "SCENE"


class Certainty(str, Enum):
    """Certainty level attached to a plan node."""

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
    """One rolling plan unit (book/arc/chapter/scene) with certainty and deps.

    Attributes:
        plan_id: Stable plan identity.
        horizon: Planning horizon of this node.
        title: Short plan title.
        summary: Plan body / summary text.
        certainty: Current certainty derived from horizon and quality feedback.
        status: ACTIVE | SUPERSEDED | STALE | DONE.
        parent_id: Optional parent plan id.
        revision: Monotonic revision counter for this node.
        constraints: Constraint hints (often from quality feedback).
        depends_on_fact_keys: Fact keys this plan relies on.
        metadata: Free-form metadata (chapter number, quality notes, ...).
        created_at: Creation timestamp.
    """

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
        """Create a plan node with certainty derived from the horizon.

        Args:
            horizon: Planning horizon for the new node.
            title: Short plan title.
            summary: Plan body / summary text.
            parent_id: Optional parent plan id.
            depends_on_fact_keys: Fact keys this plan relies on.
            constraints: Initial constraint hints.

        Returns:
            A new PlanNode with a generated plan_id.
        """
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
        """Register a plan node under a story.

        Args:
            story_id: Story that owns the plan.
            node: Plan node to store.

        Returns:
            The same PlanNode (for chaining).
        """
        self._nodes[node.plan_id] = node
        self._by_story.setdefault(story_id, []).append(node.plan_id)
        return node

    def get(self, plan_id: str) -> PlanNode | None:
        """Look up a plan node by id.

        Args:
            plan_id: Plan identity.

        Returns:
            The PlanNode, or None when unknown.
        """
        return self._nodes.get(plan_id)

    def list_story(self, story_id: str) -> list[PlanNode]:
        """List all plan nodes known for a story.

        Args:
            story_id: Story identity.

        Returns:
            Plan nodes in registration order.
        """
        return [self._nodes[i] for i in self._by_story.get(story_id, []) if i in self._nodes]

    def active_by_horizon(self, story_id: str, horizon: Horizon) -> list[PlanNode]:
        """List ACTIVE plan nodes for a story at a given horizon.

        Args:
            story_id: Story identity.
            horizon: Horizon filter.

        Returns:
            Matching ACTIVE PlanNodes.
        """
        return [
            n for n in self.list_story(story_id)
            if n.horizon is horizon and n.status == "ACTIVE"
        ]

    def next_chapter_slot(self, story_id: str) -> int:
        """Next unused chapter number for a story.

        Args:
            story_id: Story identity.

        Returns:
            Max planned chapter number + 1, or 1 when none exist.
        """
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
        """Re-evaluate plans after a Canonical commit.

        Marks the committed plan DONE and STALE any plan depending on changed
        fact keys; book-horizon plans stay active.

        Args:
            story_id: Story whose plans should be re-evaluated.
            committed_plan_id: Plan id that was just committed, if any.
            changed_fact_keys: Fact keys changed by the commit or edit.
            reason: Audit/label reason stored on adjusted nodes.

        Returns:
            Plans that were marked DONE or STALE.
        """
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
        """Quality-driven planning adjustments.

        BLOCK/REVISE on near-horizon plans lowers certainty and attaches
        constraint hints; a clean PASS restores HIGH certainty after a dip.

        Args:
            story_id: Story whose latest chapter plan should adjust.
            decision: Quality decision string (PASS/REVISE/BLOCK).
            issue_actions: Recommended actions from quality issues.
            constraint_change: Structured constraint change payload.
            reason: Label stored on the adjusted plan metadata.

        Returns:
            Plan nodes that were adjusted (possibly empty).
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
        """Create and register the next chapter-horizon plan node.

        Args:
            story_id: Story being planned.
            title: Chapter plan title.
            summary: Chapter plan summary.
            parent_arc_id: Optional parent arc plan id.
            depends_on_fact_keys: Fact keys the chapter will rely on.

        Returns:
            The stored PlanNode with metadata["number"] set.
        """
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
