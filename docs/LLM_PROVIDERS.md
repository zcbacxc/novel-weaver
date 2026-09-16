[![English](https://img.shields.io/badge/English-LLM_Providers-blue)](LLM_PROVIDERS.md)
[![简体中文](https://img.shields.io/badge/简体中文-Provider配置-green)](LLM_PROVIDERS.zh-CN.md)

# LLM Provider Configuration

Generation and optional semantic review use any **OpenAI-compatible** Chat Completions endpoint. Switching vendors means changing three config values. **Without LLM keys, `fake` / `template` still run the full engine loop.**

## Quick selection

| Scenario | Recommendation |
|----------|----------------|
| Local tests / CI | `fake` or `template` — no keys |
| Fastest real generation smoke | any OpenAI-compatible endpoint + small model |
| Fully offline | `template`, or a local compatible gateway (e.g. Ollama `/v1`) |
| Long runs on a budget | small model + `NOVEL_WEAVER_FAILOVER=openai,template` |

## Generic configuration

Copy `.env.example` to project-root `.env`, or use `~/.novel-weaver/.env`:

```env
NOVEL_WEAVER_LLM_BASE_URL=https://api.openai.com/v1
NOVEL_WEAVER_LLM_API_KEY=sk-...
NOVEL_WEAVER_LLM_MODEL=gpt-4o-mini
```

Optional:

```env
# failover chain (names from ai/registry)
NOVEL_WEAVER_FAILOVER=openai,template
# default provider: fake | template | openai | failover
NOVEL_WEAVER_DEFAULT_PROVIDER=template
# LLM semantic review (empty = auto on for openai/llm)
NOVEL_WEAVER_USE_LLM_REVIEW=
```

Verify:

```bash
novel-weaver config --show
novel-weaver engine --provider openai --workspace .workspaces/llm
```

On config errors, CLI/engine exits with a clear message and does **not** write Canonical.

## Endpoint contract

Any service implementing the following relative to `BASE_URL` can plug in:

- `POST /chat/completions`
- request body includes `model`, `messages`
- response contains `choices[0].message.content` and optional `usage`

Local example (illustration only, not an endorsement):

```env
# Ollama (if OpenAI-compatible API is enabled)
NOVEL_WEAVER_LLM_BASE_URL=http://127.0.0.1:11434/v1
NOVEL_WEAVER_LLM_API_KEY=ollama
NOVEL_WEAVER_LLM_MODEL=qwen2.5:7b
```

When vendor-specific guides grow beyond one page, split under `docs/llm-providers/` and keep this file as the index (planned; not required today).

## Design constraints

- Providers only produce Candidates / review opinions — they never write Canonical.
- Commits must pass Commit Guard; provider failures may retry or failover without polluting official state.
- Never put API keys in the repo, issues, or log bodies.

## Related

- [Architecture: Provider layer](ARCHITECTURE.md#provider-layer)
- [Quickstart](QUICKSTART.md)
- [Contributing](CONTRIBUTING.md)
