[![English](https://img.shields.io/badge/English-ADR-blue)](ADR.md)
[![简体中文](https://img.shields.io/badge/简体中文-架构决策记录-green)](ADR.zh-CN.md)

# Architecture Decision Records

Records significant architecture decisions for Novel Weaver. Each ADR is immutable once accepted — if a decision changes, add a new ADR that supersedes the old one and update the index.

## How to add

1. Take the next id (`ADR-006`, …).
2. Use the same structure: Status / Context / Decision Drivers / Considered Options / Decision Outcome / Consequences / References.
3. Append at the end and update the index table.
4. Only record decisions that exist in code/history — do not invent.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [001](#adr-001-canonical-story-as-the-only-official-truth) | Canonical Story as the only official truth | Accepted |
| [002](#adr-002-commit-guard-for-commits) | Commit Guard for commits | Accepted |
| [003](#adr-003-sqlite-as-primary-storage) | SQLite as primary storage | Accepted |
| [004](#adr-004-swappable-providers-that-never-write-canon) | Swappable providers that never write Canon | Accepted |
| [005](#adr-005-stdlib-first-and-zero-mandatory-runtime-deps) | stdlib first and zero mandatory runtime deps | Accepted |

---

## ADR-001: Canonical Story as the only official truth

**Status:** Accepted

### Context

Long-form generation also produces summaries, retrieval indexes, memory snippets, and runtime caches. If any projection becomes an unverifiable source of truth, upstream edits, model swaps, or crash recovery leave the story drifting and unauditable.

### Decision Drivers

- Traceability: official facts must point back to evidence or committed content.
- Recoverability: lost projections must be rebuildable.
- Repairability: upstream edits must identify real downstream dependents.

### Considered Options

- Vector/memory stores as authority (rejected: unverifiable, hard to migrate).
- Multi-source truth voting (rejected: no single conflict rule; high complexity).

### Decision Outcome

Canonical Story (domain entities + versioned state) is the only official truth. Summaries, indexes, memory, etc. are Derived Projections and must be rebuildable from Canonical; they must not define Canon.

### Consequences

- Positive: clear recovery path; providers/UI are swappable.
- Cost: every official change must cross the Truth/Commit boundary.

### References

- `docs/ARCHITECTURE.md`
- `src/novel_weaver/domain/`
- `src/novel_weaver/truth/`

---

## ADR-002: Commit Guard for commits

**Status:** Accepted

### Context

A generation session is based on a Story/Plan revision and context fingerprint. If Canonical advances mid-session (other commits or external edits), writing back the old session would overwrite newer truth or create ghost state.

### Decision Drivers

- Prevent double-commit and stale overwrite.
- Safe interrupt/retry.
- Auditable rejection reasons.

### Considered Options

- Last-writer-wins by timestamp (rejected: silent data loss).
- Whole-DB long transaction locks (rejected: blocks concurrent reads and long generation).

### Decision Outcome

Each production session pins a `ProductionSession` (baseline revision, plan version, unit, fingerprint). Commits must pass `CommitGuard`; mismatches are rejected with recorded reasons. Official writes still go through the orchestrator commit path.

### Consequences

- Positive: old sessions cannot overwrite newer Canon; resume-without-double-commit is testable.
- Cost: sessions must be created correctly; Guard changes need regression tests.

### References

- `src/novel_weaver/truth/commit_guard.py`
- `src/novel_weaver/production/orchestrator.py`

---

## ADR-003: SQLite as primary storage

**Status:** Accepted

### Context

The engine needs transactions, version fields, auditability, and queryable Canonical state, with single-machine, low-ops, easy testing.

### Decision Drivers

- stdlib available; no service process.
- transactions cover commit atomicity.
- tests/CI isolate per workspace file.

### Considered Options

- pure JSON file trees (rejected: weak concurrency/transaction boundaries).
- external PostgreSQL (rejected: ops cost vs minimal kernel).

### Decision Outcome

Primary storage is stdlib `sqlite3` in the workspace (`novel.sqlite3`). Repositories encapsulate access; snapshot/release/artifact helpers live in the storage package. Future backends must preserve Truth-boundary semantics.

### Consequences

- Positive: zero-setup, easy backup (file copy/export).
- Cost: not targeting huge concurrent writers; migration strategy required if schema evolves.

### References

- `src/novel_weaver/storage/`

---

## ADR-004: Swappable providers that never write Canon

**Status:** Accepted

### Context

Model vendors iterate quickly. Hard-coding one SDK in orchestration couples domain state to a vendor; letting models write tables bypasses Truth.

### Decision Drivers

- Providers/models are swappable.
- Agents are implementation detail, not system boundary.
- Tests can run offline deterministically.

### Considered Options

- vendor SDK hard-coded in orchestrator (rejected: lock-in).
- direct model updates to state tables (rejected: bypasses evidence and Guard).

### Decision Outcome

`ai.base.Provider` defines task protocols (generate, review, …). Implementations include `fake`, `template`, OpenAI-compatible HTTP, and `failover`. Providers return Candidates/review results; **Canonical writes happen only on the Commit path**.

### Consequences

- Positive: CI uses `fake`; production can swap endpoints/models.
- Cost: protocol/registry maintenance; normalize outputs at the provider layer.

### References

- `src/novel_weaver/ai/base.py`
- `src/novel_weaver/ai/registry.py`

---

## ADR-005: stdlib first and zero mandatory runtime deps

**Status:** Accepted

### Context

The core is a domain state machine and orchestration, not a web/ML framework. Heavy deps raise install and supply-chain cost and fragilize the minimal kernel.

### Decision Drivers

- `pip install novel-weaver` should stay light.
- LLM calls over HTTP are possible with stdlib.
- tests/packaging should run in constrained environments.

### Considered Options

- mandatory `openai` / `pydantic` / `httpx` (rejected: unnecessary coupling).
- mandatory vector-DB deps (rejected: projections are not truth).

### Decision Outcome

Core runtime has **zero mandatory third-party dependencies**. OpenAI-compatible calls use stdlib HTTP; dev deps are `pytest` (`[dev]` extra). Optional capabilities must not expand the default install surface.

### Consequences

- Positive: fast install, small audit surface, aligned with “engine kernel”.
- Cost: own HTTP/parse code; keep schema validation lean.

### References

- `pyproject.toml`
- `src/novel_weaver/ai/openai_compat.py`

---

## Related

- [Architecture](ARCHITECTURE.md)
- [Packaging](PACKAGING.md)
