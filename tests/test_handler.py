import asyncio
import logging
import threading
import time

from logflare_logger import LogFlareHandler, LogPayload
from logflare_logger.handler import _STOP
from logflare_logger.transport import SendResult


def wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


class FakeTransport:
    sent_payloads: list[LogPayload] = []

    def __init__(self, **options: object) -> None:
        self.options = options

    async def start(self) -> None:
        return None

    async def send(self, payload: LogPayload) -> SendResult:
        self.sent_payloads.append(payload)
        return SendResult(True, 204, 1)

    async def close(self) -> None:
        return None


class BlockingTransport(FakeTransport):
    release = threading.Event()
    entered = threading.Event()

    async def send(self, payload):
        self.entered.set()
        await asyncio.to_thread(self.release.wait)
        return await super().send(payload)


class BoomOnceTransport(FakeTransport):
    calls = 0

    async def send(self, payload: LogPayload) -> SendResult:
        type(self).calls += 1
        if type(self).calls == 1:
            raise RuntimeError("boom")
        return await super().send(payload)


class FailStartTransport(FakeTransport):
    allow_fail = threading.Event()

    async def start(self) -> None:
        await asyncio.to_thread(type(self).allow_fail.wait)
        raise RuntimeError("cannot start")


def test_handler_extracts_message_level_and_exception_type(monkeypatch) -> None:
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", FakeTransport)
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
        level=logging.ERROR,
    )
    logger = logging.getLogger("handler-exception-test")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    try:
        raise ValueError("bad value")
    except ValueError:
        logger.exception("request %s", "failed")

    wait_until(lambda: len(FakeTransport.sent_payloads) == 1)
    payload = FakeTransport.sent_payloads[0]
    assert payload.error_type == "ValueError"
    assert payload.level == "ERROR"
    assert payload.message == "request failed"
    handler.close()


def test_standard_handler_level_filters_records(monkeypatch) -> None:
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", FakeTransport)
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
        level=logging.WARNING,
    )
    logger = logging.getLogger("handler-level-test")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    logger.info("ignored")
    logger.warning("accepted")

    wait_until(lambda: len(FakeTransport.sent_payloads) == 1)
    assert FakeTransport.sent_payloads[0].message == "accepted"
    handler.close()


def test_formatter_does_not_change_transmitted_message(monkeypatch) -> None:
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", FakeTransport)
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
    )
    handler.setFormatter(logging.Formatter("PREFIX %(message)s"))
    record = logging.LogRecord("test", logging.ERROR, "", 0, "raw %s", ("message",), None)

    handler.emit(record)

    wait_until(lambda: len(FakeTransport.sent_payloads) == 1)
    assert FakeTransport.sent_payloads[0].message == "raw message"
    handler.close()


def test_emit_drops_newest_record_without_blocking(monkeypatch, capsys) -> None:
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", BlockingTransport)
    BlockingTransport.release.clear()
    BlockingTransport.entered.clear()
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
        queue_capacity=1,
    )
    record = logging.LogRecord("test", logging.ERROR, "", 0, "message", (), None)

    handler.emit(record)
    assert BlockingTransport.entered.wait(1.0)
    started = time.monotonic()
    handler.emit(record)
    handler.emit(record)
    elapsed = time.monotonic() - started

    assert elapsed < 0.1
    assert "queue full; dropped newest log record" in capsys.readouterr().err
    BlockingTransport.release.set()
    assert handler.close(timeout=1.0) is True


def test_flush_times_out_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", BlockingTransport)
    BlockingTransport.release.clear()
    BlockingTransport.entered.clear()
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
    )
    record = logging.LogRecord("test", logging.ERROR, "", 0, "message", (), None)
    handler.emit(record)

    assert handler.flush(timeout=0.01) is False
    BlockingTransport.release.set()
    assert handler.flush(timeout=1.0) is True
    assert handler.close(timeout=1.0) is True
    assert handler.close(timeout=1.0) is True


def test_connection_waits_for_actual_worker_result(monkeypatch) -> None:
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", FakeTransport)
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
    )

    assert handler.test_connection(timeout=1.0) is True
    assert FakeTransport.sent_payloads[0].test is True
    assert handler.close(timeout=1.0) is True


def test_unexpected_send_exception_does_not_strand_pending(monkeypatch) -> None:
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", BoomOnceTransport)
    BoomOnceTransport.calls = 0
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
    )
    record = logging.LogRecord("test", logging.ERROR, "", 0, "first", (), None)
    second = logging.LogRecord("test", logging.ERROR, "", 0, "second", (), None)

    handler.emit(record)
    wait_until(lambda: handler.pending_count == 0)
    handler.emit(second)
    wait_until(lambda: len(FakeTransport.sent_payloads) == 1)

    assert FakeTransport.sent_payloads[0].message == "second"
    assert handler.close(timeout=1.0) is True


