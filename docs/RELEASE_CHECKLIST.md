# 发布清单

打正式 tag 前，下列条目必须全部满足。任一失败则停止发布。

版本号唯一来源：`pyproject.toml` 的 `version`（与 `src/novel_weaver/__init__.py` 的 `__version__` 保持一致）。

## 1. 测试与构建

- [ ] `python -m pytest tests -v` 全部通过  
- [ ] `python -m build` 成功产出 sdist + wheel  
- [ ] `python -m twine check dist/*` 通过  
- [ ] 干净环境安装 wheel 后 `novel-weaver --help` 可用  

## 2. 版本与变更说明

- [ ] `pyproject.toml` / `__version__` 已 bump 到目标 `X.Y.Z`  
- [ ] `CHANGELOG.md` 将 `[Unreleased]` 收入 `## [X.Y.Z] - YYYY-MM-DD`  
- [ ] 条目无内部追踪码；已发布历史未改写  
- [ ] 底部 compare 链接已更新  

## 3. 文档与元数据

- [ ] `README.md` 安装/命令与当前 CLI 一致  
- [ ] 公开文档未把「规划中」写成「已交付」  
- [ ] `pyproject.toml` 的 URLs / description 仍准确  

## 4. Git 与 CI

- [ ] 变更经 PR 合入 `main`，CI 绿  
- [ ] 注释 tag：`git tag -a vX.Y.Z -m "vX.Y.Z — <主题>"`  
- [ ] **分支与 tag 分开推送**：先 `git push origin main`，再 `git push origin vX.Y.Z`  
- [ ] 预发布用 `vX.Y.Z-test` / `vX.Y.Z-rc.N`（不与正式 tag 混用）  

## 5. PyPI（启用 Trusted Publishing 后）

- [ ] pypi.org 上已配置 Publisher：Owner `zcbacxc` · Repo `novel-weaver` · Workflow `publish.yml`  
- [ ] 推 tag 后 Actions 发布成功  
- [ ] `pip install novel-weaver==X.Y.Z` 验证  
- [ ] GitHub Release 非 draft，正文与 CHANGELOG 对应版本一致  

## 6. 发布后冒烟

- [ ] 安装该版本后：`novel-weaver demo --workspace <tmp>` 成功  
- [ ] Canonical / Runtime 分离未被发布流程破坏（demo 路径即可覆盖）  

## 当前状态说明

- 仓库已具备 CI 与打包基建；**自动 publish 工作流可在启用 PyPI Trusted Publishing 时再添加**。  
- 同一版本号不可重复发布。  
- 测试失败或构建失败时 **禁止** 打 tag。  
