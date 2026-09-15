# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Canonical file export: human-auditable prose + state beside SQLite (§17.2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_weaver.domain.models import FactStatus, ProductionUnitStatus
from novel_weaver.storage.repositories import StoryRepository


class CanonicalFileStore:
    """Write/read Canonical story as version-control friendly files.

    Decision: markdown chapters + JSON state under workspace/canonical/.
    These files are *derived exports* of Canonical DB — DB remains source of truth.
    Alternative: files as primary store — rejected for Phase 1 (plan prefers DB
    for production state; files for audit).
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def story_dir(self, story_id: str) -> Path:
        d = self.root / story_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def export_story(self, repo: StoryRepository, story_id: str) -> dict[str, str]:
        story = repo.get_story(story_id)
        if story is None:
            raise ValueError(f"story not found: {story_id}")
        base = self.story_dir(story_id)
        written: dict[str, str] = {}

        meta_path = base / "story.json"
        meta = {
            "story_id": story.story_id,
            "title": story.title,
            "premise": story.premise,
            "creative_intent": story.creative_intent,
            "constraints": story.constraints,
            "current_canonical_revision": story.current_canonical_revision,
            "lifecycle_status": story.lifecycle_status,
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        written["story.json"] = str(meta_path)

        chapters_dir = base / "chapters"
        chapters_dir.mkdir(exist_ok=True)
        for ch in sorted(repo.list_chapters(story_id), key=lambda c: c.number):
            if ch.status is not ProductionUnitStatus.COMMITTED:
                continue
            fname = f"{ch.number:04d}_{ch.chapter_id}.md"
            path = chapters_dir / fname
            body = [
                f"---",
                f"chapter_id: {ch.chapter_id}",
                f"number: {ch.number}",
                f"title: {ch.title!r}",
                f"revision: {ch.revision}",
                f"status: {ch.status.value}",
                f"content_fingerprint: {ch.provenance.get('content_fingerprint', '')}",
                f"---",
                "",
                f"# {ch.title or f'第{ch.number}章'}",
                "",
                ch.content or "",
                "",
            ]
            path.write_text("\n".join(body), encoding="utf-8")
            written[fname] = str(path)

        state_path = base / "state.json"
        state = [
            {
                "key": i.key,
                "value": i.value,
                "kind": i.kind,
                "status": i.status.value,
                "revision": i.revision,
                "effective_from": i.effective_from,
                "effective_to": i.effective_to,
            }
            for i in repo.list_state_items(story_id)
            if i.status in (FactStatus.CANONICAL, FactStatus.PENDING, FactStatus.PROPOSED)
        ]
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        written["state.json"] = str(state_path)

        threads_path = base / "threads.json"
        threads = [
            {
                "name": t.name,
                "status": t.current_status,
                "introduced_at": t.introduced_at,
                "last_touched_at": t.last_touched_at,
                "expected_resolution": t.expected_resolution,
            }
            for t in repo.list_threads(story_id)
        ]
        threads_path.write_text(
            json.dumps(threads, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        written["threads.json"] = str(threads_path)

        return written

    def read_chapter_markdown(self, story_id: str, number: int) -> str | None:
        chapters_dir = self.story_dir(story_id) / "chapters"
        if not chapters_dir.exists():
            return None
        matches = sorted(chapters_dir.glob(f"{number:04d}_*.md"))
        if not matches:
            return None
        return matches[0].read_text(encoding="utf-8")

    def list_exported_chapters(self, story_id: str) -> list[str]:
        chapters_dir = self.story_dir(story_id) / "chapters"
        if not chapters_dir.exists():
            return []
        return sorted(p.name for p in chapters_dir.glob("*.md"))
