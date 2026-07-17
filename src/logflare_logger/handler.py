import asyncio
import logging
import queue
import sys
import threading
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass

from .payload import LogPayload
from .transport import LogFlareTransport

_STOP = object()


@dataclass(frozen=True, slots=True)
class _WorkItem:
    payload: LogPayload
    completion: Future[bool] | None = None


class LogFlareHandler(logging.Handler):
    def __init__(
        self,
        *,
        url: str,
        project: str,
        project_key: str,
        level: int = logging.NOTSET,
        queue_capacity: int = 1000,
        request_timeout: float = 5.0,
        max_attempts: int = 3,
        backoff_base: float = 0.25,
        backoff_cap: float = 5.0,
        close_timeout: float = 5.0,
    ) -> None:
        super().__init__(level)
        if queue_capacity < 1:
            raise ValueError("queue_capacity must be at least 1")
        self.close_timeout = close_timeout
        self._queue_capacity = queue_capacity
        self._transport_options = {
            "url": url,
            "project": project,
            "project_key": project_key,
            "request_timeout": request_timeout,
            "max_attempts": max_attempts,
            "backoff_base": backoff_base,
            "backoff_cap": backoff_cap,
        }
        # +1 reserved slot so a stop sentinel can always be queued.
        self._queue: queue.Queue[_WorkItem | object] = queue.Queue(queue_capacity + 1)
        self._queued = 0
        self._pending = 0
        self._condition = threading.Condition()
        self._close_lock = threading.Lock()
        self._closed = False
        self._start_failed = False
        self._stop_queued = False
        self._thread = threading.Thread(
            target=self._worker_main,
            name="logflare-worker",
            daemon=True,
        )
        self._thread.start()

    @property
    def pending_count(self) -> int:
        with self._condition:
            return self._pending

    @staticmethod
    def _payload_from_record(record: logging.LogRecord) -> LogPayload:
        error_type = None
        if record.exc_info and record.exc_info[0]:
            error_type = record.exc_info[0].__name__
        elif isinstance(record.msg, BaseException):
            error_type = type(record.msg).__name__
        return LogPayload(
            error_type=error_type,
            level=record.levelname,
            message=record.getMessage(),
        )

    def _enqueue(self, item: _WorkItem) -> bool:
        with self._condition:
            if self._closed:
                if self._start_failed:
                    self._diagnostic(
                        "handler disabled after transport start failure; log record rejected"
                    )
                return False
            if self._queued >= self._queue_capacity:
                self._diagnostic("queue full; dropped newest log record")
                return False
            self._queued += 1
            self._pending += 1
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                self._queued -= 1
                self._pending -= 1
                self._condition.notify_all()
                self._diagnostic("queue full; dropped newest log record")
                return False
            return True

    def emit(self, record: logging.LogRecord) -> None:
        self._enqueue(_WorkItem(self._payload_from_record(record)))

    def flush(self, timeout: float | None = None) -> bool:
        if not hasattr(self, "_condition"):
            return True
        effective_timeout = self.close_timeout if timeout is None else timeout
        deadline = time.monotonic() + effective_timeout
        with self._condition:
            while self._pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._diagnostic(f"flush timed out with {self._pending} pending record(s)")
                    return False
                self._condition.wait(remaining)
        return True

    def test_connection(self, timeout: float = 5.0) -> bool:
        completion: Future[bool] = Future()
        item = _WorkItem(
            LogPayload("ConnectionTest", "INFO", "Test connection", test=True),
            completion,
        )
        if not self._enqueue(item):
            return False
        try:
            return completion.result(timeout)
        except FutureTimeoutError:
            self._diagnostic("connection test timed out")
            return False

    @staticmethod
    def _diagnostic(message: str) -> None:
        sys.stderr.write(f"[logflare-logger] {message}\n")

    def _worker_main(self) -> None:
        asyncio.run(self._worker())

    async def _worker(self) -> None:
        transport = LogFlareTransport(**self._transport_options)
        started = False
        try:
            await transport.start()
            started = True
        except Exception as error:
            self._diagnostic(f"transport start failed: {error!r}")
            with self._condition:
                self._start_failed = True
            self._fail_all_queued()
            return
        try:
            try:
                while True:
                    item = await asyncio.to_thread(self._queue.get)
                    if item is _STOP:
                        self._queue.task_done()
                        return
                    if not isinstance(item, _WorkItem):
                        self._queue.task_done()
                        self._diagnostic(
                            "worker received unexpected queue item type: "
                            f"{type(item).__name__}"
                        )
                        self._fail_all_queued()
                        return
                    with self._condition:
                        self._queued -= 1
                    try:
                        result = await transport.send(item.payload)
                        if not result.success:
                            self._diagnostic(
                                f"delivery failed after {result.attempts} attempt(s): "
                                f"status={result.status} detail={result.detail!r}"
                            )
                        if item.completion is not None and not item.completion.done():
                            item.completion.set_result(result.success)
                    except Exception as error:
                        self._diagnostic(f"unexpected worker error: {error!r}")
                        if item.completion is not None and not item.completion.done():
                            item.completion.set_result(False)
                    finally:
                        self._finish_item()
            except BaseException as error:
                self._diagnostic(f"worker stopped unexpectedly: {error!r}")
                self._fail_all_queued()
        finally:
            if started:
                await transport.close()

    def _fail_all_queued(self) -> None:
        with self._condition:
            self._closed = True
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is _STOP:
                self._queue.task_done()
                continue
            if not isinstance(item, _WorkItem):
                self._queue.task_done()
                continue
            with self._condition:
                self._queued -= 1
            if item.completion is not None and not item.completion.done():
                item.completion.set_result(False)
            self._finish_item()
        with self._condition:
            self._condition.notify_all()

    def _finish_item(self) -> None:
        self._queue.task_done()
        with self._condition:
            self._pending -= 1
            self._condition.notify_all()

    def _queue_stop_locked(self) -> bool:
        """Enqueue STOP while holding ``_condition``. Caller must hold the lock."""
        if self._stop_queued:
            return True
        try:
            self._queue.put_nowait(_STOP)
        except queue.Full:
            self._diagnostic("worker stop signal could not be queued before timeout")
            return False
        self._stop_queued = True
        return True

    def close(self, timeout: float | None = None) -> bool:
        if not hasattr(self, "_closed"):
            super().close()
            return True

        effective_timeout = self.close_timeout if timeout is None else timeout
        with self._close_lock:
            with self._condition:
                first_close = not self._closed
                self._closed = True
            # Start the budget after shutdown is ordered so admission waits do not
            # consume the caller's close/join timeout.
            started = time.monotonic()

            flushed = True
            if first_close:
                flushed = self.flush(effective_timeout)
                remaining = max(0.0, effective_timeout - (time.monotonic() - started))
                with self._condition:
                    if not self._queue_stop_locked():
                        super().close()
                        return False
                self._thread.join(remaining)
            else:
                with self._condition:
                    if not self._queue_stop_locked():
                        super().close()
                        return False
                self._thread.join(effective_timeout)

            stopped = not self._thread.is_alive()
            if not stopped:
                self._diagnostic("worker did not stop before timeout")
            super().close()
            if first_close:
                return flushed and stopped
            return stopped and self.pending_count == 0
