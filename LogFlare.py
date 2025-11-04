import logging
import asyncio
import aiohttp


class LogFlare(logging.Logger):
    def __init__(self, name: str):
        super().__init__(name)
        self.conn = None
        self.broadcastlevel = "INFO"
        self.url = "http://localhost:80"

    async def broadcast(self, level_name: str, msg: str) -> None:
        base = self.url
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
            numeric_broadcast_level = logging._nameToLevel[
                str(self.broadcastlevel).upper()
            ]
        except KeyError:
            numeric_broadcast_level = logging.INFO
        try:
            formatted = (msg % args) if args else str(msg)
        except Exception:
            formatted = str(msg)

        if level >= numeric_broadcast_level:
            level_name = logging.getLevelName(level)
            asyncio.create_task(self.broadcast(level_name, formatted))
        return super().log(level, msg, *args, **kwargs)
