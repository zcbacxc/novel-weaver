[![English](https://img.shields.io/badge/English-Roadmap-blue)](ROADMAP.md)
[![简体中文](https://img.shields.io/badge/简体中文-路线图-green)](ROADMAP.zh-CN.md)

# 路线图

> 版本细节见 [CHANGELOG.md](../CHANGELOG.md)。本页只作公开摘要；**不**替代内部实现方案，也不承诺未交付日期。

## 规划原则

1. 只服务 **Core Engine** 定位 —— 不做聊天 UI、社区、SaaS、Agent 链产品化。  
2. 优先工程属性（可重复 / 可恢复 / 可修复 / 可追溯 / Provider 可替换），而非一次性演示。  
3. 用户可见能力与基础设施加固交替推进。  
4. 在导出明确公开契约前，不宣称「公开 Python API 已稳定」。

## 已完成（公开摘要）

| 版本 / 阶段 | 主题 |
|-------------|------|
| 0.1.0（Phase 0–5 内核） | 真相边界与 Commit Guard；单章生产；连续生产与 Resume；增量失效/修复；质量闭环与语义审校；加固（重试、成本、诊断、Failover、快照、基准）；OpenAI 兼容 Provider；SQLite 存储与 CLI |

当前包版本以 `pyproject.toml` 为准（**0.1.0**）。公开 Python API **尚未**声明稳定契约（见 [PACKAGING.zh-CN.md](PACKAGING.zh-CN.md)）。

## 近期方向（规划中，未交付）

下列条目是方向而非承诺，实现以实际提交与 CHANGELOG 为准：

- 在配置好 Trusted Publisher 后打通 PyPI Trusted Publishing  
- 公开双语文档集（本轮：英文主 + `.zh-CN.md` 成对）  
- 按需补强公开架构图 / 状态机说明  
- Provider 推荐矩阵，以及可选的 `docs/llm-providers/` 拆分  
- 评估更强的一致性全书扫描与可选投影重建工具  
- 仅在公开参考体量足够时再考虑 mkdocs 站点  

## 明确非目标（本仓库）

| 不做 | 原因 |
|------|------|
| 社区 / 发布 / 会员 SaaS | 属于上层产品 |
| 聊天式写作 UI 作为核心 | 不是持续生产内核 |
| 「一键整本」替代可控生产闭环 | 破坏可恢复性与可追溯性 |

上层产品可以依赖本引擎，但不反过来定义核心定位。

## 历史说明

Phase 0–5 的验收细节与工程过程记录属于本地设计文档，不随本仓库公开。公开侧只维护：已交付能力（CHANGELOG）、架构概述（ARCHITECTURE）、决策理由（ADR）。
