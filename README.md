# Novel Weaver

[![License: AGPL v3+](https://img.shields.io/badge/License-AGPL%20v3%2B-blue.svg)](LICENSE)

产品化工程阶段的 AI 长篇小说生成引擎（Core Engine）。

本仓库当前阶段聚焦 **Phase 0：Truth Boundary & Canonical Domain Core**——最小可验证的连续生产内核。

## 快速开始

```bash
# 安装测试依赖（开发）
python -m pip install pytest

# 运行测试
python -m pytest tests -v

# 初始化示例故事并跑通假生成闭环
python -m novel_weaver.cli demo --workspace .workspaces/demo
```

## 包结构

```text
src/novel_weaver/
  domain/       # Canonical 实体与版本
  truth/        # Evidence / Proposal / Commit Guard
  storage/      # SQLite 仓储
  runtime/      # Session / Checkpoint / Audit
  production/   # 编排、失效、假生成
  cli/          # 命令行入口
tests/
```

## 设计约束

- Canonical Story 是唯一正式真相；派生数据可重建。
- Draft / Candidate / Canonical 严格分层；无证据不得晋升 Canon。
- Runtime 失败不污染 Canon；Commit 必须通过 Guard。
- 修改前文只使真实依赖范围失效。

## 许可证

本项目采用 **GNU Affero General Public License v3.0 or later**（AGPL-3.0-or-later）。

完整条款见 [LICENSE](LICENSE)。通过网络提供基于本引擎的服务时，须按 AGPL 第 13 条向用户提供对应源代码。
