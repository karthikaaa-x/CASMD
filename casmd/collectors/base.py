"""
Base collector utilities: a token-bucket rate limiter and a backoff helper.

These exist because every real platform throttles you. The policy here is the
same one the README documents: throttle proactively to the published quota,
back off exponentially on 429/5xx, and checkpoint so a killed run resumes
instead of re-fetching.
"""

from __future__ import annotations

import time
import random
from typing import Callable, Any


class RateLimiter:
    """Simple token bucket. `rate` tokens per `per` seconds."""

    def __init__(self, rate: float, per: float = 1.0):
        self.rate = rate
        self.per = per
        self.allowance = rate
        self.last = time.monotonic()

    def acquire(self) -> None:
        now = time.monotonic()
        self.allowance += (now - self.last) * (self.rate / self.per)
        self.last = now
        if self.allowance > self.rate:
            self.allowance = self.rate
        if self.allowance < 1.0:
            sleep_for = (1.0 - self.allowance) * (self.per / self.rate)
            time.sleep(sleep_for)
            self.allowance = 0.0
        else:
            self.allowance -= 1.0


def with_backoff(fn: Callable[..., Any], *args,
                 retries: int = 5, base: float = 2.0, **kwargs) -> Any:
    """Call fn with exponential backoff + jitter on transient failures."""
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - collectors decide what is transient
            transient = _is_transient(exc)
            if not transient or attempt == retries - 1:
                raise
            wait = base ** attempt + random.uniform(0, 1)
            print(f"[backoff] {type(exc).__name__}: retry {attempt+1}/{retries} "
                  f"in {wait:.1f}s")
            time.sleep(wait)


def _is_transient(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(k in text for k in
               ("429", "timeout", "timed out", "temporar", "5xx",
                "500", "502", "503", "504", "flood", "rate"))
