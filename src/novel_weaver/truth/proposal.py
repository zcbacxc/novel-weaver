# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fact proposals and Canonical promotion rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from novel_weaver.domain.errors import DomainError
from novel_weaver.domain.models import FactStatus, FactProposalRecord, StateItem
from novel_weaver.truth.evidence import EvidenceStore


class PromotionError(DomainError):
    """Proposal cannot be promoted to Canonical."""


@dataclass
class FactProposal:
    """Working view over a persisted proposal plus claim payload and deps.

    Main interface: ``proposal_id``, ``evidence_refs``, ``status`` properties
    and ``promote_proposal`` for Canonical promotion.
    """

    record: FactProposalRecord
    claim_value: Any = None
    depends_on: list[str] = field(default_factory=list)

    @property
    def proposal_id(self) -> str:
        """Id of the underlying proposal record.

        Returns:
            Proposal identifier string.
        """
        return self.record.proposal_id

    @property
    def evidence_refs(self) -> list[str]:
        """Evidence ids that support this proposal.

        Returns:
            List of evidence identifiers from the record.
        """
        return self.record.evidence_refs

    @property
    def status(self) -> FactStatus:
        """Current fact status of the proposal.

        Returns:
            The record's ``FactStatus``.
        """
        return self.record.status


def promote_proposal(
    proposal: FactProposal,
    evidence_store: EvidenceStore,
    *,
    story_revision: int,
    allow_weak_evidence: bool = False,
) -> StateItem:
    """Promote a proposal to a Canonical StateItem.

    Rules (implementation plan §3.11 / §5.4 / §23.5):
    - Must have at least one existing Evidence ref (unless weak path for pending).
    - Unresolved strong conflicts block promotion.
    - PROPOSED never auto-upgrades without this explicit call.

    Args:
        proposal: Proposal to promote.
        evidence_store: Store used to resolve evidence refs and confidence.
        story_revision: Story revision stamped as ``effective_from`` on the item.
        allow_weak_evidence: When ``True``, skip the minimum-confidence gate.

    Returns:
        The new ``CANONICAL`` ``StateItem`` linked from the proposal.

    Raises:
        PromotionError: If the proposal is already terminal, has unresolved
            conflicts, lacks evidence refs, or any evidence is missing or too weak.
    """
    rec = proposal.record
    if rec.status in (FactStatus.CANONICAL, FactStatus.SUPERSEDED, FactStatus.INVALIDATED):
        raise PromotionError(f"proposal {rec.proposal_id} already terminal: {rec.status}")

    if rec.conflicts:
        raise PromotionError(
            f"proposal {rec.proposal_id} has unresolved conflicts: {rec.conflicts}"
        )

    if not rec.evidence_refs:
        raise PromotionError(
            f"proposal {rec.proposal_id} has no evidence; cannot enter Canon"
        )

    for eid in rec.evidence_refs:
        ev = evidence_store.get(eid)
        if ev is None:
            raise PromotionError(f"evidence {eid} not found for proposal {rec.proposal_id}")
        if ev.confidence < 0.3 and not allow_weak_evidence:
            raise PromotionError(
                f"evidence {eid} confidence too low ({ev.confidence}); keep as PROPOSED"
            )

    item = StateItem.create(
        key=rec.target_key,
        value=proposal.claim_value if proposal.claim_value is not None else rec.claim,
        kind=rec.target_kind,
        status=FactStatus.CANONICAL,
        source=f"proposal:{rec.proposal_id}",
        confidence=min(1.0, max(ev.confidence for eid in rec.evidence_refs for ev in [evidence_store.get(eid)] if ev)),
        depends_on=proposal.depends_on,
    )
    item.effective_from = story_revision
    item.provenance = {
        "proposal_id": rec.proposal_id,
        "evidence_refs": list(rec.evidence_refs),
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "proposed_by": rec.proposed_by,
    }
    rec.status = FactStatus.CANONICAL
    rec.promoted_item_id = item.item_id
    return item
