# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Dependency graph for impact analysis and repair escalation."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class NodeKind(str, Enum):
    """Kind of node in the production dependency graph."""

    FACT = "FACT"
    EVENT = "EVENT"
    PLAN = "PLAN"
    CANDIDATE = "CANDIDATE"
    CHAPTER = "CHAPTER"
    THREAD = "THREAD"


@dataclass
class DepNode:
    """One dependency-graph node (fact/event/plan/candidate/chapter/thread).

    Attributes:
        node_id: Stable node identity.
        kind: NodeKind classification.
        label: Human-readable label.
        meta: Free-form metadata.
    """

    node_id: str
    kind: NodeKind
    label: str = ""
    meta: dict = field(default_factory=dict)


class DependencyGraph:
    """Directed graph of production dependencies for impact analysis.

    Edges point upstream → downstream: downstream depends on upstream.
    """
    def __init__(self) -> None:
        self._nodes: dict[str, DepNode] = {}
        self._edges: dict[str, set[str]] = defaultdict(set)  # from -> to (to depends on from)
        self._rev: dict[str, set[str]] = defaultdict(set)  # to -> froms

    def add_node(self, node: DepNode) -> None:
        """Insert or replace a node in the graph.

        Args:
            node: Node to store.

        Returns:
            None.
        """
        self._nodes[node.node_id] = node

    def add_edge(self, upstream: str, downstream: str) -> None:
        """Record that downstream depends on upstream.

        Args:
            upstream: Provider node id.
            downstream: Dependent node id.

        Returns:
            None.
        """
        self._edges[upstream].add(downstream)
        self._rev[downstream].add(upstream)

    def remove_node(self, node_id: str) -> None:
        """Remove a node and all of its edges.

        Args:
            node_id: Node to drop.

        Returns:
            None.
        """
        self._nodes.pop(node_id, None)
        for downs in list(self._edges.get(node_id, ())):
            self._rev[downs].discard(node_id)
        self._edges.pop(node_id, None)
        for ups in list(self._rev.get(node_id, ())):
            self._edges[ups].discard(node_id)
        self._rev.pop(node_id, None)

    def dependents(self, node_id: str) -> set[str]:
        """Transitive downstream dependents (excluding self).

        Args:
            node_id: Starting node id.

        Returns:
            Set of transitively dependent node ids.
        """
        seen: set[str] = set()
        q: deque[str] = deque(self._edges.get(node_id, ()))
        while q:
            cur = q.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            q.extend(self._edges.get(cur, ()))
        return seen

    def dependencies(self, node_id: str) -> set[str]:
        """Transitive upstream dependencies (excluding self).

        Args:
            node_id: Starting node id.

        Returns:
            Set of transitively upstream node ids.
        """
        seen: set[str] = set()
        q: deque[str] = deque(self._rev.get(node_id, ()))
        while q:
            cur = q.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            q.extend(self._rev.get(cur, ()))
        return seen

    def impact_scope(self, changed_ids: Iterable[str]) -> set[str]:
        """Union of dependents for each changed node id.

        Args:
            changed_ids: Node ids that changed.

        Returns:
            Set of downstream node ids in the impact scope.
        """
        scope: set[str] = set()
        for cid in changed_ids:
            scope |= self.dependents(cid)
        return scope

    def nodes_of_kind(self, kind: NodeKind, ids: Iterable[str] | None = None) -> list[DepNode]:
        """Filter graph nodes by kind, optionally restricted to given ids.

        Args:
            kind: NodeKind to select.
            ids: Optional id subset; None selects all nodes.

        Returns:
            Matching DepNode list.
        """
        pool = self._nodes.values() if ids is None else (self._nodes[i] for i in ids if i in self._nodes)
        return [n for n in pool if n.kind is kind]


class RepairLevel(str, Enum):
    """Repair escalation level from scene up to whole-book."""

    NONE = "NONE"
    SCENE = "SCENE"
    CHAPTER = "CHAPTER"
    ARC = "ARC"
    BOOK = "BOOK"


_ORDER = [
    RepairLevel.NONE,
    RepairLevel.SCENE,
    RepairLevel.CHAPTER,
    RepairLevel.ARC,
    RepairLevel.BOOK,
]


def escalate_repair(current: RepairLevel, issue_count: int, blocker_count: int) -> RepairLevel:
    """Escalate repair level only when issue/blocker counts require it.

    Args:
        current: Current repair level for the story.
        issue_count: Total quality issues in the latest decision.
        blocker_count: Blocker-severity issue count.

    Returns:
        The next RepairLevel (same as current when no escalation applies).
    """
    if blocker_count >= 3:
        return RepairLevel.BOOK
    if current is RepairLevel.NONE:
        if blocker_count > 0 or issue_count > 0:
            return RepairLevel.SCENE
        return RepairLevel.NONE
    if blocker_count >= 1:
        idx = _ORDER.index(current)
        return _ORDER[min(idx + 1, len(_ORDER) - 1)]
    if issue_count >= 5 and current is RepairLevel.SCENE:
        return RepairLevel.CHAPTER
    return current

