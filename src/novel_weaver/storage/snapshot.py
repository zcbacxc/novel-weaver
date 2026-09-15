# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Release snapshot: portable export/import of Canonical story state.

Decision: JSON envelope (not raw sqlite copy) so snapshots are schema-versioned,
diffable, and importable across machines. Alternative: file-level DB copy —
rejected (opaque, couples to SQLite layout, hard to validate).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from novel_weaver.domain.errors import DomainError
from novel_weaver.domain.models import (
    Chapter,
    Event,
    FactStatus,
    ProductionUnitStatus,
    ReconcileRecord,
    ReconcileStatus,
    StateItem,
    Story,
    ThreadRecord,
)
from novel_weaver.storage.db import SCHEMA_VERSION, Database
from novel_weaver.storage.repositories import StoryRepository

SNAPSHOT_FORMAT = "novel-weaver-snapshot"
SNAPSHOT_FORMAT_VERSION = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SnapshotMeta:
    format: str = SNAPSHOT_FORMAT
    format_version: int = SNAPSHOT_FORMAT_VERSION
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=lambda: _now().isoformat())
    story_id: str = ""
    story_title: str = ""
    counts: dict[str, int] = field(default_factory=dict)


def export_story_snapshot(repo: StoryRepository, story_id: str) -> dict[str, Any]:
    story = repo.get_story(story_id)
    if story is None:
        raise DomainError(f"story not found: {story_id}")

    state = repo.list_state_items(story_id)
    events = repo.list_events(story_id)
    chapters = repo.list_chapters(story_id)
    threads = repo.list_threads(story_id)
    reconciles = repo.list_reconciles(story_id)

    meta = SnapshotMeta(
        story_id=story.story_id,
        story_title=story.title,
        counts={
            "state_items": len(state),
            "events": len(events),
            "chapters": len(chapters),
            "threads": len(threads),
            "reconciles": len(reconciles),
        },
    )
    return {
        "meta": asdict(meta),
        "story": {
            "story_id": story.story_id,
            "title": story.title,
            "premise": story.premise,
            "creative_intent": story.creative_intent,
            "constraints": story.constraints,
            "current_canonical_revision": story.current_canonical_revision,
            "lifecycle_status": story.lifecycle_status,
            "created_at": story.created_at.isoformat(),
            "updated_at": story.updated_at.isoformat(),
        },
        "state_items": [
            {
                "item_id": i.item_id,
                "key": i.key,
                "value": i.value,
                "kind": i.kind,
                "status": i.status.value,
                "revision": i.revision,
                "source": i.source,
                "confidence": i.confidence,
                "effective_from": i.effective_from,
                "effective_to": i.effective_to,
                "provenance": i.provenance,
                "superseded_by": i.superseded_by,
                "invalidated_by": i.invalidated_by,
                "depends_on": i.depends_on,
            }
            for i in state
        ],
        "events": [
            {
                "event_id": e.event_id,
                "time_ref": e.time_ref,
                "summary": e.summary,
                "participants": e.participants,
                "location": e.location,
                "claims": e.claims,
                "source_chapter": e.source_chapter,
                "status": e.status,
                "revision": e.revision,
                "provenance": e.provenance,
            }
            for e in events
        ],
        "chapters": [
            {
                "chapter_id": c.chapter_id,
                "number": c.number,
                "title": c.title,
                "plan": c.plan,
                "content": c.content,
                "status": c.status.value,
                "revision": c.revision,
                "depends_on": c.depends_on,
                "fact_keys_used": c.fact_keys_used,
                "provenance": c.provenance,
            }
            for c in chapters
        ],
        "threads": [
            {
                "thread_id": t.thread_id,
                "name": t.name,
                "introduced_at": t.introduced_at,
                "current_status": t.current_status,
                "obligations": t.obligations,
                "related_entities": t.related_entities,
                "expected_resolution": t.expected_resolution,
                "last_touched_at": t.last_touched_at,
                "revision": t.revision,
            }
            for t in threads
        ],
        "reconciles": [
            {
                "reconcile_id": r.reconcile_id,
                "chapter_id": r.chapter_id,
                "previous_content_hash": r.previous_content_hash,
                "current_content_hash": r.current_content_hash,
                "previous_story_revision": r.previous_story_revision,
                "status": r.status.value,
                "reason": r.reason,
                "fact_keys_changed": r.fact_keys_changed,
                "stale_chapter_ids": r.stale_chapter_ids,
                "still_valid_chapter_ids": r.still_valid_chapter_ids,
                "invalidated_plan_ids": r.invalidated_plan_ids,
                "extracted_fact_keys": r.extracted_fact_keys,
                "created_at": r.created_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "provenance": r.provenance,
            }
            for r in reconciles
        ],
    }


