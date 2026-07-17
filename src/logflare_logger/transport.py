import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import aiohttp

from .payload import LogPayload

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class SendResult:
    success: bool
    status: int | None
    attempts: int
    detail: str | None = None


class LogFlareTransport:
    def __init__(
        self,
        *,
        url: str,
        project: str,
        project_key: str,
        request_timeout: float = 5.0,
        max_attempts: int = 3,
        backoff_base: float = 0.25,
        backoff_cap: float = 5.0,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.url = url
        self.project = project
        self.project_key = project_key
        self.request_timeout = request_timeout
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self._sleep = sleep
        self._session: aiohttp.ClientSession | None = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError("transport has not been started")
        return self._session

    async def start(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
            await asyncio.sleep(0)

    def _delay(self, attempt: int) -> float:
        return min(self.backoff_cap, self.backoff_base * (2 ** (attempt - 1)))

    async def send(self, payload: LogPayload) -> SendResult:
        for attempt in range(1, self.max_attempts + 1):
            try:
                async with self.session.post(
                    self.url,
                    json=payload.as_json(),
                    headers={
                        "Project": self.project,
                        "ProjectKey": f"Bearer {self.project_key}",
                    },
                ) as response:
                    if 200 <= response.status < 300:
                        return SendResult(True, response.status, attempt)
                    detail = await response.text()
                    retryable = response.status == 429 or response.status >= 500
                    if not retryable or attempt == self.max_attempts:
                        return SendResult(False, response.status, attempt, detail)
            except (aiohttp.ClientError, TimeoutError) as error:
                if attempt == self.max_attempts:
                    return SendResult(False, None, attempt, str(error))
            await self._sleep(self._delay(attempt))
        raise RuntimeError("retry loop ended unexpectedly")
