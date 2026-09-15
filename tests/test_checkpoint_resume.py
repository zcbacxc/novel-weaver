"""Phase 2 checkpoint / resume foundation tests.

Covers:
- Checkpoint dataclass + RuntimeRun helpers
- Repository save/load/list (idempotent)
- decide_resume_action matrix
- Runtime failure must not mutate Canonical story revision
"""

from __future__ import annotations

from pathlib import Path

import pytest

from novel_weaver.domain.models import Story
from novel_weaver.runtime.checkpoint import (
    Checkpoint,
    RunStatus,
    RunStep,
    RuntimeRun,
    StepStatus,
    run_from_checkpoints,
    stable_checkpoint_id,
)
from novel_weaver.runtime.resume import (
    ResumeAction,
    decide_resume_action,
    next_step_name_after_action,
)
from novel_weaver.storage.db import Database
from novel_weaver.storage.repositories import StoryRepository


@pytest.fixture()
def repo(tmp_path: Path):
    db = Database(tmp_path / "ckpt.sqlite3")
    r = StoryRepository(db)
    yield r
    db.close()


def _make_run(**overrides: object) -> RuntimeRun:
    defaults: dict = {
        "run_id": "run_abc",
        "story_id": "story_1",
        "production_unit": "ch_1",
        "base_story_revision": 3,
    }
    defaults.update(overrides)
    return RuntimeRun(**defaults)  # type: ignore[arg-type]


# --- Checkpoint / RuntimeRun ---


def test_checkpoint_for_step_roundtrip_fields() -> None:
    run = _make_run()
    step = RunStep(name="generate", status=StepStatus.SUCCEEDED, payload={"tokens": 12})
    run.upsert_step(step)
    ckpt = Checkpoint.for_step(run, step)
    assert ckpt.run_id == "run_abc"
    assert ckpt.story_id == "story_1"
    assert ckpt.production_unit == "ch_1"
    assert ckpt.step == "generate"
    assert ckpt.status is StepStatus.SUCCEEDED
    assert ckpt.payload == {"tokens": 12}
    assert ckpt.base_story_revision == 3
    assert ckpt.checkpoint_id == stable_checkpoint_id("run_abc", "generate")
    assert ckpt.created_at is not None


def test_runtime_run_upsert_and_last_step() -> None:
    run = _make_run()
    run.upsert_step(RunStep(name="plan"))
    run.upsert_step(RunStep(name="generate", status=StepStatus.FAILED, error="boom"))
    assert run.last_step() is not None
    assert run.last_step().name == "generate"
    # replace by name
    run.upsert_step(RunStep(name="generate", status=StepStatus.SUCCEEDED))
    assert len(run.steps) == 2
    assert run.step("generate").status is StepStatus.SUCCEEDED
    assert run.next_pending_step().name == "plan"


def test_run_from_checkpoints_rebuilds_run() -> None:
    run = _make_run()
    s1 = RunStep(name="plan", status=StepStatus.SUCCEEDED, payload={"outline": "x"})
    s2 = RunStep(name="generate", status=StepStatus.FAILED, error="timeout")
    run.upsert_step(s1)
    run.upsert_step(s2)
    ckpts = [Checkpoint.for_step(run, s1), Checkpoint.for_step(run, s2)]
    rebuilt = run_from_checkpoints("run_abc", ckpts)
    assert rebuilt is not None
    assert rebuilt.run_id == "run_abc"
    assert rebuilt.base_story_revision == 3
    assert rebuilt.status is RunStatus.FAILED
    assert rebuilt.step("plan").status is StepStatus.SUCCEEDED
    assert rebuilt.step("generate").status is StepStatus.FAILED


def test_run_from_checkpoints_empty_and_mixed() -> None:
    assert run_from_checkpoints("r", []) is None
    a = Checkpoint.for_step(_make_run(run_id="r1"), RunStep(name="plan"))
    b = Checkpoint.for_step(_make_run(run_id="r2"), RunStep(name="plan"))
    with pytest.raises(ValueError):
        run_from_checkpoints("r1", [a, b])


