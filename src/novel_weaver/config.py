# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Configuration and settings management (stdlib-only).

Mirrors the movie-narrator pattern:
  - project ``.env`` + user ``~/.novel-weaver/.env``
  - ``.env.example`` as the default template
  - first-run ``ensure_user_config()`` bootstrap
  - ``get_settings()`` cached loader

Decision: stdlib dataclass + dotenv parser (no pydantic-settings) to keep
novel-weaver dependency-free. Alternative: add pydantic-settings — rejected
for the core engine (plan prefers zero-dep kernel).
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_USER_DIR = Path.home() / ".novel-weaver"
_USER_ENV = _USER_DIR / ".env"

_PACKAGE_DIR = Path(__file__).resolve().parent  # src/novel_weaver/
_SRC_DIR = _PACKAGE_DIR.parent  # src/
_PROJECT_ROOT = _SRC_DIR.parent  # novel-weaver/
_EXAMPLE_ENV = _PROJECT_ROOT / ".env.example"

ENV_PREFIX = "NOVEL_WEAVER_"

_DEFAULT_EXAMPLE = """\
# ============================================================
# novel-weaver — .env
#
# Infrastructure config for the long-form novel production engine.
# Pipeline / story behavior lives in Canonical Story (SQLite), not here.
# ============================================================

# ── LLM (OpenAI-compatible Chat Completions) ──
NOVEL_WEAVER_LLM_BASE_URL=https://api.openai.com/v1
NOVEL_WEAVER_LLM_API_KEY=
NOVEL_WEAVER_LLM_MODEL=gpt-4o-mini
# NOVEL_WEAVER_LLM_TIMEOUT=90
# NOVEL_WEAVER_LLM_MAX_TOKENS=1200
# NOVEL_WEAVER_LLM_ORG=

# ── Provider chain / quality ──
# Comma-separated failover order; empty = single provider.
# NOVEL_WEAVER_FAILOVER=openai,template
# Default provider name: fake | template | openai | llm | failover
# NOVEL_WEAVER_DEFAULT_PROVIDER=template
# Enable LLM semantic review (auto when provider is openai/llm)
# NOVEL_WEAVER_USE_LLM_REVIEW=

# ── Workspace ──
# Default CLI workspace directory (relative or absolute)
# NOVEL_WEAVER_WORKSPACE=.workspaces/default
"""


def _read_example_env() -> str:
    if _EXAMPLE_ENV.is_file():
        return _EXAMPLE_ENV.read_text(encoding="utf-8")
    return _DEFAULT_EXAMPLE


def ensure_user_config() -> Path:
    """Create ``~/.novel-weaver/.env`` from ``.env.example`` if missing.

    Never overwrites an existing file. Atomic write. Non-interactive.

    Returns:
        Path to the user config file (created when absent).
    """
    if not _USER_ENV.exists():
        _USER_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=_USER_DIR, suffix=".env.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(_read_example_env())
            os.replace(tmp_path, _USER_ENV)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        _print_first_run_notice(_USER_ENV)
    return _USER_ENV


def _print_first_run_notice(env_path: Path) -> None:
    if os.getenv("CI"):
        return
    print(
        f"\n[novel-weaver] 首次运行：已创建配置文件\n"
        f"  路径: {env_path}\n"
        f"  请编辑此文件，至少填写：\n"
        f"    NOVEL_WEAVER_LLM_BASE_URL — OpenAI 兼容 API 地址\n"
        f"    NOVEL_WEAVER_LLM_API_KEY  — API 密钥\n"
        f"    NOVEL_WEAVER_LLM_MODEL    — 模型名（如 deepseek-chat）\n"
        f"  配置完成后重新运行即可。\n",
        file=sys.stderr,
    )


