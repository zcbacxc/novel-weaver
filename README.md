# Novel Weaver

[![License: AGPL v3+](https://img.shields.io/badge/License-AGPL%20v3%2B-blue.svg)](LICENSE)

产品化工程阶段的 AI 长篇小说生成引擎（Core Engine）。

本仓库当前阶段聚焦 **Phase 0–5 最小可验证连续生产内核**：Truth Boundary、单章生产、连续生产/恢复、增量修复、质量闭环与生产加固。

## 快速开始

```bash
# 安装测试依赖（开发）
python -m pip install pytest

# 运行测试（无需安装包；也可设置 PYTHONPATH=src）
python -m pytest tests -v

# 初始化示例故事并跑通假生成闭环
$env:PYTHONPATH="src"; python -m novel_weaver demo --workspace .workspaces/demo
```

配置真实 LLM（可选）时，复制 `.env.example` 为项目根 `.env` 或 `~/.novel-weaver/.env`。

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

## 许可证

本项目采用 **GNU Affero General Public License v3.0 or later**（AGPL-3.0-or-later）。

完整条款见 [LICENSE](LICENSE)。通过网络提供基于本引擎的服务时，须按 AGPL 第 13 条向用户提供对应源代码。
