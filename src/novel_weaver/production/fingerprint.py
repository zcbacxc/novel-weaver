# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Deterministic fingerprints for context and generation specs."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _stable_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def context_fingerprint(payload: Any) -> str:
    """Stable short hash of a JSON-serializable payload.

    Args:
        payload: Any JSON-serializable structure.

    Returns:
        16-character hex digest of the canonical JSON form.
    """
    return hashlib.sha256(_stable_dumps(payload).encode("utf-8")).hexdigest()[:16]


def generation_spec_fingerprint(spec: dict[str, Any]) -> str:
    """Stable hash of a generation specification dict.

    Args:
        spec: Generation specification payload.

    Returns:
        16-character hex digest shared with context_fingerprint.
    """
    return context_fingerprint(spec)


def content_fingerprint(text: str) -> str:
    """Stable hash of chapter content for external-edit drift detection.

    Args:
        text: Chapter body (empty string when None).

    Returns:
        16-character hex digest of the UTF-8 content.
    """
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]
