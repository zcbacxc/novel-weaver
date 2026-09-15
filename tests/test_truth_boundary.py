"""Truth boundary tests: evidence, promotion, commit guard."""

from __future__ import annotations

import pytest

from novel_weaver.domain.errors import GuardRejectError
from novel_weaver.domain.models import FactStatus, FactProposalRecord, StateItem
from novel_weaver.truth.commit_guard import (
    CommitGuard,
    CommitRequest,
    ProductionSession,
    RejectReason,
)
from novel_weaver.truth.evidence import Evidence, EvidenceStore
from novel_weaver.truth.proposal import FactProposal, PromotionError, promote_proposal


def test_evidence_requires_claim() -> None:
    with pytest.raises(ValueError):
        Evidence.capture("author", "x", "   ")


def test_proposal_without_evidence_cannot_promote() -> None:
    store = EvidenceStore()
    rec = FactProposalRecord.create("claim", evidence_refs=[], confidence=0.9)
    proposal = FactProposal(record=rec, claim_value=1)
    with pytest.raises(PromotionError):
        promote_proposal(proposal, store, story_revision=0)


def test_promote_with_evidence_creates_canonical() -> None:
    store = EvidenceStore()
    ev = Evidence.capture("author", "outline", "顾言受伤", confidence=0.9)
    store.add(ev)
    rec = FactProposalRecord.create(
        "顾言受伤",
        evidence_refs=[ev.evidence_id],
        confidence=0.9,
        target_key="character.gu_yan.injury",
        target_kind="character",
    )
    proposal = FactProposal(record=rec, claim_value="right_hand")
    item = promote_proposal(proposal, store, story_revision=3)
    assert item.status is FactStatus.CANONICAL
    assert item.value == "right_hand"
    assert item.effective_from == 3
    assert rec.status is FactStatus.CANONICAL
    assert rec.promoted_item_id == item.item_id


def test_promote_rejects_unknown_evidence_id() -> None:
    store = EvidenceStore()
    rec = FactProposalRecord.create("x", evidence_refs=["missing"])
    with pytest.raises(PromotionError):
        promote_proposal(FactProposal(record=rec), store, story_revision=0)


def test_commit_guard_rejects_stale_story_revision() -> None:
    guard = CommitGuard()
    session = ProductionSession(
        session_id="s1",
        story_id="st1",
        base_story_revision=1,
        plan_revision=0,
        production_unit="ch1",
        context_fingerprint="abc",
    )
    req = CommitRequest(session=session, candidate_id="c1", target_unit="ch1")
    result = guard.validate(req, current_story_revision=2, current_plan_revision=0)
    assert not result.accepted
    assert result.reason is RejectReason.STORY_REVISION_MISMATCH


def test_commit_guard_rejects_double_commit() -> None:
    guard = CommitGuard()
    session = ProductionSession(
        session_id="s1",
        story_id="st1",
        base_story_revision=1,
        plan_revision=0,
        production_unit="ch1",
        context_fingerprint="abc",
    )
    req = CommitRequest(session=session, candidate_id="c1", target_unit="ch1")
    guard.mark_committed("ch1")
    result = guard.validate(req, current_story_revision=1, current_plan_revision=0)
    assert result.reason is RejectReason.ALREADY_COMMITTED


def test_commit_guard_accepts_matching_session() -> None:
    guard = CommitGuard()
    session = ProductionSession(
        session_id="s1",
        story_id="st1",
        base_story_revision=5,
        plan_revision=2,
        production_unit="ch9",
        context_fingerprint="fp",
    )
    req = CommitRequest(session=session, candidate_id="c1", target_unit="ch9")
    result = guard.validate(req, current_story_revision=5, current_plan_revision=2)
    assert result.accepted


def test_commit_guard_raise_helper() -> None:
    guard = CommitGuard()
    session = ProductionSession(
        session_id="s",
        story_id="st",
        base_story_revision=0,
        plan_revision=0,
        production_unit="u",
        context_fingerprint="",
    )
    req = CommitRequest(session=session, candidate_id="c", target_unit="other")
    result = guard.validate(req, current_story_revision=0, current_plan_revision=0)
    with pytest.raises(GuardRejectError):
        guard.raise_if_rejected(result)
