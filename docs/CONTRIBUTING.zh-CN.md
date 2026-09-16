[![English](https://img.shields.io/badge/English-Contributing-blue)](CONTRIBUTING.md)
[![简体中文](https://img.shields.io/badge/简体中文-贡献指南-green)](CONTRIBUTING.zh-CN.md)

# 贡献指南

感谢关注 Novel Weaver。本仓库是 **AI 长篇小说生成引擎**（Core Engine），不是聊天写作工具或小说编辑器。提交前请先阅读 [README.zh-CN](../README.zh-CN.md) 中的定位与设计约束。

## 定位提醒

确认变更服务于长篇持续生产，而不是上层表面产品化：

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

## 开发环境

```bash
git clone https://github.com/zcbacxc/novel-weaver.git
cd novel-weaver
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
python -m pip install -e ".[dev]"
```

需要 **Python 3.12+**。核心运行时无强制第三方依赖。

## 运行测试

```bash
python -m pytest tests -v
```

CI 在 Linux 上对 Python 3.12 / 3.13 跑同一套测试，并单独校验 sdist/wheel 构建。合并前请保证本地全绿。

可选冒烟（无需真实 LLM）：

```bash
novel-weaver demo --workspace .workspaces/demo
novel-weaver engine --provider template --workspace .workspaces/engine
```

## 项目结构（公开摘要）

```text
src/novel_weaver/
  domain/       # Canonical 实体与状态枚举
  truth/        # Evidence / Proposal / Commit Guard / Audit
  storage/      # SQLite 仓储、Snapshot / Release / Artifact
  production/   # 编排、规划、失效、修复、质量、审校
  ai/           # Provider（fake / template / openai 兼容 / failover）
  runtime/      # Checkpoint / Resume / Cost / Diagnostics
  benchmarks/   # 长程生产基准
  cli/          # novel-weaver 命令行入口
tests/
docs/           # 公开双语文档（英文主文档）
```

更完整的分层说明见 [ARCHITECTURE.zh-CN.md](ARCHITECTURE.zh-CN.md)。

## 分支与 PR

| 分支 | 用途 |
|------|------|
| `main` | 可交付主干；禁止未经 PR 的代码变更直推 |
| `feature/*` | 功能或文档，自 `main` 拉出，PR 合回 |
| `hotfix/*` | 紧急修复，自 `main` 拉出，PR 合回 |

```text
git checkout main && git pull
git checkout -b feature/<name>
# ... 开发、本地测试 ...
git push origin feature/<name>
# → 打开 PR → CI 绿后合并
```

合并前要求：

- CI（`test` + `build`）必须通过
- 新行为补测试；修复缺陷时优先加回归用例
- 用户可见变更更新 [CHANGELOG.md](../CHANGELOG.md) 的 `[Unreleased]`
- 版本号只在发版提交中改 `pyproject.toml`（见 [RELEASE_CHECKLIST.zh-CN.md](RELEASE_CHECKLIST.zh-CN.md)）
- 仓库仅允许 **Squash and merge**（禁 merge commit / rebase merge）；合并后自动删除源分支
- `main` 受保护：需 1 个批准、过期 review 会失效、禁止 force push / 删除分支、线性历史

## 提交约定

前缀（与 CI/历史提交一致）：

- `feat:` — 新功能
- `fix:` — 缺陷修复
- `docs:` — 仅文档
- `chore:` — 维护、CI、工具
- `refactor:` — 不改行为的重构
- `test:` — 测试

提交信息写清 **为什么**，避免只罗列文件名。

## 代码与注释

- Python 使用类型注解；公共 API 用英文 Google-style docstring（`Args` / `Returns` / `Raises`）。
- 行内注释解释非显而易见决策（`Decision:` / 为何不用另一方案）。
- 源文件保留 SPDX 头：`AGPL-3.0-or-later`。
- 禁止在代码、文档、提交信息中使用内部追踪码（如 `EP*` / `WP*` / `NA-M*`）。

## 文档成对维护

- 公开页以**英文为主**（`.md`），中文为结构对齐的 `.zh-CN.md`
- 两边标题层级、图/表数量保持对齐
- 禁止把本地设计文档复制进 `docs/`

## 设计红线（贡献前必读）

以下不变量不得在 PR 中削弱：

1. **Canonical Story 是唯一正式真相**；向量/摘要/Memory 等只是可重建投影。
2. **Draft / Candidate / Canonical 严格分层**；模型输出默认只是 Candidate。
3. **`PENDING` ≠ `FALSE` ≠ `TRUE`**；无证据不得晋升 Canon。
4. **正式状态变更必须过 Commit Guard / 版本校验**；LLM 不直接写 Canon。
5. **Runtime 失败不污染 Canon**；中断/重试不得产生重复 Commit。
6. **变化只传播到真实依赖范围**（Impact → 最小失效）。
7. **Provider 可替换**；Agent 是实现方式，不是系统边界。

范围上请拒绝：社区/发布平台、聊天 UI、会员支付、「一键整本」作为核心目标。

## 许可证

本项目采用 **AGPL-3.0-or-later**。贡献即表示同意以相同许可证贡献代码。新增依赖前请确认许可证兼容；通过网络提供基于本引擎的服务时，须遵守 AGPL 第 13 条。
