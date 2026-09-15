# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Failover / migration / snapshot / throughline tests (Phase 5 completion)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_weaver.ai.base import (
    GenerationRequest,
    GenerationResult,
    Provider,
    ProviderError,
    TokenUsage,
)
from novel_weaver.ai.failover import FailoverProvider
from novel_weaver.domain.models import ProductionUnitStatus
from novel_weaver.production.engine import ProductionEngine
from novel_weaver.production.threads import ThreadService
from novel_weaver.storage.db import SCHEMA_VERSION, Database
from novel_weaver.storage.repositories import StoryRepository
from novel_weaver.storage.snapshot import (
    export_story_snapshot,
    import_story_snapshot,
    read_snapshot,
    write_snapshot,
)


class _P(Provider):
    def __init__(self, name: str, *, fail_times: int = 0, retryable: bool = True, text: str = "ok") -> None:
        self.name = name
        self.fail_times = fail_times
        self.retryable = retryable
        self.text = text
        self.calls = 0

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ProviderError(f"{self.name} down", retryable=self.retryable)
        return GenerationResult(
            text=self.text,
            model=self.name,
            provider=self.name,
            usage=TokenUsage.of(1, 1),
            latency_ms=0.0,
        )


def _req() -> GenerationRequest:
    return GenerationRequest(task="chapter_generation", prompt="p", context={})


def test_failover_uses_second_on_retryable() -> None:
    a = _P("a", fail_times=1)
    b = _P("b", text="from-b")
    fo = FailoverProvider([a, b])
    result = fo.generate(_req())
    assert result.text == "from-b"
    assert result.raw["failover_served_by"] == "b"
    assert a.calls == 1 and b.calls == 1


def test_failover_uses_second_on_fatal() -> None:
    a = _P("a", fail_times=1, retryable=False)
    b = _P("b", text="from-b")
    fo = FailoverProvider([a, b])
    assert fo.generate(_req()).text == "from-b"


def test_failover_exhausted_raises() -> None:
    a = _P("a", fail_times=1)
    b = _P("b", fail_times=1)
    fo = FailoverProvider([a, b])
    with pytest.raises(ProviderError, match="exhausted"):
        fo.generate(_req())


def test_schema_version_fresh_db() -> None:
    db = Database(":memory:")
    try:
        assert db.schema_version() == SCHEMA_VERSION
        assert db.migrate() == []
        row = db.execute("SELECT COUNT(*) AS c FROM threads").fetchone()
        assert row["c"] == 0
    finally:
        db.close()


