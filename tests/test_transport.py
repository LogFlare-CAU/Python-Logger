import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from aiohttp import web

from logflare_logger.payload import LogPayload
from logflare_logger.transport import LogFlareTransport


@asynccontextmanager
async def serve(
    statuses: list[int],
    *,
    response_delay: float = 0.0,
) -> AsyncIterator[tuple[str, list[dict[str, object]]]]:
    requests: list[dict[str, object]] = []

    async def receive(request: web.Request) -> web.Response:
        requests.append(
            {
                "project": request.headers["Project"],
                "project_key": request.headers["ProjectKey"],
                "body": await request.json(),
            }
        )
        await asyncio.sleep(response_delay)
        return web.Response(status=statuses.pop(0))

    app = web.Application()
    app.router.add_post("/log/error", receive)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    server = site._server
    assert server is not None
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/log/error", requests
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_send_matches_backend_contract_and_reuses_session() -> None:
    async with serve([204, 204]) as (url, requests):
        transport = LogFlareTransport(url=url, project="demo", project_key="secret")
        await transport.start()
        session = transport.session

        first = await transport.send(LogPayload("ValueError", "ERROR", "first"))
        second = await transport.send(LogPayload(None, "WARNING", "second"))

        assert first.success is True
        assert second.success is True
        assert transport.session is session
        assert requests[0] == {
            "project": "demo",
            "project_key": "Bearer secret",
            "body": {"errortype": "ValueError", "level": "ERROR", "message": "first"},
        }
        assert requests[1] == {
            "project": "demo",
            "project_key": "Bearer secret",
            "body": {"errortype": None, "level": "WARNING", "message": "second"},
        }
        await transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_status", [429, 500, 503])
async def test_retryable_status_is_retried(retry_status: int) -> None:
    delays: list[float] = []

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    async with serve([retry_status, 204]) as (url, requests):
        transport = LogFlareTransport(
            url=url,
            project="demo",
            project_key="secret",
            max_attempts=2,
            backoff_base=0.1,
            sleep=record_delay,
        )
        await transport.start()
        result = await transport.send(LogPayload(None, "ERROR", "retry"))
        await transport.close()

    assert result.success is True
    assert result.attempts == 2
    assert len(requests) == 2
    assert delays == [0.1]


@pytest.mark.asyncio
async def test_permanent_client_error_is_not_retried() -> None:
    async with serve([401]) as (url, requests):
        transport = LogFlareTransport(
            url=url, project="demo", project_key="bad", max_attempts=3
        )
        await transport.start()
        result = await transport.send(LogPayload(None, "ERROR", "unauthorized"))
        await transport.close()

    assert result.success is False
    assert result.status == 401
    assert result.attempts == 1
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_request_timeout_is_retried_and_exhausted() -> None:
    delays: list[float] = []

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    async with serve([204, 204], response_delay=0.05) as (url, requests):
        transport = LogFlareTransport(
            url=url,
            project="demo",
            project_key="secret",
            request_timeout=0.01,
            max_attempts=2,
            sleep=record_delay,
        )
        await transport.start()
        result = await transport.send(LogPayload(None, "ERROR", "slow"))
        await transport.close()

    assert result.success is False
    assert result.status is None
    assert result.attempts == 2
    assert len(requests) == 2
    assert delays == [0.25]


@pytest.mark.asyncio
async def test_connection_error_exhausts_attempts() -> None:
    delays: list[float] = []

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    transport = LogFlareTransport(
        url="http://127.0.0.1:1/log/error",
        project="demo",
        project_key="secret",
        request_timeout=0.1,
        max_attempts=2,
        sleep=record_delay,
    )
    await transport.start()
    result = await transport.send(LogPayload(None, "ERROR", "offline"))
    await transport.close()

    assert result.success is False
    assert result.status is None
    assert result.attempts == 2
    assert delays == [0.25]
