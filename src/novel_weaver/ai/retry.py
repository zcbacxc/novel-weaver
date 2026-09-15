# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Retry helper for transient provider faults (Phase 5 hardening foundation)."""

from __future__ import annotations

import functools
import time
from collections.abc import Callable, Iterator
from typing import ParamSpec, TypeVar

from novel_weaver.ai.base import ProviderError

P = ParamSpec("P")
R = TypeVar("R")


def _backoff_delays(
    attempts: int,
    base_delay: float,
    max_delay: float,
    jitter: float,
) -> Iterator[float]:
    for i in range(max(0, attempts - 1)):
        delay = min(max_delay, base_delay * (2**i))
        if jitter:
            delay += jitter * (i + 1)
        yield delay


def retry_with_backoff(
    *,
    max_attempts: int = 3,
    base_delay: float = 0.05,
    max_delay: float = 2.0,
    jitter: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Retry only when ProviderError.retryable is True; re-raise otherwise."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_error: ProviderError | None = None
            delays = list(_backoff_delays(max_attempts, base_delay, max_delay, jitter))
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except ProviderError as exc:
                    if not exc.retryable:
                        raise
                    last_error = exc
                    if attempt < len(delays):
                        sleep(delays[attempt])
            assert last_error is not None
            raise last_error

        return wrapper

    return decorator