def test_close_succeeds_when_application_queue_is_full(monkeypatch) -> None:
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", BlockingTransport)
    BlockingTransport.release.clear()
    BlockingTransport.entered.clear()
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
        queue_capacity=1,
    )
    record = logging.LogRecord("test", logging.ERROR, "", 0, "message", (), None)

    handler.emit(record)
    assert BlockingTransport.entered.wait(1.0)
    handler.emit(record)
    assert handler.pending_count == 2

    closer = threading.Thread(target=lambda: setattr(closer, "result", handler.close(timeout=1.0)))
    closer.start()
    time.sleep(0.05)
    BlockingTransport.release.set()
    closer.join(2.0)

    assert closer.result is True
    assert not handler._thread.is_alive()


def test_emit_rejected_after_shutdown_ordered(monkeypatch) -> None:
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", BlockingTransport)
    BlockingTransport.release.clear()
    BlockingTransport.entered.clear()
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
    )
    record = logging.LogRecord("test", logging.ERROR, "", 0, "in-flight", (), None)
    late = logging.LogRecord("test", logging.ERROR, "", 0, "after-close", (), None)

    handler.emit(record)
    assert BlockingTransport.entered.wait(1.0)

    closer = threading.Thread(target=lambda: setattr(closer, "result", handler.close(timeout=1.0)))
    closer.start()
    wait_until(lambda: handler._closed)
    handler.emit(late)
    BlockingTransport.release.set()
    closer.join(2.0)

    assert closer.result is True
    assert all(payload.message != "after-close" for payload in FakeTransport.sent_payloads)


def test_second_close_reports_incomplete_shutdown(monkeypatch) -> None:
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", BlockingTransport)
    BlockingTransport.release.clear()
    BlockingTransport.entered.clear()
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
        close_timeout=0.05,
    )
    record = logging.LogRecord("test", logging.ERROR, "", 0, "message", (), None)
    handler.emit(record)
    assert BlockingTransport.entered.wait(1.0)

    assert handler.close(timeout=0.05) is False
    assert handler._thread.is_alive()
    assert handler.close(timeout=0.05) is False

    BlockingTransport.release.set()
    wait_until(lambda: not handler._thread.is_alive())
    assert handler.close(timeout=1.0) is True


def test_accepted_item_cannot_land_after_stop(monkeypatch) -> None:
    """Widen the accept→put gap so STOP cannot overtake an already-accepted item."""
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", FakeTransport)
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
    )
    original_put = handler._queue.put_nowait
    put_order: list[object] = []
    in_work_put = threading.Event()
    resume_work_put = threading.Event()

    def gated_put(item: object) -> None:
        if item is not _STOP:
            in_work_put.set()
            assert resume_work_put.wait(2.0)
        put_order.append(item)
        original_put(item)

    handler._queue.put_nowait = gated_put  # type: ignore[method-assign]
    # Force close to attempt STOP immediately once it passes admission locking.
    handler.flush = lambda timeout=None: False  # type: ignore[method-assign]
    record = logging.LogRecord("test", logging.ERROR, "", 0, "accepted-before-stop", (), None)

    emitter = threading.Thread(target=handler.emit, args=(record,))
    emitter.start()
    assert in_work_put.wait(1.0)

    closer = threading.Thread(target=lambda: setattr(closer, "result", handler.close(timeout=1.0)))
    closer.start()
    # If acceptance released the lock before put, STOP lands during this window.
    deadline = time.monotonic() + 0.2
    while time.monotonic() < deadline and not handler._stop_queued:
        time.sleep(0.01)
    resume_work_put.set()
    emitter.join(2.0)
    closer.join(2.0)

    seen_stop = False
    for item in put_order:
        if item is _STOP:
            seen_stop = True
        elif seen_stop:
            raise AssertionError("accepted work item was queued after STOP")
    wait_until(lambda: handler.pending_count == 0)
    wait_until(lambda: not handler._thread.is_alive())
    assert handler.pending_count == 0


