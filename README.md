# LogFlare Python Logger

Non-blocking Python 3.12+ logging handler for the LogFlare `/log/error` API.

## Installation

```shell
pip install git+https://github.com/LogFlare-CAU/Python-Logger.git
```

## Usage

```python
import logging
import os

from logflare_logger import LogFlareHandler

handler = LogFlareHandler(
    url=os.environ["LOGFLARE_URL"],
    project=os.environ["LOGFLARE_PROJECT"],
    project_key=os.environ["LOGFLARE_PROJECT_KEY"],
    level=logging.WARNING,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(handler)

try:
    logger.warning("service is degraded")
except Exception:
    logger.exception("service failed")
finally:
    handler.close(timeout=5.0)
```

No formatter is required for LogFlare delivery. Other console or file handlers
may use any formatter.

## Delivery behavior

- Logging calls enqueue records without network I/O.
- The in-memory queue is bounded; when full, the newest record is dropped and a
  diagnostic is written to stderr.
- Connection errors, timeouts, HTTP 429, and HTTP 5xx responses are retried with
  capped exponential backoff (default `max_attempts=3`).
- Other HTTP 4xx responses are not retried.
- If the background worker cannot start its HTTP transport, the handler
  permanently disables itself: already-queued work is failed, later `emit`
  calls are rejected with a stderr diagnostic, and there is no automatic
  reconnect. Create a new handler instance to resume delivery.
- Abrupt process termination can lose queued records.

Call `flush(timeout=5.0)` to wait for accepted records without closing the
handler. Call `close(timeout=5.0)` during orderly shutdown. Both return `True`
on completion and `False` on timeout.

`test_connection(timeout=5.0)` sends a real request with `"test": true` and
returns `True` on successful delivery or `False` on failure or timeout.

## Development

```shell
python -m pip install -e ".[dev]"
python -m ruff check src tests
python -m pytest
python -m build
```
