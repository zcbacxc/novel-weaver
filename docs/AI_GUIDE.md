[![English](https://img.shields.io/badge/English-AI_Guide-blue)](AI_GUIDE.md)
[![简体中文](https://img.shields.io/badge/简体中文-AI导航-green)](AI_GUIDE.zh-CN.md)

# AI Coding Assistant Guide

> Navigation index for AI coding tools (Claude Code, Codex, Cursor, Copilot, etc.). Content lives in the linked documents; this page only routes and states edit constraints.

## Start here

| Topic | Document |
|-------|----------|
| Overview and install | [README](../README.md) |
| Chinese README | [README.zh-CN](../README.zh-CN.md) |
| 10-minute quickstart | [QUICKSTART.md](QUICKSTART.md) |
| Architecture (layers, commit path) | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Contributing rules | [CONTRIBUTING.md](CONTRIBUTING.md) |

## Design decisions

| Topic | Document |
|-------|----------|
| ADR index | [ADR.md](ADR.md) |
| Provider setup | [LLM_PROVIDERS.md](LLM_PROVIDERS.md) |
| Versioning and PyPI | [PACKAGING.md](PACKAGING.md) |
| Shipped / planned themes | [ROADMAP.md](ROADMAP.md) |
| Tag DoD | [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) |

## Invariants for edits

1. Core Engine only — no chat UI, community, SaaS, or “one-shot whole book” scope creep
2. Canonical Story is the only official truth; derived projections must be rebuildable
3. Draft / Candidate / Canonical stay strictly layered; providers never write Canon
4. `PENDING` is not `FALSE`; no evidence, no Canonical promotion
5. Public bilingual docs stay structure-aligned (`.md` English primary + `.zh-CN.md`)
6. No internal tracking codes (EP*, WP*, NA-M*, …) in public docs or commits
7. Local design docs (`PROJECT_POSITIONING.md`, `docs-nocommit/`, `CLAUDE.md`, `.claude/`) must **not** be committed or copied into `docs/`
8. User-facing changes update CHANGELOG; package version lives only in `pyproject.toml`

## CLI cheat sheet

```bash
novel-weaver demo --workspace .workspaces/demo
novel-weaver engine --provider template --workspace .workspaces/engine
novel-weaver produce --workspace .workspaces/prod
novel-weaver book-check --workspace .workspaces/demo
novel-weaver bench --chapters 30 --workspace .workspaces/bench-30
novel-weaver config --show
novel-weaver --help
```

## Local-only (do not publish)

| File | Role |
|------|------|
| `PROJECT_POSITIONING.md` | Positioning / non-goals (gitignored) |
| `docs-nocommit/confirmed/NOVEL_WEAVER_IMPLEMENTATION_PLAN.md` | Full engineering plan (gitignored) |
| `CLAUDE.md` / `.claude/rules/` | Agent working rules (gitignored) |
