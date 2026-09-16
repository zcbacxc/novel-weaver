[![English](https://img.shields.io/badge/English-Quickstart-blue)](QUICKSTART.md)
[![简体中文](https://img.shields.io/badge/简体中文-快速开始-green)](QUICKSTART.zh-CN.md)

# 快速开始

先离线跑通引擎，再按需接入真实 LLM。

## 前置条件

- Python 3.12+
- Git（从源码安装时）

```bash
git clone https://github.com/zcbacxc/novel-weaver.git
cd novel-weaver
python -m pip install -e ".[dev]"
novel-weaver --help
```

## 1. 验证离线安装

```bash
python -m pytest tests -v
```

默认测试使用 `fake` / `template` Provider，不调用付费 API。

## 2. 运行引擎演示

```bash
novel-weaver demo --workspace .workspaces/demo
```

创建 workspace，走通真相边界，并完成一段短生产闭环。

## 3. 用 template Provider 生产

```bash
novel-weaver engine --provider template --workspace .workspaces/engine
novel-weaver status --workspace .workspaces/engine
```

`template` 无需密钥，可完整看到 Candidate → 质量 → Commit Guard 路径。

## 4. 连续生产与检查

```bash
# 连续多章生产
novel-weaver produce --workspace .workspaces/prod

# 全书一致性
novel-weaver book-check --workspace .workspaces/demo

# 长程基准（默认 30 章）
novel-weaver bench --chapters 10 --workspace .workspaces/bench
```

## 5. 可选：真实 LLM

复制根目录 `.env.example` 为 `.env`（或使用 `~/.novel-weaver/.env`）：

```env
NOVEL_WEAVER_LLM_BASE_URL=https://api.openai.com/v1
NOVEL_WEAVER_LLM_API_KEY=sk-...
NOVEL_WEAVER_LLM_MODEL=gpt-4o-mini
NOVEL_WEAVER_FAILOVER=openai,template
```

```bash
novel-weaver config --show
novel-weaver engine --provider openai --workspace .workspaces/llm
```

任意 OpenAI 兼容 `POST /chat/completions` 端点均可。Provider 失败会让该步失败，**不会**写入 Canonical。详见 [LLM_PROVIDERS.zh-CN.md](LLM_PROVIDERS.zh-CN.md)。

## 6. 查看与导出

```bash
novel-weaver status --workspace .workspaces/demo
novel-weaver timeline --workspace .workspaces/demo
novel-weaver snapshot-export --workspace .workspaces/demo
novel-weaver canonical-export --workspace .workspaces/demo
novel-weaver release-create --workspace .workspaces/demo
```

## Workspace 概念布局

每个 `--workspace` 目录大致包含：

- `novel.sqlite3` — Canonical + Runtime 存储
- 快照 / Canonical 导出 / 制品等派生文件

以 SQLite 中的 Canonical 为正式故事真相；投影可重建。

## 什么算「跑通」

| 检查 | 通过表现 |
|------|----------|
| 离线 CI | 无密钥时 pytest 全绿 |
| 单章 | 产出 Candidate、记录质量结果，提交被 Guard 接受或明确拒绝 |
| Resume | 中断重跑不双提交 |
| 改前文 | 仅真实依赖单元变 stale，无关章节仍 valid |
| 换 Provider | `template` → `openai` 不必改写 Canon 结构 |

## 下一步

- [架构](ARCHITECTURE.zh-CN.md) — 分层与提交路径
- [Provider 配置](LLM_PROVIDERS.zh-CN.md) — 端点与 failover
- [贡献指南](CONTRIBUTING.zh-CN.md) — 测试与设计红线
