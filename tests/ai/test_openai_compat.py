# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""OpenAI-compatible provider unit tests (mocked HTTP, no live key)."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

import pytest

from novel_weaver.ai.base import GenerationRequest, ProviderError
from novel_weaver.ai.openai_compat import OpenAICompatibleProvider


def _request(**overrides: Any) -> GenerationRequest:
    payload = {
        "task": "chapter_generation",
        "prompt": "Write chapter 1",
        "context": {
            "creative_intent": "冷硬侦探",
            "current_plan": "码头雨夜",
            "chapter_title": "第1章",
            "selected_facts": [{"key": "character.gu.name", "value": "顾言"}],
            "active_threads": [{"key": "thread.x", "value": "OPEN", "status": "PENDING"}],
            "quality_feedback": [{"issue": "none", "recommended_action": "continue"}],
        },
        "model": "default",
        "story_id": "s1",
        "chapter_id": "c1",
    }
    payload.update(overrides)
    return GenerationRequest(**payload)  # type: ignore[arg-type]


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _provider(**kwargs: Any) -> OpenAICompatibleProvider:
    defaults = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "deepseek-flash",
    }
    defaults.update(kwargs)
    return OpenAICompatibleProvider(**defaults)  # type: ignore[arg-type]


def test_missing_api_key_raises() -> None:
    import os

    env = {k: os.environ.pop(k, None) for k in (
        "NOVEL_WEAVER_LLM_API_KEY",
        "NOVEL_WEAVER_LLM_BASE_URL",
        "NOVEL_WEAVER_LLM_MODEL",
    )}
    try:
        with pytest.raises(ProviderError, match="API key"):
            OpenAICompatibleProvider(base_url="https://x/v1", api_key="")
    finally:
        for k, v in env.items():
            if v is not None:
                os.environ[k] = v


def test_generate_parses_chat_completions(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float = 0):  # noqa: ANN001
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(
            {
                "id": "chatcmpl-1",
                "model": "deepseek-flash",
                "choices": [
                    {"message": {"role": "assistant", "content": "雨落在码头上。"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = _provider().generate(_request())
    assert result.text == "雨落在码头上。"
    assert result.provider == "openai"
    assert result.model == "deepseek-flash"
    assert result.usage.prompt_tokens == 100
    assert result.usage.completion_tokens == 40
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["model"] == "deepseek-flash"
    assert "顾言" in captured["body"]["messages"][1]["content"]
    assert "正式事实" in captured["body"]["messages"][0]["content"]
    assert "不得违背" in captured["body"]["messages"][1]["content"]


def test_http_429_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: Any, timeout: float = 0):  # noqa: ANN001
        raise __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
            req.full_url, 429, "rate", hdrs=None, fp=BytesIO(b'{"error":"rate limit"}')
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(ProviderError) as exc:
        _provider().generate(_request())
    assert exc.value.retryable is True


def test_http_401_is_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: Any, timeout: float = 0):  # noqa: ANN001
        raise __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
            req.full_url, 401, "unauth", hdrs=None, fp=BytesIO(b'{"error":"bad key"}')
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(ProviderError) as exc:
        _provider().generate(_request())
    assert exc.value.retryable is False


def test_request_model_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float = 0):  # noqa: ANN001
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(
            {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = _provider().generate(_request(model="deepseek-chat"))
    assert result.model == "deepseek-chat"
    assert captured["body"]["model"] == "deepseek-chat"
