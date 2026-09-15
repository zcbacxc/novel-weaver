# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SQLite connection and schema bootstrap."""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Canonical story core. Each row is one long-form novel being produced.
SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    story_id TEXT PRIMARY KEY,              -- stable story identity
    title TEXT NOT NULL,                    -- display title
    premise TEXT NOT NULL DEFAULT '',       -- one-line premise
    creative_intent TEXT NOT NULL DEFAULT '', -- author creative direction
    constraints_json TEXT NOT NULL DEFAULT '{}', -- production constraints payload
    current_canonical_revision INTEGER NOT NULL DEFAULT 0, -- commit-guard base revision
    lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE', -- ACTIVE | ARCHIVED | ...
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Immutable revision log for Canon history (why a story revision exists).
CREATE TABLE IF NOT EXISTS story_revisions (
    story_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    checkpoint_ref TEXT,                    -- optional runtime checkpoint link
    PRIMARY KEY (story_id, revision)
);

-- Canonical fact slots (character/world/timeline/thread/...).
CREATE TABLE IF NOT EXISTS state_items (
    item_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    key TEXT NOT NULL,                      -- namespaced fact key
    value_json TEXT NOT NULL,               -- fact payload
    kind TEXT NOT NULL,                     -- character|world|location|timeline|...
    status TEXT NOT NULL,                   -- FactStatus lifecycle
    revision INTEGER NOT NULL DEFAULT 0,    -- Canon revision when accepted
    source TEXT NOT NULL DEFAULT '',        -- provenance origin
    confidence REAL NOT NULL DEFAULT 1.0,   -- evidence strength
    effective_from INTEGER,                 -- narrative start chapter (inclusive)
    effective_to INTEGER,                   -- narrative end chapter (inclusive/null)
    provenance_json TEXT NOT NULL DEFAULT '{}',
    superseded_by TEXT,                     -- replacement item_id
    invalidated_by TEXT,                    -- invalidation cause ref
    depends_on_json TEXT NOT NULL DEFAULT '[]' -- dependency keys for impact analysis
);
-- Lookup facts by story+key during context pack and impact analysis.
CREATE INDEX IF NOT EXISTS idx_state_items_story_key ON state_items(story_id, key);
-- Filter active/canonical facts without full table scan.
CREATE INDEX IF NOT EXISTS idx_state_items_story_status ON state_items(story_id, status);

-- Narrative event ledger (what happened, independent of chapter text).
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    time_ref TEXT NOT NULL,                 -- stable ordering token
    summary TEXT NOT NULL,
    participants_json TEXT NOT NULL DEFAULT '[]',
    location TEXT NOT NULL DEFAULT '',
    claims_json TEXT NOT NULL DEFAULT '{}', -- claims extracted from this event
    source_chapter TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    revision INTEGER NOT NULL DEFAULT 0,
    provenance_json TEXT NOT NULL DEFAULT '{}'
);
-- Chronology queries by story.
CREATE INDEX IF NOT EXISTS idx_events_story ON events(story_id);

-- Committed chapter text and production metadata.
CREATE TABLE IF NOT EXISTS chapters (
    chapter_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    plan TEXT NOT NULL DEFAULT '',          -- rolling plan slot used for this chapter
    content TEXT NOT NULL DEFAULT '',       -- Canonical prose after commit
    status TEXT NOT NULL DEFAULT 'PLANNED',
    revision INTEGER NOT NULL DEFAULT 0,
    depends_on_json TEXT NOT NULL DEFAULT '[]', -- upstream chapter ids
    fact_keys_used_json TEXT NOT NULL DEFAULT '[]', -- facts this chapter consumes
    provenance_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (story_id, number)               -- one Canon chapter per slot
);

-- Evidence rows supporting fact proposals (never auto-promoted alone).
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    source_type TEXT NOT NULL,              -- author|generation|import|...
    source_ref TEXT NOT NULL,
    source_revision INTEGER,
    chapter_ref TEXT,
    location TEXT NOT NULL DEFAULT '',
    extracted_claim TEXT NOT NULL,
    confidence REAL NOT NULL,
    captured_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

-- Candidate facts awaiting explicit promotion into Canon.
CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    claim TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL,
    status TEXT NOT NULL,                   -- FactStatus for proposal lifecycle
    conflicts_json TEXT NOT NULL DEFAULT '[]',
    proposed_by TEXT NOT NULL DEFAULT 'system',
    target_kind TEXT NOT NULL DEFAULT 'world',
    target_key TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    promoted_item_id TEXT,                  -- resulting state_items.item_id
    claim_value_json TEXT,
    depends_on_json TEXT NOT NULL DEFAULT '[]'
);

