"""Deterministic fingerprints for context and generation specs."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _stable_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def context_fingerprint(payload: Any) -> str:
    return hashlib.sha256(_stable_dumps(payload).encode("utf-8")).hexdigest()[:16]


def generation_spec_fingerprint(spec: dict[str, Any]) -> str:
    return context_fingerprint(spec)
