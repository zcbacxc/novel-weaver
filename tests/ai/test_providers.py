"""Functional tests for replaceable AI providers (no external API keys)."""

from __future__ import annotations

import pytest

from novel_weaver.ai.base import GenerationRequest, Provider, ProviderError, TokenUsage
from novel_weaver.ai.fake import FakeProvider
from novel_weaver.ai.registry import (
    UnknownProviderError,
    get_provider,
    list_providers,
    register_provider,
    unregister_provider,
)
from novel_weaver.ai.retry import retry_with_backoff
from novel_weaver.ai.template import TemplateProvider


def _sample_request(**overrides: object) -> GenerationRequest:
    payload: dict = {
        "task": "chapter_generation",
        "prompt": "Write chapter 1: Opening",
        "context": {
            "creative_intent": "quiet tension",
            "current_plan": "Introduce the protagonist at the harbor.",
            "production_unit": "ch_001",
            "selected_facts": [
                {"key": "character.lead.name", "value": "Gu Yan", "source": "author"},
                {"key": "world.city", "value": "Port Meridian", "source": "author"},
            ],
            "active_threads": [
                {"key": "thread.missing_cargo", "value": "crate vanished", "status": "PENDING"},
            ],
            "quality_feedback": [],
        },
        "model": "default",
        "story_id": "story_test",
        "chapter_id": "ch_001",
    }
    payload.update(overrides)
    return GenerationRequest(**payload)  # type: ignore[arg-type]


def test_generation_request_fingerprint_stable() -> None:
    a = _sample_request()
    b = _sample_request()
    assert a.fingerprint() == b.fingerprint()
    assert len(a.fingerprint()) == 16


def test_generation_request_fingerprint_changes_with_context() -> None:
    a = _sample_request()
    b = _sample_request(context={**a.context, "current_plan": "Different plan"})
    assert a.fingerprint() != b.fingerprint()


def test_fake_provider_is_deterministic() -> None:
    provider = FakeProvider()
    request = _sample_request()
    first = provider.generate(request)
    second = provider.generate(_sample_request())
    assert first.text == second.text
    assert first.fingerprint == second.fingerprint
    assert first.provider == "fake"
    assert first.usage.total_tokens == first.usage.prompt_tokens + first.usage.completion_tokens
    assert first.latency_ms >= 0


def test_fake_provider_differs_across_requests() -> None:
    provider = FakeProvider()
    a = provider.generate(_sample_request())
    b = provider.generate(_sample_request(chapter_id="ch_002"))
    assert a.fingerprint != b.fingerprint
    assert a.text != b.text


def test_template_provider_builds_readable_draft() -> None:
    provider = TemplateProvider()
    result = provider.generate(_sample_request())
    assert result.provider == "template"
    assert "Gu Yan" in result.text
    assert "Port Meridian" in result.text
    assert "Introduce the protagonist" in result.text
    assert "missing_cargo" in result.text
    assert "not Canon" in result.text or "Candidate only" in result.text
    assert result.usage.completion_tokens > 0


def test_template_provider_without_facts() -> None:
    provider = TemplateProvider()
    request = _sample_request(context={"current_plan": "Solo scene."})
    result = provider.generate(request)
    assert "No canonical facts selected" in result.text
    assert "Solo scene." in result.text


def test_registry_exposes_fake_and_template() -> None:
    assert set(list_providers()) >= {"fake", "template", "openai", "llm"}
    fake = get_provider("fake")
    template = get_provider("template")
    assert isinstance(fake, Provider)
    assert isinstance(template, Provider)
    assert fake.name == "fake"
    assert template.name == "template"


def test_registry_unknown_provider() -> None:
    with pytest.raises(UnknownProviderError):
        get_provider("does-not-exist")


def test_registry_register_custom_provider() -> None:
    class StubProvider(Provider):
        name = "stub"

        def generate(self, request: GenerationRequest):
            from novel_weaver.ai.base import GenerationResult

            return GenerationResult(
                text="stub",
                model="stub-1",
                provider=self.name,
                usage=TokenUsage.of(1, 1),
                latency_ms=0.0,
            )

    register_provider("stub", StubProvider)
    try:
        provider = get_provider("stub")
        assert provider.generate(_sample_request()).text == "stub"
        with pytest.raises(ValueError):
            register_provider("stub", StubProvider)
        register_provider("stub", StubProvider, replace=True)
    finally:
        unregister_provider("stub")
    assert "stub" not in list_providers()


def test_retry_retries_transient_then_succeeds() -> None:
    sleeps: list[float] = []
    calls = {"n": 0}

    @retry_with_backoff(max_attempts=3, base_delay=0.01, sleep=sleeps.append)
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderError("rate limited", retryable=True)
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]


def test_retry_does_not_retry_fatal_errors() -> None:
    calls = {"n": 0}

    @retry_with_backoff(max_attempts=5, base_delay=0.0, sleep=lambda _d: None)
    def fatal() -> str:
        calls["n"] += 1
        raise ProviderError("invalid api key", retryable=False)

    with pytest.raises(ProviderError, match="invalid api key"):
        fatal()
    assert calls["n"] == 1


def test_retry_exhausts_attempts() -> None:
    calls = {"n": 0}

    @retry_with_backoff(max_attempts=2, base_delay=0.0, sleep=lambda _d: None)
    def always_transient() -> str:
        calls["n"] += 1
        raise ProviderError("timeout", retryable=True)

    with pytest.raises(ProviderError, match="timeout"):
        always_transient()
    assert calls["n"] == 2


def test_fake_provider_with_retry_decorator() -> None:
    provider = FakeProvider(fail_times=2)
    request = _sample_request()

    @retry_with_backoff(max_attempts=3, base_delay=0.0, sleep=lambda _d: None)
    def call() -> str:
        return provider.generate(request).text

    text = call()
    assert text.startswith("[FAKE:")


def test_token_usage_of() -> None:
    usage = TokenUsage.of(10, 5)
    assert usage.total_tokens == 15
