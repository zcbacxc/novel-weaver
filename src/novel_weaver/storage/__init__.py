# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SQLite persistence for Canonical story state and runtime records.

Public surface:

- ``Database``: connection handle, schema bootstrap, additive migrations.
- ``StoryRepository``: map domain entities (stories, state, events,
  chapters, evidence, proposals, audit, checkpoints, threads,
  reconcile records) to SQLite rows.
"""

from novel_weaver.storage.db import Database
from novel_weaver.storage.repositories import StoryRepository

__all__ = ["Database", "StoryRepository"]
