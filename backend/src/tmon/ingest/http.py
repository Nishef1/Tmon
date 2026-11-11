"""Polite async HTTP client: per-domain rate limit + exponential backoff.

Rule set from docs/02-data-sources.md ("crawler rules"). Raw payload storage and
provenance are layered on top in :mod:`tmon.ingest.fetcher`.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from tmon.core.config import get_settings

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 5
    base_delay: float = 1.0
    max_delay: float = 60.0
    jitter: float = 0.25

    def delay(self, attempt: int) -> float:
        raw = min(self.max_delay, self.base_delay * (2**attempt))
        return float(raw * (1 + random.uniform(-self.jitter, self.jitter)))


class DomainRateLimiter:
    """Guarantees a minimum interval between requests to the same host."""

    def __init__(
        self,
        min_interval: float,
        per_domain: dict[str, float] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._default = min_interval
        self._per_domain = per_domain or {}
        self._next_slot: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._clock = clock
        self._sleep = sleep

    def interval_for(self, host: str) -> float:
        return self._per_domain.get(host, self._default)

    async def wait(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = self._clock()
            ready = self._next_slot.get(host, now)
            if ready > now:
                await self._sleep(ready - now)
            self._next_slot[host] = max(now, ready) + self.interval_for(host)


class PoliteClient:
    def __init__(
        self,
        *,
        limiter: DomainRateLimiter | None = None,
        retry: RetryPolicy | None = None,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        s = get_settings()
        self._limiter = limiter or DomainRateLimiter(s.http_min_interval_seconds)
        self._retry = retry or RetryPolicy(max_retries=s.http_max_retries)
        self._client = client or httpx.AsyncClient(
            timeout=s.http_timeout_seconds,
            headers={"User-Agent": s.http_user_agent},
            follow_redirects=True,
            proxy=s.http_proxy,
        )
        self._sleep = sleep

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        host = urlparse(url).netloc
        last_error: Exception | None = None
        for attempt in range(self._retry.max_retries + 1):
            await self._limiter.wait(host)
            try:
                resp = await self._client.get(url, **kwargs)  # type: ignore[arg-type]
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_error = exc
                log.warning("GET %s failed (%s), attempt %d", url, exc, attempt + 1)
            else:
                if resp.status_code not in RETRYABLE_STATUS:
                    if resp.status_code >= 400:
                        raise FetchError(f"GET {url} -> HTTP {resp.status_code}")
                    return resp
                last_error = FetchError(f"GET {url} -> HTTP {resp.status_code}")
                log.warning("GET %s -> %d, attempt %d", url, resp.status_code, attempt + 1)
            if attempt < self._retry.max_retries:
                await self._sleep(self._retry.delay(attempt))
        raise FetchError(f"GET {url} failed after retries: {last_error}")

    async def aclose(self) -> None:
        await self._client.aclose()
