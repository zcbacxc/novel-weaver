# AI 编程助手导航

> 给 Claude Code / Cursor / Copilot 等工具的英文/中文文档索引。内容以各权威文件为准，本页只做链接。

## 快速入口

| 主题 | 文档 |
|------|------|
| 项目定位与安装 | [README](../README.md) |
| 变更记录 | [CHANGELOG](../CHANGELOG.md) |
| 贡献流程 | [CONTRIBUTING](CONTRIBUTING.md) |

## 架构与决策

| 主题 | 文档 |
|------|------|
| 分层与主路径 | [ARCHITECTURE](ARCHITECTURE.md) |
| 关键决策 | [ADR](ADR.md) |
| LLM 配置 | [LLM_PROVIDERS](LLM_PROVIDERS.md) |

## 发布

| 主题 | 文档 |
|------|------|
| 打包与版本 | [PACKAGING](PACKAGING.md) |
| 发版核对 | [RELEASE_CHECKLIST](RELEASE_CHECKLIST.md) |
| 公开路线摘要 | [ROADMAP](ROADMAP.md) |

## CLI 速查

```bash
novel-weaver demo --workspace .workspaces/demo
novel-weaver engine --provider template --workspace .workspaces/engine
novel-weaver produce --workspace .workspaces/prod
novel-weaver book-check --workspace .workspaces/demo
novel-weaver bench --chapters 30 --workspace .workspaces/bench-30
novel-weaver --help
```

## 贡献时注意

- 禁止提交 `PROJECT_POSITIONING.md`、`docs-nocommit/`、`CLAUDE.md`、`.claude/`。  
- 勿在代码/文档中引入内部追踪码。  
- 勿削弱 Canonical Truth / Commit Guard 不变量。  
