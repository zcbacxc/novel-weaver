[![English](https://img.shields.io/badge/English-Roadmap-blue)](ROADMAP.md)
[![简体中文](https://img.shields.io/badge/简体中文-路线图-green)](ROADMAP.zh-CN.md)

# Roadmap

> Per-release details live in [CHANGELOG.md](../CHANGELOG.md). This page is a public summary only — it does **not** replace internal planning and does not commit to undelivered dates.

## Planning principles

1. Serve **Core Engine** positioning only — no chat UI, community, SaaS, or agent-chain productization.
2. Prefer engineering properties (repeat / recover / repair / trace / swap provider) over demos.
3. Alternate user-visible capability with infrastructure hardening.
4. Do not claim “stable public Python API” until an explicit contract is exported.

## Shipped

| Version / stage | Theme |
|-----------------|-------|
| 0.1.0 (Phase 0–5 kernel) | Truth boundary + Commit Guard; single-chapter production; continuous production/resume; incremental invalidation/repair; quality loop + semantic review; hardening (retry, cost, diagnostics, failover, snapshot, bench); OpenAI-compatible provider; SQLite + CLI |

Package version source of truth: `pyproject.toml` (**0.1.0**). Public Python API is **not** yet a formal stability contract (see [PACKAGING](PACKAGING.md)).

## Near-term direction (planned, not delivered)

Themes are ordered for engineering risk reduction; ship status is determined by commits and CHANGELOG.

- Enable PyPI Trusted Publishing end-to-end when Publisher is configured
- Public bilingual docs set (this batch: EN primary + `.zh-CN.md` pairs)
- Richer public architecture diagrams / state-machine notes if demand grows
- Provider recommendation matrix and optional `docs/llm-providers/` splits
- Evaluate stronger book-wide consistency scans and optional projection rebuild tools
- Optional mkdocs site only if public reference volume justifies it

## Explicit non-goals (this repo)

| Not here | Why |
|----------|-----|
| Community / publishing / membership SaaS | upper product layer |
| Chat-style writing UI as core | not continuous-production kernel |
| “One-click whole book” replacing the controlled loop | violates recoverability/traceability |

Upper products may depend on this engine; they must not redefine the core boundary.

## Historical note

Phase 0–5 acceptance details and engineering process notes live in local design docs and are not published here. Public surface keeps: shipped capability (CHANGELOG), architecture overview (ARCHITECTURE), decision rationale (ADR).
