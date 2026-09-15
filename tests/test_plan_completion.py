# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for remaining plan gaps: timeline, dispute, files, artifacts, releases, memory, quality plan."""

from __future__ import annotations

from pathlib import Path

from novel_weaver.domain.models import FactStatus
from novel_weaver.production.engine import ProductionEngine
from novel_weaver.production.memory import MemoryIndex
from novel_weaver.production.planning import Certainty, Horizon, PlanNode, RollingPlanner
from novel_weaver.production.timeline import TimelineService
from novel_weaver.storage.artifacts import ArtifactStore
from novel_weaver.storage.canonical_files import CanonicalFileStore
from novel_weaver.storage.db import Database
from novel_weaver.storage.releases import ReleaseRegistry
from novel_weaver.storage.repositories import StoryRepository
from novel_weaver.truth.dispute import DisputeOutcome, DisputeService


def _produce(eng: ProductionEngine, n: int = 2):
    story = eng.create_story(
        "雾港",
        creative_intent="连续",
        initial_state=[
            {"key": "character.hero.name", "value": "顾言", "kind": "character", "status": "CANONICAL"},
            {"key": "world.port", "value": "雾港", "kind": "world", "status": "CANONICAL"},
        ],
    )
    for i in range(1, n + 1):
        ch, _ = eng.plan_with_rolling(
            story.story_id,
            number=i,
            title=f"第{i}章",
            summary=f"推进{i}",
            depends_on_fact_keys=["character.hero.name", "world.port"],
        )
        r = eng.produce_chapter(story.story_id, ch.chapter_id)
        assert r.ok, r.message
    return story


def test_timeline_position_and_events() -> None:
    db = Database(":memory:")
    try:
        repo = StoryRepository(db)
        eng = ProductionEngine(repo, provider_name="template")
        story = _produce(eng, 3)
        tl = TimelineService(repo)
        pos = tl.narrative_position(story.story_id)
        assert pos is not None and pos.chapter_number == 3
        events = tl.ordered_events(story.story_id)
        assert len(events) >= 3
        assert tl.check_ordering_violations(story.story_id) == []
        snap = tl.snapshot(story.story_id)
        assert snap.position is not None
        assert snap.stats["events"] >= 3
    finally:
        db.close()


def test_dispute_keep_and_supersede() -> None:
    db = Database(":memory:")
    try:
        repo = StoryRepository(db)
        eng = ProductionEngine(repo, provider_name="template")
        story = eng.create_story(
            "d",
            initial_state=[
                {"key": "world.port", "value": "雾港", "kind": "world", "status": "CANONICAL"},
            ],
        )
        # Force a second canonical-like value via author edit then mark both disputed path.
        eng.orch.author_set_fact(story.story_id, "world.port", "新雾港", reason="conflict")
        items = [
            i
            for i in repo.find_state_by_key(story.story_id, "world.port")
            if i.status is FactStatus.CANONICAL
        ]
        assert len(items) == 1
        svc = DisputeService(repo)
        # Create a synthetic second disputed candidate by marking and adding via author path.
        # Mark current disputed, then author_set another value.
        svc.mark_key_disputed(story.story_id, "world.port", reason="double claim")
        eng.orch.author_set_fact(story.story_id, "world.port", "旧雾港", reason="restore")
        disputed_or_canon = [
            i
            for i in repo.find_state_by_key(story.story_id, "world.port")
            if i.status in (FactStatus.DISPUTED, FactStatus.CANONICAL)
        ]
        assert disputed_or_canon
        result = svc.resolve(
            story.story_id,
            "world.port",
            outcome=DisputeOutcome.KEEP,
            keep_item_id=disputed_or_canon[-1].item_id,
            reason="author pick",
        )
        assert result.ok
        live = [
            i
            for i in repo.find_state_by_key(story.story_id, "world.port")
            if i.status is FactStatus.CANONICAL
        ]
        assert len(live) == 1
    finally:
        db.close()


def test_canonical_files_and_artifacts(tmp_path: Path) -> None:
    db = Database(":memory:")
    try:
        repo = StoryRepository(db)
        store = ArtifactStore(tmp_path / "artifacts")
        eng = ProductionEngine(repo, provider_name="template", artifact_store=store)
        story = _produce(eng, 2)
        files = CanonicalFileStore(tmp_path / "canonical")
        written = files.export_story(repo, story.story_id)
        assert "story.json" in written
        assert files.list_exported_chapters(story.story_id)
        md = files.read_chapter_markdown(story.story_id, 1)
        assert md is not None and "第1章" in md

        arts = store.list(story.story_id)
        kinds = {a.kind for a in arts}
        assert "candidate" in kinds
        assert "review" in kinds
    finally:
        db.close()


def test_release_registry_immutable_append(tmp_path: Path) -> None:
    db = Database(":memory:")
    try:
        repo = StoryRepository(db)
        eng = ProductionEngine(repo, provider_name="template")
        story = _produce(eng, 1)
        reg = ReleaseRegistry(tmp_path / "releases")
        r1 = reg.create_release(repo, story.story_id, label="R1")
        eng.orch.author_set_fact(story.story_id, "world.port", "新港", reason="retcon")
        r2 = reg.create_release(repo, story.story_id, label="R2")
        assert r1.sequence == 1 and r2.sequence == 2
        assert r1.story_revision < r2.story_revision
        snaps = reg.load_release_snapshot(r2.release_id)
        assert snaps["story"]["story_id"] == story.story_id
        # first release snapshot still loadable
        s1 = reg.load_release_snapshot(r1.release_id)
        assert s1["story"]["current_canonical_revision"] == r1.story_revision
    finally:
        db.close()


def test_memory_index_rebuild_and_search() -> None:
    db = Database(":memory:")
    try:
        repo = StoryRepository(db)
        eng = ProductionEngine(repo, provider_name="template")
        story = _produce(eng, 2)
        idx = MemoryIndex()
        proj = idx.rebuild(repo, story.story_id)
        assert proj.doc_count >= 4
        hits = idx.search("顾言", k=5)
        assert hits
        # Rebuild is idempotent-ish
        proj2 = idx.rebuild(repo, story.story_id)
        assert proj2.fingerprint == proj.fingerprint
    finally:
        db.close()


def test_quality_feedback_adjusts_plan_certainty() -> None:
    planner = RollingPlanner()
    story_id = "s1"
    node = PlanNode.create(Horizon.CHAPTER, title="下一章", summary="s")
    node.metadata["number"] = 2
    planner.add(story_id, node)
    assert node.certainty is Certainty.HIGH
    adjusted = planner.after_quality_feedback(
        story_id,
        decision="REVISE",
        issue_actions=["统一时间线", "补环境"],
    )
    assert adjusted and adjusted[0].plan_id == node.plan_id
    assert node.certainty is Certainty.MEDIUM
    assert "统一时间线" in node.constraints
    # PASS recovers certainty
    planner.after_quality_feedback(story_id, decision="PASS")
    assert node.certainty is Certainty.HIGH
