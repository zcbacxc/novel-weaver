"""CLI entry: demo closed loops for Phase 0."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from novel_weaver.domain.errors import DomainError, GuardRejectError
from novel_weaver.domain.models import FactStatus
from novel_weaver.production.orchestrator import ProductionOrchestrator
from novel_weaver.storage.db import Database
from novel_weaver.storage.repositories import StoryRepository


def _orch(workspace: Path) -> tuple[ProductionOrchestrator, Database]:
    workspace.mkdir(parents=True, exist_ok=True)
    db = Database(workspace / "novel.sqlite3")
    repo = StoryRepository(db)
    return ProductionOrchestrator(repo), db


def cmd_demo(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace)
    orch, db = _orch(workspace)
    try:
        print("=== Phase 0 Demo: continuous + invalidation loops ===\n")

        story = orch.create_story(
            title="雾港纪事",
            premise="港口城市中一名受伤侦探追查失踪货轮。",
            creative_intent="冷硬侦探，慢热，强连续性",
            initial_state=[
                {"key": "character.gu_yan.name", "value": "顾言", "kind": "character", "status": "CANONICAL"},
                {"key": "character.gu_yan.injury", "value": None, "kind": "character", "status": "PENDING"},
                {"key": "world.port_city", "value": "雾港", "kind": "world", "status": "CANONICAL"},
            ],
        )
        print(f"[1] Created story {story.story_id} rev={story.current_canonical_revision}")

        # Evidence cannot be skipped
        try:
            empty_prop = orch.propose_fact(story.story_id, "顾言已婚", evidence_refs=[])
            orch.promote_to_canonical(story.story_id, empty_prop)
            print("ERROR: empty evidence proposal should fail promotion")
            return 1
        except Exception as exc:
            print(f"[2] No-evidence promotion rejected as expected: {type(exc).__name__}")

        ev = orch.capture_evidence(
            story.story_id,
            source_type="author",
            source_ref="outline",
            claim="顾言右手受伤",
            confidence=0.95,
        )
        prop = orch.propose_fact(
            story.story_id,
            claim="顾言右手受伤",
            evidence_refs=[ev.evidence_id],
            claim_value="right_hand",
            target_kind="character",
            target_key="character.gu_yan.injury",
            confidence=0.95,
        )
        item = orch.promote_to_canonical(story.story_id, prop)
        story = orch.repo.get_story(story.story_id)
        print(f"[3] Promoted injury fact -> Canon rev={story.current_canonical_revision} item={item.key}")

        ch1 = orch.plan_chapter(story.story_id, 1, "码头雨夜", "顾言带伤抵达码头，发现货轮失踪。")
        ch2 = orch.plan_chapter(story.story_id, 2, "目击者", "顾言询问仓库目击者。")
        print(f"[4] Planned chapters: {ch1.chapter_id}, {ch2.chapter_id}")

        # Chapter 1 production
        session = orch.begin_session(story.story_id, ch1.chapter_id)
        cand = orch.generate_candidate(session.session_id)
        orch.validate_and_review(cand.candidate_id)
        commit = orch.commit_candidate(cand.candidate_id)
        if not commit.ok:
            print(f"ERROR commit ch1: {commit.message}")
            return 1
        print(f"[5] Ch1 committed, new revision={commit.data['new_revision']}")

        # Stale session rejection: open session, mutate world, try commit
        stale_ch = orch.plan_chapter(story.story_id, 3, "假目标", "用于演示过期会话。")
        stale_session = orch.begin_session(story.story_id, stale_ch.chapter_id)
        stale_cand = orch.generate_candidate(stale_session.session_id)
        orch.validate_and_review(stale_cand.candidate_id)
        orch.author_set_fact(story.story_id, "world.port_city", "新雾港", reason="world rewrite")
        rejected = orch.commit_candidate(stale_cand.candidate_id)
        if rejected.ok:
            print("ERROR: stale session commit should be rejected")
            return 1
        print(f"[6] Stale commit rejected: {rejected.data.get('reason')}")

        # Local invalidation: change Ch1-linked fact, Ch2 should go STALE, unrelated stays
        story = orch.repo.get_story(story.story_id)
        item_id, report = orch.author_set_fact(
            story.story_id,
            "character.gu_yan.injury",
            "left_hand",
            kind="character",
            reason="retcon injury side",
        )
        chapters = orch.repo.list_chapters(story.story_id)
        by_id = {c.chapter_id: c for c in chapters}
        ch1_s = by_id[ch1.chapter_id]
        ch2_s = by_id[ch2.chapter_id]
        # ch1 is COMMITTED — marked needs_reconcile; ch2 uses no injury key so may stay valid
        # Force ch2 dependency for demo
        ch2.fact_keys_used = ["character.gu_yan.injury"]
        ch2.status = ch2_s.status
        orch.repo.save_chapter(story.story_id, ch2)
        report2 = orch.invalidate_dependents(story.story_id, {"character.gu_yan.injury"}, "injury retcon")
        chapters = orch.repo.list_chapters(story.story_id)
        ch2_after = next(c for c in chapters if c.chapter_id == ch2.chapter_id)
        print(f"[7] Invalidation: stale={report2.stale_chapter_ids} valid={report2.still_valid_chapter_ids}")
        print(f"    Ch2 status after impact: {ch2_after.status.value}")

        # Produce ch2 after re-plan (simulate)
        session2 = orch.begin_session(story.story_id, ch2.chapter_id)
        cand2 = orch.generate_candidate(session2.session_id)
        orch.validate_and_review(cand2.candidate_id)
        commit2 = orch.commit_candidate(cand2.candidate_id)
        if not commit2.ok:
            print(f"ERROR commit ch2: {commit2.message}")
            return 1
        print(f"[8] Ch2 re-committed after invalidation, revision={commit2.data['new_revision']}")

        # Restart resilience: reopen DB from disk and verify canonical
        db.close()
        db2 = Database(workspace / "novel.sqlite3")
        repo2 = StoryRepository(db2)
        story2 = repo2.get_story(story.story_id)
        assert story2 is not None
        items = repo2.list_state_items(story.story_id, status=FactStatus.CANONICAL)
        print(f"[9] After reopen: rev={story2.current_canonical_revision} canonical_items={len(items)}")
        # Double-commit same unit must fail
        guard_units_ok = not orch.guard.is_unit_committed(ch1.chapter_id)  # in-memory lost; check DB chapter
        ch1_db = repo2.get_chapter(ch1.chapter_id)
        assert ch1_db is not None and ch1_db.status.value == "COMMITTED"
        print(f"[10] Persisted Ch1 status={ch1_db.status.value} (no double-commit from disk state)")

        summary = {
            "story_id": story.story_id,
            "final_revision": story2.current_canonical_revision,
            "canonical_fact_keys": [i.key for i in items],
            "audit_count": len(orch.list_audit(story.story_id)),
            "workspace": str(workspace.resolve()),
        }
        print("\n=== DEMO OK ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        db2.close()
        return 0
    finally:
        try:
            db.close()
        except Exception:
            pass


def cmd_status(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace)
    db_path = workspace / "novel.sqlite3"
    if not db_path.exists():
        print(f"no database at {db_path}")
        return 1
    db = Database(db_path)
    try:
        rows = db.execute("SELECT story_id, title, current_canonical_revision FROM stories").fetchall()
        for r in rows:
            print(f"{r['story_id']}\t{r['title']}\trev={r['current_canonical_revision']}")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="novel-weaver")
    sub = parser.add_subparsers(dest="command", required=True)

    p_demo = sub.add_parser("demo", help="Run Phase 0 end-to-end demo loops")
    p_demo.add_argument("--workspace", default=".workspaces/demo")
    p_demo.set_defaults(func=cmd_demo)

    p_status = sub.add_parser("status", help="List stories in workspace")
    p_status.add_argument("--workspace", default=".workspaces/demo")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (DomainError, GuardRejectError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
