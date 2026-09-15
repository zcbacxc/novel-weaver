# 打包说明

## 包标识

| 项 | 值 |
|----|-----|
| PyPI / 分发名 | `novel-weaver` |
| Import 包名 | `novel_weaver` |
| 入口脚本 | `novel-weaver` → `novel_weaver.cli.main:main` |
| 布局 | `src/` layout |
| Python | `>=3.12` |
| 许可证 | `AGPL-3.0-or-later`（PEP 639 字符串表达式） |

版本号唯一来源：`pyproject.toml` → `version`。运行时可读 `novel_weaver.__version__`；发版时两者保持一致。

## 构建

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
```

产物：`dist/novel_weaver-<version>-py3-none-any.whl` 与 `dist/novel_weaver-<version>.tar.gz`。

本地若因镜像源拉不到 `setuptools>=77`，可使用本机已安装的 setuptools：`python -m build --no-isolation`。CI 使用官方源隔离构建。

## 安装

```bash
# 源码（开发）
pip install -e ".[dev]"

# 发布后
pip install novel-weaver
```

运行时 **无强制第三方依赖**；`[dev]` 仅含 `pytest`。

## 发版流程（摘要）

完整核对项见 [RELEASE_CHECKLIST](RELEASE_CHECKLIST.md)。

1. `feature/*` PR 合入 `main`，CI 绿  
2. 更新版本 + CHANGELOG（同一提交）  
3. `git tag -a vX.Y.Z`（与 `main` 推送分离）  
4. 推 tag；启用 Trusted Publishing 后由 `publish.yml` 发布  
5. 发布后干净环境安装冒烟  

预发布 tag：`vX.Y.Z-test` / `vX.Y.Z-rc.N`。**同一版本号不可重复发布。**

## 依赖策略

- 核心保持零强制运行时依赖（见 [ADR-005](ADR.md#adr-005-python-stdlib-优先与零强制运行时依赖)）。  
- 新增依赖前评估：是否可 stdlib、许可证是否 AGPL 兼容、是否拉高供应链面。  
- 开发/CI 依赖放在 `[project.optional-dependencies]`，不进入核心 `dependencies`。

## 许可证与 SPDX

- 源文件头：`SPDX-License-Identifier: AGPL-3.0-or-later`  
- `pyproject.toml` 使用 PEP 639：`license = "AGPL-3.0-or-later"`，**不**再添加 license Trove classifier  
- 构建后端：`setuptools>=77.0`

## 相关文档

- [发布清单](RELEASE_CHECKLIST.md)  
- [贡献指南](CONTRIBUTING.md)  
- [ADR](ADR.md)  
