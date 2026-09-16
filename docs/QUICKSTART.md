[![English](https://img.shields.io/badge/English-Quickstart-blue)](QUICKSTART.md)
[![简体中文](https://img.shields.io/badge/简体中文-快速开始-green)](QUICKSTART.zh-CN.md)

# Quickstart

Get Novel Weaver running offline first, then optionally point it at a real LLM.

## Prerequisites

- Python 3.12+
- Git (if installing from source)

```bash
git clone https://github.com/zcbacxc/novel-weaver.git
cd novel-weaver
python -m pip install -e ".[dev]"
novel-weaver --help
```

## 1. Verify offline install

```bash
python -m pytest tests -v
```

Default tests use `fake` / `template` providers and never call a paid API.

## 2. Run the engine demo

```bash
novel-weaver demo --workspace .workspaces/demo
```

This creates a workspace, walks the truth-boundary path, and exercises a short production loop.

## 3. Produce with the template provider

```bash
novel-weaver engine --provider template --workspace .workspaces/engine
novel-weaver status --workspace .workspaces/engine
```

`template` needs no keys and shows the full Candidate → quality → Commit Guard path.

## 4. Continuous production and checks

```bash
# multi-chapter continuous production
novel-weaver produce --workspace .workspaces/prod

# book-level consistency
novel-weaver book-check --workspace .workspaces/demo

# long-run benchmark (default 30 chapters)
novel-weaver bench --chapters 10 --workspace .workspaces/bench
```

## 5. Optional real LLM

Copy `.env.example` to `.env` in the repo root (or `~/.novel-weaver/.env`):

```env
NOVEL_WEAVER_LLM_BASE_URL=https://api.openai.com/v1
NOVEL_WEAVER_LLM_API_KEY=sk-...
NOVEL_WEAVER_LLM_MODEL=gpt-4o-mini
NOVEL_WEAVER_FAILOVER=openai,template
```

```bash
novel-weaver config --show
novel-weaver engine --provider openai --workspace .workspaces/llm
```

Any OpenAI-compatible `POST /chat/completions` endpoint works. Provider failures fail the step; they do **not** write Canonical. See [LLM_PROVIDERS](LLM_PROVIDERS.md).

## 6. Inspect and export

```bash
novel-weaver status --workspace .workspaces/demo
novel-weaver timeline --workspace .workspaces/demo
novel-weaver snapshot-export --workspace .workspaces/demo
novel-weaver canonical-export --workspace .workspaces/demo
novel-weaver release-create --workspace .workspaces/demo
```

## Workspace layout (conceptual)

Each `--workspace` directory holds:

- `novel.sqlite3` — Canonical + runtime storage
- derived/export files produced by snapshot / canonical export / artifacts

Treat the SQLite Canonical store as the official story; projections can be rebuilt.

## What “working” means

| Check | Pass looks like |
|-------|-----------------|
| Offline CI | full pytest green without network keys |
| Single chapter | Candidate produced, quality result recorded, commit accepted or rejected by Guard |
| Resume | interrupted run does not double-commit |
| Upstream edit | only dependent units go stale; unrelated chapters stay valid |
| Provider swap | `template` → `openai` without rewriting Canon schema |

## Next reading

- [ARCHITECTURE](ARCHITECTURE.md) — layers and commit path
- [LLM_PROVIDERS](LLM_PROVIDERS.md) — endpoint matrix and failover
- [CONTRIBUTING](CONTRIBUTING.md) — tests and design red lines
