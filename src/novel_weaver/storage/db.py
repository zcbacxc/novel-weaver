# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SQLite connection and schema bootstrap."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    story_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    premise TEXT NOT NULL DEFAULT '',
    creative_intent TEXT NOT NULL DEFAULT '',
    constraints_json TEXT NOT NULL DEFAULT '{}',
    current_canonical_revision INTEGER NOT NULL DEFAULT 0,
    lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS story_revisions (
    story_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    checkpoint_ref TEXT,
    PRIMARY KEY (story_id, revision)
);

CREATE TABLE IF NOT EXISTS state_items (
    item_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 1.0,
    effective_from INTEGER,
    effective_to INTEGER,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    superseded_by TEXT,
    invalidated_by TEXT,
    depends_on_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_state_items_story_key ON state_items(story_id, key);
CREATE INDEX IF NOT EXISTS idx_state_items_story_status ON state_items(story_id, status);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    time_ref TEXT NOT NULL,
    summary TEXT NOT NULL,
    participants_json TEXT NOT NULL DEFAULT '[]',
    location TEXT NOT NULL DEFAULT '',
    claims_json TEXT NOT NULL DEFAULT '{}',
    source_chapter TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    revision INTEGER NOT NULL DEFAULT 0,
    provenance_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_story ON events(story_id);

CREATE TABLE IF NOT EXISTS chapters (
    chapter_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    plan TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'PLANNED',
    revision INTEGER NOT NULL DEFAULT 0,
    depends_on_json TEXT NOT NULL DEFAULT '[]',
    fact_keys_used_json TEXT NOT NULL DEFAULT '[]',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (story_id, number)
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_revision INTEGER,
    chapter_ref TEXT,
    location TEXT NOT NULL DEFAULT '',
    extracted_claim TEXT NOT NULL,
    confidence REAL NOT NULL,
    captured_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    claim TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    conflicts_json TEXT NOT NULL DEFAULT '[]',
    proposed_by TEXT NOT NULL DEFAULT 'system',
    target_kind TEXT NOT NULL DEFAULT 'world',
    target_key TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    promoted_item_id TEXT,
    claim_value_json TEXT,
    depends_on_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS candidates (
    candidate_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    content TEXT NOT NULL,
    session_id TEXT NOT NULL,
    base_story_revision INTEGER NOT NULL,
    plan_revision INTEGER NOT NULL,
    context_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    validation_json TEXT NOT NULL DEFAULT '{}',
    quality_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS production_units (
    unit_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'chapter',
    ref_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PLANNED',
    depends_on_json TEXT NOT NULL DEFAULT '[]',
    stale_reason TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    base_revision INTEGER NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'OK',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconcile_records (
    reconcile_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    previous_content_hash TEXT NOT NULL,
    current_content_hash TEXT NOT NULL,
    previous_story_revision INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
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
CREATE INDEX IF NOT EXISTS idx_reconcile_story_status ON reconcile_records(story_id, status);
CREATE INDEX IF NOT EXISTS idx_reconcile_chapter ON reconcile_records(chapter_id);

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
);
CREATE INDEX IF NOT EXISTS idx_threads_story_status ON threads(story_id, current_status);

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
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self.migrate()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def schema_version(self) -> int:
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
        """Apply pending additive migrations. Returns list of versions applied.

        Fresh DBs get stamped at SCHEMA_VERSION immediately (base SCHEMA is current).
        Existing DBs without a stamp are treated as v1 and upgraded stepwise.
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
        return self._conn.execute(sql, params)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
