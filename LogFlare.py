import logging
import asyncio
import threading
import sys
import aiohttp
import os


class LogFlare(logging.Logger):
    def __init__(self, name: str):
        super().__init__(name)
        self.conn = None
        self.project_name: str | None = None
        self.project_key: str | None = None
        self.broadcasturl: str | None = None
        self.broadcastlevel: int = logging.WARNING
        self.broadcast: bool = False

    # --------------------------- 내부 유틸 ---------------------------

    def _spawn_coro(self, coro):
        """비동기 루프 유무에 상관없이 안전하게 코루틴 실행"""
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

    # --------------------------- 브로드캐스트 ---------------------------

    def set_broadcastlevel(self, level: int) -> None:
        """브로드캐스트 레벨 설정"""
        self.broadcastlevel = level

    async def broadcast_(self, errortype, level_name: str, msg: str) -> None:
        if not (self.project_name and self.project_key and self.broadcasturl):
            return
        payload = {"errortype": errortype, "level": level_name, "message": msg}
        headers = {
            "Content-Type": "application/json",
            "Project": self.project_name,
            "ProjectKey": "Bearer " + self.project_key,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.broadcasturl, json=payload, headers=headers
                ) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        print(f"[Broadcast FAIL] {resp.status} {text}")
        except Exception as e:
            print(f"[Broadcast EXC] {e!r}")

    # --------------------------- 오버라이드 ---------------------------

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
        """표준 로깅 경로 오버라이드: errortype 자동 감지 + 브로드캐스트"""
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
            elif exc_info:
                exc_type, _, _ = sys.exc_info()
                if exc_type:
                    errortype = exc_type.__name__

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

    # --------------------------- 표준 레벨 메서드 오버라이드 ---------------------------

    def warning(self, msg, *args, exc_info=True, **kwargs):
        """기본적으로 exc_info=True를 붙여서 errortype 자동 감지"""
        return self._log(logging.WARNING, msg, args, exc_info=exc_info, **kwargs)

    def error(self, msg, *args, exc_info=True, **kwargs):
        """에러 로그 → 기본 exc_info=True"""
        return self._log(logging.ERROR, msg, args, exc_info=exc_info, **kwargs)

    def exception(self, msg, *args, exc_info=True, **kwargs):
        """exception()은 항상 예외 컨텍스트 포함"""
        return self._log(logging.ERROR, msg, args, exc_info=exc_info, **kwargs)

    def critical(self, msg, *args, exc_info=True, **kwargs):
        """치명적 에러 → 기본 exc_info=True"""
        return self._log(logging.CRITICAL, msg, args, exc_info=exc_info, **kwargs)
