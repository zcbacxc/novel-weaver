# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Smoke tests for the long-run benchmark harness (not the 30-chapter soak)."""

from __future__ import annotations

from novel_weaver.benchmarks.long_run import LongRunBenchmark, run_benchmark


def test_bench_five_chapters_clean_path() -> None:
    report = LongRunBenchmark(chapters=5, repair_at=(), recover_at=()).run()
    assert report.produced_chapters == 5
    assert report.total_attempts == 5
    assert report.failed_attempts == 0
    assert report.continuity is not None
    assert report.continuity.violation_count == 0
    assert report.continuity.committed_chapters == 5
    assert report.continuity.sequential_numbers is True


def test_bench_with_repair_and_recovery() -> None:
    report = LongRunBenchmark(
        chapters=8,
        repair_at=(5,),
        recover_at=(3,),
    ).run()
    assert report.produced_chapters == 8
    assert len(report.repairs) == 1
    assert report.repairs[0].production_blocked_before_complete is True
    assert report.repairs[0].production_blocked_after_complete is False
    assert report.recovery_success_rate == 1.0
    assert report.regenerations >= 1
    assert report.continuity is not None
    assert report.continuity.violation_count == 0
    assert report.mean_invalidation_precision > 0


def test_run_benchmark_writes_report(tmp_path) -> None:
    out = tmp_path / "r.json"
    report = run_benchmark(chapters=4, workspace=tmp_path / "ws", output=out)
    assert out.exists()
    assert report.produced_chapters == 4
    payload = out.read_text(encoding="utf-8")
    assert "continuity_violations" in payload
