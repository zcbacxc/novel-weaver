# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""OpenAI-compatible Chat Completions provider (stdlib HTTP only).

Works with OpenAI, DeepSeek, Moonshot, OpenRouter, Ollama, vLLM, and any
endpoint that speaks `POST {base_url}/chat/completions`.

Configuration precedence:
  1. constructor kwargs
  2. process environment (NOVEL_WEAVER_LLM_*)
  3. project/user .env via novel_weaver.config.get_settings()
  4. built-in defaults
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from novel_weaver.ai.base import (
    GenerationRequest,
    GenerationResult,
    Provider,
    ProviderError,
    TokenUsage,
    estimate_tokens,
)
from novel_weaver.config import get_settings

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT_S = 90.0
DEFAULT_MAX_TOKENS = 1200

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

# Chinese system prompt is intentional model-facing prose (not project docs).
_SYSTEM_PROMPT = """你是长篇小说引擎的章节写手。严格遵守：
1. 只输出本章正文（可含小节标题），不要输出大纲、元数据、JSON 或解释。
2. 不得发明与「正式事实」冲突的世界真相；正式事实是唯一真相源。
3. 遵循本章计划与创作意图推进情节，保持人物状态与时间线一致。
4. 语言自然、有场景感；避免占位符与空话。
"""


