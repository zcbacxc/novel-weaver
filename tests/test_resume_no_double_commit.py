"""End-to-end production loop tests including resume without double commit."""

from __future__ import annotations

from pathlib import Path

import pytest

from novel_weaver.domain.models import FactStatus, ProductionUnitStatus
from novel_weaver.production.orchestrator import ProductionOrchestrator
from novel_weaver.storage.db import Database
from novel_weaver.storage.repositories import StoryRepository


@pytest.fixture()
def orch(tmp_path: Path):
    db = Database(tmp_path / "t.sqlite3")
    repo = StoryRepository(db)
    o = ProductionOrchestrator(repo)
    yield o
    db.close()


def test_create_story_with_initial_state(orch: ProductionOrchestrator) -> None:
    story = orch.create_story(
        "T",
        initial_state=[
            {"key": "character.hero", "value": "顾言", "kind": "character", "status": "CANONICAL"},
            {"key": "character.secret", "value": None, "kind": "character", "status": "PENDING"},
        ],
    )
    assert story.current_canonical_revision >= 1
    items = orch.repo.list_state_items(story.story_id)
    assert any(i.status is FactStatus.PENDING for i in items)
    assert any(i.status is FactStatus.CANONICAL for i in items)


def test_no_evidence_proposal_not_promoted(orch: ProductionOrchestrator) -> None:
    from novel_weaver.truth.proposal import PromotionError

    story = orch.create_story("T")
    prop = orch.propose_fact(story.story_id, "claim", evidence_refs=[])
    with pytest.raises(PromotionError):
        orch.promote_to_canonical(story.story_id, prop)


def test_commit_updates_revision_and_state(orch: ProductionOrchestrator) -> None:
    story = orch.create_story(
        "T",
        creative_intent="test",
        initial_state=[{"key": "world.port", "value": "雾港", "kind": "world"}],
    )
    ch = orch.plan_chapter(story.story_id, 1, "开篇", "抵达港口")
    session = orch.begin_session(story.story_id, ch.chapter_id)
    cand = orch.generate_candidate(session.session_id)
    orch.validate_and_review(cand.candidate_id)
    result = orch.commit_candidate(cand.candidate_id)
    assert result.ok
    assert result.data["new_revision"] > story.current_canonical_revision
    chapter = orch.repo.get_chapter(ch.chapter_id)
    assert chapter is not None
    assert chapter.status is ProductionUnitStatus.COMMITTED
    assert chapter.content
    events = orch.repo.list_events(story.story_id)
    assert len(events) == 1
    produced = orch.repo.find_state_by_key(story.story_id, "chapter.1.produced")
    assert any(i.status is FactStatus.CANONICAL for i in produced)


def test_stale_session_commit_rejected(orch: ProductionOrchestrator) -> None:
    story = orch.create_story("T", initial_state=[{"key": "k", "value": 1, "kind": "world"}])
    ch = orch.plan_chapter(story.story_id, 1)
    session = orch.begin_session(story.story_id, ch.chapter_id)
    cand = orch.generate_candidate(session.session_id)
    orch.validate_and_review(cand.candidate_id)
    # World moves on
    orch.author_set_fact(story.story_id, "k", 2)
    result = orch.commit_candidate(cand.candidate_id)
    assert not result.ok
    assert "STORY_REVISION" in result.data.get("reason", "")
    # Canon unchanged by failed commit
    chapter = orch.repo.get_chapter(ch.chapter_id)
    assert chapter is not None
    assert chapter.status is not ProductionUnitStatus.COMMITTED


def test_author_edit_invalidates_dependent_only(orch: ProductionOrchestrator) -> None:
    story = orch.create_story(
        "T",
        initial_state=[{"key": "character.injury", "value": "right", "kind": "character"}],
    )
    ch_dep = orch.plan_chapter(story.story_id, 2, "依赖", "x")
    ch_dep.fact_keys_used = ["character.injury"]
    orch.repo.save_chapter(story.story_id, ch_dep)
    ch_free = orch.plan_chapter(story.story_id, 3, "无关", "y")
    ch_free.fact_keys_used = ["world.other"]
    orch.repo.save_chapter(story.story_id, ch_free)

    _, report = orch.author_set_fact(story.story_id, "character.injury", "left")
    assert ch_dep.chapter_id in report.stale_chapter_ids
    assert ch_free.chapter_id in report.still_valid_chapter_ids
    dep = orch.repo.get_chapter(ch_dep.chapter_id)
    free = orch.repo.get_chapter(ch_free.chapter_id)
    assert dep is not None and dep.status is ProductionUnitStatus.STALE
    assert free is not None and free.status is ProductionUnitStatus.PLANNED


def test_resume_no_double_commit(tmp_path: Path) -> None:
    path = tmp_path / "r.sqlite3"
    db = Database(path)
    orch = ProductionOrchestrator(StoryRepository(db))
    story = orch.create_story("T", initial_state=[{"key": "a", "value": 1, "kind": "world"}])
    ch = orch.plan_chapter(story.story_id, 1)
    session = orch.begin_session(story.story_id, ch.chapter_id)
    cand = orch.generate_candidate(session.session_id)
    orch.validate_and_review(cand.candidate_id)
    assert orch.commit_candidate(cand.candidate_id).ok
    rev_after = orch.repo.get_story(story.story_id).current_canonical_revision
    db.close()

    # Reopen: in-memory guard lost, but chapter already COMMITTED — new commit path must not double-write
    db2 = Database(path)
    repo2 = StoryRepository(db2)
    story2 = repo2.get_story(story.story_id)
    assert story2 is not None
    assert story2.current_canonical_revision == rev_after
    ch2 = repo2.get_chapter(ch.chapter_id)
    assert ch2 is not None and ch2.status is ProductionUnitStatus.COMMITTED
    # Attempting production on committed unit should fail at begin_session
    orch2 = ProductionOrchestrator(repo2)
    with pytest.raises(Exception):
        orch2.begin_session(story.story_id, ch.chapter_id)
    db2.close()


def test_promotion_path_updates_canonical(orch: ProductionOrchestrator) -> None:
    story = orch.create_story("T")
    ev = orch.capture_evidence(story.story_id, source_type="author", source_ref="o", claim="X", confidence=0.9)
    prop = orch.propose_fact(
        story.story_id,
        "X",
        [ev.evidence_id],
        claim_value=True,
        target_key="fact.x",
        target_kind="world",
    )
    item = orch.promote_to_canonical(story.story_id, prop)
    assert item.status is FactStatus.CANONICAL
    assert orch.repo.get_story(story.story_id).current_canonical_revision > story.current_canonical_revision
