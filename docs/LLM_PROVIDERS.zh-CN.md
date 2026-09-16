[![English](https://img.shields.io/badge/English-LLM_Providers-blue)](LLM_PROVIDERS.md)
[![简体中文](https://img.shields.io/badge/简体中文-Provider配置-green)](LLM_PROVIDERS.zh-CN.md)

# LLM Provider 配置

生成与可选语义审校使用任意 **OpenAI 兼容** Chat Completions 接口。切换服务商只需改三个配置项。**无 LLM 密钥时仍可用 `fake` / `template` 跑通完整引擎闭环。**

## 快速选择

| 场景 | 建议 |
|------|------|
| 本地测试 / CI | `fake` 或 `template`，无需密钥 |
| 尽快跑通真实生成 | 任意 OpenAI 兼容端点 + 小模型 |
| 完全离线 | `template`，或自建兼容网关（如 Ollama `/v1`） |
| 省成本长跑 | 小模型 + `NOVEL_WEAVER_FAILOVER=openai,template` 故障降级 |

## 通用配置

复制 `.env.example` 为项目根 `.env`，或使用 `~/.novel-weaver/.env`：

```env
NOVEL_WEAVER_LLM_BASE_URL=https://api.openai.com/v1
NOVEL_WEAVER_LLM_API_KEY=sk-...
NOVEL_WEAVER_LLM_MODEL=gpt-4o-mini
```

可选：

```env
# 故障切换链（名称见 ai/registry）
NOVEL_WEAVER_FAILOVER=openai,template
# 默认 Provider：fake | template | openai | failover
NOVEL_WEAVER_DEFAULT_PROVIDER=template
# 是否启用 LLM 语义审校（空 = 在 openai/llm 下自动开启）
NOVEL_WEAVER_USE_LLM_REVIEW=
```

验证：

```bash
novel-weaver config --show
novel-weaver engine --provider openai --workspace .workspaces/llm
```

配置错误时，CLI/引擎会以明确错误结束，不会写入 Canonical。

## 端点契约

任何实现下列语义的服务均可接入（路径相对 `BASE_URL`）：

- `POST /chat/completions`
- 请求体包含 `model`、`messages`
- 响应含 `choices[0].message.content` 与可选 `usage`

常见本地兼容端点示例（仅示意，非背书）：

```env
# Ollama（若已开启 OpenAI 兼容 API）
NOVEL_WEAVER_LLM_BASE_URL=http://127.0.0.1:11434/v1
NOVEL_WEAVER_LLM_API_KEY=ollama
NOVEL_WEAVER_LLM_MODEL=qwen2.5:7b
```

若厂商专篇增多，再拆到 `docs/llm-providers/` 子目录，本文件只做索引（规划中，当前非必须）。

## 设计约束

- Provider **只产出 Candidate / 审校意见**，不直接写 Canonical。  
- 提交必须通过 Commit Guard；模型失败可重试或 failover，不污染正式状态。  
- 勿将 API Key 写入仓库、Issue 或日志正文。  

## 相关文档

- [架构：Provider 层](ARCHITECTURE.zh-CN.md#provider-层)  
- [快速开始](QUICKSTART.zh-CN.md)  
- [贡献指南](CONTRIBUTING.zh-CN.md)  
