# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Resume decision for interrupted production runs (实现方案 §15.2).

Resume 不是简单继续最后一步。恢复时先判断 Canonical 是否仍对齐、
最后一步是否可安全重试，再决定动作。

Decision matrix (`decide_resume_action`):

| Condition                                      | Action     |
|------------------------------------------------|------------|
| run is None / no steps                         | RESUME     |
| run.status == ABORTED                          | ABORT      |
| current_story_revision provided and != base    | REPLAN     |
| last step SUCCEEDED / SKIPPED / PENDING        | RESUME     |
| last step RUNNING (crash mid-step)             | RETRY_STEP |
| last step FAILED and retryable                 | RETRY_STEP |
| last step FAILED and not retryable             | REPLAN     |

Notes:
- RESUME continues from the next unfinished step; it never re-commits.
- RETRY_STEP re-executes only the failed/unfinished step.
- REPLAN discards the current plan against a moved Canonical revision
  or a non-retryable failure.
- ABORT stops the run; operator intervention required.

This module is pure decision logic: it never writes Canonical story state.
"""

from __future__ import annotations

from enum import Enum

from novel_weaver.runtime.checkpoint import RunStatus, RuntimeRun, StepStatus


class ResumeAction(str, Enum):
    """Action the orchestrator should take after an interrupted run."""

    RESUME = "RESUME"
    RETRY_STEP = "RETRY_STEP"
    REPLAN = "REPLAN"
    ABORT = "ABORT"


def decide_resume_action(
    run: RuntimeRun | None,
    *,
    current_story_revision: int | None = None,
) -> ResumeAction:
    """Decide how to continue a run after interruption.

    Args:
        run: Reconstructed runtime run, or None if nothing was checkpointed.
        current_story_revision: Live Canonical revision, if known. When it
            differs from ``run.base_story_revision``, the plan is stale.

    Returns:
        ResumeAction from the matrix in this module's docstring.
    """
    if run is None or not run.steps:
        return ResumeAction.RESUME

    if run.status is RunStatus.ABORTED:
        return ResumeAction.ABORT

    if (
        current_story_revision is not None
        and current_story_revision != run.base_story_revision
    ):
        return ResumeAction.REPLAN

    last = run.last_step()
    if last is None:
        return ResumeAction.RESUME

    if last.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED, StepStatus.PENDING):
        return ResumeAction.RESUME

    if last.status is StepStatus.RUNNING:
        # Crash mid-step: the step did not finish; retry is safe when marked retryable.
        return ResumeAction.RETRY_STEP if last.retryable else ResumeAction.REPLAN

    if last.status is StepStatus.FAILED:
        return ResumeAction.RETRY_STEP if last.retryable else ResumeAction.REPLAN

    return ResumeAction.ABORT


def next_step_name_after_action(
    run: RuntimeRun,
    action: ResumeAction,
) -> str | None:
    """Helper: which step name the orchestrator should enter next, if any.

    Pure advisory — does not mutate the run or Canonical state.

    Args:
        run: Reconstructed runtime run.
        action: Resume action chosen by decide_resume_action.

    Returns:
        Next step name, or None when there is nothing to enter.
    """
    if action is ResumeAction.ABORT or action is ResumeAction.REPLAN:
        return None
    if action is ResumeAction.RETRY_STEP:
        last = run.last_step()
        return last.name if last else None
    # RESUME
    pending = run.next_pending_step()
    if pending is not None:
        return pending.name
    last = run.last_step()
    if last is not None and last.status is not StepStatus.SUCCEEDED:
        return last.name
    return None
