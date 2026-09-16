[![English](https://img.shields.io/badge/English-Packaging-blue)](PACKAGING.md)
[![简体中文](https://img.shields.io/badge/简体中文-打包-green)](PACKAGING.zh-CN.md)

# Packaging Guide

## Package identity

| Item | Value |
|------|-------|
| PyPI / distribution name | `novel-weaver` |
| Import package | `novel_weaver` |
| Console script | `novel-weaver` → `novel_weaver.cli.main:main` |
| Layout | `src/` |
| Python | `>=3.12` |
| License | `AGPL-3.0-or-later` (PEP 639 string expression) |

Version source of truth: `pyproject.toml` → `version`. Runtime exposes `novel_weaver.__version__`; keep them aligned on release commits.

## Build

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
```

Artifacts: `dist/novel_weaver-<version>-py3-none-any.whl` and `dist/novel_weaver-<version>.tar.gz`.

If a local mirror cannot resolve `setuptools>=77`, use the installed setuptools: `python -m build --no-isolation`. CI builds with isolation from the official index.

## Install

```bash
# source (dev)
pip install -e ".[dev]"

# after publish
pip install novel-weaver
```

Runtime has **no mandatory third-party dependencies**; `[dev]` is `pytest` only.

## Release flow (summary)

Full DoD: [RELEASE_CHECKLIST](RELEASE_CHECKLIST.md).

1. Merge `feature/*` PR to `main` with green CI
2. Bump version + CHANGELOG in the same commit
3. `git tag -a vX.Y.Z` (push tags separately from branch push)
4. Push the tag; after Trusted Publishing is enabled, `publish.yml` publishes
5. Clean-env install smoke after publish

Pre-release tags: `vX.Y.Z-test` / `vX.Y.Z-rc.N`. **Never reuse a published version number.**

## Dependency policy

- Keep zero mandatory runtime deps ([ADR-005](ADR.md#adr-005-stdlib-first-and-zero-mandatory-runtime-deps)).
- Before adding a dep: can stdlib do it? AGPL-compatible license? supply-chain surface?
- Dev/CI deps go in `[project.optional-dependencies]`, not core `dependencies`.

## Public surface (current)

Still evolving under `0.x`:

- CLI commands documented in README / ARCHITECTURE
- `NOVEL_WEAVER_*` env vars in `.env.example`
- workspace SQLite Canonical schema (may migrate with documented notes)

Internal modules may change without notice. A formal stability promise document is deferred until a public Python contract is exported.

## License and SPDX

- Source headers: `SPDX-License-Identifier: AGPL-3.0-or-later`
- `pyproject.toml` uses PEP 639: `license = "AGPL-3.0-or-later"` — **no** license Trove classifier
- Build backend: `setuptools>=77.0`

## Related

- [Release checklist](RELEASE_CHECKLIST.md)
- [Contributing](CONTRIBUTING.md)
- [ADR](ADR.md)
