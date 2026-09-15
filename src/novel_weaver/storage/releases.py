# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Immutable Canonical release registry (§16.3)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from novel_weaver.domain.errors import DomainError
from novel_weaver.storage.repositories import StoryRepository
from novel_weaver.storage.snapshot import export_story_snapshot


def _now() -> datetime:
    """Current UTC timestamp used for release records."""
    return datetime.now(timezone.utc)


@dataclass
class ReleaseRecord:
    """Metadata for one immutable Canonical release.

    Attributes:
        release_id: Stable release identity.
        story_id: Owning story identity.
        sequence: Monotonic per-story release number.
        story_revision: Canonical revision frozen by this release.
        created_at: ISO-8601 creation timestamp.
        snapshot_path: Filesystem path of the snapshot JSON.
        label: Optional display label.
        notes: Optional free-form release notes.
    """

    release_id: str
    story_id: str
    sequence: int
    story_revision: int
    created_at: str
    snapshot_path: str
    label: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize the record for the append-only JSON index.

        Returns:
            Plain dict suitable for JSON encoding.
        """
        return {
            "release_id": self.release_id,
            "story_id": self.story_id,
            "sequence": self.sequence,
            "story_revision": self.story_revision,
            "created_at": self.created_at,
            "snapshot_path": self.snapshot_path,
            "label": self.label,
            "notes": self.notes,
        }


class ReleaseRegistry:
    """Append-only release list; each release freezes a Canonical snapshot.

    Decision: JSON registry + snapshot files (no update/delete API).
    Alternative: DB table with mutable labels — rejected for immutability.

    Main interface:
        ``list_releases``, ``next_sequence``, ``create_release``,
        ``get_release``, ``load_release_snapshot``.
    """

    def __init__(self, root: Path | str) -> None:
        """Create the registry root and locate the index file.

        Args:
            root: Workspace directory holding ``releases.json`` and snapshots.
        """
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "releases.json"

    def _load_index(self) -> list[dict[str, Any]]:
        """Load release index rows; empty list on missing or corrupt index."""
        if not self.index_path.exists():
            return []
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def _save_index(self, rows: list[dict[str, Any]]) -> None:
        """Persist the full release index (append-only callers rebuild the list)."""
        self.index_path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def list_releases(self, story_id: str | None = None) -> list[ReleaseRecord]:
        """List known releases, optionally filtered by story.

        Args:
            story_id: Restrict to this story when provided.

        Returns:
            Release records in index order.
        """
        rows = self._load_index()
        out: list[ReleaseRecord] = []
        for r in rows:
            if story_id and r.get("story_id") != story_id:
                continue
            out.append(
                ReleaseRecord(
                    release_id=r["release_id"],
                    story_id=r["story_id"],
                    sequence=int(r["sequence"]),
                    story_revision=int(r["story_revision"]),
                    created_at=r["created_at"],
                    snapshot_path=r["snapshot_path"],
                    label=r.get("label", ""),
                    notes=r.get("notes", ""),
                )
            )
        return out

    def next_sequence(self, story_id: str) -> int:
        """Compute the next release sequence number for a story.

        Args:
            story_id: Owning story identity.

        Returns:
            One past the current maximum sequence (or 1 when none exist).
        """
        rels = self.list_releases(story_id)
        return (max((r.sequence for r in rels), default=0) + 1)

    def create_release(
        self,
        repo: StoryRepository,
        story_id: str,
        *,
        label: str = "",
        notes: str = "",
    ) -> ReleaseRecord:
        """Freeze the current Canonical story state as a new release.

        Args:
            repo: Repository providing Canonical reads.
            story_id: Story to snapshot and release.
            label: Optional display label; defaults to ``Release NNN``.
            notes: Optional free-form notes.

        Returns:
            The newly appended ``ReleaseRecord``.

        Raises:
            DomainError: If the story does not exist.
        """
        story = repo.get_story(story_id)
        if story is None:
            raise DomainError(f"story not found: {story_id}")
        seq = self.next_sequence(story_id)
        release_id = f"rel_{story_id}_{seq:04d}"
        snap_dir = self.root / story_id
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap_path = snap_dir / f"{release_id}.json"
        payload = export_story_snapshot(repo, story_id)
        snap_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        record = ReleaseRecord(
            release_id=release_id,
            story_id=story_id,
            sequence=seq,
            story_revision=story.current_canonical_revision,
            created_at=_now().isoformat(),
            snapshot_path=str(snap_path),
            label=label or f"Release {seq:03d}",
            notes=notes,
        )
        rows = self._load_index()
        rows.append(record.to_dict())
        self._save_index(rows)
        return record

    def get_release(self, release_id: str) -> ReleaseRecord | None:
        """Look up one release by id.

        Args:
            release_id: Release primary key.

        Returns:
            The release record, or ``None`` when not found.
        """
        for r in self.list_releases():
            if r.release_id == release_id:
                return r
        return None

    def load_release_snapshot(self, release_id: str) -> dict[str, Any]:
        """Load the frozen snapshot payload for a release.

        Args:
            release_id: Release primary key.

        Returns:
            Parsed snapshot dict (meta, story, state_items, chapters, ...).

        Raises:
            DomainError: If the release or its snapshot file is missing.
        """
        rec = self.get_release(release_id)
        if rec is None:
            raise DomainError(f"release not found: {release_id}")
        path = Path(rec.snapshot_path)
        if not path.exists():
            raise DomainError(f"release snapshot missing: {path}")
        return json.loads(path.read_text(encoding="utf-8"))
