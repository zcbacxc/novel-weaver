# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI entry: Phase 0 loops + full engine demo."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from novel_weaver.domain.errors import DomainError, GuardRejectError
from novel_weaver.domain.models import FactStatus
from novel_weaver.production.engine import ProductionEngine
from novel_weaver.production.orchestrator import ProductionOrchestrator
from novel_weaver.storage.db import Database
from novel_weaver.storage.repositories import StoryRepository


def _open_db(workspace: Path) -> Database:
    workspace.mkdir(parents=True, exist_ok=True)
    return Database(workspace / "novel.sqlite3")


def cmd_demo(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace)
    db = _open_db(workspace)
    try:
        repo = StoryRepository(db)
        orch = ProductionOrchestrator(repo)
        print("=== Phase 0 Demo: truth boundary + commit guard ===\n")

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
        print(f"[1] story={story.story_id} rev={story.current_canonical_revision}")

        empty = orch.propose_fact(story.story_id, "顾言已婚", evidence_refs=[])
        try:
            orch.promote_to_canonical(story.story_id, empty)
            print("ERROR: empty evidence should fail")
            return 1
        except Exception as exc:
            print(f"[2] no-evidence promotion rejected: {type(exc).__name__}")

        ev = orch.capture_evidence(
            story.story_id, source_type="author", source_ref="outline",
            claim="顾言右手受伤", confidence=0.95,
        )
        prop = orch.propose_fact(
            story.story_id, "顾言右手受伤", [ev.evidence_id],
            claim_value="right_hand", target_kind="character",
            target_key="character.gu_yan.injury", confidence=0.95,
        )
        orch.promote_to_canonical(story.story_id, prop)
        print("[3] evidence-backed promotion ok")

        ch1 = orch.plan_chapter(story.story_id, 1, "码头雨夜", "顾言带伤抵达码头。")
        session = orch.begin_session(story.story_id, ch1.chapter_id)
        cand = orch.generate_candidate(session.session_id)
        orch.validate_and_review(cand.candidate_id)
        commit = orch.commit_candidate(cand.candidate_id)
        if not commit.ok:
            print(f"ERROR commit: {commit.message}")
            return 1
        print(f"[4] ch1 committed rev={commit.data['new_revision']}")

        stale_ch = orch.plan_chapter(story.story_id, 3, "假目标", "过期会话演示")
        ss = orch.begin_session(story.story_id, stale_ch.chapter_id)
        sc = orch.generate_candidate(ss.session_id)
        orch.validate_and_review(sc.candidate_id)
        orch.author_set_fact(story.story_id, "world.port_city", "新雾港", reason="rewrite")
        rejected = orch.commit_candidate(sc.candidate_id)
        if rejected.ok:
            print("ERROR stale commit should fail")
            return 1
        print(f"[5] stale commit rejected: {rejected.data.get('reason')}")

        print("\n=== Phase 1-5 Engine Demo ===\n")
        eng = ProductionEngine(repo, provider_name="template")
        story2 = eng.create_story(
            title="长夜列车",
            creative_intent="悬疑，连续性优先",
            initial_state=[
                {"key": "character.lin.name", "value": "林昭", "kind": "character", "status": "CANONICAL"},
                {"key": "world.train", "value": "夜行7号", "kind": "world", "status": "CANONICAL"},
            ],
        )
        print(f"[E1] engine story={story2.story_id}")

        ch_a, _ = eng.plan_with_rolling(
            story2.story_id, title="第一节车厢", summary="林昭登车",
            depends_on_fact_keys=["character.lin.name", "world.train"],
        )
        r1 = eng.produce_chapter(story2.story_id, ch_a.chapter_id)
        if not r1.ok:
            print(f"ERROR engine produce: {r1.message} {r1.data}")
            return 1
        print(f"[E2] produced ch1 rev={r1.data['new_revision']} cost={r1.data['cost']['cost_usd']}")

        ch_b, _ = eng.plan_with_rolling(
            story2.story_id, title="第二节车厢", summary="目击者",
            depends_on_fact_keys=["character.lin.name"],
        )
        impact = eng.impact_after_author_edit(story2.story_id, "character.lin.name", "林昭（伪装）")
        print(f"[E3] impact stale={impact['stale_chapters']}")

        r2 = eng.produce_chapter(story2.story_id, ch_b.chapter_id)
        print(f"[E4] re-produce ch2 ok={r2.ok} rev={r2.data.get('new_revision')}")

        # Quality block path
        eng.constraints = {"forbidden_keywords": ["TBD"]}
        ch_c, _ = eng.plan_with_rolling(story2.story_id, title="第三节", summary="x")
        # inject bad content via block on empty plan quality - use min_words high after patching provider is hard;
        # instead demonstrate quality module directly through empty candidate path already in tests.
        print(f"[E5] diagnostics={eng.diagnostics_summary()}")
        print(f"[E6] resume ch1={eng.resume_decision(r1.data['run_id']).value}")

        summary = {
            "phase0_story": story.story_id,
            "engine_story": story2.story_id,
            "final_revision": repo.get_story(story2.story_id).current_canonical_revision,
            "canonical_items": [
                i.key for i in repo.list_state_items(story2.story_id, status=FactStatus.CANONICAL)
            ],
            "workspace": str(workspace.resolve()),
        }
        print("\n=== DEMO OK ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def cmd_engine(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace)
    db = _open_db(workspace)
    try:
        eng = ProductionEngine(StoryRepository(db), provider_name=args.provider)
        story = eng.create_story(
            args.title,
            creative_intent=args.intent,
            initial_state=[
                {"key": "world.setting", "value": args.setting, "kind": "world", "status": "CANONICAL"},
            ],
        )
        chapter, _ = eng.plan_with_rolling(
            story.story_id, title=args.chapter_title, summary=args.plan,
            depends_on_fact_keys=["world.setting"],
        )
        result = eng.produce_chapter(story.story_id, chapter.chapter_id)
        print(json.dumps({
            "ok": result.ok,
            "stage": result.stage,
            "message": result.message,
            "data": result.data,
            "diagnostics": eng.diagnostics_summary(),
        }, ensure_ascii=False, indent=2))
        return 0 if result.ok else 1
    finally:
        db.close()


def cmd_status(args: argparse.Namespace) -> int:
    db_path = Path(args.workspace) / "novel.sqlite3"
    if not db_path.exists():
        print(f"no database at {db_path}")
        return 1
    db = Database(db_path)
    try:
        rows = db.execute(
            "SELECT story_id, title, current_canonical_revision FROM stories"
        ).fetchall()
        for r in rows:
            print(f"{r['story_id']}\t{r['title']}\trev={r['current_canonical_revision']}")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="novel-weaver")
    sub = parser.add_subparsers(dest="command", required=True)

    p_demo = sub.add_parser("demo", help="Phase 0 + engine end-to-end demo")
    p_demo.add_argument("--workspace", default=".workspaces/demo")
    p_demo.set_defaults(func=cmd_demo)

    p_eng = sub.add_parser("engine", help="Produce one chapter via ProductionEngine")
    p_eng.add_argument("--workspace", default=".workspaces/engine")
    p_eng.add_argument("--provider", default="fake", choices=["fake", "template"])
    p_eng.add_argument("--title", default="示例长篇")
    p_eng.add_argument("--intent", default="稳定连续")
    p_eng.add_argument("--setting", default="雾港")
    p_eng.add_argument("--chapter-title", default="第1章")
    p_eng.add_argument("--plan", default="开篇")
    p_eng.set_defaults(func=cmd_engine)

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
