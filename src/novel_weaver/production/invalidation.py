"""Impact analysis and invalidation propagation."""

from __future__ import annotations

from dataclasses import dataclass, field

from novel_weaver.domain.models import Chapter, ProductionUnitStatus, StateItem


@dataclass
class ImpactReport:
    changed_keys: list[str] = field(default_factory=list)
    stale_chapter_ids: list[str] = field(default_factory=list)
    still_valid_chapter_ids: list[str] = field(default_factory=list)
    dependent_item_ids: list[str] = field(default_factory=list)


class ImpactAnalyzer:
    """Compute which chapters/units depend on changed fact keys."""

    def analyze(
        self,
        chapters: list[Chapter],
        state_items: list[StateItem],
        changed_keys: set[str],
    ) -> ImpactReport:
        report = ImpactReport(changed_keys=sorted(changed_keys))

        for chapter in chapters:
            uses = set(chapter.fact_keys_used)
            depends = set(chapter.depends_on)
            # chapter.depends_on may hold item_ids or keys; match both
            item_ids = {i.item_id for i in state_items if i.key in changed_keys}
            keys_hit = bool(uses & changed_keys) or bool(depends & changed_keys)
            ids_hit = bool(depends & item_ids)
            if keys_hit or ids_hit:
                report.stale_chapter_ids.append(chapter.chapter_id)
            else:
                report.still_valid_chapter_ids.append(chapter.chapter_id)

        for item in state_items:
            if item.status.value in ("SUPERSEDED", "INVALIDATED"):
                continue
            if item.key in changed_keys:
                report.dependent_item_ids.append(item.item_id)
            elif any(
                dep_key in changed_keys
                for dep_key in _keys_of(item, state_items)
            ):
                report.dependent_item_ids.append(item.item_id)

        return report


def _keys_of(item: StateItem, all_items: list[StateItem]) -> set[str]:
    by_id = {i.item_id: i.key for i in all_items}
    return {by_id.get(dep, dep) for dep in item.depends_on}


def mark_stale(chapters: list[Chapter], chapter_ids: list[str], reason: str) -> list[Chapter]:
    stale_set = set(chapter_ids)
    updated: list[Chapter] = []
    for ch in chapters:
        if ch.chapter_id in stale_set and ch.status not in (
            ProductionUnitStatus.COMMITTED,
        ):
            # committed content becomes STALE via reconcile path separately
            ch.status = ProductionUnitStatus.STALE
            ch.provenance = {**ch.provenance, "stale_reason": reason}
            updated.append(ch)
        elif ch.chapter_id in stale_set and ch.status == ProductionUnitStatus.COMMITTED:
            ch.provenance = {**ch.provenance, "stale_reason": reason, "needs_reconcile": True}
            updated.append(ch)
    return updated
