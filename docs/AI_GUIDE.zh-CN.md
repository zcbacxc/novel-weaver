[![English](https://img.shields.io/badge/English-AI_Guide-blue)](AI_GUIDE.md)
[![简体中文](https://img.shields.io/badge/简体中文-AI导航-green)](AI_GUIDE.zh-CN.md)

# AI 编程助手导航

> 面向 Claude Code / Cursor / Copilot 等工具的导航索引。正文以各权威文件为准，本页只做路由并声明编辑约束。

## 从这里开始

| 主题 | 文档 |
|------|------|
| 概览与安装 | [README](../README.md) |
| 中文 README | [README.zh-CN](../README.zh-CN.md) |
| 10 分钟快速开始 | [QUICKSTART.zh-CN.md](QUICKSTART.zh-CN.md) |
| 架构（分层与提交路径） | [ARCHITECTURE.zh-CN.md](ARCHITECTURE.zh-CN.md) |
| 贡献规则 | [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md) |

## 设计决策

| 主题 | 文档 |
|------|------|
| ADR 索引 | [ADR.zh-CN.md](ADR.zh-CN.md) |
| Provider 配置 | [LLM_PROVIDERS.zh-CN.md](LLM_PROVIDERS.zh-CN.md) |
| 版本与 PyPI | [PACKAGING.zh-CN.md](PACKAGING.zh-CN.md) |
| 已交付 / 计划主题 | [ROADMAP.zh-CN.md](ROADMAP.zh-CN.md) |
| 打 tag 前核对 | [RELEASE_CHECKLIST.zh-CN.md](RELEASE_CHECKLIST.zh-CN.md) |

## 编辑时的硬约束

1. 只做 Core Engine —— 不引入聊天 UI、社区、SaaS、「一键整本」范围蔓延
2. Canonical Story 是唯一正式真相；派生投影必须可重建
3. Draft / Candidate / Canonical 严格分层；Provider 永不写 Canon
4. `PENDING` ≠ `FALSE`；无证据不得晋升 Canonical
5. 对外双语保持结构对齐（英文主 `.md` + `.zh-CN.md`）
6. 公开文档与 commit 中不得出现内部追踪码（EP*、WP*、NA-M* 等）
7. 本地设计文档（`PROJECT_POSITIONING.md`、`docs-nocommit/`、`CLAUDE.md`、`.claude/`）**不得**提交或复制进 `docs/`
8. 用户可见变更更新 CHANGELOG；版本号只在 `pyproject.toml`

## CLI 速查

```bash
novel-weaver demo --workspace .workspaces/demo
novel-weaver engine --provider template --workspace .workspaces/engine
novel-weaver produce --workspace .workspaces/prod
novel-weaver book-check --workspace .workspaces/demo
novel-weaver bench --chapters 30 --workspace .workspaces/bench-30
novel-weaver config --show
novel-weaver --help
```

## 仅本地（不要外发）

| 文件 | 职责 |
|------|------|
| `PROJECT_POSITIONING.md` | 定位 / 不做清单（gitignore） |
| `docs-nocommit/confirmed/NOVEL_WEAVER_IMPLEMENTATION_PLAN.md` | 完整工程方案（gitignore） |
| `CLAUDE.md` / `.claude/rules/` | Agent 工作规则（gitignore） |
