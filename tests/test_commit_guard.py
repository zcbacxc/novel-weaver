"""Commit guard focused tests (duplicate coverage kept minimal)."""

from novel_weaver.truth.commit_guard import CommitGuard, CommitRequest, ProductionSession, RejectReason


def test_plan_revision_mismatch() -> None:
    guard = CommitGuard()
    session = ProductionSession("s", "st", 1, plan_revision=1, production_unit="ch1", context_fingerprint="x")
    req = CommitRequest(session, "c", "ch1")
    result = guard.validate(req, current_story_revision=1, current_plan_revision=2)
    assert result.reason is RejectReason.PLAN_REVISION_MISMATCH


def test_context_fingerprint_mismatch() -> None:
    guard = CommitGuard()
    session = ProductionSession("s", "st", 1, plan_revision=0, production_unit="ch1", context_fingerprint="old")
    req = CommitRequest(session, "c", "ch1")
    result = guard.validate(
        req,
        current_story_revision=1,
        current_plan_revision=0,
        current_context_fingerprint="new",
    )
    assert result.reason is RejectReason.CONTEXT_FINGERPRINT_MISMATCH


def test_unit_lock() -> None:
    guard = CommitGuard()
    guard.lock_unit("ch1")
    session = ProductionSession("s", "st", 0, 0, "ch1", "fp")
    req = CommitRequest(session, "c", "ch1")
    result = guard.validate(req, current_story_revision=0, current_plan_revision=0)
    assert result.reason is RejectReason.UNIT_LOCKED
