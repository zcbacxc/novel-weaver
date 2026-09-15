# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Settings / .env configuration tests."""

from __future__ import annotations

import os
from pathlib import Path

from novel_weaver.config import (
    Settings,
    clear_settings_cache,
    load_dotenv_into_environ,
    _parse_env_file,
)


def test_parse_env_file_basic(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text(
        "# comment\n"
        "NOVEL_WEAVER_LLM_MODEL=deepseek-chat\n"
        "export NOVEL_WEAVER_LLM_TIMEOUT=30\n"
        'NOVEL_WEAVER_LLM_API_KEY="sk-abc"\n'
        "EMPTY=\n",
        encoding="utf-8",
    )
    data = _parse_env_file(p)
    assert data["NOVEL_WEAVER_LLM_MODEL"] == "deepseek-chat"
    assert data["NOVEL_WEAVER_LLM_TIMEOUT"] == "30"
    assert data["NOVEL_WEAVER_LLM_API_KEY"] == "sk-abc"
    assert data["EMPTY"] == ""


def test_settings_from_environ() -> None:
    env = {
        "NOVEL_WEAVER_LLM_BASE_URL": "http://127.0.0.1:12580/v1",
        "NOVEL_WEAVER_LLM_API_KEY": "sk-x",
        "NOVEL_WEAVER_LLM_MODEL": "deepseek-v4-pro",
        "NOVEL_WEAVER_LLM_TIMEOUT": "45",
        "NOVEL_WEAVER_LLM_MAX_TOKENS": "800",
        "NOVEL_WEAVER_DEFAULT_PROVIDER": "openai",
        "NOVEL_WEAVER_FAILOVER": "openai,template",
        "NOVEL_WEAVER_USE_LLM_REVIEW": "true",
        "NOVEL_WEAVER_WORKSPACE": ".workspaces/x",
    }
    s = Settings.from_environ(env)
    assert s.llm_base_url.endswith("/v1")
    assert s.llm_model == "deepseek-v4-pro"
    assert s.llm_timeout == 45.0
    assert s.llm_max_tokens == 800
    assert s.default_provider == "openai"
    assert s.failover_names() == ["openai", "template"]
    assert s.use_llm_review_flag() is True


def test_load_dotenv_respects_process_env(tmp_path: Path, monkeypatch) -> None:
    proj = tmp_path / "proj.env"
    user = tmp_path / "user.env"
    proj.write_text("NOVEL_WEAVER_LLM_MODEL=from-project\n", encoding="utf-8")
    user.write_text("NOVEL_WEAVER_LLM_MODEL=from-user\nNOVEL_WEAVER_WORKSPACE=.ws\n", encoding="utf-8")
    monkeypatch.setenv("NOVEL_WEAVER_LLM_MODEL", "from-process")
    loaded = load_dotenv_into_environ(project_env=proj, user_env=user, override=False)
    assert os.environ["NOVEL_WEAVER_LLM_MODEL"] == "from-process"
    assert os.environ.get("NOVEL_WEAVER_WORKSPACE") == ".ws"
    assert "NOVEL_WEAVER_LLM_MODEL" not in loaded


def test_openai_provider_reads_settings(monkeypatch) -> None:
    clear_settings_cache()
    monkeypatch.setenv("NOVEL_WEAVER_LLM_BASE_URL", "http://cfg.example/v1")
    monkeypatch.setenv("NOVEL_WEAVER_LLM_API_KEY", "sk-cfg")
    monkeypatch.setenv("NOVEL_WEAVER_LLM_MODEL", "cfg-model")
    monkeypatch.setenv("NOVEL_WEAVER_LLM_TIMEOUT", "12")
    monkeypatch.setenv("NOVEL_WEAVER_LLM_MAX_TOKENS", "64")
    # Avoid creating user .env side effects in CI-like runs: ensure exists is ok.
    from novel_weaver.ai.openai_compat import OpenAICompatibleProvider

    p = OpenAICompatibleProvider()
    assert p.base_url == "http://cfg.example/v1"
    assert p.api_key == "sk-cfg"
    assert p.model == "cfg-model"
    assert p.timeout == 12.0
    assert p.max_tokens == 64
    clear_settings_cache()
