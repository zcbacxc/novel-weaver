"""Impact analysis and invalidation tests."""

from novel_weaver.domain.models import Chapter, FactStatus, ProductionUnitStatus, StateItem
from novel_weaver.production.invalidation import ImpactAnalyzer, mark_stale


def _ch(num: int, keys: list[str], depends: list[str] | None = None) -> Chapter:
    ch = Chapter.create(num, f"c{num}", "plan")
    ch.fact_keys_used = keys
    ch.depends_on = depends or []
    return ch


def test_only_dependent_chapters_stale() -> None:
    ch1 = _ch(1, ["character.a"])
    ch2 = _ch(2, ["character.a"])
    ch3 = _ch(3, ["world.b"])
    item = StateItem.create("character.a", "x", "character", status=FactStatus.CANONICAL)
    report = ImpactAnalyzer().analyze([ch1, ch2, ch3], [item], {"character.a"})
    assert ch1.chapter_id in report.stale_chapter_ids
    assert ch2.chapter_id in report.stale_chapter_ids
    assert ch3.chapter_id in report.still_valid_chapter_ids


def test_mark_stale_skips_nothing_but_sets_status() -> None:
    ch = _ch(1, ["k"])
    ch.status = ProductionUnitStatus.CANDIDATE_READY
    updated = mark_stale([ch], [ch.chapter_id], "retcon")
    assert updated[0].status is ProductionUnitStatus.STALE
    assert updated[0].provenance["stale_reason"] == "retcon"


def test_committed_marked_needs_reconcile() -> None:
    ch = _ch(1, ["k"])
    ch.status = ProductionUnitStatus.COMMITTED
    updated = mark_stale([ch], [ch.chapter_id], "retcon")
    assert updated[0].provenance.get("needs_reconcile") is True
