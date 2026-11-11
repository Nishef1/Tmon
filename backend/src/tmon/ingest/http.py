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
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
)

from tmon.core.config import get_settings

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    pass


class _RetryableStatusError(Exception):
    """A response status worth retrying (429/5xx…), carrying any ``Retry-After`` seconds."""

    def __init__(self, url: str, resp: httpx.Response) -> None:
        super().__init__(f"GET {url} -> HTTP {resp.status_code}")
        self.retry_after = _parse_retry_after(resp.headers.get("Retry-After"))


def _parse_retry_after(value: str | None) -> float | None:
    """Seconds from a ``Retry-After`` header (delta-seconds or HTTP-date); None if absent/bad."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


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

    def _wait(self, state: RetryCallState) -> float:
        """Exponential backoff with jitter; a server's ``Retry-After`` wins if it is longer."""
        backoff = self._retry.delay(state.attempt_number - 1)
        exc = state.outcome.exception() if state.outcome else None
        if isinstance(exc, _RetryableStatusError) and exc.retry_after is not None:
            return min(self._retry.max_delay, max(backoff, exc.retry_after))
        return backoff

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        host = urlparse(url).netloc
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._retry.max_retries + 1),
            wait=self._wait,
            retry=retry_if_exception_type(
                (httpx.TransportError, httpx.TimeoutException, _RetryableStatusError)
            ),
            sleep=self._sleep,
            before_sleep=lambda s: log.warning(
                "GET %s failed (%s), attempt %d",
                url,
                s.outcome.exception() if s.outcome else None,
                s.attempt_number,
            ),
            reraise=True,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    await self._limiter.wait(host)
                    resp = await self._client.get(url, **kwargs)  # type: ignore[arg-type]
                    if resp.status_code in RETRYABLE_STATUS:
                        raise _RetryableStatusError(url, resp)
                    if resp.status_code >= 400:
                        raise FetchError(f"GET {url} -> HTTP {resp.status_code}")
                    return resp
        except (httpx.TransportError, httpx.TimeoutException, _RetryableStatusError) as exc:
            raise FetchError(f"GET {url} failed after retries: {exc}") from exc
        raise AssertionError("unreachable")  # pragma: no cover

    async def aclose(self) -> None:
        await self._client.aclose()
