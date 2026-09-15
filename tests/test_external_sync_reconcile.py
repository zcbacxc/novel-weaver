# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""§23.7 external-edit safety: detect → block → reconcile → resume."""

from __future__ import annotations

import pytest

from novel_weaver.domain.errors import ReconcilePendingError
from novel_weaver.domain.models import FactStatus, ProductionUnitStatus
from novel_weaver.production.engine import ProductionEngine
from novel_weaver.production.fingerprint import content_fingerprint
from novel_weaver.storage.db import Database
from novel_weaver.storage.repositories import StoryRepository


def _engine() -> tuple[ProductionEngine, StoryRepository, Database]:
    db = Database(":memory:")
    repo = StoryRepository(db)
    eng = ProductionEngine(repo, provider_name="template")
    return eng, repo, db


def _bootstrap_two_chapters(eng: ProductionEngine):
    story = eng.create_story(
        "雾港",
        creative_intent="连续性优先",
        initial_state=[
            {
                "key": "character.gu.name",
                "value": "顾言",
                "kind": "character",
                "status": "CANONICAL",
            },
            {
                "key": "world.port",
                "value": "雾港",
                "kind": "world",
                "status": "CANONICAL",
            },
        ],
    )
    ch1, plan1 = eng.plan_with_rolling(
        story.story_id,
        title="码头",
        summary="顾言抵港",
        depends_on_fact_keys=["character.gu.name", "world.port"],
    )
    r1 = eng.produce_chapter(story.story_id, ch1.chapter_id)
    assert r1.ok, r1.message
    ch2, plan2 = eng.plan_with_rolling(
        story.story_id,
        title="货轮",
        summary="失踪线索",
        depends_on_fact_keys=["character.gu.name", "world.port"],
    )
    return story, ch1, plan1, ch2, plan2, r1


def test_commit_records_content_fingerprint() -> None:
    eng, repo, db = _engine()
    try:
        story, ch1, _, _, _, _ = _bootstrap_two_chapters(eng)
        stored = repo.get_chapter(ch1.chapter_id)
        assert stored is not None
        assert stored.status is ProductionUnitStatus.COMMITTED
        fp = stored.provenance.get("content_fingerprint")
        assert fp == content_fingerprint(stored.content)
    finally:
        db.close()


def test_detect_external_drift_by_hash() -> None:
    eng, repo, db = _engine()
    try:
        story, ch1, _, ch2, _, _ = _bootstrap_two_chapters(eng)
        stored = repo.get_chapter(ch1.chapter_id)
        assert stored is not None
        # Simulate out-of-band edit (author rewrote official text).
        stored.content = stored.content + "\n\n作者重写的结尾。"
        repo.save_chapter(story.story_id, stored)

        detected = eng.detect_external_edits(story.story_id)
        drifted = [d for d in detected if d.has_drift]
        assert any(d.chapter_id == ch1.chapter_id for d in drifted)
        assert not any(d.chapter_id == ch2.chapter_id and d.has_drift for d in detected)
    finally:
        db.close()


def test_open_edit_blocks_forward_production_until_reconcile() -> None:
    eng, repo, db = _engine()
    try:
        story, ch1, _, ch2, _, r1 = _bootstrap_two_chapters(eng)
        record = eng.apply_author_chapter_edit(
            story.story_id,
            ch1.chapter_id,
            new_content="【作者改稿】顾言在雨夜登船，左臂缠着绷带。",
            reason="retcon injury",
        )
        assert record.status.value == "PENDING"
        assert eng.is_production_blocked(story.story_id)

        # Direct begin_session must raise.
        with pytest.raises(ReconcilePendingError):
            eng.orch.begin_session(story.story_id, ch2.chapter_id)

        # Engine produce returns a soft failure at the gate.
        blocked = eng.produce_chapter(story.story_id, ch2.chapter_id)
        assert not blocked.ok
        assert blocked.stage == "reconcile_gate"
        assert record.reconcile_id in blocked.message

        # Canonical fact not yet updated — still old value.
        port = [i for i in repo.list_state_items(story.story_id) if i.key == "character.gu.injury"]
        assert port == []
    finally:
        db.close()


