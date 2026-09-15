# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Full-book consistency pass tests."""

from __future__ import annotations

import json

from novel_weaver.ai.base import (
    GenerationRequest,
    GenerationResult,
    Provider,
    TokenUsage,
)
from novel_weaver.domain.models import FactStatus, ProductionUnitStatus
from novel_weaver.production.book_pass import BookConsistencyPass
from novel_weaver.production.engine import ProductionEngine
from novel_weaver.production.fingerprint import content_fingerprint
from novel_weaver.production.quality import Decision, Severity
from novel_weaver.storage.db import Database
from novel_weaver.storage.repositories import StoryRepository


class _BookLLM(Provider):
    name = "book-llm"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        return GenerationResult(
            text=self.reply,
            model="book-1",
            provider=self.name,
            usage=TokenUsage.of(5, 5),
            latency_ms=0.1,
            task=request.task,
        )


def _engine() -> tuple[ProductionEngine, StoryRepository, Database]:
    db = Database(":memory:")
    repo = StoryRepository(db)
    eng = ProductionEngine(repo, provider_name="template")
    return eng, repo, db


def _produce_n(eng: ProductionEngine, n: int = 3):
    story = eng.create_story(
        "书检",
        creative_intent="连续",
        initial_state=[
            {"key": "character.hero.name", "value": "顾言", "kind": "character", "status": "CANONICAL"},
            {"key": "world.port", "value": "雾港", "kind": "world", "status": "CANONICAL"},
            {"key": "thread.missing_cargo", "value": "OPEN", "kind": "thread", "status": "PENDING"},
        ],
    )
    for i in range(1, n + 1):
        ch, _ = eng.plan_with_rolling(
            story.story_id,
            number=i,
            title=f"第{i}章",
            summary=f"推进 {i}",
            depends_on_fact_keys=["character.hero.name", "world.port", "thread.missing_cargo"],
        )
        r = eng.produce_chapter(story.story_id, ch.chapter_id)
        assert r.ok, r.message
    return story


def test_book_pass_clean_template_story() -> None:
    eng, repo, db = _engine()
    try:
        story = _produce_n(eng, 3)
        report = BookConsistencyPass(repo).run(story.story_id)
        assert report.committed_chapters == 3
        assert report.blocker_count == 0
        assert report.decision in (Decision.PASS, Decision.REVISE)
        # thread touched by chapters → no "never appears" WARN
        assert not any("never appears" in i.evidence for i in report.issues)
    finally:
        db.close()


def test_book_pass_flags_empty_and_drift() -> None:
    eng, repo, db = _engine()
    try:
        story = _produce_n(eng, 2)
        chapters = repo.list_chapters(story.story_id)
        # Drift chapter 1 content without updating fingerprint.
        ch1 = chapters[0]
        ch1.content = ch1.content + "\n\n被外部改写。"
        repo.save_chapter(story.story_id, ch1)
        # Empty a committed chapter's content but keep status.
        ch2 = chapters[1]
        ch2.content = "   "
        repo.save_chapter(story.story_id, ch2)

        report = BookConsistencyPass(repo).run(story.story_id)
        assert report.decision is Decision.BLOCK
        evidences = " | ".join(i.evidence for i in report.issues)
        assert "hash drift" in evidences
        assert "empty content" in evidences
    finally:
        db.close()


def test_book_pass_flags_abandoned_thread_and_needs_reconcile() -> None:
    eng, repo, db = _engine()
    try:
        story = _produce_n(eng, 2)
        # Remove thread from state so it looks abandoned without history touch...
        # Instead mark a committed chapter needs_reconcile.
        ch = repo.list_chapters(story.story_id)[0]
        ch.provenance = {**ch.provenance, "needs_reconcile": True, "stale_reason": "manual"}
        repo.save_chapter(story.story_id, ch)

        # Thread that no chapter depends on.
        from novel_weaver.domain.models import StateItem

        orphan = StateItem.create(
            "thread.orphan", "OPEN", "thread", status=FactStatus.PENDING
        )
        repo.upsert_state_item(story.story_id, orphan)

        report = BookConsistencyPass(repo).run(story.story_id)
        assert report.decision is Decision.REVISE
        assert any("needs_reconcile" in i.evidence for i in report.issues)
        assert any("never appears" in i.evidence for i in report.issues)
    finally:
        db.close()


def test_book_pass_llm_issues_merged() -> None:
    eng, repo, db = _engine()
    try:
        story = _produce_n(eng, 2)
        reply = json.dumps(
            {
                "decision": "REVISE",
                "issues": [
                    {
                        "severity": "WARN",
                        "evidence": "第1章与第2章对港口时间描述不一致",
                        "suggested_action": "统一时间线表述",
                        "affected_scope": "book",
                    }
                ],
            },
            ensure_ascii=False,
        )
        llm = _BookLLM(reply)
        report = BookConsistencyPass(repo, llm_provider=llm).run(story.story_id)
        assert report.used_llm is True
        assert any("时间" in i.evidence for i in report.issues)
        assert llm.calls and llm.calls[0].task == "continuity_review"
    finally:
        db.close()


def test_book_pass_llm_failure_falls_back() -> None:
    class Boom(Provider):
        name = "boom"

        def generate(self, request: GenerationRequest) -> GenerationResult:
            from novel_weaver.ai.base import ProviderError

            raise ProviderError("down", retryable=False)

    eng, repo, db = _engine()
    try:
        story = _produce_n(eng, 1)
        report = BookConsistencyPass(repo, llm_provider=Boom()).run(story.story_id)
        assert report.used_llm is False
        assert "down" in report.llm_error
        assert report.committed_chapters == 1
    finally:
        db.close()