def test_concurrent_close_does_not_enqueue_stop_during_flush(monkeypatch) -> None:
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", BlockingTransport)
    BlockingTransport.release.clear()
    BlockingTransport.entered.clear()
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
    )
    record = logging.LogRecord("test", logging.ERROR, "", 0, "message", (), None)
    handler.emit(record)
    assert BlockingTransport.entered.wait(1.0)

    original_put = handler._queue.put_nowait
    stop_during_flush = threading.Event()
    flush_entered = threading.Event()

    def tracking_put(item: object) -> None:
        if item is _STOP and flush_entered.is_set() and handler.pending_count > 0:
            stop_during_flush.set()
        original_put(item)

    handler._queue.put_nowait = tracking_put  # type: ignore[method-assign]

    original_flush = handler.flush

    def gated_flush(timeout: float | None = None) -> bool:
        flush_entered.set()
        time.sleep(0.1)
        return original_flush(timeout)

    handler.flush = gated_flush  # type: ignore[method-assign]

    results: list[bool] = []

    def run_close() -> None:
        results.append(handler.close(timeout=1.0))

    first = threading.Thread(target=run_close)
    second = threading.Thread(target=run_close)
    first.start()
    assert flush_entered.wait(1.0)
    second.start()
    time.sleep(0.05)
    BlockingTransport.release.set()
    first.join(2.0)
    second.join(2.0)

    assert not stop_during_flush.is_set()
    assert results == [True, True]
    assert handler.pending_count == 0
    assert not handler._thread.is_alive()


def test_transport_start_failure_clears_pending(monkeypatch) -> None:
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", FailStartTransport)
    FailStartTransport.allow_fail.clear()
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
    )
    record = logging.LogRecord("test", logging.ERROR, "", 0, "stranded?", (), None)
    handler.emit(record)
    assert handler.pending_count == 1

    FailStartTransport.allow_fail.set()
    wait_until(lambda: handler.pending_count == 0)
    wait_until(lambda: not handler._thread.is_alive())
    assert handler.close(timeout=1.0) is True


class GatedStartTransport(FakeTransport):
    allow_start = threading.Event()

    async def start(self) -> None:
        await asyncio.to_thread(type(self).allow_start.wait)


class WorkerFatal(BaseException):
    """BaseException subclass used to escape the per-item Exception handler."""


class FatalSendTransport(GatedStartTransport):
    async def send(self, payload: LogPayload) -> SendResult:
        raise WorkerFatal("worker fatal")


def test_worker_fatal_exit_fails_queued_and_stops_accepting(monkeypatch) -> None:
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", FatalSendTransport)
    FatalSendTransport.allow_start.clear()
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
    )
    first = logging.LogRecord("test", logging.ERROR, "", 0, "fatal", (), None)
    second = logging.LogRecord("test", logging.ERROR, "", 0, "queued", (), None)
    late = logging.LogRecord("test", logging.ERROR, "", 0, "after-fatal", (), None)

    handler.emit(first)
    handler.emit(second)
    assert handler.pending_count == 2

    FatalSendTransport.allow_start.set()
    wait_until(lambda: handler._closed)
    wait_until(lambda: handler.pending_count == 0)
    wait_until(lambda: not handler._thread.is_alive())

    handler.emit(late)
    assert handler.pending_count == 0
    assert handler.close(timeout=1.0) is True


def test_worker_unexpected_queue_item_fails_queued_and_stops_accepting(monkeypatch) -> None:
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", GatedStartTransport)
    GatedStartTransport.allow_start.clear()
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
    )
    record = logging.LogRecord("test", logging.ERROR, "", 0, "should-fail", (), None)
    late = logging.LogRecord("test", logging.ERROR, "", 0, "after-unexpected", (), None)

    handler._queue.put_nowait("not-a-work-item")
    handler.emit(record)
    assert handler.pending_count == 1

    GatedStartTransport.allow_start.set()
    wait_until(lambda: handler._closed)
    wait_until(lambda: handler.pending_count == 0)
    wait_until(lambda: not handler._thread.is_alive())

    handler.emit(late)
    assert handler.pending_count == 0
    assert handler.close(timeout=1.0) is True


def test_emit_after_start_failure_emits_diagnostic(monkeypatch, capsys) -> None:
    monkeypatch.setattr("logflare_logger.handler.LogFlareTransport", FailStartTransport)
    FailStartTransport.allow_fail.clear()
    FakeTransport.sent_payloads = []
    handler = LogFlareHandler(
        url="https://example.invalid/log/error",
        project="demo",
        project_key="secret",
    )
    record = logging.LogRecord("test", logging.ERROR, "", 0, "before-fail", (), None)
    late = logging.LogRecord("test", logging.ERROR, "", 0, "after-fail", (), None)

    handler.emit(record)
    FailStartTransport.allow_fail.set()
    wait_until(lambda: handler.pending_count == 0)
    wait_until(lambda: not handler._thread.is_alive())
    capsys.readouterr()

    handler.emit(late)
    err = capsys.readouterr().err
    assert "transport start failure" in err
    assert handler.pending_count == 0
    assert handler.close(timeout=1.0) is True