def write_snapshot(path: Path | str, payload: dict[str, Any]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def read_snapshot(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise DomainError(f"snapshot not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("meta", {}).get("format") != SNAPSHOT_FORMAT:
        raise DomainError("invalid snapshot format")
    return data


def import_story_snapshot(
    db: Database, payload: dict[str, Any], *, preserve_ids: bool = True
) -> str:
    """Import a snapshot into a database. Returns story_id.

    Decision: preserve_ids=True by default so Canonical identity is stable across
    release handoff. Alternative: remap ids — only needed for multi-story merge.
    """
    repo = StoryRepository(db)
    story_raw = payload.get("story") or {}
    if not story_raw.get("story_id"):
        raise DomainError("snapshot missing story.story_id")

    story = Story(
        story_id=story_raw["story_id"],
        title=story_raw.get("title", ""),
        premise=story_raw.get("premise", ""),
        creative_intent=story_raw.get("creative_intent", ""),
        constraints=dict(story_raw.get("constraints") or {}),
        current_canonical_revision=int(story_raw.get("current_canonical_revision") or 0),
        lifecycle_status=story_raw.get("lifecycle_status", "ACTIVE"),
    )
    repo.save_story(story)
    story_id = story.story_id

    for row in payload.get("state_items") or []:
        item = StateItem(
            item_id=row["item_id"],
            key=row["key"],
            value=row.get("value"),
            kind=row.get("kind", "world"),
            status=FactStatus(row.get("status", "CANONICAL")),
            revision=int(row.get("revision") or 0),
            source=row.get("source", ""),
            confidence=float(row.get("confidence") or 1.0),
            effective_from=row.get("effective_from"),
            effective_to=row.get("effective_to"),
            provenance=dict(row.get("provenance") or {}),
            superseded_by=row.get("superseded_by"),
            invalidated_by=row.get("invalidated_by"),
            depends_on=list(row.get("depends_on") or []),
        )
        repo.upsert_state_item(story_id, item)

    for row in payload.get("events") or []:
        event = Event(
            event_id=row["event_id"],
            time_ref=row.get("time_ref", ""),
            summary=row.get("summary", ""),
            participants=list(row.get("participants") or []),
            location=row.get("location", ""),
            claims=dict(row.get("claims") or {}),
            source_chapter=row.get("source_chapter"),
            status=row.get("status", "ACTIVE"),
            revision=int(row.get("revision") or 0),
            provenance=dict(row.get("provenance") or {}),
        )
        repo.save_event(story_id, event)

    for row in payload.get("chapters") or []:
        chapter = Chapter(
            chapter_id=row["chapter_id"],
            number=int(row["number"]),
            title=row.get("title", ""),
            plan=row.get("plan", ""),
            content=row.get("content", ""),
            status=ProductionUnitStatus(row.get("status", "PLANNED")),
            revision=int(row.get("revision") or 0),
            depends_on=list(row.get("depends_on") or []),
            fact_keys_used=list(row.get("fact_keys_used") or []),
            provenance=dict(row.get("provenance") or {}),
        )
        repo.save_chapter(story_id, chapter)

    for row in payload.get("threads") or []:
        thread = ThreadRecord(
            thread_id=row["thread_id"],
            name=row.get("name", ""),
            introduced_at=row.get("introduced_at", ""),
            current_status=row.get("current_status", "OPEN"),
            obligations=list(row.get("obligations") or []),
            related_entities=list(row.get("related_entities") or []),
            expected_resolution=row.get("expected_resolution", ""),
            last_touched_at=row.get("last_touched_at"),
            revision=int(row.get("revision") or 0),
        )
        repo.save_thread(story_id, thread)

    for row in payload.get("reconciles") or []:
        rec = ReconcileRecord(
            reconcile_id=row["reconcile_id"],
            story_id=story_id,
            chapter_id=row["chapter_id"],
            previous_content_hash=row.get("previous_content_hash", ""),
            current_content_hash=row.get("current_content_hash", ""),
            previous_story_revision=int(row.get("previous_story_revision") or 0),
            status=ReconcileStatus(row.get("status", "COMPLETED")),
            reason=row.get("reason", ""),
            fact_keys_changed=list(row.get("fact_keys_changed") or []),
            stale_chapter_ids=list(row.get("stale_chapter_ids") or []),
            still_valid_chapter_ids=list(row.get("still_valid_chapter_ids") or []),
            invalidated_plan_ids=list(row.get("invalidated_plan_ids") or []),
            extracted_fact_keys=list(row.get("extracted_fact_keys") or []),
            created_at=(
                datetime.fromisoformat(row["created_at"])
                if row.get("created_at")
                else _now()
            ),
            completed_at=(
                datetime.fromisoformat(row["completed_at"])
                if row.get("completed_at")
                else None
            ),
            provenance=dict(row.get("provenance") or {}),
        )
        repo.save_reconcile(rec)

    # Keep story_revisions in sync for the latest revision at least.
    if story.current_canonical_revision > 0:
        try:
            repo.append_revision(
                story_id, story.current_canonical_revision, reason="snapshot-import"
            )
        except Exception:
            pass

    return story_id
