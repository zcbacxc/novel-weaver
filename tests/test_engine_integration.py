from pathlib import Path

import pytest

from novel_weaver.domain.models import ProductionUnitStatus
from novel_weaver.production.engine import ProductionEngine
from novel_weaver.runtime.resume import ResumeAction
from novel_weaver.storage.db import Database
from novel_weaver.storage.repositories import StoryRepository


@pytest.fixture()
def engine(tmp_path: Path):
    db = Database(tmp_path / "e.sqlite3")
    eng = ProductionEngine(StoryRepository(db), provider_name="fake")
    yield eng
    db.close()


def test_engine_full_produce_chapter(engine: ProductionEngine) -> None:
    story = engine.create_story(
        "引擎故事",
        creative_intent="测试引擎",
        initial_state=[
            {"key": "character.hero", "value": "顾言", "kind": "character", "status": "CANONICAL"},
        ],
    )
    chapter, plan = engine.plan_with_rolling(
        story.story_id,
        title="开篇",
        summary="抵达雾港",
        depends_on_fact_keys=["character.hero"],
    )
    result = engine.produce_chapter(story.story_id, chapter.chapter_id)
    assert result.ok, result.message
    ch = engine.repo.get_chapter(chapter.chapter_id)
    assert ch is not None and ch.status is ProductionUnitStatus.COMMITTED
    assert result.data["cost"]["calls"] == 1
    action = engine.resume_decision(result.data["run_id"])
    assert action in (ResumeAction.RESUME, ResumeAction.REPLAN)


def test_engine_quality_block_with_empty_content(engine: ProductionEngine) -> None:
    # Force empty generation via constraints that cannot pass + custom provider path
    from novel_weaver.ai.base import GenerationRequest, GenerationResult, Provider, TokenUsage
    from novel_weaver.production.quality import Decision, DeterministicChecker, decide
    from novel_weaver.production.fake_gen import GeneratedCandidate

    cand = GeneratedCandidate(
        candidate_id="c1",
        chapter_id="ch1",
        content="",
        session_id="s",
        base_story_revision=0,
        plan_revision=0,
        context_fingerprint="fp",
    )
    qd = decide(cand, {"min_words": 5})
    assert qd.decision is Decision.BLOCK
    assert qd.manifest.ordering
    assert qd.feedback_for_next_run.recommended_action


def test_engine_template_provider_produces(engine: ProductionEngine) -> None:
    eng = ProductionEngine(engine.repo, provider_name="template")
    story = eng.create_story(
        "模板故事",
        creative_intent="清晰叙述",
        initial_state=[{"key": "world.city", "value": "雾港", "kind": "world"}],
    )
    chapter, _ = eng.plan_with_rolling(story.story_id, title="潮汐", summary="港口黎明")
    result = eng.produce_chapter(story.story_id, chapter.chapter_id)
    assert result.ok, result.message
    ch = eng.repo.get_chapter(chapter.chapter_id)
    assert ch is not None and len(ch.content) > 50
    assert "Canonical" in ch.content or "canonical" in ch.content or "港口" in ch.content or "雾港" in ch.content


def test_engine_impact_via_dependency_graph(engine: ProductionEngine) -> None:
    story = engine.create_story(
        "依赖故事",
        initial_state=[{"key": "character.injury", "value": "right", "kind": "character"}],
    )
    ch_a, _ = engine.plan_with_rolling(
        story.story_id, title="依赖章", summary="a", depends_on_fact_keys=["character.injury"]
    )
    ch_b, _ = engine.plan_with_rolling(
        story.story_id, title="无关章", summary="b", depends_on_fact_keys=["world.other"]
    )
    report = engine.impact_after_author_edit(story.story_id, "character.injury", "left")
    assert ch_a.chapter_id in report["stale_chapters"]
    stale = engine.repo.get_chapter(ch_a.chapter_id)
    valid = engine.repo.get_chapter(ch_b.chapter_id)
    assert stale is not None and stale.status is ProductionUnitStatus.STALE
    assert valid is not None and valid.status is ProductionUnitStatus.PLANNED
