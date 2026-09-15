# 安全策略

## 受支持的版本

在稳定版发布前，仅最新开发主线接收安全更新。

| 版本 | 是否支持 |
|------|----------|
| main / latest | ✅ |
| 更早提交 | ❌ |

## 报告漏洞

如果发现安全漏洞，请**不要**公开提交 Issue。

在公开 Security Advisories 渠道建立之前：

1. 通过维护者邮箱私下联系：`zcbacxc@users.noreply.github.com`
2. 提供清晰描述、影响范围与复现步骤
3. 在公开披露前留出合理修复时间

项目托管到 GitHub 后，请优先使用 `novel-weaver` 仓库的 [Security Advisories](../../security/advisories/new)。

### 响应时间线

- **确认收悉**：72 小时内
- **初步评估**：1 周内
- **修复或缓解**：核心引擎关键问题尽力处理

## 适用范围

本策略覆盖 `novel-weaver` 核心引擎包（`src/novel_weaver/`）。

## 不适用范围

- 用户配置中的 API 密钥泄露（用户责任）
- 第三方 LLM / Embedding 提供商漏洞
- 仅存在于本地 `docs-nocommit/` 设计文档中的问题（不随包分发）
- 社会工程与物理攻击
