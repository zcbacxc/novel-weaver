[![English](https://img.shields.io/badge/English-Architecture-blue)](ARCHITECTURE.md)
[![简体中文](https://img.shields.io/badge/简体中文-架构-green)](ARCHITECTURE.zh-CN.md)

# 架构概述

描述 Novel Weaver **已落地代码** 的分层与主路径，面向公开贡献者。定位与完整内部实现方案不在本目录；本文件与代码冲突时以代码为准并回写。

## 一句话

引擎把「长篇章节生产」做成可恢复的工程流水线：**规划 → 生成 Candidate → 校验/审校 → Commit Guard → Canonical**；模型负责理解与生成，**不直接写正式真相**。

## 分层

```text
Production Interface（CLI）
        │
        ▼
Production Engine / Orchestrator
  plan → context → generate → quality → commit
        │
        ├─► Truth Layer（Evidence / Proposal / Commit Guard / Audit）
        │
        ├─► Canonical Domain（Story / StateItem / Event / Chapter…）
        │
        ├─► Derived / Support
        │     Context Pack · Dependency · Invalidation · Fingerprint
        │     Threads · Memory · Timeline · BookPass · Reconcile
        │
        ├─► Runtime（Checkpoint · Resume · Cost · Diagnostics）
        │
        └─► AI Providers（fake / template / openai-compat / failover）
                    │
                    ▼
              Persistence（SQLite + Workspace files）
```

| 层 | 包路径 | 职责 |
|----|--------|------|
| CLI | `novel_weaver.cli` | 参数解析、打开 workspace、调用 Engine/仓储 |
| 编排 | `novel_weaver.production` | 章节生产闭环、规划、失效修复、质量与审校 |
| 真相 | `novel_weaver.truth` | 证据、提案晋升、提交门禁、审计 |
| 领域 | `novel_weaver.domain` | Canonical 实体与状态机 |
| 存储 | `novel_weaver.storage` | SQLite 表与仓储、快照、发布、制品 |
| 运行时 | `novel_weaver.runtime` | 检查点、续跑、成本、诊断 |
| AI | `novel_weaver.ai` | Provider 协议与实现 |

## Canonical 与状态分层

**Canonical Story** 是唯一正式真相（SQLite 中的 Story / StateItem / Event / Chapter 等）。派生投影（上下文包、检索、记忆、时间线视图）必须可从 Canonical 重建，不得成为不可验证的唯一事实源。

事实生命周期（`FactStatus`）：

```text
UNKNOWN / PENDING ──► PROPOSED ──► REVIEWED ──► CANONICAL
                         │                        │
                         ▼                        ▼
                    DISPUTED                 SUPERSEDED
                                              INVALIDATED
```

要点：

- `PENDING` 表示未知/待定，**不是** `FALSE`。
- 模型猜测不得跳过证据与晋升路径直接变成 `CANONICAL`。
- 晋升需要 **Evidence 支撑的 Proposal**；空证据会被拒绝。

章节相关状态：

- **ProductionUnitStatus**：`PLANNED → GENERATING → CANDIDATE_READY → … → COMMITTED`（或 `STALE` / `BLOCKED`）
- **CandidateStatus**：`DRAFT → VALIDATED → REVIEWED → ACCEPTED → COMMITTED`（或 `REJECTED` / `STALE`）

模型输出默认是 **Candidate**；只有 Commit 成功才改变正式 Story State。

## 单章生产主路径

`ProductionEngine.produce_chapter`（`production/engine.py`）串联：

1. **规划** — `RollingPlanner` 产出/复用章节计划  
2. **会话** — `ProductionOrchestrator.begin_session` 固定 `base_story_revision`、计划版本、Context 指纹  
3. **上下文** — `build_context_pack` 从 Canonical 组装生成所需状态  
4. **生成** — 选定 `Provider` 产出 Candidate（默认可走 `fake` / `template`）  
5. **质量** — 双层检查与可选 LLM 语义审校，得到 accept/revise/reject  
6. **提交** — 经 **Commit Guard** 校验后写入 Canonical；失败不落正式状态  
7. **运行时** — Checkpoint / Cost / Diagnostics 记录过程，可 Resume  

```text
plan ──► begin_session ──► context ──► provider.generate
                                              │
                                              ▼
                                    validate / review
                                              │
                         reject/revise ◄──────┤
                                              ▼ accept
                                       Commit Guard
                                         │      │
                                      reject   accept
                                                ▼
                                          Canonical + Audit
```

## Commit Guard

`truth/commit_guard.py` 拒绝过期或错位的提交，原因包括：

- Story / Plan 版本与会话基线不一致  
- 生产单元不匹配、单元锁定  
- Context 指纹不匹配（上游已变）  
- 重复 Commit  

会话（`ProductionSession`）是对「生成时所依据的世界」的不可变快照；Guard 保证 **旧会话不能覆盖新 Canonical**。

## 失效与修复

前文修改（作者外部编辑或重新晋升事实）走：

1. **Reconcile** 检测正文/状态差异（`production/reconcile.py`）  
2. **Dependency Graph + Impact** 找出真实受影响节点（`dependency.py` / `invalidation.py`）  
3. 最小范围 **mark stale** → 局部重规划/重生成  
4. 无关章节保持 valid；必要时扩大修复级别  

目标是 **最小必要重生产**，不是全书重写。

## Provider 层

`ai/base.py` 定义协议：Provider 执行生成/审校类任务，**不写 Canon**。

| 名称 | 用途 |
|------|------|
| `fake` | 测试与 CI，确定性假文本 |
| `template` | 无 LLM 的模板生成，本地可演示 |
| `openai` | OpenAI 兼容 Chat Completions（stdlib HTTP） |
| `failover` | 按链故障切换 |

注册与选择见 `ai/registry.py`；瞬时错误可 `retry_with_backoff`。配置通过 `NOVEL_WEAVER_LLM_*` 环境变量（见根目录 `.env.example`）。

## 存储与工作区

- 主库：workspace 下 `novel.sqlite3`（stdlib `sqlite3`）  
- 仓储：`storage/repositories.py`  
- 辅助：快照导入导出、Release、Artifact、Canonical 文件导出  
- Runtime 表与 Canonical 表分离：中断、重试、换 Provider 不污染小说真相  

## CLI

入口：`novel-weaver` / `python -m novel_weaver`（`cli/main.py`）。

| 命令 | 作用 |
|------|------|
| `demo` | 真相边界 + 短引擎演示 |
| `engine` | 单章/引擎生产（可选 `--provider`） |
| `produce` | 连续多章生产 |
| `book-check` | 全书一致性检查 |
| `bench` | 长程基准 |
| `status` | 工作区状态 |
| `snapshot-export` / `snapshot-import` | 快照 |
| `release-create` | 发布记录 |
| `canonical-export` | Canonical 导出 |
| `timeline` | 时间线视图 |
| `config` | 配置查看 |

## 测试策略

- 默认离线：`fake` / `template` Provider，不调用付费 API  
- 边界：Commit Guard 拒绝路径、Evidence 晋升、Resume 不双提交、Impact 最小失效、质量清单  
- 长程：`benchmarks/` + `bench` 命令可重复跑多章  

## 非目标

本引擎 **不是** 小说站、社区、发布 SaaS，也 **不是** 多 Agent 聊天工作流编排器。上层产品可依赖本包；核心边界不被上层 UI 反向定义。

## 相关文档

- [快速开始](QUICKSTART.zh-CN.md)  
- [贡献指南](CONTRIBUTING.zh-CN.md)  
- [架构决策记录](ADR.zh-CN.md)  
- [发布清单](RELEASE_CHECKLIST.zh-CN.md)  
- [路线图](ROADMAP.zh-CN.md)  
