[![English](https://img.shields.io/badge/English-Release_Checklist-blue)](RELEASE_CHECKLIST.md)
[![简体中文](https://img.shields.io/badge/简体中文-发布清单-green)](RELEASE_CHECKLIST.zh-CN.md)

# Release Checklist

All items must pass before cutting a formal tag. Any failure stops the release.

Version source of truth: `pyproject.toml` `version` (keep aligned with `src/novel_weaver/__init__.py` `__version__`).

## 1. Tests and build

- [ ] `python -m pytest tests -v` all green
- [ ] `python -m build` produces sdist + wheel
- [ ] `python -m twine check dist/*` passes
- [ ] clean-env install of the wheel: `novel-weaver --help` works

## 2. Version and changelog

- [ ] `pyproject.toml` / `__version__` bumped to target `X.Y.Z`
- [ ] `CHANGELOG.md` moves `[Unreleased]` into `## [X.Y.Z] - YYYY-MM-DD`
- [ ] entries have no internal tracking codes; published history is not rewritten
- [ ] compare links at the bottom updated

## 3. Docs and metadata

- [ ] `README.md` / `README.zh-CN.md` install and commands match current CLI
- [ ] public docs do not present “planned” as “shipped”
- [ ] `pyproject.toml` URLs / description still accurate
- [ ] bilingual pairs remain structure-aligned for touched pages

## 4. Git and CI

- [ ] changes merged to `main` via PR with green CI
- [ ] annotated tag: `git tag -a vX.Y.Z -m "vX.Y.Z — <theme>"`
- [ ] **push branch and tag separately**: `git push origin main`, then `git push origin vX.Y.Z`
- [ ] pre-releases use `vX.Y.Z-test` / `vX.Y.Z-rc.N` (never mix with the formal tag)

## 5. PyPI (after Trusted Publishing is enabled)

- [ ] Publisher configured on pypi.org: Owner `zcbacxc` · Repo `novel-weaver` · Workflow `publish.yml`
- [ ] Actions publish succeeds after tag push
- [ ] `pip install novel-weaver==X.Y.Z` verified
- [ ] GitHub Release is not draft; body matches that CHANGELOG version

## 6. Post-release smoke

- [ ] after install: `novel-weaver demo --workspace <tmp>` succeeds
- [ ] Canonical / Runtime separation still holds on the demo path

## Current status notes

- CI and packaging scaffolding exist; Trusted Publishing publish path is ready in `publish.yml` once Publisher is configured on PyPI.
- Never reuse a published version number.
- **Do not tag** if tests or the build fail.
