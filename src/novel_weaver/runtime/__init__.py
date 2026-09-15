# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Runtime package: execution state, checkpoints, resume decisions.

Runtime State is execution-only (实现方案 §17). It must never become the
source of truth for story facts; Canonical changes go through Commit only.
"""

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

__all__ = [
    "Checkpoint",
    "ResumeAction",
    "RunStatus",
    "RunStep",
    "RuntimeRun",
    "StepStatus",
    "decide_resume_action",
    "next_step_name_after_action",
    "run_from_checkpoints",
    "stable_checkpoint_id",
]
