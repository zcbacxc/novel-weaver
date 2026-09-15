# Novel Weaver

[![License: AGPL v3+](https://img.shields.io/badge/License-AGPL%20v3%2B-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/zcbacxc/novel-weaver/actions/workflows/ci.yml/badge.svg)](https://github.com/zcbacxc/novel-weaver/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/novel-weaver.svg)](https://pypi.org/project/novel-weaver/)

产品化工程阶段的 **AI 长篇小说生成引擎**（Core Engine）。

本仓库聚焦 **Phase 0–5 最小可验证连续生产内核**：Truth Boundary、单章生产、连续生产/恢复、增量修复、质量闭环与生产加固。目标不是「一键写完一本小说」，而是让长篇生产**可重复、可控制、可恢复、可修复、可追溯**。

## 安装

```bash
# 从源码（当前推荐）
git clone https://github.com/zcbacxc/novel-weaver.git
cd novel-weaver
python -m pip install -e ".[dev]"

# PyPI（发布后可用）
pip install novel-weaver
```

需要 **Python 3.12+**。核心运行时无强制第三方依赖（LLM 走 OpenAI 兼容 HTTP，可选）。

## 快速开始

```bash
# 运行测试
python -m pytest tests -v

# 初始化示例故事并跑通假生成闭环
novel-weaver demo --workspace .workspaces/demo

# 使用 template / openai Provider 单章生产
novel-weaver engine --provider template --workspace .workspaces/engine
# novel-weaver engine --provider openai --workspace .workspaces/llm

# 长程基准（默认 30 章）
novel-weaver bench --chapters 30 --workspace .workspaces/bench-30
```

配置真实 LLM（可选）：复制 `.env.example` 为项目根 `.env` 或 `~/.novel-weaver/.env`。

## 包结构

```text
src/novel_weaver/
  config.py         # 配置与 workspace 引导
  domain/           # Canonical 实体与版本
  truth/            # Evidence / Proposal / Commit Guard / Audit
  storage/          # SQLite 仓储 + Snapshot / Release / Artifact
  production/       # 编排、失效、修复、语义审校、全书一致性
  ai/               # Provider（fake / template / openai 兼容 / failover）
  runtime/          # Checkpoint / Resume / Cost / Diagnostics
  benchmarks/       # 长程生产基准
  cli/              # 命令行入口
tests/
```

## 设计约束

- Canonical Story 是唯一正式真相；派生数据可重建。
- Draft / Candidate / Canonical 严格分层；无证据不得晋升 Canon。
- Runtime 失败不污染 Canon；Commit 必须通过 Guard。
- 修改前文只使真实依赖范围失效。
- Provider / 模型可替换；Agent 是实现方式，不是系统边界。

## 文档

| 文档 | 说明 |
|------|------|
| [docs/](docs/index.md) | 公开文档索引 |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | 架构概述与主路径 |
| [CONTRIBUTING](docs/CONTRIBUTING.md) | 贡献指南 |
| [LLM_PROVIDERS](docs/LLM_PROVIDERS.md) | LLM 配置 |
| [ADR](docs/ADR.md) | 架构决策 |
| [RELEASE_CHECKLIST](docs/RELEASE_CHECKLIST.md) | 发布清单 |

## 发布

- 版本号唯一来源：`pyproject.toml`。
- 变更记录：[CHANGELOG.md](CHANGELOG.md)。
- 当前阶段以源码安装与 CI 验证为主；PyPI Trusted Publishing 流水线预留为后续发布步骤。

## 许可证

本项目采用 **GNU Affero General Public License v3.0 or later**（AGPL-3.0-or-later）。

完整条款见 [LICENSE](LICENSE)。通过网络提供基于本引擎的服务时，须按 AGPL 第 13 条向用户提供对应源代码。
