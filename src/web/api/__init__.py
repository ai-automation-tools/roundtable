"""/api/* route handlers for the web UI.

Handlers are plain ``def`` (audit RT-28): Starlette runs them in its threadpool,
so synchronous SQLite (a 10 s busy timeout), file and HTTP work can't stall the
event loop and every other request with it. ``request_json`` reads the body from
inside such a handler. Only the SSE stream and the streamed ingest stay async.
"""

from typing import Any

import anyio.from_thread
from starlette.requests import Request


def request_json(request: Request) -> Any:
    """``await request.json()`` for a sync handler running in the threadpool.
    Raises what ``request.json()`` raises (``ValueError`` on a bad body)."""
    return anyio.from_thread.run(request.json)