def test_migration_from_v1_without_threads() -> None:
    # Simulate legacy DB: create minimal schema without threads, stamp v1.
    import sqlite3

    path = Path(":memory:")
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE stories (
            story_id TEXT PRIMARY KEY, title TEXT NOT NULL,
            premise TEXT NOT NULL DEFAULT '', creative_intent TEXT NOT NULL DEFAULT '',
            constraints_json TEXT NOT NULL DEFAULT '{}',
            current_canonical_revision INTEGER NOT NULL DEFAULT 0,
            lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO schema_meta VALUES ('schema_version', '1');
        """
    )
    conn.commit()
    conn.close()

    # Fresh Database on a real temp file.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        dbfile = Path(td) / "legacy.sqlite3"
        c = sqlite3.connect(dbfile)
        c.executescript(
            """
            CREATE TABLE stories (
                story_id TEXT PRIMARY KEY, title TEXT NOT NULL,
                premise TEXT NOT NULL DEFAULT '', creative_intent TEXT NOT NULL DEFAULT '',
                constraints_json TEXT NOT NULL DEFAULT '{}',
                current_canonical_revision INTEGER NOT NULL DEFAULT 0,
                lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO schema_meta VALUES ('schema_version', '1');
            """
        )
        c.commit()
        c.close()

        db = Database(dbfile)
        try:
            # Opening runs full SCHEMA + migrate from v1 → v2
            assert db.schema_version() == SCHEMA_VERSION
            tables = {
                r["name"]
                for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "threads" in tables
            assert "reconcile_records" in tables
        finally:
            db.close()


def test_thread_service_touch_and_resolve() -> None:
    db = Database(":memory:")
    try:
        repo = StoryRepository(db)
        eng = ProductionEngine(repo, provider_name="template")
        story = eng.create_story(
            "t",
            initial_state=[
                {"key": "thread.missing_cargo", "value": "OPEN", "kind": "thread", "status": "PENDING"},
                {"key": "world.port", "value": "雾港", "kind": "world", "status": "CANONICAL"},
            ],
        )
        ch, _ = eng.plan_with_rolling(
            story.story_id, number=1, title="c1", summary="s",
            depends_on_fact_keys=["thread.missing_cargo", "world.port"],
        )
        r = eng.produce_chapter(story.story_id, ch.chapter_id)
        assert r.ok, r.message
        threads = repo.list_threads(story.story_id)
        assert any(t.name == "thread.missing_cargo" for t in threads)
        touched = next(t for t in threads if t.name == "thread.missing_cargo")
        assert touched.current_status in ("TOUCHED", "OPEN")
        assert touched.last_touched_at == "ch1"

        svc = ThreadService(repo)
        resolved = svc.resolve(story.story_id, "thread.missing_cargo", resolution_note="found")
        assert resolved is not None and resolved.current_status == "RESOLVED"
        summary = svc.summary(story.story_id)
        assert summary["by_status"].get("RESOLVED", 0) >= 1
    finally:
        db.close()


def test_snapshot_roundtrip(tmp_path: Path) -> None:
    db = Database(":memory:")
    try:
        repo = StoryRepository(db)
        eng = ProductionEngine(repo, provider_name="template")
        story = eng.create_story(
            "雾港",
            creative_intent="连续",
            initial_state=[
                {"key": "character.hero.name", "value": "顾言", "kind": "character", "status": "CANONICAL"},
                {"key": "world.port", "value": "雾港", "kind": "world", "status": "CANONICAL"},
            ],
        )
        for i in (1, 2):
            ch, _ = eng.plan_with_rolling(
                story.story_id, number=i, title=f"c{i}", summary="s",
                depends_on_fact_keys=["character.hero.name", "world.port"],
            )
            assert eng.produce_chapter(story.story_id, ch.chapter_id).ok

        payload = export_story_snapshot(repo, story.story_id)
        assert payload["meta"]["counts"]["chapters"] == 2
        path = write_snapshot(tmp_path / "snap.json", payload)
        reloaded = read_snapshot(path)
        assert reloaded["story"]["story_id"] == story.story_id

        db2 = Database(":memory:")
        try:
            sid = import_story_snapshot(db2, reloaded)
            assert sid == story.story_id
            repo2 = StoryRepository(db2)
            chapters = repo2.list_chapters(sid)
            assert len(chapters) == 2
            assert all(c.status is ProductionUnitStatus.COMMITTED for c in chapters)
            assert chapters[0].content == payload["chapters"][0]["content"]
            items = repo2.list_state_items(sid)
            keys = {i.key for i in items if i.status.value == "CANONICAL"}
            assert "character.hero.name" in keys
            story2 = repo2.get_story(sid)
            assert story2 is not None
            fresh = repo.get_story(story.story_id)
            assert fresh is not None
            assert story2.current_canonical_revision == fresh.current_canonical_revision
            assert story2.current_canonical_revision >= 1
        finally:
            db2.close()
    finally:
        db.close()


def test_engine_failover_name_chain() -> None:
    db = Database(":memory:")
    try:
        repo = StoryRepository(db)
        # template-only chain still constructs
        eng = ProductionEngine(repo, failover_names=["template"])
        assert isinstance(eng.provider, FailoverProvider)
        story = eng.create_story("x", initial_state=[])
        ch, _ = eng.plan_with_rolling(story.story_id, number=1, title="a", summary="b")
        r = eng.produce_chapter(story.story_id, ch.chapter_id)
        assert r.ok, r.message
        assert eng._effective_provider_name() in ("template", "failover")
    finally:
        db.close()
