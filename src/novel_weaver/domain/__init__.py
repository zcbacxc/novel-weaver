# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Canonical domain types and rule-violation errors."""

from novel_weaver.domain.models import (
    Chapter,
    Character,
    Event,
    FactStatus,
    FactProposalRecord,
    ProductionUnitStatus,
    StateItem,
    Story,
    StoryRevision,
    ThreadRecord,
)
from novel_weaver.domain.errors import DomainError, GuardRejectError, StaleRevisionError

__all__ = [
    "Chapter",
    "Character",
    "Event",
    "FactStatus",
    "FactProposalRecord",
    "ProductionUnitStatus",
    "StateItem",
    "Story",
    "StoryRevision",
    "ThreadRecord",
    "DomainError",
    "GuardRejectError",
    "StaleRevisionError",
]
