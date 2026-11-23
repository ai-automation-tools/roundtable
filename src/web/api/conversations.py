"""Conversation JSON/download/stream endpoints under /api/conversations/."""

from __future__ import annotations

import asyncio
import json

from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from orchestrator.export import (
    export_filename as _export_filename,
    export_zip_filename as _export_zip_filename,
    render_export_markdown as _render_export_markdown,
    render_export_zip as _render_export_zip,
)
from orchestrator.media_prompts import (
    PROMPT_KINDS,
    build_prompt as _build_prompt,
    prompt_filename as _prompt_filename,
)

from web.db import (
    conversation_turn_state,
    delete_conversation,
    get_conversation,
    list_conversations,
    messages_since,
    stop_conversation,
)
from web.render.common import MESSAGE_HEADING_LEVEL, render_markdown

POLL_INTERVAL_SECONDS = 1.0

# Open SSE streams, in total and per client. Each one holds a connection and
# polls SQLite every second, and the public mirror is a 256 MB VM anyone can
# open a hundred tabs against (audit RT-17). A browser caps a host at ~6
# HTTP/1.1 connections anyway, so a real reader never meets the per-client cap.
MAX_STREAMS = 100
MAX_STREAMS_PER_CLIENT = 10
_streams: dict[str, int] = {}


def _stream_client(request: Request) -> str:
    """Who is opening a stream: Fly's ``Fly-Client-IP`` on the mirror (every
    request reaches the app from Fly's proxy), else the socket's peer."""
    headers = getattr(request, "headers", None) or {}
    client = getattr(request, "client", None)
    return headers.get("fly-client-ip") or (client.host if client else "?")


def api_conversations(request: Request) -> Response:
    return JSONResponse(list_conversations())


def api_conversation(request: Request) -> Response:
    cid = int(request.path_params["cid"])
    data = get_conversation(cid)
    if not data:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(data)


def api_conversation_export(request: Request) -> Response:
    """Serve a conversation as a downloadable Markdown document.

    Content-Disposition forces a download in browsers; the URL ends in
    `.md` so command-line tools (curl, wget) save with the right
    extension by default.
    """
    cid = int(request.path_params["cid"])
    data = get_conversation(cid)
    if not data:
        return Response("Not found", status_code=404, media_type="text/plain")
    md = _render_export_markdown(data)
    topic = str(data["conversation"].get("topic") or "")
    filename = _export_filename(cid, topic)
    return Response(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


def api_conversation_prompt(request: Request) -> Response:
    """Serve a media-production prompt for one conversation.

    ``GET /api/conversations/{cid}/prompts/{kind}.md`` where kind is ``images``
    or ``audio`` — see ``orchestrator.media_prompts``. The conversation page
    fetches these for its two buttons; they're also useful straight from curl.

    Read-only by construction (it renders text from rows that already exist), so
    it works unchanged on the hosted mirror. ``?download=1`` switches from an
    inline response to a file download.
    """
    kind = str(request.path_params["kind"])
    if kind not in PROMPT_KINDS:
        return Response(f"Unknown prompt kind {kind!r}", status_code=404,
                        media_type="text/plain")
    cid = int(request.path_params["cid"])
    data = get_conversation(cid)
    if not data:
        return Response("Not found", status_code=404, media_type="text/plain")

    # The transcript URL baked into the audio prompt has to be one the reader
    # can actually curl, so derive it from the request rather than assuming
    # localhost — a hosted visitor needs the hosted origin.
    base_url = str(request.base_url).rstrip("/")
    text = _build_prompt(kind, data, cid, base_url)

    headers = {"Cache-Control": "no-store"}
    if request.query_params.get("download"):
        topic = str(data["conversation"].get("topic") or "")
        filename = _prompt_filename(kind, cid, topic)
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(text, media_type="text/markdown; charset=utf-8", headers=headers)


def api_conversation_export_zip(request: Request) -> Response:
    """Serve a conversation as a downloadable .zip of Markdown documents.

    Bundle: ``topic.md`` (topic + overview), ``personas/<agent>.md`` (one per
    participant — CLI tool + personality card), and ``transcript.md`` (the full
    debate). See :func:`_render_export_zip`.
    """
    cid = int(request.path_params["cid"])
    data = get_conversation(cid)
    if not data:
        return Response("Not found", status_code=404, media_type="text/plain")
    blob = _render_export_zip(data)
    topic = str(data["conversation"].get("topic") or "")
    filename = _export_zip_filename(cid, topic)
    return Response(
        blob,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


def api_stop(request: Request) -> Response:
    cid = int(request.path_params["cid"])
    result = stop_conversation(cid)
    if result is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(result)


def api_delete(request: Request) -> Response:
    """Permanently delete a conversation. Hosted-UI affordance.

    Cascades messages. The local sidecar picks this up on the next pull
    tick (via ``GET /api/since``) and applies the deletion to the local
    DB so the two sides converge. Idempotent — second DELETE returns 404.
    """
    cid = int(request.path_params["cid"])
    result = delete_conversation(cid)
    if result is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(result)

def _tick(cid: int, last_id: int) -> tuple[tuple[str | None, str | None], list]:
    return conversation_turn_state(cid), messages_since(cid, last_id)


async def api_stream(request: Request) -> Response:
    """SSE stream for a conversation: ``message`` per new row, ``turn`` when
    ``current_turn`` changes (whose-turn indicator), ``complete`` on close."""
    cid = int(request.path_params["cid"])
    try:
        last_id = int(request.query_params.get("since", "0"))
    except ValueError:
        return JSONResponse({"error": "since must be a message id"}, status_code=400)
    who = _stream_client(request)
    if sum(_streams.values()) >= MAX_STREAMS or _streams.get(who, 0) >= MAX_STREAMS_PER_CLIENT:
        return JSONResponse({"error": "too many open streams"}, status_code=429,
                            headers={"Retry-After": "30"})

    async def event_generator():
        nonlocal last_id
        last_turn: object = "\x00unset"  # sentinel — always emit the first turn
        while True:
            if await request.is_disconnected():
                break
            # State BEFORE messages: a send commits its message and the close
            # in one transaction (RT-09), so once 'complete' is read every
            # message is visible to the read below. The other order could see
            # 'complete' and stop without the final message (audit RT-17).
            # In the threadpool: a reader that waits on a lock must not hold
            # up the loop that serves every other viewer (audit RT-28).
            (status, current_turn), new = await run_in_threadpool(_tick, cid, last_id)
            for m in new:
                payload = {**m, "content_html": render_markdown(m["content"], MESSAGE_HEADING_LEVEL)}
                yield {"event": "message", "data": json.dumps(payload)}
                last_id = max(last_id, m["id"])
            if status == "complete":
                yield {"event": "complete", "data": ""}
                break
            if status is None:
                break
            if current_turn != last_turn:
                yield {"event": "turn", "data": json.dumps({"current_turn": current_turn})}
                last_turn = current_turn
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def counted():
        # Counted from the first iteration, so a response that never starts
        # streaming can't leak a slot (an unstarted generator runs no finally).
        _streams[who] = _streams.get(who, 0) + 1
        try:
            async for event in event_generator():
                yield event
        finally:
            _streams[who] -= 1
            if not _streams[who]:
                del _streams[who]

    return EventSourceResponse(counted())