# --- Repository CRUD ---


def test_save_load_checkpoint_roundtrip(repo: StoryRepository) -> None:
    run = _make_run(story_id="story_rt")
    step = RunStep(name="validate", status=StepStatus.SUCCEEDED, payload={"ok": True})
    ckpt = Checkpoint.for_step(run, step)
    repo.save_checkpoint(ckpt)
    loaded = repo.load_checkpoint(ckpt.checkpoint_id)
    assert loaded is not None
    assert loaded.run_id == "run_abc"
    assert loaded.story_id == "story_rt"
    assert loaded.production_unit == "ch_1"
    assert loaded.step == "validate"
    assert loaded.status is StepStatus.SUCCEEDED
    assert loaded.payload == {"ok": True}
    assert loaded.base_story_revision == 3


def test_load_checkpoint_twice_idempotent(repo: StoryRepository) -> None:
    run = _make_run(story_id="story_idem")
    step = RunStep(name="plan", status=StepStatus.SUCCEEDED)
    ckpt = Checkpoint.for_step(run, step)
    repo.save_checkpoint(ckpt)
    first = repo.load_checkpoint(ckpt.checkpoint_id)
    second = repo.load_checkpoint(ckpt.checkpoint_id)
    assert first is not None and second is not None
    assert first == second
    # list also stable
    a = repo.list_checkpoints_for_story("story_idem")
    b = repo.list_checkpoints_for_story("story_idem")
    assert a == b
    assert len(a) == 1


def test_save_checkpoint_same_id_overwrites(repo: StoryRepository) -> None:
    run = _make_run(story_id="story_ow")
    step = RunStep(name="generate", status=StepStatus.RUNNING)
    ckpt = Checkpoint.for_step(run, step)
    repo.save_checkpoint(ckpt)
    step.mark_failed("timeout", retryable=True)
    ckpt2 = Checkpoint.for_step(run, step)
    assert ckpt2.checkpoint_id == ckpt.checkpoint_id
    repo.save_checkpoint(ckpt2)
    items = repo.list_checkpoints_for_story("story_ow")
    assert len(items) == 1
    assert items[0].status is StepStatus.FAILED


def test_list_checkpoints_for_story_orders_and_filters(repo: StoryRepository) -> None:
    run_a = _make_run(run_id="run_a", story_id="story_list")
    run_b = _make_run(run_id="run_b", story_id="story_other")
    for name in ("plan", "generate"):
        repo.save_checkpoint(
            Checkpoint.for_step(run_a, RunStep(name=name, status=StepStatus.SUCCEEDED))
        )
    repo.save_checkpoint(Checkpoint.for_step(run_b, RunStep(name="plan")))
    listed = repo.list_checkpoints_for_story("story_list")
    assert [c.step for c in listed] == ["plan", "generate"]
    assert all(c.story_id == "story_list" for c in listed)


def test_checkpoint_ops_do_not_mutate_canonical_revision(repo: StoryRepository) -> None:
    """Runtime failure / checkpoint I/O must never bump Canonical revision."""
    story = Story.create("Canon Safe")
    story.current_canonical_revision = 7
    repo.save_story(story)
    before = repo.get_story(story.story_id).current_canonical_revision

    run = _make_run(story_id=story.story_id, base_story_revision=before)
    step = RunStep(name="generate", status=StepStatus.RUNNING)
    run.upsert_step(step)
    step.mark_failed("provider down", retryable=True)
    run.status = RunStatus.FAILED
    ckpt = Checkpoint.for_step(run, step)
    repo.save_checkpoint(ckpt)
    repo.load_checkpoint(ckpt.checkpoint_id)
    repo.list_checkpoints_for_story(story.story_id)

    after = repo.get_story(story.story_id)
    assert after.current_canonical_revision == before == 7
    # no orphan story_revisions from runtime path
    revs = repo.db.execute(
        "SELECT COUNT(*) AS n FROM story_revisions WHERE story_id = ?",
        (story.story_id,),
    ).fetchone()
    assert revs["n"] == 0


