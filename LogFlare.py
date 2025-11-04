import logging
import asyncio
import aiohttp


class LogFlare(logging.Logger):
    def __init__(self, name: str):
        super().__init__(name)
        self.conn = None
        self.broadcastlevel: int = logging.WARNING  # int 기반
        self.broadcasturl: str = "http://localhost:80"
        self.broadcast: bool = False  # 브로드캐스트 on/off 스위치

    def set_broadcastlevel(self, level: int):
        if not isinstance(level, int):
            raise TypeError("broadcastlevel must be an int (e.g. logging.WARNING)")
        if level not in logging._levelToName:  # 유효한 로그레벨인지 검사
            raise ValueError(f"Invalid logging level: {level}")
        self.broadcastlevel = level

    async def broadcast_(self, level_name: str, msg: str) -> None:
        base = self.broadcasturl
        if not base.startswith(("http://", "https://")):
            base = "http://" + base
        base = base.rstrip("/")
        url = f"{base}/{level_name.lower()}"
        payload = {"logger": self.name, "level": level_name, "message": msg}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        print(f"[Broadcast FAIL] {resp.status} {text}")
        except Exception as e:
            print(f"[Broadcast EXC] {e!r}")
        finally:
            pass

        print(f"[Broadcast] {msg}")

    def log(self, level, msg, *args, **kwargs):
        try:
            formatted = (msg % args) if args else str(msg)
        except Exception:
            formatted = str(msg)
        if level >= self.broadcastlevel and self.broadcast:
            level_name = logging.getLevelName(level)
            asyncio.create_task(self.broadcast_(level_name, formatted))
        return super().log(level, msg, *args, **kwargs)
