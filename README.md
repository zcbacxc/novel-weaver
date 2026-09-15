# Novel Weaver

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
