from novel_weaver.production.dependency import (
    DependencyGraph,
    DepNode,
    NodeKind,
    RepairLevel,
    escalate_repair,
)
from novel_weaver.production.planning import Horizon, PlanNode, RollingPlanner


def test_rolling_planner_certainty_and_next_slot() -> None:
    p = RollingPlanner()
    p.add("st", PlanNode.create(Horizon.BOOK, "整书方向", "低确定性"))
    p.add("st", PlanNode.create(Horizon.ARC, "第一卷", "中确定性"))
    ch = p.plan_next_chapter("st", "第1章", "高确定性计划", depends_on_fact_keys=["character.a"])
    assert ch.certainty.value == "HIGH"
    assert ch.metadata["number"] == 1
    ch2 = p.plan_next_chapter("st", "第2章", "x")
    assert ch2.metadata["number"] == 2

    marked = p.after_commit("st", committed_plan_id=ch.plan_id, changed_fact_keys={"character.a"})
    assert any(n.plan_id == ch.plan_id and n.status == "DONE" for n in marked)
    assert p.get(ch.plan_id).status == "DONE"
    # ch2 does not depend on character.a → stays ACTIVE
    assert p.get(ch2.plan_id).status == "ACTIVE"


def test_dependency_graph_impact() -> None:
    g = DependencyGraph()
    g.add_node(DepNode("fact.a", NodeKind.FACT))
    g.add_node(DepNode("event.1", NodeKind.EVENT))
    g.add_node(DepNode("plan.ch2", NodeKind.PLAN))
    g.add_node(DepNode("chapter.2", NodeKind.CHAPTER))
    g.add_node(DepNode("plan.ch3", NodeKind.PLAN))
    g.add_node(DepNode("chapter.3", NodeKind.CHAPTER))
    g.add_edge("fact.a", "event.1")
    g.add_edge("event.1", "plan.ch2")
    g.add_edge("plan.ch2", "chapter.2")
    g.add_edge("chapter.2", "plan.ch3")
    g.add_edge("plan.ch3", "chapter.3")
    scope = g.impact_scope(["fact.a"])
    assert "chapter.2" in scope
    assert "chapter.3" in scope
    assert "fact.a" not in scope


def test_repair_escalation() -> None:
    assert escalate_repair(RepairLevel.NONE, 0, 0) is RepairLevel.NONE
    assert escalate_repair(RepairLevel.NONE, 1, 0) is RepairLevel.SCENE
    assert escalate_repair(RepairLevel.SCENE, 1, 1) is RepairLevel.CHAPTER
    assert escalate_repair(RepairLevel.CHAPTER, 0, 3) is RepairLevel.BOOK
