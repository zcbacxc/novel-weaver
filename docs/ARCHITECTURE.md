[![English](https://img.shields.io/badge/English-Architecture-blue)](ARCHITECTURE.md)
[![简体中文](https://img.shields.io/badge/简体中文-架构-green)](ARCHITECTURE.zh-CN.md)

# Architecture Overview

Public overview of the **implemented** Novel Weaver layers and main paths. Product positioning and the full internal plan live outside this directory. If this page conflicts with code, treat code as truth and update the page.

## One sentence

Chapter production is a recoverable pipeline: **plan → generate Candidate → validate/review → Commit Guard → Canonical**. Models understand and generate; they **never write official truth directly**.

## Layers

```text
Production Interface (CLI)
        │
        ▼
Production Engine / Orchestrator
  plan → context → generate → quality → commit
        │
        ├─► Truth Layer (Evidence / Proposal / Commit Guard / Audit)
        │
        ├─► Canonical Domain (Story / StateItem / Event / Chapter…)
        │
        ├─► Derived / Support
        │     Context Pack · Dependency · Invalidation · Fingerprint
        │     Threads · Memory · Timeline · BookPass · Reconcile
        │
        ├─► Runtime (Checkpoint · Resume · Cost · Diagnostics)
        │
        └─► AI Providers (fake / template / openai-compat / failover)
                    │
                    ▼
              Persistence (SQLite + Workspace files)
```

| Layer | Package | Responsibility |
|-------|---------|----------------|
| CLI | `novel_weaver.cli` | parse args, open workspace, call Engine/repositories |
| Production | `novel_weaver.production` | chapter loop, planning, invalidation/repair, quality |
| Truth | `novel_weaver.truth` | evidence, promotion, commit gate, audit |
| Domain | `novel_weaver.domain` | Canonical entities and state machines |
| Storage | `novel_weaver.storage` | SQLite tables/repos, snapshot, release, artifacts |
| Runtime | `novel_weaver.runtime` | checkpoint, resume, cost, diagnostics |
| AI | `novel_weaver.ai` | provider protocol and implementations |

## Canonical vs derived

**Canonical Story** is the only official truth (Story / StateItem / Event / Chapter in SQLite). Projections (context packs, retrieval, memory, timeline views) must be rebuildable from Canonical and must not become unverifiable fact sources.

Fact lifecycle (`FactStatus`):

```text
UNKNOWN / PENDING ──► PROPOSED ──► REVIEWED ──► CANONICAL
                         │                        │
                         ▼                        ▼
                    DISPUTED                 SUPERSEDED
                                              INVALIDATED
```

Rules:

- `PENDING` means unknown/to-be-settled — **not** `FALSE`.
- Model guesses cannot skip evidence and promotion into `CANONICAL`.
- Promotion requires an **Evidence-backed Proposal**; empty evidence is rejected.

Chapter-related states:

- **ProductionUnitStatus**: `PLANNED → GENERATING → CANDIDATE_READY → … → COMMITTED` (or `STALE` / `BLOCKED`)
- **CandidateStatus**: `DRAFT → VALIDATED → REVIEWED → ACCEPTED → COMMITTED` (or `REJECTED` / `STALE`)

Model output defaults to **Candidate**. Only a successful commit changes official story state.

## Single-chapter main path

`ProductionEngine.produce_chapter` (`production/engine.py`) chains:

1. **Plan** — `RollingPlanner` creates/reuses the chapter plan
2. **Session** — `ProductionOrchestrator.begin_session` pins `base_story_revision`, plan version, context fingerprint
3. **Context** — `build_context_pack` assembles generation state from Canonical
4. **Generate** — selected `Provider` emits a Candidate (`fake` / `template` offline)
5. **Quality** — dual-layer checks + optional LLM semantic review → accept/revise/reject
6. **Commit** — **Commit Guard** then Canonical write; failure leaves official state untouched
7. **Runtime** — checkpoint / cost / diagnostics; resume is supported

```text
plan ──► begin_session ──► context ──► provider.generate
                                              │
                                              ▼
                                    validate / review
                                              │
                         reject/revise ◄──────┤
                                              ▼ accept
                                       Commit Guard
                                         │      │
                                      reject   accept
                                                ▼
                                          Canonical + Audit
```

## Commit Guard

`truth/commit_guard.py` rejects stale or mismatched commits, including:

- Story / plan version ≠ session baseline
- production unit mismatch or lock
- context fingerprint mismatch (upstream changed)
- duplicate commit

A `ProductionSession` is an immutable snapshot of “the world used to generate”. The Guard ensures **an old session cannot overwrite newer Canonical**.

## Invalidation and repair

Upstream edits (external author edit or re-promoted facts) follow:

1. **Reconcile** detects text/state drift (`production/reconcile.py`)
2. **Dependency graph + impact** finds real dependents (`dependency.py` / `invalidation.py`)
3. minimal **mark stale** → local re-plan / regenerate
4. unrelated chapters stay valid; escalate when needed

Goal: **minimal necessary re-production**, not a full-book rewrite.

## Provider layer

`ai/base.py` defines the protocol. Providers execute generate/review tasks and **do not write Canon**.

| Name | Role |
|------|------|
| `fake` | deterministic text for tests/CI |
| `template` | offline template generation for demos |
| `openai` | OpenAI-compatible chat completions (stdlib HTTP) |
| `failover` | ordered failover chain |

Registration lives in `ai/registry.py`. Transient errors can use `retry_with_backoff`. Configure via `NOVEL_WEAVER_LLM_*` (see `.env.example`).

## Storage and workspace

- Primary DB: `novel.sqlite3` under the workspace (stdlib `sqlite3`)
- Repositories: `storage/repositories.py`
- Helpers: snapshot import/export, release, artifact, canonical file export
- Runtime tables stay separate from Canonical tables so crashes/retries/provider swaps do not pollute the story

## CLI

Entry: `novel-weaver` / `python -m novel_weaver` (`cli/main.py`).

| Command | Purpose |
|---------|---------|
| `demo` | truth boundary + short engine demo |
| `engine` | single-chapter production (`--provider`) |
| `produce` | continuous multi-chapter production |
| `book-check` | full-book consistency pass |
| `bench` | long-run benchmark |
| `status` | workspace stories |
| `snapshot-export` / `snapshot-import` | snapshots |
| `release-create` | immutable release record |
| `canonical-export` | Canonical file export |
| `timeline` | timeline projection |
| `config` | show configuration |

## Test strategy

- Offline by default with `fake` / `template`
- Boundary focus: Commit Guard rejects, Evidence promotion, resume without double-commit, minimal impact invalidation, quality manifests
- Long-run: `benchmarks/` + `bench` command

## Non-goals

This engine is **not** a novel site, community, publishing SaaS, or multi-agent chat workflow orchestrator. Upper products may depend on this package; they do not redefine the core boundary.

## Related

- [Quickstart](QUICKSTART.md)
- [Contributing](CONTRIBUTING.md)
- [ADR](ADR.md)
- [Release checklist](RELEASE_CHECKLIST.md)
- [Roadmap](ROADMAP.md)
