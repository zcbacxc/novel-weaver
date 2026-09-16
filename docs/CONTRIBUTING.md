[![English](https://img.shields.io/badge/English-Contributing-blue)](CONTRIBUTING.md)
[![简体中文](https://img.shields.io/badge/简体中文-贡献指南-green)](CONTRIBUTING.zh-CN.md)

# Contributing

Thanks for your interest in Novel Weaver. This repo is the **AI long-form novel production Core Engine** — not a chat writing tool or novel editor. Read [README](../README.md) positioning and design constraints before opening a PR.

## Scope reminder

Confirm the change serves long-run continuous production, not surface product polish:

```
Evidence / Canonical Truth
  → Commit Guard / Version Integrity
  → Dependency / Invalidation / Repair
  → Context / Temporal Retrieval
  → Quality / Revision Manifest
  → Recovery / Provenance / Audit
  → Runtime Intelligence
  → Model Intelligence
  → UI / Convenience
```

## Development setup

```bash
git clone https://github.com/zcbacxc/novel-weaver.git
cd novel-weaver
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Python **3.12+**. Core runtime has no mandatory third-party dependencies.

## Run tests

```bash
python -m pytest tests -v
```

CI runs the same suite on Linux for Python 3.12 / 3.13 and separately validates sdist/wheel builds. Keep local tests green before merge.

Optional offline smoke:

```bash
novel-weaver demo --workspace .workspaces/demo
novel-weaver engine --provider template --workspace .workspaces/engine
```

## Project structure (public summary)

```text
src/novel_weaver/
  domain/       # Canonical entities and state enums
  truth/        # Evidence / Proposal / Commit Guard / Audit
  storage/      # SQLite repos, Snapshot / Release / Artifact
  production/   # orchestration, planning, invalidation, repair, quality
  ai/           # providers (fake / template / openai-compat / failover)
  runtime/      # Checkpoint / Resume / Cost / Diagnostics
  benchmarks/   # long-run production benchmark
  cli/          # novel-weaver entrypoint
tests/
docs/           # public bilingual docs (English primary)
```

See [ARCHITECTURE](ARCHITECTURE.md) for layers and the commit path.

## Branches and PRs

| Branch | Purpose |
|--------|---------|
| `main` | deliverable trunk; no direct code pushes without PR |
| `feature/*` | features or docs from `main` |
| `hotfix/*` | urgent fixes from `main` |

```text
git checkout main && git pull
git checkout -b feature/<name>
# develop + local tests
git push origin feature/<name>
# open PR → merge after CI green
```

Before merge:

- CI (`test` + `build`) must pass
- new behavior needs tests; bug fixes prefer a regression case
- user-facing changes update [CHANGELOG.md](../CHANGELOG.md) `[Unreleased]`
- version bumps only in release commits touching `pyproject.toml` ([RELEASE_CHECKLIST](RELEASE_CHECKLIST.md))
- repository allows **Squash and merge** only; delete source branch after merge
- `main` is protected: 1 approval, stale reviews dismiss, no force-push, linear history

## Commit messages

Prefixes:

- `feat:` — feature
- `fix:` — bug fix
- `docs:` — docs only
- `chore:` — maintenance / CI / tooling
- `refactor:` — behavior-preserving refactor
- `test:` — tests

Explain **why**, not just a file list.

## Code and comments

- Python type annotations; public APIs use English Google-style docstrings (`Args` / `Returns` / `Raises`)
- inline comments explain non-obvious decisions (`Decision:` / rejected alternative)
- keep SPDX headers: `AGPL-3.0-or-later`
- no internal tracking codes (`EP*` / `WP*` / `NA-M*`) in code, docs, or commits

## Documentation pairs

- Public pages are **English primary** (`.md`) with structure-aligned Chinese (`.zh-CN.md`)
- Keep heading levels and diagram/table counts aligned across the pair
- Do not copy local design documents into `docs/`

## Design red lines (must read)

Do not weaken these invariants in a PR:

1. **Canonical Story is the only official truth**; vectors/summaries/memory are rebuildable projections.
2. **Draft / Candidate / Canonical strictly layered**; model output defaults to Candidate.
3. **`PENDING` ≠ `FALSE` ≠ `TRUE`**; no evidence, no Canon promotion.
4. **Official state changes pass Commit Guard / version checks**; LLMs never write Canon.
5. **Runtime failures do not pollute Canon**; interrupt/retry must not double-commit.
6. **Changes propagate only to real dependents** (impact → minimal invalidation).
7. **Providers are swappable**; agents are an implementation detail, not a system boundary.

Reject scope: community/publishing platforms, chat UI, membership payments, “one-click whole book” as a core goal.

## License

**AGPL-3.0-or-later**. Contributions imply the same license. Check dependency license compatibility before adding deps. Network service use triggers AGPL §13 obligations.
