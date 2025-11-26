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

        payload = {
            "errortype": errortype,
            "level": level_name,
            "message": msg,
        }
        headers = {
            "Content-Type": "application/json",
            "Project": self.project_name,
            "ProjectKey": "Bearer " + self.project_key,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.broadcasturl,
                    json=payload,
                    headers=headers,
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
        # 원본 메시지 포맷팅
        try:
            formatted = (msg % args) if args else str(msg)
        except Exception:
            formatted = str(msg)

        # errortype 추출
        errortype = None
        if exc_info:
            if isinstance(exc_info, tuple):
                # (exc_type, exc, tb)
                errortype = getattr(exc_info[0], "__name__", None)
            elif isinstance(exc_info, BaseException):
                # Exception 인스턴스 직접 전달된 경우
                errortype = type(exc_info).__name__
            else:
                # exc_info=True 이고, 현재 컨텍스트에 예외가 있는 경우
                exc_type, _, _ = sys.exc_info()
                if exc_type:
                    errortype = exc_type.__name__

        # 3번의 추가 보정: 실수로 logger.error(error) 같은 패턴을 쓴 경우
        if errortype is None and isinstance(msg, BaseException):
            errortype = type(msg).__name__

        # 브로드캐스트
        if self.broadcast and level >= self.broadcastlevel:
            level_name = logging.getLevelName(level)
            self._spawn_coro(self.broadcast_(errortype, level_name, formatted))

        # 실제 로그 출력
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

    def warning(self, msg, *args, **kwargs):
        return self._log(logging.WARNING, msg, args, **kwargs)

    def error(self, msg, *args, **kwargs):
        return self._log(logging.ERROR, msg, args, **kwargs)

    def exception(self, msg, *args, exc_info=True, **kwargs):
        return self._log(logging.ERROR, msg, args, exc_info=exc_info, **kwargs)
