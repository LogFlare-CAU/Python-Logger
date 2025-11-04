import asyncio, logging


class LogFlare(logging.Logger):
    def __init__(self, name: str):
        super().__init__(name)
        self.conn = None
        self.broadcastlevel = "info"

    async def broadcast(self, msg):
        # broadcast 동작 (예: 웹소켓 전송, 파일 기록 등)
        print(f"[Broadcast] {msg}")

    def log(self, level, msg, *args, **kwargs):
        try:
            numeric_broadcast_level = logging._nameToLevel[self.broadcastlevel.upper()]
        except KeyError:
            numeric_broadcast_level = logging.INFO  # fallback
        if level >= numeric_broadcast_level:
            asyncio.create_task(self.broadcast(msg))
        return super().log(level, msg, *args, **kwargs)
