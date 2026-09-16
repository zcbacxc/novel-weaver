# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Public bilingual documentation set (English primary + `.zh-CN.md` pairs) for README and `docs/` (Quickstart, Architecture, Contributing, ADR, LLM Providers, Packaging, Release checklist, Roadmap, AI guide).
- AI coding assistant guide now states edit invariants and local-only files.

## [0.1.0] - 2026-09-15

### Added

- Phase 0–5 minimal continuous production kernel for long-form novel generation.
- Truth boundary: Evidence → Proposal → Canonical promotion with Commit Guard; `PENDING` ≠ `FALSE` ≠ `TRUE`.
- Single-chapter production loop: Context Pack → Candidate → validate/review → Commit → Provenance.
- Continuous production with checkpoint/resume and no double-commit on retry.
- Incremental repair: dependency graph, impact analysis, minimal invalidation, escalation path.
- Quality loop: structured Revision Manifest, dual-layer checks, optional LLM semantic review, book-level consistency pass.
- Production hardening: retry, cost tracking, diagnostics, provider failover, snapshots, releases, throughline.
- Providers: `fake`, `template`, OpenAI-compatible, failover chain (stdlib HTTP; no heavy runtime deps).
- SQLite storage for Story / State / Event / Timeline plus snapshot, release, and artifact helpers.
- CLI: `novel-weaver demo|engine|produce|book-check|bench|status|snapshot|release|canonical-export|timeline`.
- Packaging metadata for source install and future PyPI publication (`novel-weaver`).

[Unreleased]: https://github.com/zcbacxc/novel-weaver/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/zcbacxc/novel-weaver/releases/tag/v0.1.0
