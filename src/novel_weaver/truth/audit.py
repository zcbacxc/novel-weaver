# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Append-only audit trail for truth-changing operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AuditEntry:
    audit_id: str
    action: str
    actor: str
    story_id: str
    base_revision: int
    payload: dict[str, Any] = field(default_factory=dict)
    outcome: str = "OK"  # OK | REJECT | ERROR
    created_at: datetime = field(default_factory=_now)


class AuditLog:
    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def record(
        self,
        action: str,
        *,
        actor: str,
        story_id: str,
        base_revision: int,
        outcome: str = "OK",
        **payload: Any,
    ) -> AuditEntry:
        entry = AuditEntry(
            audit_id=f"aud_{uuid4().hex[:12]}",
            action=action,
            actor=actor,
            story_id=story_id,
            base_revision=base_revision,
            outcome=outcome,
            payload=payload,
        )
        self._entries.append(entry)
        return entry

    def list_for_story(self, story_id: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.story_id == story_id]

    def list_all(self) -> list[AuditEntry]:
        return list(self._entries)