def test_load_missing_checkpoint_returns_none(repo: StoryRepository) -> None:
    assert repo.load_checkpoint("ckpt_missing_step") is None


# --- decide_resume_action matrix ---


def test_resume_when_no_run_or_no_steps() -> None:
    assert decide_resume_action(None) is ResumeAction.RESUME
    assert decide_resume_action(_make_run()) is ResumeAction.RESUME


def test_resume_when_last_succeeded_or_skipped_or_pending() -> None:
    for status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED, StepStatus.PENDING):
        run = _make_run()
        run.upsert_step(RunStep(name="generate", status=status))
        assert decide_resume_action(run) is ResumeAction.RESUME, status


def test_retry_step_when_running_or_retryable_failed() -> None:
    run = _make_run()
    run.upsert_step(RunStep(name="generate", status=StepStatus.RUNNING))
    assert decide_resume_action(run) is ResumeAction.RETRY_STEP

    run2 = _make_run()
    run2.upsert_step(
        RunStep(name="generate", status=StepStatus.FAILED, retryable=True, error="net")
    )
    assert decide_resume_action(run2) is ResumeAction.RETRY_STEP


def test_replan_when_non_retryable_failed_or_revision_moved() -> None:
    run = _make_run()
    run.upsert_step(
        RunStep(name="generate", status=StepStatus.FAILED, retryable=False, error="hard")
    )
    assert decide_resume_action(run) is ResumeAction.REPLAN

    run2 = _make_run(base_story_revision=3)
    run2.upsert_step(RunStep(name="generate", status=StepStatus.SUCCEEDED))
    assert decide_resume_action(run2, current_story_revision=5) is ResumeAction.REPLAN


def test_abort_when_run_aborted() -> None:
    run = _make_run(status=RunStatus.ABORTED)
    run.upsert_step(RunStep(name="generate", status=StepStatus.FAILED))
    assert decide_resume_action(run) is ResumeAction.ABORT


def test_next_step_name_helper() -> None:
    run = _make_run()
    run.upsert_step(RunStep(name="plan", status=StepStatus.SUCCEEDED))
    run.upsert_step(RunStep(name="generate", status=StepStatus.FAILED, retryable=True))
    assert (
        next_step_name_after_action(run, ResumeAction.RETRY_STEP) == "generate"
    )
    assert next_step_name_after_action(run, ResumeAction.ABORT) is None
    assert next_step_name_after_action(run, ResumeAction.REPLAN) is None
    # RESUME with a pending step
    run.upsert_step(RunStep(name="validate", status=StepStatus.PENDING))
    assert next_step_name_after_action(run, ResumeAction.RESUME) == "validate"


def test_end_to_end_checkpoint_then_resume_decision(repo: StoryRepository) -> None:
    """Simulate crash mid-generate, reload checkpoints, decide RETRY_STEP."""
    story = Story.create("Resume E2E")
    repo.save_story(story)
    rev = story.current_canonical_revision

    run = _make_run(run_id="run_e2e", story_id=story.story_id, base_story_revision=rev)
    plan = RunStep(name="plan", status=StepStatus.SUCCEEDED, payload={"units": 1})
    gen = RunStep(name="generate", status=StepStatus.RUNNING)
    run.upsert_step(plan)
    run.upsert_step(gen)
    run.status = RunStatus.RUNNING
    repo.save_checkpoint(Checkpoint.for_step(run, plan))
    repo.save_checkpoint(Checkpoint.for_step(run, gen))

    loaded = repo.list_checkpoints_for_story(story.story_id)
    rebuilt = run_from_checkpoints("run_e2e", loaded)
    assert rebuilt is not None
    action = decide_resume_action(rebuilt, current_story_revision=rev)
    assert action is ResumeAction.RETRY_STEP
    assert next_step_name_after_action(rebuilt, action) == "generate"
    # Canonical untouched
    assert repo.get_story(story.story_id).current_canonical_revision == rev
