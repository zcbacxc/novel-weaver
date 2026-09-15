# 路线图

> 版本细节见 [CHANGELOG](../CHANGELOG.md)。本页只作公开摘要；**不**替代内部实现方案，也不承诺未落地日期。

## 已完成（公开摘要）

| 版本 / 阶段 | 主题 |
|-------------|------|
| 0.1.0（Phase 0–5 内核） | 真相边界与 Commit Guard；单章生产；连续生产与 Resume；增量失效/修复；质量闭环与语义审校；加固（重试、成本、诊断、Failover、快照、基准）；OpenAI 兼容 Provider；SQLite 存储与 CLI |

当前包版本以 `pyproject.toml` 为准（**0.1.0**）。公开 API **尚未**声明稳定契约（见 [PACKAGING](PACKAGING.md)）。

## 近期方向（规划中，未交付）

下列条目是方向而非承诺，实现以实际提交与 CHANGELOG 为准：

- 启用 PyPI Trusted Publishing 自动发版流水线  
- 更完整的公开架构图与领域状态机说明  
- Provider 实测矩阵与推荐配置样例（在 [LLM_PROVIDERS](LLM_PROVIDERS.md) 增补）  
- 按需评估：更强的一致性全书扫描、可选投影重建工具  

## 明确非目标（本仓库）

- 社区 / 发布 / 会员 SaaS  
- 聊天式写作 UI 作为核心  
- 「一键整本」替代可控生产闭环  

上层产品可以依赖本引擎，但不反过来定义核心定位。

## 历史说明

Phase 0–5 的验收细节与工程过程记录属于内部设计文档，不随本仓库公开。公开侧只维护：已交付能力（CHANGELOG）、架构概述（ARCHITECTURE）、决策理由（ADR）。
