import logging
import os
import asyncio
import threading
import sys
import aiohttp


class LogFlare(logging.Logger):
    def __init__(self, name: str):
        super().__init__(name)
        self.conn = None
        self.project_name: str | None = None
        self.project_key: str | None = None
        self.broadcasturl: str | None = None
        self.broadcastlevel: int = logging.WARNING
        self.broadcast: bool = False

    def headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Project": self.project_name,
            "ProjectKey": "Bearer " + self.project_key,
        }

    def test_connection(self) -> bool:
        """동기 함수에서 비동기 연결 테스트 실행"""
        try:
            self._spawn_coro(self._test_connection())
            return True
        except Exception:
            return False

    async def _test_connection(self) -> bool:
        self.info("\n\n====================\nTesting LogFlare Connection\n====================\n\n")
        if not (self.project_name and self.project_key and self.broadcasturl):
            self.warning("\n\n====================\nLogFlare Info InComplete\n====================\n\n")
            return False
        payload = {"errortype": "Test", "level": "INFO", "message": "Test connection", "test":True}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.broadcasturl, json=payload, headers=self.headers()
                ) as resp:
                    self.info(f"\n\n====================\nLogFlare connection test status: {resp.status}\n====================\n\n")
                    return resp.status < 400
        except Exception:
            self.exception("\n\n====================\nLogFlare connection test failed\n====================\n\n")
            return False

    def _spawn_coro(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:

            def _runner():
                try:
                    asyncio.run(coro)
                except Exception as e:
                    print(f"[Broadcast THREAD EXC] {e!r}")

            threading.Thread(target=_runner, daemon=True).start()
        else:
            loop.create_task(coro)

    def set_broadcastlevel(self, level: int) -> None:
        self.broadcastlevel = level

    async def _enable_broadcast_after(self, delay: float) -> None:
        await asyncio.sleep(delay)
        self.broadcast = True
        super().info(f"logger.broadcast enabled after {delay:.1f}s")

    def enable_broadcast_after(self, delay: float) -> None:
        """루프 유무와 상관없이 delay 후 broadcast=True로 전환"""
        if delay <= 0:
            self.broadcast = True
            return
        self._spawn_coro(self._enable_broadcast_after(delay))

    async def broadcast_(self, errortype, level_name: str, msg: str) -> None:
        if not (self.project_name and self.project_key and self.broadcasturl):
            return
        payload = {"errortype": errortype, "level": level_name, "message": msg}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.broadcasturl, json=payload, headers=self.headers()
                ) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        print(f"[Broadcast FAIL] {resp.status} {text}")
        except Exception as e:
            print(f"[Broadcast EXC] {e!r}")

    def _log(
        self,
        level,
        msg,
        args,
        exc_info=None,
        extra=None,
        stack_info=False,
        stacklevel=1,
    ):
        try:
            formatted = (msg % args) if args else str(msg)
        except Exception:
            formatted = str(msg)

        errortype = None
        if exc_info:
            if isinstance(exc_info, tuple):
                errortype = getattr(exc_info[0], "__name__", None)
            elif isinstance(exc_info, BaseException):
                errortype = type(exc_info).__name__
            else:
                exc_type, _, _ = sys.exc_info()
                if exc_type:
                    errortype = exc_type.__name__

        if errortype is None and isinstance(msg, BaseException):
            errortype = type(msg).__name__

        if self.broadcast and level >= self.broadcastlevel:
            level_name = logging.getLevelName(level)
            self._spawn_coro(self.broadcast_(errortype, level_name, formatted))

        super()._log(
            level,
            msg,
            args,
            exc_info=exc_info,
            extra=extra,
            stack_info=stack_info,
            stacklevel=stacklevel,
        )

    def warning(self, msg, *args, **kwargs):
        return self._log(logging.WARNING, msg, args, **kwargs)

    def error(self, msg, *args, **kwargs):
        return self._log(logging.ERROR, msg, args, **kwargs)

    def exception(self, msg, *args, exc_info=True, **kwargs):
        return self._log(logging.ERROR, msg, args, exc_info=exc_info, **kwargs)
