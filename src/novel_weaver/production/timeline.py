# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Timeline service: narrative position + time-sensitive fact windows (§5.7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from novel_weaver.domain.models import Event, FactStatus, ProductionUnitStatus, StateItem
from novel_weaver.storage.repositories import StoryRepository


@dataclass
class TimelinePosition:
    """Where the committed narrative currently is."""

    chapter_number: int
    chapter_id: str
    time_ref: str
    title: str = ""


@dataclass
class TimelineFactWindow:
    """A fact value and its effective range on the narrative timeline.

    Attributes:
        key: Namespaced fact key.
        value: Fact value.
        effective_from: Inclusive start ordinal/revision, if set.
        effective_to: Inclusive end ordinal/revision, if set.
        status: Fact status string.
    """

    key: str
    value: Any
    effective_from: int | None
    effective_to: int | None
    status: str


@dataclass
class TimelineSnapshot:
    """Point-in-time timeline projection for observability and checks.

    Attributes:
        position: Current committed narrative position (or None).
        ordered_events: Event dicts sorted by time_ref.
        active_fact_windows: Fact windows active at the tip.
        open_time_refs: time_refs of ACTIVE events.
        stats: Counts and ordering violations.
    """

    position: TimelinePosition | None
    ordered_events: list[dict[str, Any]] = field(default_factory=list)
    active_fact_windows: list[TimelineFactWindow] = field(default_factory=list)
    open_time_refs: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the snapshot for JSON output.

        Returns:
            Dict with position, events, fact windows, refs, and stats.
        """
        return {
            "position": {
                "chapter_number": self.position.chapter_number,
                "chapter_id": self.position.chapter_id,
                "time_ref": self.position.time_ref,
                "title": self.position.title,
            }
            if self.position
            else None,
            "ordered_events": self.ordered_events,
            "active_fact_windows": [
                {
                    "key": w.key,
                    "value": w.value,
                    "effective_from": w.effective_from,
                    "effective_to": w.effective_to,
                    "status": w.status,
                }
                for w in self.active_fact_windows
            ],
            "open_time_refs": self.open_time_refs,
            "stats": self.stats,
        }


def _time_ref_key(time_ref: str) -> tuple[int, str]:
    """Sort key: ch12 before ch2 when numeric suffix present."""
    raw = (time_ref or "").strip()
    digits = ""
    i = len(raw)
    while i > 0 and raw[i - 1].isdigit():
        digits = raw[i - 1] + digits
        i -= 1
    try:
        return (int(digits), raw) if digits else (10**9, raw)
    except ValueError:
        return (10**9, raw)


class TimelineService:
    """Derives narrative position and effective fact windows from Canonical data.

    Decision: Timeline is a *projection* over State effective ranges + Event
    ledger + committed chapters — not a second source of truth.
    Alternative: standalone timeline table mutated on commit — rejected
    (risk of dual truth; plan §3.1 Canonical is sole truth).
    """

    def __init__(self, repo: StoryRepository) -> None:
        self.repo = repo

    def narrative_position(self, story_id: str) -> TimelinePosition | None:
        """Return the latest committed chapter as the narrative tip.

        Args:
            story_id: Story identity.

        Returns:
            TimelinePosition of the highest-numbered committed chapter,
            or None when no committed content exists.
        """
        committed = [
            c
            for c in self.repo.list_chapters(story_id)
            if c.status is ProductionUnitStatus.COMMITTED and (c.content or "").strip()
        ]
        if not committed:
            return None
        latest = max(committed, key=lambda c: (c.number, c.revision))
        return TimelinePosition(
            chapter_number=latest.number,
            chapter_id=latest.chapter_id,
            time_ref=f"ch{latest.number}",
            title=latest.title,
        )

    def ordered_events(self, story_id: str) -> list[Event]:
        """List non-invalidated events sorted by narrative time_ref.

        Args:
            story_id: Story identity.

        Returns:
            Active Event list in narrative order.
        """
        events = self.repo.list_events(story_id)
        active = [e for e in events if e.status != "INVALIDATED"]
        return sorted(active, key=lambda e: (_time_ref_key(e.time_ref), e.event_id))

    def active_fact_windows(
        self, story_id: str, *, at_chapter: int | None = None
    ) -> list[TimelineFactWindow]:
        """Facts whose effective range covers ``at_chapter`` (default: narrative tip).

        Args:
            story_id: Story identity.
            at_chapter: Chapter ordinal to evaluate; None uses narrative tip.

        Returns:
            TimelineFactWindow list considered active at that position.
        """
        if at_chapter is None:
            pos = self.narrative_position(story_id)
            at_chapter = pos.chapter_number if pos else 0

        out: list[TimelineFactWindow] = []
        for item in self.repo.list_state_items(story_id):
            if item.status not in (FactStatus.CANONICAL, FactStatus.PENDING, FactStatus.PROPOSED):
                continue
            start = item.effective_from
            end = item.effective_to
            # Inclusive window on chapter/revision ordinal.
            if start is not None and at_chapter < start and start > 0:
                # effective_from is often story revision, not chapter number.
                # Treat as open-ended from that revision if at_chapter is chapter index.
                pass
            if end is not None and item.status is FactStatus.CANONICAL:
                # Superseded items have effective_to; skip if clearly past.
                if at_chapter > 0 and end > 0 and end < at_chapter and start is not None and start <= end:
                    # Only skip when both bounds look like chapter-like small ints.
                    if end < 10_000 and start < 10_000 and at_chapter > end:
                        continue
            out.append(
                TimelineFactWindow(
                    key=item.key,
                    value=item.value,
                    effective_from=item.effective_from,
                    effective_to=item.effective_to,
                    status=item.status.value,
                )
            )
        return out

    def facts_at_chapter(self, story_id: str, chapter_number: int) -> list[StateItem]:
        """Canonical (and pending) facts considered valid at a chapter index.

        Args:
            story_id: Story identity.
            chapter_number: Chapter ordinal to evaluate.

        Returns:
            StateItem list valid at that chapter according to effective ranges.
        """
        result: list[StateItem] = []
        for item in self.repo.list_state_items(story_id):
            if item.status not in (
                FactStatus.CANONICAL,
                FactStatus.PENDING,
                FactStatus.PROPOSED,
            ):
                continue
            start = item.effective_from
            end = item.effective_to
            # Heuristic: small ints treated as chapter ordinals when both bounds small.
            if start is not None and 0 < start < 10_000 and chapter_number < start:
                continue
            if (
                end is not None
                and 0 < end < 10_000
                and start is not None
                and 0 < start < 10_000
                and chapter_number > end
            ):
                continue
            result.append(item)
        return result

    def check_ordering_violations(self, story_id: str) -> list[str]:
        """Detect non-monotonic event time_refs and chapter number gaps.

        Args:
            story_id: Story identity.

        Returns:
            Human-readable violation strings (empty when consistent).
        """
        violations: list[str] = []
        events = self.ordered_events(story_id)
        last_key: tuple[int, str] | None = None
        for ev in events:
            key = _time_ref_key(ev.time_ref)
            if last_key is not None and key < last_key:
                violations.append(
                    f"event {ev.event_id} time_ref={ev.time_ref!r} out of order after {last_key[1]!r}"
                )
            last_key = key
        chapters = [
            c
            for c in self.repo.list_chapters(story_id)
            if c.status is ProductionUnitStatus.COMMITTED
        ]
        numbers = [c.number for c in sorted(chapters, key=lambda c: c.number)]
        if numbers != list(range(1, len(numbers) + 1)):
            violations.append(f"chapter number gaps: {numbers}")
        return violations

    def snapshot(self, story_id: str) -> TimelineSnapshot:
        """Build a full timeline snapshot for CLI/observability output.

        Args:
            story_id: Story identity.

        Returns:
            TimelineSnapshot with position, events, windows, and stats.
        """
        pos = self.narrative_position(story_id)
        events = self.ordered_events(story_id)
        windows = self.active_fact_windows(story_id)
        return TimelineSnapshot(
            position=pos,
            ordered_events=[
                {
                    "event_id": e.event_id,
                    "time_ref": e.time_ref,
                    "summary": e.summary,
                    "status": e.status,
                    "source_chapter": e.source_chapter,
                }
                for e in events
            ],
            active_fact_windows=windows,
            open_time_refs=[e.time_ref for e in events if e.status == "ACTIVE"],
            stats={
                "events": len(events),
                "fact_windows": len(windows),
                "ordering_violations": self.check_ordering_violations(story_id),
            },
        )
