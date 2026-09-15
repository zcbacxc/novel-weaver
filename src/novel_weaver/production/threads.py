# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Throughline thread service: persist and advance OPEN/TOUCHED/RESOLVED threads."""

from __future__ import annotations

from typing import Any

from novel_weaver.domain.models import Chapter, ThreadRecord
from novel_weaver.storage.repositories import StoryRepository


class ThreadService:
    """Canonical throughline bookkeeping (§ Phase 2/4 Thread checks)."""

    def __init__(self, repo: StoryRepository, *, actor: str = "threads") -> None:
        self.repo = repo
        self.actor = actor

    def ensure_thread(
        self,
        story_id: str,
        name: str,
        *,
        introduced_at: str = "",
        expected_resolution: str = "",
        related_entities: list[str] | None = None,
        obligations: list[str] | None = None,
    ) -> ThreadRecord:
        existing = self.repo.find_thread_by_name(story_id, name)
        if existing is not None:
            return existing
        thread = ThreadRecord.create(
            name=name,
            introduced_at=introduced_at or "ch0",
            expected_resolution=expected_resolution,
            related_entities=list(related_entities or []),
            obligations=list(obligations or []),
        )
        self.repo.save_thread(story_id, thread)
        return thread

    def touch_on_commit(
        self,
        story_id: str,
        chapter: Chapter,
        *,
        thread_keys: list[str] | None = None,
    ) -> list[ThreadRecord]:
        """Advance threads referenced by a committed chapter (fact_keys or explicit)."""
        keys = list(thread_keys or [])
        if not keys:
            keys = [
                k
                for k in (chapter.fact_keys_used or [])
                if k.startswith("thread.") or "thread" in k
            ]
        updated: list[ThreadRecord] = []
        ref = f"ch{chapter.number}"
        for key in keys:
            # Prefer name == key; else key's last segment as display name.
            name = key
            thread = self.repo.find_thread_by_name(story_id, name)
            if thread is None:
                thread = self.ensure_thread(story_id, name, introduced_at=ref)
            if thread.current_status == "OPEN":
                thread.current_status = "TOUCHED"
            thread.last_touched_at = ref
            thread.revision += 1
            self.repo.save_thread(story_id, thread)
            updated.append(thread)
        return updated

    def resolve(
        self, story_id: str, name: str, *, resolution_note: str = ""
    ) -> ThreadRecord | None:
        thread = self.repo.find_thread_by_name(story_id, name)
        if thread is None:
            return None
        thread.current_status = "RESOLVED"
        if resolution_note:
            thread.obligations = [
                o for o in thread.obligations if o != resolution_note
            ]
            thread.expected_resolution = resolution_note
        thread.revision += 1
        self.repo.save_thread(story_id, thread)
        return thread

    def abandon(self, story_id: str, name: str) -> ThreadRecord | None:
        thread = self.repo.find_thread_by_name(story_id, name)
        if thread is None:
            return None
        thread.current_status = "ABANDONED"
        thread.revision += 1
        self.repo.save_thread(story_id, thread)
        return thread

    def open_threads(self, story_id: str) -> list[ThreadRecord]:
        out: list[ThreadRecord] = []
        for status in ("OPEN", "TOUCHED"):
            out.extend(self.repo.list_threads(story_id, status=status))
        return out

    def summary(self, story_id: str) -> dict[str, Any]:
        all_threads = self.repo.list_threads(story_id)
        by_status: dict[str, int] = {}
        for t in all_threads:
            by_status[t.current_status] = by_status.get(t.current_status, 0) + 1
        return {
            "total": len(all_threads),
            "by_status": by_status,
            "open": [t.name for t in self.open_threads(story_id)],
        }
