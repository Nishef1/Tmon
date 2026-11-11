import asyncio

import httpx
import pytest
import respx

from tmon.ingest.http import DomainRateLimiter, FetchError, PoliteClient, RetryPolicy


def _client(handler_routes, *, max_retries=3):
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    limiter = DomainRateLimiter(0.0)
    c = PoliteClient(
        limiter=limiter,
        retry=RetryPolicy(max_retries=max_retries, base_delay=1.0, max_delay=8.0, jitter=0.0),
        client=httpx.AsyncClient(),
        sleep=fake_sleep,
    )
    return c, sleeps


def test_retries_with_exponential_backoff_then_succeeds() -> None:
    async def run() -> None:
        with respx.mock:
            route = respx.get("http://x.test/a").mock(
                side_effect=[
                    httpx.Response(503),
                    httpx.Response(429),
                    httpx.Response(200, text="ok"),
                ]
            )
            c, sleeps = _client(None)
            r = await c.get("http://x.test/a")
            assert r.text == "ok"
            assert route.call_count == 3
            assert sleeps == [1.0, 2.0]
            await c.aclose()

    asyncio.run(run())


def test_gives_up_after_max_retries() -> None:
    async def run() -> None:
        with respx.mock:
            respx.get("http://x.test/a").mock(return_value=httpx.Response(500))
            c, _ = _client(None, max_retries=2)
            with pytest.raises(FetchError):
                await c.get("http://x.test/a")
            await c.aclose()

    asyncio.run(run())


def test_client_errors_are_not_retried() -> None:
    async def run() -> None:
        with respx.mock:
            route = respx.get("http://x.test/a").mock(return_value=httpx.Response(404))
            c, sleeps = _client(None)
            with pytest.raises(FetchError):
                await c.get("http://x.test/a")
            assert route.call_count == 1 and sleeps == []
            await c.aclose()

    asyncio.run(run())


def test_transport_errors_are_retried() -> None:
    async def run() -> None:
        with respx.mock:
            respx.get("http://x.test/a").mock(
                side_effect=[httpx.ConnectError("boom"), httpx.Response(200, text="ok")]
            )
            c, _ = _client(None)
            assert (await c.get("http://x.test/a")).text == "ok"
            await c.aclose()

    asyncio.run(run())


def test_rate_limiter_spaces_requests_per_domain() -> None:
    async def run() -> None:
        now = [0.0]
        slept: list[float] = []

        async def sleep(s: float) -> None:
            slept.append(s)
            now[0] += s

        lim = DomainRateLimiter(
            2.0, per_domain={"fast.test": 0.5}, clock=lambda: now[0], sleep=sleep
        )
        await lim.wait("slow.test")
        await lim.wait("slow.test")
        await lim.wait("slow.test")
        assert slept == [2.0, 2.0]
        await lim.wait("fast.test")  # independent domain, no wait
        await lim.wait("fast.test")
        assert slept[2:] == [0.5]

    asyncio.run(run())


def test_backoff_is_capped() -> None:
    p = RetryPolicy(max_retries=10, base_delay=1.0, max_delay=8.0, jitter=0.0)
    assert [p.delay(i) for i in range(6)] == [1, 2, 4, 8, 8, 8]
