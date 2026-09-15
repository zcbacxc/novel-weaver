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
    """Run the Phase 0 truth-boundary demo plus a short engine demo.

    Args:
        args: Parsed CLI namespace with ``workspace``.

    Returns:
        Process exit code (0 on success).
    """
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

        # External Edit Sync / Reconcile (§23.7)
        ch1_stored = repo.get_chapter(ch_a.chapter_id)
        rec = eng.apply_author_chapter_edit(
            story2.story_id,
            ch_a.chapter_id,
            new_content=(ch1_stored.content or "") + "\n\n【作者改稿】林昭左臂缠着绷带登车。",
            reason="retcon injury",
        )
        blocked = eng.produce_chapter(story2.story_id, ch_b.chapter_id)
        print(f"[E7] reconcile opened={rec.reconcile_id} produce_blocked={not blocked.ok}")
        sync = eng.complete_reconcile(
            story2.story_id,
            rec.reconcile_id,
            fact_deltas=[
                {
                    "key": "character.lin.injury",
                    "value": "left_arm",
                    "kind": "character",
                    "claim": "林昭左臂受伤",
                }
            ],
        )
        print(
            f"[E8] reconcile ok={sync.ok} stale={sync.stale_chapter_ids} "
            f"blocked={sync.production_blocked} rev={sync.new_story_revision}"
        )

        summary = {
            "phase0_story": story.story_id,
            "engine_story": story2.story_id,
            "final_revision": repo.get_story(story2.story_id).current_canonical_revision,
            "canonical_items": [
                i.key for i in repo.list_state_items(story2.story_id, status=FactStatus.CANONICAL)
            ],
            "reconcile_id": rec.reconcile_id,
            "workspace": str(workspace.resolve()),
        }
        print("\n=== DEMO OK ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def cmd_engine(args: argparse.Namespace) -> int:
    """Produce a single chapter via ProductionEngine and print JSON result.

    Args:
        args: Parsed CLI namespace (workspace, provider, title, plan, failover).

    Returns:
        Process exit code (0 when the chapter committed).
    """
    from novel_weaver.config import get_settings

    cfg = get_settings()
    workspace = Path(args.workspace or cfg.workspace)
    db = _open_db(workspace)
    try:
        failover = [x.strip() for x in (args.failover or cfg.failover or "").split(",") if x.strip()]
        provider = args.provider or cfg.default_provider
        eng = ProductionEngine(
            StoryRepository(db),
            provider_name=provider,
            failover_names=failover or None,
            use_llm_review=cfg.use_llm_review_flag(),
        )
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


def cmd_produce(args: argparse.Namespace) -> int:
    """Continuous multi-chapter production on a single story.

    Args:
        args: Parsed CLI namespace (workspace, provider, chapters, title, plan).

    Returns:
        Process exit code (0 when every planned chapter committed).
    """
    workspace = Path(args.workspace)
    db = _open_db(workspace)
    try:
        eng = ProductionEngine(StoryRepository(db), provider_name=args.provider)
        repo = eng.repo
        story = eng.create_story(
            args.title,
            premise=args.premise,
            creative_intent=args.intent,
            initial_state=[
                {
                    "key": "world.setting",
                    "value": args.setting,
                    "kind": "world",
                    "status": "CANONICAL",
                },
                {
                    "key": "character.lead.name",
                    "value": args.lead,
                    "kind": "character",
                    "status": "CANONICAL",
                },
            ],
        )
        print(f"story={story.story_id} rev={story.current_canonical_revision}")
        results: list[dict] = []
        for i in range(1, args.chapters + 1):
            title = f"第{i}章"
            plan = args.plan_template.format(i=i, lead=args.lead, setting=args.setting)
            chapter, _ = eng.plan_with_rolling(
                story.story_id,
                number=i,
                title=title,
                summary=plan,
                depends_on_fact_keys=["world.setting", "character.lead.name"],
            )
            result = eng.produce_chapter(story.story_id, chapter.chapter_id)
            stored = repo.get_chapter(chapter.chapter_id)
            preview = (stored.content[:120] + "…") if stored and stored.content else ""
            row = {
                "number": i,
                "ok": result.ok,
                "stage": result.stage,
                "message": result.message,
                "chapter_id": chapter.chapter_id,
                "revision": result.data.get("new_revision"),
                "run_id": result.data.get("run_id"),
                "chars": len(stored.content) if stored else 0,
                "preview": preview,
            }
            results.append(row)
            status = "OK" if result.ok else f"FAIL@{result.stage}"
            print(
                f"[{i}/{args.chapters}] {status} rev={row['revision']} "
                f"chars={row['chars']} {preview[:60]}"
            )
            if not result.ok:
                print(f"    error: {result.message}")
                break

        story_after = repo.get_story(story.story_id)
        cost = eng.cost.total_for_story(story.story_id)
        chapters = repo.list_chapters(story.story_id)
        committed = [c for c in chapters if c.status.value == "COMMITTED"]
        summary = {
            "story_id": story.story_id,
            "provider": args.provider,
            "planned": args.chapters,
            "produced": sum(1 for r in results if r["ok"]),
            "final_revision": story_after.current_canonical_revision if story_after else None,
            "committed_chapters": len(committed),
            "chapter_numbers": [c.number for c in committed],
            "canonical_keys": [
                i.key
                for i in repo.list_state_items(story.story_id, status=FactStatus.CANONICAL)
            ],
            "cost": cost,
            "diagnostics": eng.diagnostics_summary(),
            "results": results,
            "workspace": str(workspace.resolve()),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["produced"] == args.chapters else 1
    finally:
        db.close()


def cmd_book_check(args: argparse.Namespace) -> int:
    """Run the full-book consistency pass and print the JSON report.

    Args:
        args: Parsed CLI namespace (workspace, db, story_id, llm, ack_all).

    Returns:
        Process exit code (1 when the decision is BLOCK).
    """
    from novel_weaver.production.book_pass import BookConsistencyPass
    from novel_weaver.ai.registry import get_provider

    workspace = Path(args.workspace)
    db_path = Path(args.db) if args.db else workspace / "novel.sqlite3"
    if not db_path.exists():
        # Bench workspaces use bench.sqlite3.
        alt = workspace / "bench.sqlite3"
        if alt.exists():
            db_path = alt
        else:
            print(f"no database at {db_path}")
            return 1
    db = Database(db_path)
    try:
        repo = StoryRepository(db)
        llm = None
        if args.llm:
            llm = get_provider(args.llm)
        story_id = args.story_id
        if not story_id:
            rows = db.execute(
                "SELECT story_id FROM stories WHERE lifecycle_status='ACTIVE' "
                "ORDER BY updated_at DESC LIMIT 1"
            ).fetchall()
            if not rows:
                print("no active story")
                return 1
            story_id = rows[0]["story_id"]
        checker = BookConsistencyPass(repo, llm_provider=llm)
        if args.ack_all:
            n = checker.acknowledge_all_flagged(story_id, note="cli book-check --ack-all")
            print(f"acknowledged_needs_reconcile={n}", flush=True)
        report = checker.run(story_id)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        if report.decision.value == "BLOCK":
            return 1
        return 0
    finally:
        db.close()


def cmd_snapshot_export(args: argparse.Namespace) -> int:
    """Export a Canonical story snapshot JSON file.

    Args:
        args: Parsed CLI namespace (workspace, db, story_id, output).

    Returns:
        Process exit code (0 on success).
    """
    from novel_weaver.storage.snapshot import export_story_snapshot, write_snapshot

    workspace = Path(args.workspace)
    db_path = Path(args.db) if args.db else workspace / "novel.sqlite3"
    if not db_path.exists():
        alt = workspace / "bench.sqlite3"
        if alt.exists():
            db_path = alt
        else:
            print(f"no database at {db_path}")
            return 1
    db = Database(db_path)
    try:
        repo = StoryRepository(db)
        story_id = args.story_id
        if not story_id:
            rows = db.execute(
                "SELECT story_id FROM stories ORDER BY updated_at DESC LIMIT 1"
            ).fetchall()
            if not rows:
                print("no story")
                return 1
            story_id = rows[0]["story_id"]
        payload = export_story_snapshot(repo, story_id)
        out = Path(args.output) if args.output else workspace / f"snapshot_{story_id}.json"
        write_snapshot(out, payload)
        print(json.dumps({"ok": True, "output": str(out.resolve()), "meta": payload["meta"]}, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def cmd_snapshot_import(args: argparse.Namespace) -> int:
    """Import a Canonical story snapshot JSON into a workspace database.

    Args:
        args: Parsed CLI namespace (input, workspace).

    Returns:
        Process exit code (0 on success).
    """
    from novel_weaver.storage.snapshot import import_story_snapshot, read_snapshot

    payload = read_snapshot(args.input)
    workspace = Path(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    db_path = workspace / "novel.sqlite3"
    db = Database(db_path)
    try:
        story_id = import_story_snapshot(db, payload)
        print(json.dumps({"ok": True, "story_id": story_id, "workspace": str(workspace.resolve())}, ensure_ascii=False))
        return 0
    finally:
        db.close()


def cmd_release_create(args: argparse.Namespace) -> int:
    """Create an immutable Canonical release for a story.

    Args:
        args: Parsed CLI namespace (workspace, story_id, label, notes).

    Returns:
        Process exit code (0 on success).
    """
    from novel_weaver.storage.releases import ReleaseRegistry

    workspace = Path(args.workspace)
    db_path = workspace / "novel.sqlite3"
    if not db_path.exists():
        alt = workspace / "bench.sqlite3"
        if alt.exists():
            db_path = alt
        else:
            print(f"no database at {db_path}")
            return 1
    db = Database(db_path)
    try:
        repo = StoryRepository(db)
        story_id = args.story_id
        if not story_id:
            rows = db.execute(
                "SELECT story_id FROM stories ORDER BY updated_at DESC LIMIT 1"
            ).fetchall()
            if not rows:
                print("no story")
                return 1
            story_id = rows[0]["story_id"]
        registry = ReleaseRegistry(workspace / "releases")
        rec = registry.create_release(repo, story_id, label=args.label, notes=args.notes)
        print(json.dumps(rec.to_dict(), ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def cmd_canonical_export(args: argparse.Namespace) -> int:
    """Export Canonical story markdown/state files to the workspace.

    Args:
        args: Parsed CLI namespace (workspace, story_id).

    Returns:
        Process exit code (0 on success).
    """
    from novel_weaver.storage.canonical_files import CanonicalFileStore

    workspace = Path(args.workspace)
    db_path = workspace / "novel.sqlite3"
    if not db_path.exists():
        alt = workspace / "bench.sqlite3"
        if alt.exists():
            db_path = alt
        else:
            print(f"no database at {db_path}")
            return 1
    db = Database(db_path)
    try:
        repo = StoryRepository(db)
        story_id = args.story_id
        if not story_id:
            rows = db.execute(
                "SELECT story_id FROM stories ORDER BY updated_at DESC LIMIT 1"
            ).fetchall()
            if not rows:
                print("no story")
                return 1
            story_id = rows[0]["story_id"]
        store = CanonicalFileStore(workspace / "canonical")
        written = store.export_story(repo, story_id)
        print(json.dumps({"ok": True, "files": written}, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def cmd_timeline(args: argparse.Namespace) -> int:
    """Print the narrative timeline projection as JSON.

    Args:
        args: Parsed CLI namespace (workspace, story_id).

    Returns:
        Process exit code (0 on success).
    """
    from novel_weaver.production.timeline import TimelineService

    workspace = Path(args.workspace)
    db_path = workspace / "novel.sqlite3"
    if not db_path.exists():
        alt = workspace / "bench.sqlite3"
        if alt.exists():
            db_path = alt
        else:
            print(f"no database at {db_path}")
            return 1
    db = Database(db_path)
    try:
        repo = StoryRepository(db)
        story_id = args.story_id
        if not story_id:
            rows = db.execute(
                "SELECT story_id FROM stories ORDER BY updated_at DESC LIMIT 1"
            ).fetchall()
            if not rows:
                print("no story")
                return 1
            story_id = rows[0]["story_id"]
        snap = TimelineService(repo).snapshot(story_id)
        print(json.dumps(snap.to_dict(), ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def cmd_config_show(args: argparse.Namespace) -> int:
    """Bootstrap user config if needed and print effective settings as JSON.

    Args:
        args: Parsed CLI namespace (reveal_key).

    Returns:
        Process exit code (always 0).
    """
    from novel_weaver.config import (
        clear_settings_cache,
        ensure_user_config,
        get_settings,
        user_config_path,
    )

    clear_settings_cache()
    path = ensure_user_config()
    cfg = get_settings()
    payload = {
        "user_config": str(path),
        "exists": path.exists(),
        "llm_base_url": cfg.llm_base_url,
        "llm_model": cfg.llm_model,
        "llm_api_key_set": bool(cfg.llm_api_key),
        "llm_timeout": cfg.llm_timeout,
        "llm_max_tokens": cfg.llm_max_tokens,
        "default_provider": cfg.default_provider,
        "failover": cfg.failover_names(),
        "use_llm_review": cfg.use_llm_review_flag(),
        "workspace": cfg.workspace,
    }
    if args.reveal_key:
        payload["llm_api_key"] = cfg.llm_api_key
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """List stories in the workspace database.

    Args:
        args: Parsed CLI namespace (workspace).

    Returns:
        Process exit code (0 on success, 1 when no database exists).
    """
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


def cmd_bench(args: argparse.Namespace) -> int:
    """Run the long-run production benchmark and print its summary.

    Args:
        args: Parsed CLI namespace (chapters, provider, workspace, output, delay, retries).

    Returns:
        Process exit code (1 when continuity violations are present).
    """
    from novel_weaver.benchmarks.long_run import run_benchmark

    output = (
        Path(args.output)
        if args.output
        else Path(args.workspace) / f"bench_{args.chapters}.json"
    )
    report = run_benchmark(
        chapters=args.chapters,
        provider_name=args.provider,
        workspace=args.workspace,
        output=output,
        chapter_delay_s=args.delay,
        max_provider_retries=args.retries,
    )
    print("=== Long-run Benchmark (§25.3) ===")
    for line in report.summary_lines():
        print(line)
    print(f"\nreport_json={output.resolve()}")
    if report.continuity and report.continuity.violation_count > 0:
        print("continuity: FAIL")
        return 1
    print("continuity: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and dispatch to the selected subcommand.

    Args:
        argv: Optional argument list; None uses sys.argv[1:].

    Returns:
        Process exit code from the subcommand (2 on domain/guard errors).
    """
    parser = argparse.ArgumentParser(prog="novel-weaver")
    sub = parser.add_subparsers(dest="command", required=True)

    p_demo = sub.add_parser("demo", help="Phase 0 + engine end-to-end demo")
    p_demo.add_argument("--workspace", default=".workspaces/demo")
    p_demo.set_defaults(func=cmd_demo)

    p_eng = sub.add_parser("engine", help="Produce one chapter via ProductionEngine")
    p_eng.add_argument("--workspace", default=".workspaces/engine")
    p_eng.add_argument(
        "--provider",
        default="",
        choices=["", "fake", "template", "openai", "llm", "failover"],
        help="default from NOVEL_WEAVER_DEFAULT_PROVIDER; openai/llm reads Settings/.env",
    )
    p_eng.add_argument("--title", default="示例长篇")
    p_eng.add_argument("--intent", default="稳定连续")
    p_eng.add_argument("--setting", default="雾港")
    p_eng.add_argument("--chapter-title", default="第1章")
    p_eng.add_argument("--plan", default="开篇")
    p_eng.add_argument(
        "--failover",
        default="",
        help="Comma-separated provider chain, e.g. openai,template",
    )
    p_eng.set_defaults(func=cmd_engine)

    p_cfg = sub.add_parser("config", help="Show / bootstrap configuration")
    p_cfg.add_argument("--show", action="store_true", help="Print effective settings")
    p_cfg.add_argument("--reveal-key", action="store_true", help="Include API key in output")
    p_cfg.set_defaults(func=cmd_config_show)

    p_status = sub.add_parser("status", help="List stories in workspace")
    p_status.add_argument("--workspace", default=".workspaces/demo")
    p_status.set_defaults(func=cmd_status)

    p_bench = sub.add_parser("bench", help="Long-run production benchmark (§25.3)")
    p_bench.add_argument("--chapters", type=int, default=30)
    p_bench.add_argument(
        "--provider",
        default="template",
        choices=["fake", "template", "openai", "llm"],
    )
    p_bench.add_argument("--workspace", default=".workspaces/bench-30")
    p_bench.add_argument("--output", default="", help="JSON report path (default: <workspace>/bench_<n>.json)")
    p_bench.add_argument("--delay", type=float, default=0.0, help="Seconds to sleep between chapters")
    p_bench.add_argument("--retries", type=int, default=0, help="Provider retries per chapter")
    p_bench.set_defaults(func=cmd_bench)

    p_prod = sub.add_parser("produce", help="Continuous multi-chapter production on one story")
    p_prod.add_argument("--workspace", default=".workspaces/produce")
    p_prod.add_argument(
        "--provider",
        default="template",
        choices=["fake", "template", "openai", "llm"],
    )
    p_prod.add_argument("--chapters", type=int, default=3)
    p_prod.add_argument("--title", default="雾港纪事")
    p_prod.add_argument("--premise", default="港口侦探追查失踪货轮。")
    p_prod.add_argument("--intent", default="冷硬侦探，强连续性，禁止无来源改写关键事实")
    p_prod.add_argument("--setting", default="雾港")
    p_prod.add_argument("--lead", default="顾言")
    p_prod.add_argument(
        "--plan-template",
        default="在{setting}推进第{i}章：{lead}依据已有正式事实继续追查，情节前后衔接。",
    )
    p_prod.set_defaults(func=cmd_produce)

    p_exp = sub.add_parser("snapshot-export", help="Export Canonical story snapshot JSON")
    p_exp.add_argument("--workspace", default=".workspaces/demo")
    p_exp.add_argument("--db", default="")
    p_exp.add_argument("--story-id", default="")
    p_exp.add_argument("--output", default="")
    p_exp.set_defaults(func=cmd_snapshot_export)

    p_imp = sub.add_parser("snapshot-import", help="Import Canonical story snapshot JSON")
    p_imp.add_argument("--input", required=True)
    p_imp.add_argument("--workspace", default=".workspaces/imported")
    p_imp.set_defaults(func=cmd_snapshot_import)

    p_book = sub.add_parser("book-check", help="Full-book consistency pass (Phase 4)")
    p_book.add_argument("--workspace", default=".workspaces/demo")
    p_book.add_argument("--db", default="", help="Explicit sqlite path (default: <workspace>/novel.sqlite3 or bench.sqlite3)")
    p_book.add_argument("--story-id", default="", help="Story id (default: latest ACTIVE)")
    p_book.add_argument(
        "--llm",
        default="",
        choices=["", "openai", "llm"],
        help="Optional LLM provider for semantic book review",
    )
    p_book.add_argument(
        "--ack-all",
        action="store_true",
        help="Clear needs_reconcile flags after review (repair backlog accept)",
    )
    p_book.set_defaults(func=cmd_book_check)

    p_rel = sub.add_parser("release-create", help="Create immutable Canonical release")
    p_rel.add_argument("--workspace", default=".workspaces/demo")
    p_rel.add_argument("--story-id", default="")
    p_rel.add_argument("--label", default="")
    p_rel.add_argument("--notes", default="")
    p_rel.set_defaults(func=cmd_release_create)

    p_can = sub.add_parser("canonical-export", help="Export Canonical markdown/state files")
    p_can.add_argument("--workspace", default=".workspaces/demo")
    p_can.add_argument("--story-id", default="")
    p_can.set_defaults(func=cmd_canonical_export)

    p_tl = sub.add_parser("timeline", help="Show narrative timeline projection")
    p_tl.add_argument("--workspace", default=".workspaces/demo")
    p_tl.add_argument("--story-id", default="")
    p_tl.set_defaults(func=cmd_timeline)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (DomainError, GuardRejectError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