class OpenAICompatibleProvider(Provider):
    """Chat Completions provider for any OpenAI-compatible HTTP endpoint.

    Resolves config from constructor/env/.env/defaults, builds system+user
    messages from the request context, and maps HTTP failures to
    ``ProviderError`` with retryability by status code.
    """

    name = "openai"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        temperature: float | None = 0.7,
        max_tokens: int | None = None,
        organization: str | None = None,
    ) -> None:
        """Create the provider after merging configuration sources.

        Args:
            base_url: API root without trailing path; defaults via settings.
            api_key: Bearer token; defaults via settings.
            model: Default model id for requests that do not override it.
            timeout: HTTP timeout in seconds.
            temperature: Default sampling temperature (``None`` omits the field).
            max_tokens: Default completion cap.
            organization: Optional OpenAI organization header value.

        Raises:
            ProviderError: If no API key can be resolved from any source.
        """
        cfg = get_settings()
        self.base_url = (base_url or cfg.llm_base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else cfg.llm_api_key
        self.model = model or cfg.llm_model or DEFAULT_MODEL
        self.timeout = float(timeout if timeout is not None else cfg.llm_timeout or DEFAULT_TIMEOUT_S)
        self.temperature = temperature
        if max_tokens is not None:
            self.max_tokens = max_tokens
        else:
            self.max_tokens = int(cfg.llm_max_tokens or DEFAULT_MAX_TOKENS)
        self.organization = organization if organization is not None else cfg.llm_org
        if not self.api_key:
            raise ProviderError(
                "missing API key: pass api_key=, set NOVEL_WEAVER_LLM_API_KEY, "
                "or edit ~/.novel-weaver/.env",
                retryable=False,
            )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Call ``POST {base_url}/chat/completions`` and normalize the response.

        Args:
            request: Task, prompt, and context pack for the model call.

        Returns:
            Generation text, resolved model id, usage, and latency.

        Raises:
            ProviderError: On connection failure, timeout, HTTP error, empty
                content, or non-JSON response body.
        """
        started = time.perf_counter()
        fingerprint = request.fingerprint()
        model = self._resolve_model(request)
        payload = self._build_payload(request, model)
        body = self._post_chat_completions(payload)
        text = self._extract_text(body)
        latency_ms = (time.perf_counter() - started) * 1000.0
        usage = self._extract_usage(body, request, text)
        return GenerationResult(
            text=text,
            model=model,
            provider=self.name,
            usage=usage,
            latency_ms=latency_ms,
            task=request.task,
            story_id=request.story_id,
            chapter_id=request.chapter_id,
            fingerprint=fingerprint,
            raw={
                "id": body.get("id"),
                "model": body.get("model", model),
                "finish_reason": self._finish_reason(body),
            },
        )

    # ------------------------------------------------------------------ request
    def _resolve_model(self, request: GenerationRequest) -> str:
        if request.model and request.model not in ("default", "openai"):
            return request.model
        return self.model

    def _build_payload(self, request: GenerationRequest, model: str) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": self._user_content(request)},
        ]
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        temperature = request.temperature if request.temperature is not None else self.temperature
        if temperature is not None:
            payload["temperature"] = temperature
        max_tokens = request.max_tokens or self.max_tokens
        if max_tokens:
            payload["max_tokens"] = max_tokens
        return payload

    def _user_content(self, request: GenerationRequest) -> str:
        ctx = request.context or {}
        facts = ctx.get("selected_facts") or []
        threads = ctx.get("active_threads") or []
        feedback = ctx.get("quality_feedback") or []
        fact_lines = [
            f"- {f.get('key')}: {f.get('value')}" if isinstance(f, dict) else f"- {f}"
            for f in facts
        ] or ["- (无)"]
        thread_lines = [
            f"- {t.get('key')}: {t.get('value')} [{t.get('status')}]" if isinstance(t, dict) else f"- {t}"
            for t in threads
        ] or ["- (无)"]
        feedback_lines = []
        for item in feedback:
            if isinstance(item, dict) and item.get("issue") and item.get("issue") != "none":
                feedback_lines.append(
                    f"- {item.get('issue')}: {item.get('recommended_action', '')}"
                )
        intent = ctx.get("creative_intent") or ""
        plan = ctx.get("current_plan") or request.prompt
        title = ctx.get("chapter_title") or request.chapter_id or "本章"

        parts = [
            f"任务：{request.task or 'chapter_generation'}",
            f"章节：{title}",
        ]
        if intent:
            parts.append(f"创作意图：{intent}")
        parts.append(f"本章计划：{plan}")
        parts.append("正式事实（Canonical，不得违背）：\n" + "\n".join(fact_lines))
        parts.append("开放线索：\n" + "\n".join(thread_lines))
        if feedback_lines:
            parts.append("上轮质量问题（必须规避）：\n" + "\n".join(feedback_lines))
        parts.append(f"补充指令：{request.prompt}")
        parts.append("请直接输出正文。")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------- HTTP
    def _post_chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if self.organization:
            headers["OpenAI-Organization"] = self.organization

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                status = getattr(resp, "status", 200)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise self._http_error(exc.code, body) from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"LLM connection failed: {exc.reason}", retryable=True) from exc
        except TimeoutError as exc:
            raise ProviderError("LLM request timed out", retryable=True) from exc

        if status >= 400:
            raise self._http_error(status, raw.decode("utf-8", errors="replace"))
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ProviderError(
                f"LLM returned non-JSON body: {raw[:200]!r}", retryable=False
            ) from exc

    def _http_error(self, status: int, body: str) -> ProviderError:
        retryable = status in _RETRYABLE_STATUS
        snippet = body[:300].replace("\n", " ")
        return ProviderError(f"LLM HTTP {status}: {snippet}", retryable=retryable)

    # ----------------------------------------------------------------- parse
    def _extract_text(self, body: dict[str, Any]) -> str:
        choices = body.get("choices") or []
        if not choices:
            raise ProviderError("LLM response missing choices", retryable=False)
        message = choices[0].get("message") or {}
        content = message.get("content")
        if content is None or (isinstance(content, str) and not content.strip()):
            # Reasoning models may put the final answer only in reasoning_content
            # when content is empty; prefer any non-empty field.
            for key in ("reasoning_content", "reasoning"):
                alt = message.get(key)
                if isinstance(alt, str) and alt.strip():
                    content = alt
                    break
        if content is None:
            content = choices[0].get("text")
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("LLM returned empty content", retryable=True)
        return content.strip()

    def _finish_reason(self, body: dict[str, Any]) -> str:
        choices = body.get("choices") or []
        if not choices:
            return ""
        return str(choices[0].get("finish_reason") or "")

    def _extract_usage(
        self, body: dict[str, Any], request: GenerationRequest, text: str
    ) -> TokenUsage:
        usage = body.get("usage") or {}
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        if prompt is None or completion is None:
            # Fallback estimate when the gateway omits usage.
            prompt = estimate_tokens(request.prompt) + estimate_tokens(
                json.dumps(request.context, ensure_ascii=False, default=str)
            )
            completion = estimate_tokens(text)
        return TokenUsage.of(int(prompt), int(completion))
