[![English](https://img.shields.io/badge/English-README-blue)](README.md)
[![简体中文](https://img.shields.io/badge/简体中文-README-green)](README.zh-CN.md)

# Novel Weaver

[![License: AGPL v3+](https://img.shields.io/badge/License-AGPL%20v3%2B-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/zcbacxc/novel-weaver/actions/workflows/ci.yml/badge.svg)](https://github.com/zcbacxc/novel-weaver/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/novel-weaver.svg)](https://pypi.org/project/novel-weaver/)

> Core Engine for productized long-form novel production

Novel Weaver turns chapter production into a **repeatable, controllable, recoverable, repairable, and traceable** engineering pipeline. It is **not** a chat writing tool, novel editor, community platform, or multi-agent prompt chain.

```
Plan → Context Pack → Provider.generate → Candidate
  → Validate / Semantic Review → Commit Guard
  → Canonical Story → Checkpoint / Resume / Audit
```

Success is not “can generate one pretty chapter”. Success is whether long runs stay stable, upstream edits only invalidate real dependents, and swapping providers does not erase the official story.

## Features

- Truth boundary: Evidence → Proposal → Canonical promotion with Commit Guard
- Strict Draft / Candidate / Canonical layering (`PENDING` ≠ `FALSE` ≠ `TRUE`)
- Single-chapter production loop with dual-layer quality + optional LLM semantic review
- Continuous production with checkpoint/resume and no double-commit on retry
- Incremental repair: dependency graph, impact analysis, minimal invalidation
- External-edit reconcile before further commits
- Book-level consistency pass, snapshots, releases, timeline projection
- Swappable providers: `fake`, `template`, OpenAI-compatible HTTP, failover
- SQLite Canonical storage (stdlib); zero mandatory third-party runtime deps
- CLI for demo, production, bench, export, and diagnostics

## Requirements

- Python 3.12+

## Install

### From source (recommended today)

```bash
git clone https://github.com/zcbacxc/novel-weaver.git
cd novel-weaver
python -m pip install -e ".[dev]"
```

### From PyPI

```bash
pip install novel-weaver
```

Core runtime has **no mandatory third-party dependencies**. Real LLM calls are optional via any OpenAI-compatible HTTP endpoint.

## Quick start

```bash
# Offline tests (no paid LLM)
python -m pytest tests -v

# Demo workspace: truth boundary + short engine loop
novel-weaver demo --workspace .workspaces/demo

# Single-chapter engine production
novel-weaver engine --provider template --workspace .workspaces/engine
# novel-weaver engine --provider openai --workspace .workspaces/llm

# Continuous multi-chapter production
novel-weaver produce --workspace .workspaces/prod

# Full-book consistency check
novel-weaver book-check --workspace .workspaces/demo

# Long-run benchmark (default 30 chapters)
novel-weaver bench --chapters 30 --workspace .workspaces/bench-30
```

More paths (config, snapshots, timeline) are in [docs/QUICKSTART.md](docs/QUICKSTART.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## LLM configuration (optional)

Copy `.env.example` to project `.env` or `~/.novel-weaver/.env`:

```env
NOVEL_WEAVER_LLM_BASE_URL=https://api.openai.com/v1
NOVEL_WEAVER_LLM_API_KEY=sk-...
NOVEL_WEAVER_LLM_MODEL=gpt-4o-mini
```

See [docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md). Without LLM keys, `fake` / `template` still run the full engine loop.

## Package layout

```text
src/novel_weaver/
  config.py         # config + workspace bootstrap
  domain/           # Canonical entities and versions
  truth/            # Evidence / Proposal / Commit Guard / Audit
  storage/          # SQLite repositories + Snapshot / Release / Artifact
  production/       # orchestration, invalidation, repair, review
  ai/               # providers (fake / template / openai-compat / failover)
  runtime/          # Checkpoint / Resume / Cost / Diagnostics
  benchmarks/       # long-run production benchmark
  cli/              # novel-weaver entrypoint
tests/
docs/               # public bilingual docs (EN primary)
```

## Design constraints

- Canonical Story is the only official truth; projections must be rebuildable.
- Draft / Candidate / Canonical are strictly layered; no evidence, no Canon.
- Runtime failures never pollute Canon; commits must pass Commit Guard.
- Upstream edits invalidate only real dependents (minimal re-production).
- Providers and models are swappable; agents are an implementation detail, not a system boundary.

## Documentation

| Topic | English | 简体中文 |
|-------|---------|----------|
| Docs index | [docs/index.md](docs/index.md) | — |
| Quickstart | [QUICKSTART](docs/QUICKSTART.md) | [快速开始](docs/QUICKSTART.zh-CN.md) |
| Architecture | [ARCHITECTURE](docs/ARCHITECTURE.md) | [架构](docs/ARCHITECTURE.zh-CN.md) |
| Contributing | [CONTRIBUTING](docs/CONTRIBUTING.md) | [贡献指南](docs/CONTRIBUTING.zh-CN.md) |
| LLM providers | [LLM_PROVIDERS](docs/LLM_PROVIDERS.md) | [Provider 配置](docs/LLM_PROVIDERS.zh-CN.md) |
| ADR | [ADR](docs/ADR.md) | [架构决策](docs/ADR.zh-CN.md) |
| Packaging | [PACKAGING](docs/PACKAGING.md) | [打包](docs/PACKAGING.zh-CN.md) |
| Release checklist | [RELEASE_CHECKLIST](docs/RELEASE_CHECKLIST.md) | [发布清单](docs/RELEASE_CHECKLIST.zh-CN.md) |
| Roadmap | [ROADMAP](docs/ROADMAP.md) | [路线图](docs/ROADMAP.zh-CN.md) |
| AI guide | [AI_GUIDE](docs/AI_GUIDE.md) | [AI 导航](docs/AI_GUIDE.zh-CN.md) |

## Release

- Version source of truth: `pyproject.toml`.
- Changes: [CHANGELOG.md](CHANGELOG.md).
- Checklist: [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md).

## License

**GNU Affero General Public License v3.0 or later** (AGPL-3.0-or-later). See [LICENSE](LICENSE). Network service use triggers AGPL §13 source offer obligations.