def _parse_env_file(path: Path) -> dict[str, str]:
    """Minimal dotenv parser: KEY=VALUE, # comments, optional quotes."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def load_dotenv_into_environ(
    *,
    project_env: Path | None = None,
    user_env: Path | None = None,
    override: bool = False,
) -> dict[str, str]:
    """Load project then user .env into os.environ.

    Precedence when override=False (default): real process env wins over files.
    Project ``.env`` is applied before user ``~/.novel-weaver/.env`` so a
    checked-out project can specialize machine defaults.

    Args:
        project_env: Optional project .env path (defaults to repo root).
        user_env: Optional user .env path (defaults to ~/.novel-weaver/.env).
        override: When True, file values overwrite existing process env.

    Returns:
        Dict of keys that were loaded from files.
    """
    loaded: dict[str, str] = {}
    for path in (project_env or (_PROJECT_ROOT / ".env"), user_env or _USER_ENV):
        for key, value in _parse_env_file(Path(path)).items():
            if key in os.environ and not override:
                continue
            os.environ[key] = value
            loaded[key] = value
    return loaded


@dataclass
class Settings:
    """Typed view over NOVEL_WEAVER_* configuration."""

    # LLM
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 90.0
    llm_max_tokens: int = 1200
    llm_org: str = ""
    # Provider / quality
    default_provider: str = "template"
    failover: str = ""
    use_llm_review: str = ""
    # Workspace
    workspace: str = ".workspaces/default"

    @classmethod
    def from_environ(cls, env: dict[str, str] | None = None) -> Settings:
        """Build Settings from NOVEL_WEAVER_* environment variables.

        Args:
            env: Mapping to read (defaults to os.environ).

        Returns:
            Populated Settings instance with defaults for missing keys.
        """
        e = env if env is not None else os.environ

        def g(key: str, default: str = "") -> str:
            return (e.get(ENV_PREFIX + key) or default).strip()

        def gi(key: str, default: int) -> int:
            raw = g(key)
            try:
                return int(raw) if raw else default
            except ValueError:
                return default

        def gf(key: str, default: float) -> float:
            raw = g(key)
            try:
                return float(raw) if raw else default
            except ValueError:
                return default

        return cls(
            llm_base_url=g("LLM_BASE_URL", cls.llm_base_url) or cls.llm_base_url,
            llm_api_key=g("LLM_API_KEY", cls.llm_api_key),
            llm_model=g("LLM_MODEL", cls.llm_model) or cls.llm_model,
            llm_timeout=gf("LLM_TIMEOUT", cls.llm_timeout),
            llm_max_tokens=gi("LLM_MAX_TOKENS", cls.llm_max_tokens),
            llm_org=g("LLM_ORG", cls.llm_org),
            default_provider=g("DEFAULT_PROVIDER", cls.default_provider)
            or cls.default_provider,
            failover=g("FAILOVER", cls.failover),
            use_llm_review=g("USE_LLM_REVIEW", cls.use_llm_review),
            workspace=g("WORKSPACE", cls.workspace) or cls.workspace,
        )

    def failover_names(self) -> list[str]:
        """Parse the comma-separated failover chain into provider names.

        Returns:
            Ordered provider name list (empty when unset).
        """
        return [x.strip() for x in self.failover.split(",") if x.strip()]

    def use_llm_review_flag(self) -> bool | None:
        """Interpret USE_LLM_REVIEW as an optional boolean flag.

        Returns:
            True/False when set; None when unset (auto-detect by provider).
        """
        raw = self.use_llm_review.strip().lower()
        if not raw:
            return None
        return raw in {"1", "true", "yes", "on"}


@lru_cache
def get_settings() -> Settings:
    """Ensure user config exists, load .env files, return Settings.

    Returns:
        Cached Settings loaded from process env plus .env files.
    """
    ensure_user_config()
    load_dotenv_into_environ()
    return Settings.from_environ()


def clear_settings_cache() -> None:
    """Test helper: drop cached Settings and allow re-read.

    Returns:
        None.
    """
    get_settings.cache_clear()


def project_root() -> Path:
    """Repository root (parent of ``src/``).

    Returns:
        Absolute Path to the project root.
    """
    return _PROJECT_ROOT


def user_config_path() -> Path:
    """Path of the user-level ``~/.novel-weaver/.env`` file.

    Returns:
        Absolute Path to the user config file.
    """
    return _USER_ENV