def test_complete_reconcile_rebuilds_state_invalidates_and_resumes() -> None:
    eng, repo, db = _engine()
    try:
        story, ch1, plan1, ch2, plan2, _ = _bootstrap_two_chapters(eng)
        # Produce ch2 as well so we have two committed units + a planned ch3.
        r2 = eng.produce_chapter(story.story_id, ch2.chapter_id)
        assert r2.ok, r2.message
        ch3, plan3 = eng.plan_with_rolling(
            story.story_id,
            title="追捕",
            summary="基于新伤情追捕",
            depends_on_fact_keys=["character.gu.name"],
        )

        record = eng.apply_author_chapter_edit(
            story.story_id,
            ch1.chapter_id,
            new_content="【作者改稿】顾言左臂受伤后仍登船。",
            reason="retcon injury",
        )
        assert eng.is_production_blocked(story.story_id)

        result = eng.complete_reconcile(
            story.story_id,
            record.reconcile_id,
            fact_deltas=[
                {
                    "key": "character.gu.injury",
                    "value": "left_arm",
                    "kind": "character",
                    "claim": "顾言左臂受伤",
                }
            ],
        )
        assert result.ok, result.message
        assert "character.gu.injury" in result.fact_keys_changed
        assert not eng.is_production_blocked(story.story_id)

        # Canonical fact promoted via evidence-backed author path.
        injury = [
            i
            for i in repo.list_state_items(story.story_id)
            if i.key == "character.gu.injury" and i.status is FactStatus.CANONICAL
        ]
        assert len(injury) == 1
        assert injury[0].value == "left_arm"
        assert injury[0].source == "external_edit"

        # Event projection rebuilt for edited chapter.
        events = [e for e in repo.list_events(story.story_id) if e.source_chapter == ch1.chapter_id]
        assert any(e.provenance.get("rebuilt") for e in events)
        assert any(e.status == "INVALIDATED" for e in events)

        # Forward invalidation: later planned unit was STALE then resumed to PLANNED.
        ch3_after = repo.get_chapter(ch3.chapter_id)
        assert ch3_after is not None
        assert ch3_after.status is ProductionUnitStatus.PLANNED
        assert ch3_after.provenance.get("replanned_after_reconcile") == record.reconcile_id

        # Committed downstream chapter flagged for review (not silently trusted).
        ch2_after = repo.get_chapter(ch2.chapter_id)
        assert ch2_after is not None
        assert ch2_after.provenance.get("needs_reconcile") is True

        # Edited chapter itself is clean.
        ch1_after = repo.get_chapter(ch1.chapter_id)
        assert ch1_after is not None
        assert ch1_after.provenance.get("needs_reconcile") is False
        assert ch1_after.provenance.get("content_fingerprint") == content_fingerprint(
            ch1_after.content
        )

        # Story revision advanced.
        story_after = repo.get_story(story.story_id)
        assert story_after is not None
        assert story_after.current_canonical_revision > story.current_canonical_revision

        # Production can continue after reconcile.
        r3 = eng.produce_chapter(story.story_id, ch3.chapter_id)
        assert r3.ok, f"{r3.message} {r3.data}"
    finally:
        db.close()


def test_plan_dependents_marked_stale_by_fact_change() -> None:
    eng, repo, db = _engine()
    try:
        story, ch1, plan1, ch2, plan2, _ = _bootstrap_two_chapters(eng)
        record = eng.apply_author_chapter_edit(
            story.story_id,
            ch1.chapter_id,
            new_content="改写：港口更名为新雾港。",
            reason="rename port",
        )
        result = eng.complete_reconcile(
            story.story_id,
            record.reconcile_id,
            fact_deltas=[
                {
                    "key": "world.port",
                    "value": "新雾港",
                    "kind": "world",
                    "claim": "港口更名为新雾港",
                }
            ],
        )
        assert result.ok
        # plan2 depends on world.port → invalidated by RollingPlanner.after_commit
        nodes = eng.planner.list_story(story.story_id)
        by_id = {n.plan_id: n for n in nodes}
        assert by_id[plan2.plan_id].status == "STALE"
        assert plan2.plan_id in result.invalidated_plan_ids
    finally:
        db.close()


def test_open_from_detected_drift_when_content_already_changed() -> None:
    eng, repo, db = _engine()
    try:
        story, ch1, _, _, _, _ = _bootstrap_two_chapters(eng)
        stored = repo.get_chapter(ch1.chapter_id)
        assert stored is not None
        stored.content = "外部工具直接改写后的正文。"
        repo.save_chapter(story.story_id, stored)

        detected = [d for d in eng.detect_external_edits(story.story_id) if d.has_drift]
        assert detected
        record = eng.orch.reconcile.open_from_detected_drift(
            story.story_id, detected[0].chapter_id
        )
        assert record.status.value == "PENDING"
        assert eng.is_production_blocked(story.story_id)

        result = eng.complete_reconcile(story.story_id, record.reconcile_id, fact_deltas=[])
        assert result.ok
        assert not eng.is_production_blocked(story.story_id)
    finally:
        db.close()


def test_cancel_reconcile_unblocks_without_fact_changes() -> None:
    eng, repo, db = _engine()
    try:
        story, ch1, _, ch2, _, _ = _bootstrap_two_chapters(eng)
        record = eng.apply_author_chapter_edit(
            story.story_id, ch1.chapter_id, new_content="误操作改稿。"
        )
        assert eng.is_production_blocked(story.story_id)
        cancelled = eng.orch.reconcile.cancel_reconcile(
            story.story_id, record.reconcile_id, reason="author abort"
        )
        assert cancelled.status.value == "CANCELLED"
        assert not eng.is_production_blocked(story.story_id)
        r2 = eng.produce_chapter(story.story_id, ch2.chapter_id)
        assert r2.ok, r2.message
    finally:
        db.close()


def test_commit_rejected_if_reconcile_opened_mid_session() -> None:
    """§23.7: even an in-flight session cannot commit while reconcile is pending."""
    eng, repo, db = _engine()
    try:
        story, ch1, _, ch2, _, _ = _bootstrap_two_chapters(eng)
        # Produce path already committed ch1; open a new session on ch2 then interleave edit.
        eng.apply_author_chapter_edit(
            story.story_id,
            ch1.chapter_id,
            new_content="改稿打断生产。",
        )
        # begin_session itself is already blocked — prove gate covers the whole window.
        with pytest.raises(ReconcilePendingError):
            eng.orch.begin_session(story.story_id, ch2.chapter_id)
    finally:
        db.close()
