[![English](https://img.shields.io/badge/English-README-blue)](README.md)
[![简体中文](https://img.shields.io/badge/简体中文-README-green)](README.zh-CN.md)

# Novel Weaver

[![License: AGPL v3+](https://img.shields.io/badge/License-AGPL%20v3%2B-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/zcbacxc/novel-weaver/actions/workflows/ci.yml/badge.svg)](https://github.com/zcbacxc/novel-weaver/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/novel-weaver.svg)](https://pypi.org/project/novel-weaver/)

> 产品化长篇小说生产的 Core Engine

Novel Weaver 把章节生产做成**可重复、可控制、可恢复、可修复、可追溯**的工程流水线。它**不是**聊天写作工具、小说编辑器、社区平台，也不是多 Agent Prompt 链。

```
Plan → Context Pack → Provider.generate → Candidate
  → Validate / Semantic Review → Commit Guard
  → Canonical Story → Checkpoint / Resume / Audit
```

成功标准不是「能不能生成一章漂亮正文」，而是长跑仍能稳定向后、改前文只失效真实依赖、换 Provider 不丢失正式故事真相。

## 能力

- 真相边界：Evidence → Proposal → Commit Guard 晋升 Canon
- Draft / Candidate / Canonical 严格分层（`PENDING` ≠ `FALSE` ≠ `TRUE`）
- 单章生产闭环：双层质量检查 + 可选 LLM 语义审校
- 连续生产：Checkpoint / Resume，重试不双提交
- 增量修复：依赖图、影响分析、最小失效
- 外部改稿先 Reconcile 再继续提交
- 全书一致性检查、快照、Release、时间线投影
- Provider 可替换：`fake` / `template` / OpenAI 兼容 / failover
- SQLite Canonical 存储（stdlib）；核心零强制第三方运行时依赖
- CLI 覆盖演示、生产、基准、导出与诊断

## 环境要求

- Python 3.12+

## 安装

### 从源码（当前推荐）

```bash
git clone https://github.com/zcbacxc/novel-weaver.git
cd novel-weaver
python -m pip install -e ".[dev]"
```

### 从 PyPI

```bash
pip install novel-weaver
```

核心运行时**无强制第三方依赖**。真实 LLM 可选，走任意 OpenAI 兼容 HTTP 端点。

## 快速开始

```bash
# 离线测试（不调用付费 LLM）
python -m pytest tests -v

# 演示 workspace：真相边界 + 短引擎闭环
novel-weaver demo --workspace .workspaces/demo

# 单章引擎生产
novel-weaver engine --provider template --workspace .workspaces/engine
# novel-weaver engine --provider openai --workspace .workspaces/llm

# 连续多章生产
novel-weaver produce --workspace .workspaces/prod

# 全书一致性检查
novel-weaver book-check --workspace .workspaces/demo

# 长程基准（默认 30 章）
novel-weaver bench --chapters 30 --workspace .workspaces/bench-30
```

更多路径见 [docs/QUICKSTART.zh-CN.md](docs/QUICKSTART.zh-CN.md) 与 [docs/ARCHITECTURE.zh-CN.md](docs/ARCHITECTURE.zh-CN.md)。

## LLM 配置（可选）

复制 `.env.example` 为项目根 `.env`，或使用 `~/.novel-weaver/.env`：

```env
NOVEL_WEAVER_LLM_BASE_URL=https://api.openai.com/v1
NOVEL_WEAVER_LLM_API_KEY=sk-...
NOVEL_WEAVER_LLM_MODEL=gpt-4o-mini
```

详见 [docs/LLM_PROVIDERS.zh-CN.md](docs/LLM_PROVIDERS.zh-CN.md)。无密钥时 `fake` / `template` 仍可跑通完整引擎闭环。

## 包结构

```text
src/novel_weaver/
  config.py         # 配置与 workspace 引导
  domain/           # Canonical 实体与版本
  truth/            # Evidence / Proposal / Commit Guard / Audit
  storage/          # SQLite 仓储 + Snapshot / Release / Artifact
  production/       # 编排、失效、修复、审校
  ai/               # Provider（fake / template / openai 兼容 / failover）
  runtime/          # Checkpoint / Resume / Cost / Diagnostics
  benchmarks/       # 长程生产基准
  cli/              # novel-weaver 入口
tests/
docs/               # 公开双语文档（英文主文档）
```

## 设计约束

- Canonical Story 是唯一正式真相；派生数据可重建。
- Draft / Candidate / Canonical 严格分层；无证据不得晋升 Canon。
- Runtime 失败不污染 Canon；提交必须通过 Commit Guard。
- 修改前文只使真实依赖范围失效（最小必要重生产）。
- Provider / 模型可替换；Agent 是实现方式，不是系统边界。

## 文档

| 主题 | English | 简体中文 |
|------|---------|----------|
| 文档索引 | [docs/index.md](docs/index.md) | — |
| 快速开始 | [QUICKSTART](docs/QUICKSTART.md) | [快速开始](docs/QUICKSTART.zh-CN.md) |
| 架构 | [ARCHITECTURE](docs/ARCHITECTURE.md) | [架构](docs/ARCHITECTURE.zh-CN.md) |
| 贡献 | [CONTRIBUTING](docs/CONTRIBUTING.md) | [贡献指南](docs/CONTRIBUTING.zh-CN.md) |
| LLM 配置 | [LLM_PROVIDERS](docs/LLM_PROVIDERS.md) | [Provider 配置](docs/LLM_PROVIDERS.zh-CN.md) |
| 架构决策 | [ADR](docs/ADR.md) | [架构决策](docs/ADR.zh-CN.md) |
| 打包 | [PACKAGING](docs/PACKAGING.md) | [打包](docs/PACKAGING.zh-CN.md) |
| 发布清单 | [RELEASE_CHECKLIST](docs/RELEASE_CHECKLIST.md) | [发布清单](docs/RELEASE_CHECKLIST.zh-CN.md) |
| 路线图 | [ROADMAP](docs/ROADMAP.md) | [路线图](docs/ROADMAP.zh-CN.md) |
| AI 导航 | [AI_GUIDE](docs/AI_GUIDE.md) | [AI 导航](docs/AI_GUIDE.zh-CN.md) |

## 发布

- 版本号唯一来源：`pyproject.toml`。
- 变更记录：[CHANGELOG.md](CHANGELOG.md)。
- 核对清单：[docs/RELEASE_CHECKLIST.zh-CN.md](docs/RELEASE_CHECKLIST.zh-CN.md)。

## 许可证

**GNU Affero General Public License v3.0 or later**（AGPL-3.0-or-later）。完整条款见 [LICENSE](LICENSE)。通过网络提供基于本引擎的服务时，须按 AGPL 第 13 条提供对应源代码。