-- Generated drafts. Never Canon until commit_guard accepts a commit.
CREATE TABLE IF NOT EXISTS candidates (
    candidate_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    content TEXT NOT NULL,
    session_id TEXT NOT NULL,               -- production session that produced it
    base_story_revision INTEGER NOT NULL,   -- guard baseline at generation time
    plan_revision INTEGER NOT NULL,
    context_fingerprint TEXT NOT NULL,      -- context integrity check
    status TEXT NOT NULL DEFAULT 'DRAFT',
    validation_json TEXT NOT NULL DEFAULT '{}',
    quality_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

-- Unit of continuous production (usually one chapter slot).
CREATE TABLE IF NOT EXISTS production_units (
    unit_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'chapter',
    ref_id TEXT NOT NULL,                   -- chapter_id or other unit ref
    status TEXT NOT NULL DEFAULT 'PLANNED', -- PLANNED|GENERATING|COMMITTED|STALE|...
    depends_on_json TEXT NOT NULL DEFAULT '[]',
    stale_reason TEXT,                      -- why unit was invalidated
    updated_at TEXT NOT NULL
);

-- Append-only audit of truth/commit actions (who changed what and why).
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    action TEXT NOT NULL,                   -- promote|commit|invalidate|...
    actor TEXT NOT NULL,                    -- author|orchestrator|system
    base_revision INTEGER NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'OK',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

-- Runtime checkpoint envelopes for resume/recovery.
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    revision INTEGER NOT NULL,              -- story revision at checkpoint
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

-- External-edit reconcile records (author changed committed prose).
CREATE TABLE IF NOT EXISTS reconcile_records (
    reconcile_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    previous_content_hash TEXT NOT NULL,    -- pre-edit content fingerprint
    current_content_hash TEXT NOT NULL,
    previous_story_revision INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING|COMPLETED|CANCELLED
    reason TEXT NOT NULL DEFAULT '',
    fact_keys_changed_json TEXT NOT NULL DEFAULT '[]',
    stale_chapter_ids_json TEXT NOT NULL DEFAULT '[]',
    still_valid_chapter_ids_json TEXT NOT NULL DEFAULT '[]',
    invalidated_plan_ids_json TEXT NOT NULL DEFAULT '[]',
    extracted_fact_keys_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    provenance_json TEXT NOT NULL DEFAULT '{}'
);
-- Filter open reconcile work by story.
CREATE INDEX IF NOT EXISTS idx_reconcile_story_status ON reconcile_records(story_id, status);
-- Author-edit path looks up by chapter.
CREATE INDEX IF NOT EXISTS idx_reconcile_chapter ON reconcile_records(chapter_id);

-- Narrative throughlines / foreshadow threads tracked across chapters.
CREATE TABLE IF NOT EXISTS threads (
    thread_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    name TEXT NOT NULL,
    introduced_at TEXT NOT NULL,
    current_status TEXT NOT NULL DEFAULT 'OPEN', -- OPEN|RESOLVED|ABANDONED
    obligations_json TEXT NOT NULL DEFAULT '[]',
    related_entities_json TEXT NOT NULL DEFAULT '[]',
    expected_resolution TEXT NOT NULL DEFAULT '',
    last_touched_at TEXT,
    revision INTEGER NOT NULL DEFAULT 0
);
-- Open-thread queries during planning/context.
CREATE INDEX IF NOT EXISTS idx_threads_story_status ON threads(story_id, current_status);

-- Key/value meta (schema_version stamp).
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Current schema version. Bump when adding migrations.
SCHEMA_VERSION = 2

# version -> list of SQL statements applied on upgrade (never destructive).
MIGRATIONS: dict[int, list[str]] = {
    # v2: throughline thread persistence (also in base SCHEMA for fresh DBs).
    2: [
        """
        CREATE TABLE IF NOT EXISTS threads (
            thread_id TEXT PRIMARY KEY,
            story_id TEXT NOT NULL,
            name TEXT NOT NULL,
            introduced_at TEXT NOT NULL,
            current_status TEXT NOT NULL DEFAULT 'OPEN',
            obligations_json TEXT NOT NULL DEFAULT '[]',
            related_entities_json TEXT NOT NULL DEFAULT '[]',
            expected_resolution TEXT NOT NULL DEFAULT '',
            last_touched_at TEXT,
            revision INTEGER NOT NULL DEFAULT 0
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_threads_story_status ON threads(story_id, current_status)",
    ],
}


class Database:
    """Thin SQLite facade: schema bootstrap, additive migrations, connection access.

    Main interface:
        ``schema_version``, ``migrate``, ``execute``, ``commit``, ``close``,
        plus context-manager usage. ``connection`` exposes the raw
        ``sqlite3.Connection`` when callers need row factories or PRAGMAs.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        """Open (or create) the database and ensure the current schema is applied.

        Args:
            path: Filesystem path, or ``:memory:`` for an in-process database.
        """
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self.migrate()

    @property
    def connection(self) -> sqlite3.Connection:
        """Underlying SQLite connection.

        Returns:
            Connection whose row factory returns ``sqlite3.Row``.
        """
        return self._conn

    def schema_version(self) -> int:
        """Return the stamped schema version, or 0 if unstamped.

        Returns:
            Integer schema version from ``schema_meta``.
        """
        row = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            return 0
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return 0

    def migrate(self) -> list[int]:
        """Apply pending additive migrations.

        Fresh DBs get stamped at SCHEMA_VERSION immediately (base SCHEMA is current).
        Existing DBs without a stamp are treated as v1 and upgraded stepwise.

        Returns:
            Versions applied during this call (empty for fresh installs).
        """
        current = self.schema_version()
        if current == 0:
            # Fresh install: base SCHEMA already includes latest tables.
            self._conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()
            return []
        applied: list[int] = []
        for version in range(current + 1, SCHEMA_VERSION + 1):
            for sql in MIGRATIONS.get(version, []):
                self._conn.execute(sql)
            self._conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
                (str(version),),
            )
            applied.append(version)
        self._conn.commit()
        return applied

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        """Execute a SQL statement.

        Args:
            sql: SQL text.
            params: Bound parameters (tuple/list).

        Returns:
            SQLite cursor for the statement.
        """
        return self._conn.execute(sql, params)

    def commit(self) -> None:
        """Commit the current transaction.

        Returns:
            None
        """
        self._conn.commit()

    def close(self) -> None:
        """Close the connection. Safe to call more than once only via context manager.

        Returns:
            None
        """
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
