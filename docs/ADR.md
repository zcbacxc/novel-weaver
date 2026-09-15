# 架构决策记录（ADR）

记录 Novel Weaver 关键架构决策。每条 ADR 不可变；决策变更时新增一条 supersede 旧条目，并更新索引。

## 如何新增

1. 取下一编号（ADR-006、…）。  
2. 使用与下文相同的结构：Status / Context / Decision Drivers / Considered Options / Decision Outcome / Consequences / References。  
3. 追加到文末并更新索引表。  
4. 只写代码与历史中真实存在的决策，禁止臆造。

## 索引

| ADR | 标题 | 状态 |
|-----|------|------|
| [001](#adr-001-canonical-story-为唯一正式真相) | Canonical Story 为唯一正式真相 | Accepted |
| [002](#adr-002-commit-guard-门禁提交) | Commit Guard 门禁提交 | Accepted |
| [003](#adr-003-sqlite-作为主存储) | SQLite 作为主存储 | Accepted |
| [004](#adr-004-provider-可替换且不写-canon) | Provider 可替换且不写 Canon | Accepted |
| [005](#adr-005-python-stdlib-优先与零强制运行时依赖) | Python stdlib 优先与零强制运行时依赖 | Accepted |

---

## ADR-001: Canonical Story 为唯一正式真相

**Status:** Accepted

**Context**

长篇生成会同时产生正文摘要、检索索引、记忆片段、运行时缓存等派生数据。若任一投影成为「不可验证的唯一事实源」，修改前文、换模型或崩溃恢复后故事状态会漂移且无法审计。

**Decision Drivers**

- 可追溯：任意正式事实应能回指证据或已提交内容。  
- 可恢复：派生数据丢失后必须能重建。  
- 可修复：前文变更时能判断哪些下游真正失效。

**Considered Options**

- 允许向量库/记忆库作为权威事实（拒绝：不可验证、难迁移）。  
- 多真相源投票（拒绝：冲突时无单一裁决规则，工程复杂度高）。

**Decision Outcome**

Canonical Story（领域实体 + 版本化状态）是唯一正式真相。摘要、索引、Memory 等均为 Derived Projection，必须可从 Canonical 重建，不得反向定义 Canon。

**Consequences**

- 正面：恢复路径清晰；Provider/UI 可替换。  
- 代价：所有正式变更必须走 Truth/Commit 边界，不能图省事直写。

**References**

- `docs/ARCHITECTURE.md`  
- `src/novel_weaver/domain/models.py`  
- `src/novel_weaver/truth/`

---

## ADR-002: Commit Guard 门禁提交

**Status:** Accepted

**Context**

生成会话基于某次 Story/Plan 版本与 Context 指纹。会话进行中若其他提交或外部编辑已推进 Canonical，旧会话若直接写回会覆盖新真相或产生幽灵状态。

**Decision Drivers**

- 防止双提交与陈旧覆盖。  
- 中断/重试安全。  
- 拒绝原因可审计。

**Considered Options**

- 仅靠时间戳最后写入者获胜（拒绝：静默丢数据）。  
- 全库长事务锁（拒绝：阻塞并发读与长生成，恢复困难）。

**Decision Outcome**

每次生产会话固化 `ProductionSession`（基线 revision、计划版本、单元、指纹）。提交必须经 `CommitGuard`；不匹配则拒绝并记录原因（版本失配、指纹失配、已提交、单元锁定等）。正式写入仍经 Orchestrator 提交路径。

**Consequences**

- 正面：旧会话不能覆盖新 Canon；Resume 不双提交可测。  
- 代价：生成前必须正确建会话；Guard 逻辑变更需回归测试。

**References**

- `src/novel_weaver/truth/commit_guard.py`  
- `src/novel_weaver/production/orchestrator.py`

---

## ADR-003: SQLite 作为主存储

**Status:** Accepted

**Context**

引擎需要事务、版本字段、审计与可查询的 Canonical 状态；同时希望单机、零运维、易测试。

**Decision Drivers**

- Python 标准库可用，无服务进程。  
- 事务满足 Commit 原子性。  
- 测试与 CI 可文件级隔离（每个 workspace 一个库文件）。

**Considered Options**

- 纯 JSON 文件树（拒绝：并发与事务边界弱）。  
- 外部 PostgreSQL（拒绝：首阶段运维成本过高，违背最小内核）。

**Decision Outcome**

主存储采用 stdlib `sqlite3`，库文件位于 workspace（如 `novel.sqlite3`）。仓储层封装读写；快照/发布/制品等扩展同属 storage 包。将来可换后端，但必须保持 Truth 边界语义。

**Consequences**

- 正面：开箱即用、易备份（拷贝文件/导出）。  
- 代价：超大规模并发写不是当前目标；需注意迁移策略。

**References**

- `src/novel_weaver/storage/db.py`  
- `src/novel_weaver/storage/repositories.py`

---

## ADR-004: Provider 可替换且不写 Canon

**Status:** Accepted

**Context**

模型能力与供应商迭代快。若编排层直接假设某一家 API，换模型会牵动领域状态；若模型可写库，Truth 边界失效。

**Decision Drivers**

- Provider / 模型可替换。  
- Agent 是实现方式，不是系统边界。  
- 测试可离线确定性运行。

**Considered Options**

- 在编排内硬编码某 SDK（拒绝：锁定供应商）。  
- 允许模型直接更新 State 表（拒绝：绕过证据与 Guard）。

**Decision Outcome**

`ai.base.Provider` 定义任务协议（生成、审校等）。实现包括 `fake`、`template`、OpenAI 兼容 HTTP、`failover`。Provider 返回 Candidate/审校结果；**Canonical 写入仅发生在 Commit 路径**。

**Consequences**

- 正面：CI 用 fake；生产可换端点与模型。  
- 代价：需维护协议与注册表；不同模型输出格式需在 Provider 层归一。

**References**

- `src/novel_weaver/ai/base.py`  
- `src/novel_weaver/ai/registry.py`

---

## ADR-005: Python stdlib 优先与零强制运行时依赖

**Status:** Accepted

**Context**

核心是领域状态机与编排，不是特定 Web/ML 框架。重依赖会抬高安装与供应链成本，并让「最小可验证内核」变脆。

**Decision Drivers**

- `pip install novel-weaver` 应尽量轻。  
- LLM 走 HTTP 可用 stdlib 完成。  
- 测试与打包在受限环境可跑。

**Considered Options**

- 强制 `openai` / `pydantic` / `httpx` 等（拒绝：非必要耦合）。  
- 强制向量库依赖（拒绝：投影非真相，应可选重建）。

**Decision Outcome**

运行时核心 **零强制第三方依赖**。OpenAI 兼容调用使用标准库 HTTP；开发依赖仅 `pytest`（`[dev]` extra）。可选能力不得破坏默认安装面。

**Consequences**

- 正面：安装快、审计面小、与定位「引擎内核」一致。  
- 代价：HTTP/解析需自维护；复杂 schema 校验保持精简。

**References**

- `pyproject.toml`  
- `src/novel_weaver/ai/openai_compat.py`

---

## 相关文档

- [架构概述](ARCHITECTURE.md)  
- [打包说明](PACKAGING.md)  
