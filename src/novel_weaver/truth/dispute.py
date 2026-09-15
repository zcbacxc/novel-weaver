# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""DISPUTED fact resolution workflow (§5.4 / §7)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from novel_weaver.domain.errors import DomainError
from novel_weaver.domain.models import FactStatus, StateItem
from novel_weaver.storage.repositories import StoryRepository
from novel_weaver.truth.audit import AuditLog


class DisputeOutcome(str, Enum):
    KEEP = "KEEP"
    SUPERSEDE = "SUPERSEDE"
    INVALIDATE = "INVALIDATE"


@dataclass
class DisputeResult:
    ok: bool
    outcome: DisputeOutcome
    key: str
    kept_item_id: str | None
    message: str
    data: dict[str, Any]


class DisputeService:
    """Mark conflicting Canonical facts DISPUTED and resolve them explicitly.

    Decision: author/commit-guard path owns resolution — no auto-merge.
    Alternative: confidence-based auto-pick — rejected (plan forbids model
    guesses silently becoming Canon).
    """

    def __init__(
        self, repo: StoryRepository, *, audit: AuditLog | None = None, actor: str = "dispute"
    ) -> None:
        self.repo = repo
        self.audit = audit or AuditLog()
        self.actor = actor

    def mark_disputed(
        self, story_id: str, item_id: str, *, reason: str = "conflict"
    ) -> StateItem:
        item = self.repo.get_state_item(item_id)
        if item is None:
            raise DomainError(f"state item not found: {item_id}")
        if item.status is FactStatus.CANONICAL:
            item.status = FactStatus.DISPUTED
            item.provenance = {
                **item.provenance,
                "disputed_reason": reason,
                "disputed_at": datetime.now(timezone.utc).isoformat(),
            }
            self.repo.upsert_state_item(story_id, item)
            self.audit.record(
                "FACT_DISPUTED",
                actor=self.actor,
                story_id=story_id,
                base_revision=self._rev(story_id),
                item_id=item_id,
                key=item.key,
                reason=reason,
            )
        return item

    def mark_key_disputed(self, story_id: str, key: str, *, reason: str = "conflict") -> list[StateItem]:
        marked: list[StateItem] = []
        for item in self.repo.find_state_by_key(story_id, key):
            if item.status is FactStatus.CANONICAL:
                marked.append(self.mark_disputed(story_id, item.item_id, reason=reason))
        return marked

    def resolve(
        self,
        story_id: str,
        key: str,
        *,
        outcome: DisputeOutcome,
        keep_item_id: str | None = None,
        new_value: Any = None,
        reason: str = "",
    ) -> DisputeResult:
        items = [
            i
            for i in self.repo.find_state_by_key(story_id, key)
            if i.status in (FactStatus.DISPUTED, FactStatus.CANONICAL)
        ]
        if not items:
            return DisputeResult(
                ok=False,
                outcome=outcome,
                key=key,
                kept_item_id=None,
                message=f"no disputed/canonical items for key {key}",
                data={},
            )

        if outcome is DisputeOutcome.KEEP:
            keep = None
            if keep_item_id:
                keep = next((i for i in items if i.item_id == keep_item_id), None)
            if keep is None:
                # Prefer the highest revision disputed/canonical.
                keep = max(items, key=lambda i: (i.revision, i.item_id))
            for other in items:
                if other.item_id == keep.item_id:
                    continue
                other.status = FactStatus.SUPERSEDED
                other.superseded_by = keep.item_id
                other.provenance = {
                    **other.provenance,
                    "dispute_resolved": outcome.value,
                    "dispute_reason": reason,
                }
                self.repo.upsert_state_item(story_id, other)
            keep.status = FactStatus.CANONICAL
            keep.provenance = {
                **keep.provenance,
                "dispute_resolved": outcome.value,
                "dispute_reason": reason,
            }
            self.repo.upsert_state_item(story_id, keep)
            kept_id = keep.item_id
            message = f"kept {kept_id} for {key}"
        elif outcome is DisputeOutcome.SUPERSEDE:
            # Keep first item as base; write a new canonical value if provided.
            base = max(items, key=lambda i: (i.revision, i.item_id))
            if new_value is None:
                return DisputeResult(
                    ok=False,
                    outcome=outcome,
                    key=key,
                    kept_item_id=None,
                    message="SUPERSEDE requires new_value",
                    data={},
                )
            base.status = FactStatus.SUPERSEDED
            base.superseded_by = f"dispute:{key}:{self._rev(story_id) + 1}"
            self.repo.upsert_state_item(story_id, base)
            replacement = StateItem.create(
                key=key,
                value=new_value,
                kind=base.kind,
                status=FactStatus.CANONICAL,
                source="dispute_resolution",
            )
            replacement.provenance = {
                "origin": "dispute_supersede",
                "replaces": base.item_id,
                "reason": reason,
            }
            self.repo.upsert_state_item(story_id, replacement)
            self.repo.bump_story_revision(story_id, f"dispute-supersede:{key}")
            kept_id = replacement.item_id
            message = f"superseded {base.item_id} with {replacement.item_id}"
        else:  # INVALIDATE
            for item in items:
                item.status = FactStatus.INVALIDATED
                item.invalidated_by = f"dispute:{reason or 'invalidate'}"
                item.provenance = {
                    **item.provenance,
                    "dispute_resolved": outcome.value,
                    "dispute_reason": reason,
                }
                self.repo.upsert_state_item(story_id, item)
            kept_id = None
            message = f"invalidated {len(items)} items for {key}"

        new_rev = self._rev(story_id)
        self.audit.record(
            "DISPUTE_RESOLVED",
            actor=self.actor,
            story_id=story_id,
            base_revision=new_rev,
            key=key,
            outcome=outcome.value,
            kept_item_id=kept_id,
            reason=reason,
        )
        return DisputeResult(
            ok=True,
            outcome=outcome,
            key=key,
            kept_item_id=kept_id,
            message=message,
            data={"item_count": len(items)},
        )

    def _rev(self, story_id: str) -> int:
        story = self.repo.get_story(story_id)
        return story.current_canonical_revision if story else -1
