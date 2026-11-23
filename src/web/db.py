"""SQLite layer for the web UI — connection, schema, and all SQL helpers.

The DB path is a module global set once at startup via :func:`set_db_path`
(called from ``web_ui.main()``; tests point it at an isolated temp DB).
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator import delivery, personas
from schema import (  # noqa: F401 — the ARENA_/DRAFT_ names are re-exported to web_ui and web.api/render
    ARENA_CLOSED, ARENA_OPEN, CONV_COLUMNS, DRAFT_APPROVED, DRAFT_PENDING, DRAFT_POSTED,
    DRAFT_REJECTED, DRAFT_VERDICTS, MSG_COLUMNS, PERSONA_COLS_SQL, PERSONA_COLUMNS,
    complete_conversation, ensure_schema, write_txn,
)

DB_PATH: str = ""


def set_db_path(path: str) -> None:
    """Point the whole web process at a SQLite database file.

    Also exports ``AGENT_CHAT_DB``, because ``orchestrator.personas`` resolves
    its own path per call (``$AGENT_CHAT_DB`` > ``<repo>/db/chat.db``) and never
    sees this module's ``DB_PATH``. Without this, ``web_ui.py --db-path <other>``
    reads conversations from one DB and personas from another — and tests
    pointing at a temp DB would quietly touch the real ``db/chat.db``. On Fly the
    two already agree (``fly.toml`` sets ``AGENT_CHAT_DB=/data/chat.db``, which
    is also the ``--db-path`` default), so this only closes the divergent case.

    **The path is resolved to absolute first**, and that is load-bearing rather
    than tidiness. ``AGENT_CHAT_DB`` is inherited by every process this one
    spawns — including the CLI agents launched by ``POST /api/orchestrate``,
    which ``Set-Location`` into their own seat folder before starting. A
    relative value therefore re-resolves against *their* cwd, so
    ``set_db_path("db/chat.db")`` silently hands each agent
    ``agents/CLIs/<seat>/db/chat.db``: a fresh, empty database. ``get_kickoff()``
    then reports no conversation and the agent sits there with nothing to do,
    which is exactly how conversation #52 stalled (2026-08-26).

    Doing it here rather than asking callers to pass an absolute path keeps the
    guarantee in one place — a caller that gets it wrong cannot break the agents.

    ``abspath``, deliberately, **not** ``Path.resolve()``. The only property
    needed is "absolute, so it survives a change of cwd"; ``resolve()``
    additionally expands symlinks, 8.3 short names and case, which rewrites a
    path the caller may be comparing against. On a Windows CI runner
    ``tempfile.mkdtemp()`` returns ``C:\\Users\\RUNNER~1\\…`` and ``resolve()``
    turns it into ``C:\\Users\\runneradmin\\…`` — a different string, which broke
    seven tests that assert the exported value matches what they passed in.
    """
    global DB_PATH
    DB_PATH = os.path.abspath(os.path.expanduser(path))
    os.environ["AGENT_CHAT_DB"] = DB_PATH
    personas.DB_PATH = DB_PATH


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    # isolation_level=None (autocommit) matches every other writer on this DB —
    # agent_chat_mcp, seeding, personas, inspect_conversations. Without it,
    # sqlite3 opens an implicit transaction on the first write and holds it until
    # an explicit commit, which is exactly how a second process gets "database is
    # locked" on a shared WAL file.
    conn = sqlite3.connect(DB_PATH, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def db_init() -> None:
    """Create tables/indexes if missing, then apply additive column migrations.

    Used on the public Fly deploy where the persistent volume starts empty:
    the first request would otherwise hit "no such table: conversations".
    Locally this is a no-op when the DB already exists.

    Migrations are idempotent: each is gated on `PRAGMA table_info(table)`
    not already listing the column. Safe across schema versions in either
    direction (e.g. old sidecar pushing to a freshly-migrated server, or
    a freshly-deployed server reading an older volume snapshot).
    """
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        ensure_schema(conn)


def list_stats() -> dict[str, int]:
    """Headline counters for the landing page.

    Three numbers: total conversations, currently-active conversations,
    total messages. Cheap enough to compute on every render — three
    indexed COUNT(*) queries against the same connection.
    """
    with _connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM conversations"
        ).fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE status='active'"
        ).fetchone()[0]
        messages = conn.execute(
            "SELECT COUNT(*) FROM messages"
        ).fetchone()[0]
    return {
        "conversations": int(total),
        "active": int(active),
        "messages": int(messages),
    }


def _message_counts(conn: sqlite3.Connection) -> dict[int, int]:
    """Message count per conversation in one query; it was one COUNT per row,
    on every page that shows the rail (audit RT-28)."""
    return dict(conn.execute(
        "SELECT conversation_id, COUNT(*) FROM messages GROUP BY conversation_id"
    ).fetchall())


def list_conversations() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY id DESC"
        ).fetchall()
        counts = _message_counts(conn)
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["participants"] = json.loads(d["participants"])
            except (json.JSONDecodeError, TypeError):
                pass
            d["message_count"] = counts.get(r["id"], 0)
            out.append(d)
        return out


def list_featured_debates(limit: int = 4) -> list[dict[str, Any]]:
    """Completed conversations to feature in the homepage hero panel.

    Newest-first completed debates with at least a handful of messages (trivial
    /aborted runs are skipped). Each row carries its ``message_count`` and a
    ``teaser`` — the opening non-system message, trimmed by the renderer into a
    one-line description. Debater labels come from ``participant_personas`` when
    a cast was recorded (see ``_conv_debaters``), else the raw agent ids.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE status='complete' ORDER BY id DESC"
        ).fetchall()
        out: list[dict[str, Any]] = []
        counts = _message_counts(conn)
        for r in rows:
            n = counts.get(r["id"], 0)
            if n < 4:  # skip trivial / aborted runs
                continue
            d = dict(r)
            try:
                d["participants"] = json.loads(d["participants"])
            except (json.JSONDecodeError, TypeError):
                pass
            d["message_count"] = n
            opener = conn.execute(
                "SELECT content FROM messages "
                "WHERE conversation_id = ? AND sender != 'system' "
                "ORDER BY id ASC LIMIT 1",
                (r["id"],),
            ).fetchone()
            d["teaser"] = (opener["content"] if opener else "") or ""
            out.append(d)
            if len(out) >= limit:
                break
        return out


def existing_conversation_ids(ids: list[int]) -> set[int]:
    """Which of ``ids`` are rows on this deploy. The hosted mirror holds only
    the conversations synced to it, so a hard-coded id can exist locally and
    404 there."""
    if not ids:
        return set()
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT id FROM conversations WHERE id IN ({','.join('?' * len(ids))})",
            tuple(ids),
        ).fetchall()
    return {r[0] for r in rows}


def get_conversation(cid: int) -> dict[str, Any] | None:
    with _connect() as conn:
        c = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (cid,)
        ).fetchone()
        if not c:
            return None
        msgs = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (cid,),
        ).fetchall()
        conv = dict(c)
        try:
            conv["participants"] = json.loads(conv["participants"])
        except (json.JSONDecodeError, TypeError):
            pass
        return {"conversation": conv, "messages": [dict(m) for m in msgs]}


def messages_since(cid: int, last_id: int) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM messages "
            "WHERE conversation_id = ? AND id > ? ORDER BY id ASC",
            (cid, last_id),
        ).fetchall()
        return [dict(r) for r in rows]


def conversation_status(cid: int) -> str | None:
    with _connect() as conn:
        r = conn.execute(
            "SELECT status FROM conversations WHERE id = ?", (cid,)
        ).fetchone()
        return r["status"] if r else None


def conversation_turn_state(cid: int) -> tuple[str | None, str | None]:
    """Status + current_turn in one read — polled each tick by the SSE stream
    so the live viewer can show a whose-turn indicator. Returns (None, None)
    when the conversation doesn't exist."""
    with _connect() as conn:
        r = conn.execute(
            "SELECT status, current_turn FROM conversations WHERE id = ?", (cid,)
        ).fetchone()
        return (r["status"], r["current_turn"]) if r else (None, None)


def stop_conversation(cid: int) -> dict[str, Any] | None:
    """Force a conversation complete with end_reason='stopped by operator'.

    Goes through ``schema.complete_conversation`` like the CLI's ``stop`` and
    the MCP send path, so the row only leaves 'active' once and only the caller
    that moved it fires the ``complete`` delivery. Returns None if the
    conversation doesn't exist; otherwise returns {'already_complete': bool,
    'status': 'complete', 'end_reason': str}.
    """
    with _connect() as conn:
        if not complete_conversation(conn, cid, "stopped by operator"):
            row = conn.execute(
                "SELECT end_reason FROM conversations WHERE id = ?", (cid,)
            ).fetchone()
            if row is None:
                return None
            return {
                "already_complete": True,
                "status": "complete",
                "end_reason": row["end_reason"],
            }

    # Committed. Fan out to any configured delivery sink — a no-op unless
    # config/delivery.json turns one on. Outside the `with` for the same reason
    # the MCP server keeps it outside its own: a sink can be an HTTP POST or a
    # subprocess, neither of which belongs inside a write transaction. And on a
    # background thread: this runs inside an async route, and a slow sink would
    # stall every request and SSE stream of the web UI (audit RT-14).
    delivery.deliver_later(cid, ["complete"], DB_PATH)
    return {
        "already_complete": False,
        "status": "complete",
        "end_reason": "stopped by operator",
    }



# Composite-key wire format: group + Unit-Separator (0x1F) + slug. 0x1F is absent
# from group names and [a-z0-9-] slugs, and urlencodes cleanly. Used identically
# on both sides (here and in scripts/db_sync.py) for deletes-by-set-difference.
_PERSONA_KEY_SEP = "\x1f"


def _persona_key(row: dict[str, Any]) -> str:
    return f'{row["group"]}{_PERSONA_KEY_SEP}{row["slug"]}'


def ingest_payload(
    conversations: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    deleted_conversation_ids: list[int],
    personas: list[dict[str, Any]] | None = None,
    deleted_persona_keys: list[str] | None = None,
) -> dict[str, int]:
    """Apply a sync batch from the local writer (scripts/db_sync.py).

    Single transaction. Idempotent — re-posting the same payload is a no-op.

    - Conversations are upserted by ``id``, last write wins by
      ``updated_at``, so ``current_turn`` / ``status`` / ``end_reason`` flips
      propagate and an older batch never rolls a row back.
    - Messages use ``INSERT OR IGNORE`` so re-shipping the same id is safe.
    - Deletions run first and remove the conversation rows plus their
      messages (manual cascade — SQLite FK enforcement is off by default in
      this codebase).
    - Personas are upserted by ``(group, slug)`` via ``INSERT OR REPLACE`` and
      deleted by split composite key. Same transaction; backward-compatible —
      a payload from an old sidecar omits both and they no-op.
    """
    personas = personas or []
    deleted_persona_keys = deleted_persona_keys or []
    upserted = inserted = deleted = cascaded = 0
    personas_upserted = personas_deleted = 0
    with _connect() as conn:
        try:
            conn.execute("BEGIN")
            if deleted_conversation_ids:
                placeholders = ",".join("?" for _ in deleted_conversation_ids)
                cur = conn.execute(
                    f"DELETE FROM messages WHERE conversation_id IN ({placeholders})",
                    deleted_conversation_ids,
                )
                cascaded = cur.rowcount or 0
                cur = conn.execute(
                    f"DELETE FROM conversations WHERE id IN ({placeholders})",
                    deleted_conversation_ids,
                )
                deleted = cur.rowcount or 0
            if conversations:
                conv_rows = [
                    tuple(c.get(col) for col in CONV_COLUMNS)
                    for c in conversations
                ]
                # Last write wins by updated_at: a batch that arrives out of
                # order (a retry, an overlapping sidecar) must not roll a row
                # back. `>=` keeps a re-ship of the same row idempotent.
                updates = ",".join(
                    f"{c} = excluded.{c}" for c in CONV_COLUMNS if c != "id"
                )
                conn.executemany(
                    f"INSERT INTO conversations "
                    f"({','.join(CONV_COLUMNS)}) VALUES "
                    f"({','.join('?' * len(CONV_COLUMNS))}) "
                    f"ON CONFLICT(id) DO UPDATE SET {updates} "
                    f"WHERE excluded.updated_at >= conversations.updated_at",
                    conv_rows,
                )
                upserted = len(conv_rows)
            if messages:
                msg_rows = [
                    tuple(m.get(col) for col in MSG_COLUMNS)
                    for m in messages
                ]
                conn.executemany(
                    f"INSERT OR IGNORE INTO messages "
                    f"({','.join(MSG_COLUMNS)}) VALUES "
                    f"({','.join('?' * len(MSG_COLUMNS))})",
                    msg_rows,
                )
                # executemany's rowcount is unreliable across SQLite
                # versions; report the attempted-insert count, which the
                # client already knows. Idempotency on the server side is
                # what makes this safe.
                inserted = len(msg_rows)
            if deleted_persona_keys:
                split_keys = [
                    k.split(_PERSONA_KEY_SEP, 1)
                    for k in deleted_persona_keys
                    if _PERSONA_KEY_SEP in k
                ]
                conn.executemany(
                    'DELETE FROM personas WHERE "group" = ? AND slug = ?',
                    split_keys,
                )
                personas_deleted = len(split_keys)
            if personas:
                persona_rows = [
                    tuple(p.get(col) for col in PERSONA_COLUMNS)
                    for p in personas
                ]
                conn.executemany(
                    f"INSERT OR REPLACE INTO personas "
                    f"({PERSONA_COLS_SQL}) VALUES "
                    f"({','.join('?' * len(PERSONA_COLUMNS))})",
                    persona_rows,
                )
                personas_upserted = len(persona_rows)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return {
        "conversations_upserted": upserted,
        "messages_inserted": inserted,
        "conversations_deleted": deleted,
        "messages_deleted_cascade": cascaded,
        "personas_upserted": personas_upserted,
        "personas_deleted": personas_deleted,
    }


def delete_conversation(cid: int) -> dict[str, Any] | None:
    """Permanently remove a conversation and cascade-delete its messages.

    Returns ``None`` if the conversation doesn't exist; otherwise
    ``{"deleted": True, "cascaded_messages": <count>}``. Used by
    ``POST /api/conversations/{cid}/delete`` (operator action from the
    hosted UI) and propagated to the local DB by the sidecar's pull
    step on the next tick.

    Manual cascade because SQLite FK enforcement is off in this codebase
    (matches the convention in ``ingest_payload`` for hosted-side deletes
    coming from the local sidecar).
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM conversations WHERE id = ?", (cid,)
        ).fetchone()
        if row is None:
            return None
        conn.execute("BEGIN")
        try:
            cur = conn.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (cid,)
            )
            cascaded = cur.rowcount or 0
            conn.execute("DELETE FROM conversations WHERE id = ?", (cid,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return {"deleted": True, "cascaded_messages": cascaded}


# ---------------------------------------------------------------------------
# AgentBattleground — arenas captured from real web pages
#
# Local-only by design: these two tables are absent from CONV_COLUMNS /
# MSG_COLUMNS / PERSONA_COLUMNS above, so the sidecar never ships them to the
# Fly mirror. Captured third-party page content stays on this machine.
# ---------------------------------------------------------------------------



def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _arena_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["thread"] = json.loads(d["thread"])
    except (json.JSONDecodeError, TypeError):
        d["thread"] = []
    return d


def bg_create_arena(
    *,
    url: str,
    site: str,
    title: str,
    thread: list[dict[str, Any]],
    stance: str | None = None,
    reply_to: str | None = None,
    agent_id: str | None = None,
    persona_slug: str | None = None,
    persona_name: str | None = None,
    persona_body: str | None = None,
) -> dict[str, Any]:
    """Insert a captured debate as a new open arena and return the full row."""
    ts = _now()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO battleground_arenas "
            "(url, site, title, thread, stance, reply_to, agent_id, "
            " persona_slug, persona_name, persona_body, status, created_at, "
            " updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (url, site, title, json.dumps(thread), stance, reply_to, agent_id,
             persona_slug, persona_name, persona_body, ARENA_OPEN, ts, ts),
        )
        aid = int(cur.lastrowid)
        row = conn.execute(
            "SELECT * FROM battleground_arenas WHERE id = ?", (aid,)
        ).fetchone()
    return _arena_row(row)


def bg_list_arenas(
    status: str | None = None,
    agent_id: str | None = None,
) -> list[dict[str, Any]]:
    """Newest-first arenas, optionally filtered by status and/or assignee.

    ``agent_id`` matches arenas assigned to that agent **plus** unassigned ones
    (``agent_id IS NULL``), which are open to whoever picks them up — the same
    "any agent may join" semantics the MCP ``list_arenas`` tool exposes.
    """
    sql = "SELECT * FROM battleground_arenas"
    where: list[str] = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status)
    if agent_id:
        where.append("(agent_id = ? OR agent_id IS NULL)")
        params.append(agent_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = _arena_row(r)
            d["draft_count"] = conn.execute(
                "SELECT COUNT(*) FROM battleground_drafts WHERE arena_id = ?",
                (r["id"],),
            ).fetchone()[0]
            d["pending_count"] = conn.execute(
                "SELECT COUNT(*) FROM battleground_drafts "
                "WHERE arena_id = ? AND status = ?",
                (r["id"], DRAFT_PENDING),
            ).fetchone()[0]
            out.append(d)
        return out


def bg_get_arena(aid: int) -> dict[str, Any] | None:
    """One arena plus its drafts oldest-first, or None if it doesn't exist."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM battleground_arenas WHERE id = ?", (aid,)
        ).fetchone()
        if row is None:
            return None
        drafts = conn.execute(
            "SELECT * FROM battleground_drafts WHERE arena_id = ? ORDER BY id ASC",
            (aid,),
        ).fetchall()
    return {"arena": _arena_row(row), "drafts": [dict(d) for d in drafts]}


def bg_update_arena(
    aid: int,
    *,
    stance: str | None = None,
    reply_to: str | None = None,
    clear_reply_to: bool = False,
    agent_id: str | None = None,
    persona_slug: str | None = None,
    persona_name: str | None = None,
    persona_body: str | None = None,
    clear_persona_slug: bool = False,
    status: str | None = None,
) -> dict[str, Any] | None:
    """Patch the operator-controlled fields on an arena. None args are skipped
    (so a partial update can't blank out the cast).

    ``clear_reply_to`` and ``clear_persona_slug`` are the two escape hatches
    from that rule, for the two states "skip on None" can't express:

    * the operator un-picking a reply target, and
    * re-casting onto a **custom** persona, which has a name and a body but no
      registry row behind it. Without the flag the previous card's slug would
      survive beside the new name, leaving an arena that claims to be one
      character and reads as another.
    """
    sets: list[str] = []
    params: list[Any] = []
    for col, val in (
        ("stance", stance),
        ("reply_to", reply_to),
        ("agent_id", agent_id),
        ("persona_slug", persona_slug),
        ("persona_name", persona_name),
        ("persona_body", persona_body),
        ("status", status),
    ):
        if val is not None:
            sets.append(f"{col} = ?")
            params.append(val)
    if clear_reply_to and reply_to is None:
        sets.append("reply_to = NULL")
    if clear_persona_slug and persona_slug is None:
        sets.append("persona_slug = NULL")
    with _connect() as conn:
        if conn.execute(
            "SELECT id FROM battleground_arenas WHERE id = ?", (aid,)
        ).fetchone() is None:
            return None
        if sets:
            sets.append("updated_at = ?")
            params.extend([_now(), aid])
            conn.execute(
                f"UPDATE battleground_arenas SET {', '.join(sets)} WHERE id = ?",
                params,
            )
        row = conn.execute(
            "SELECT * FROM battleground_arenas WHERE id = ?", (aid,)
        ).fetchone()
    return _arena_row(row)


def bg_merge_thread(aid: int, posts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Fold a fresh capture into an arena's stored thread.

    Posts are matched on their ``id`` (the site adapter's stable per-post key):
    known ids are refreshed in place — score/edit churn is normal — and unknown
    ids are appended in capture order. This is what lets an operator re-capture
    a page after new replies land without losing the arena or duplicating the
    backlog the agent has already read.
    """
    # Read-modify-write of one JSON column: under BEGIN IMMEDIATE, two captures
    # arriving together merge one after the other instead of the second
    # overwriting the first's new posts (audit RT-09).
    with _connect() as conn, write_txn(conn):
        row = conn.execute(
            "SELECT thread FROM battleground_arenas WHERE id = ?", (aid,)
        ).fetchone()
        if row is None:
            return None
        try:
            existing = json.loads(row["thread"])
        except (json.JSONDecodeError, TypeError):
            existing = []
        by_id = {p.get("id"): i for i, p in enumerate(existing) if p.get("id")}
        added = 0
        for post in posts:
            pid = post.get("id")
            if pid and pid in by_id:
                existing[by_id[pid]] = post
            else:
                existing.append(post)
                added += 1
        conn.execute(
            "UPDATE battleground_arenas SET thread = ?, updated_at = ? WHERE id = ?",
            (json.dumps(existing), _now(), aid),
        )
        arena = conn.execute(
            "SELECT * FROM battleground_arenas WHERE id = ?", (aid,)
        ).fetchone()
    result = _arena_row(arena)
    result["posts_added"] = added
    return result


def bg_delete_arena(aid: int) -> dict[str, Any] | None:
    """Remove an arena and cascade-delete its drafts.

    Manual cascade, matching :func:`delete_conversation` — SQLite FK
    enforcement is off on the web connection.
    """
    with _connect() as conn:
        if conn.execute(
            "SELECT id FROM battleground_arenas WHERE id = ?", (aid,)
        ).fetchone() is None:
            return None
        conn.execute("BEGIN")
        try:
            cur = conn.execute(
                "DELETE FROM battleground_drafts WHERE arena_id = ?", (aid,)
            )
            cascaded = cur.rowcount or 0
            conn.execute("DELETE FROM battleground_arenas WHERE id = ?", (aid,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return {"deleted": True, "cascaded_drafts": cascaded}


def bg_create_draft(
    *,
    arena_id: int,
    agent_id: str,
    content: str,
    reply_to: str | None = None,
    rationale: str | None = None,
) -> dict[str, Any] | None:
    """Record an agent's proposed reply as a ``pending`` draft.

    Mirrors the INSERT the MCP ``submit_draft`` tool runs against the same
    table, so the web layer and the agent layer produce identical rows.
    Returns None when the arena doesn't exist or is closed.
    """
    ts = _now()
    with _connect() as conn:
        arena = conn.execute(
            "SELECT status FROM battleground_arenas WHERE id = ?", (arena_id,)
        ).fetchone()
        if arena is None or arena["status"] != ARENA_OPEN:
            return None
        cur = conn.execute(
            "INSERT INTO battleground_drafts "
            "(arena_id, agent_id, reply_to, content, rationale, status, "
            " verdict_note, posted_text, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)",
            (arena_id, agent_id, reply_to, content, rationale,
             DRAFT_PENDING, ts, ts),
        )
        did = int(cur.lastrowid)
        conn.execute(
            "UPDATE battleground_arenas SET updated_at = ? WHERE id = ?",
            (ts, arena_id),
        )
        row = conn.execute(
            "SELECT * FROM battleground_drafts WHERE id = ?", (did,)
        ).fetchone()
    return dict(row)


def bg_set_verdict(
    did: int,
    verdict: str,
    *,
    note: str | None = None,
    posted_text: str | None = None,
) -> dict[str, Any] | None:
    """Apply the operator's decision to a draft.

    ``verdict`` is one of :data:`DRAFT_VERDICTS`. ``posted_text`` records what
    actually landed on the page, which can differ from ``content`` — the
    operator is free to edit before posting, and the agent gets to see the edit
    on its next ``wait_for_verdict`` so it can match voice next round.

    Returns None if the draft doesn't exist; raises ValueError on a bad verdict.
    """
    if verdict not in DRAFT_VERDICTS:
        raise ValueError(
            f"verdict must be one of {DRAFT_VERDICTS}, got {verdict!r}"
        )
    ts = _now()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM battleground_drafts WHERE id = ?", (did,)
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE battleground_drafts SET status = ?, verdict_note = ?, "
            "posted_text = COALESCE(?, posted_text), updated_at = ? WHERE id = ?",
            (verdict, note, posted_text, ts, did),
        )
        conn.execute(
            "UPDATE battleground_arenas SET updated_at = ? WHERE id = ?",
            (ts, row["arena_id"]),
        )
        updated = conn.execute(
            "SELECT * FROM battleground_drafts WHERE id = ?", (did,)
        ).fetchone()
    return dict(updated)


def since_payload(
    updated_after: str,
    known_ids: list[int],
    personas_updated_after: str | None = None,
    known_persona_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Build the response body for ``GET /api/since``.

    Returns conversations whose ``updated_at`` is strictly greater than
    ``updated_after`` plus the subset of ``known_ids`` that no longer
    exist server-side (i.e., what the sidecar should delete locally).
    Also returns ``server_time`` so the sidecar can use it as its next
    watermark and avoid clock-skew bugs.

    Personas sync the same way, keyed on composite ``(group, slug)``:
    rows with ``updated_at`` > ``personas_updated_after`` plus the
    ``known_persona_keys`` no longer present server-side. When
    ``personas_updated_after`` is None (an old sidecar that doesn't send
    the param) the persona work is skipped entirely and empty lists are
    returned — backward-compatible.

    **Messages are intentionally not included.** They flow local-only-
    origin: agents only run locally, so messages always originate
    locally; bidirectional sync covers conversation-row mutations
    (status, topic, end_reason, deletion). Client: ``scripts/db_sync.py``.
    """
    cols = ",".join(CONV_COLUMNS)
    server_time = datetime.now(timezone.utc).isoformat()
    persona_rows: list[dict[str, Any]] = []
    deleted_persona_keys: list[str] = []
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT {cols} FROM conversations "
            f"WHERE updated_at > ? ORDER BY updated_at ASC",
            (updated_after,),
        ).fetchall()
        existing = {
            int(r[0])
            for r in conn.execute("SELECT id FROM conversations").fetchall()
        }
        if personas_updated_after is not None:
            prows = conn.execute(
                f"SELECT {PERSONA_COLS_SQL} FROM personas "
                f"WHERE updated_at > ? ORDER BY updated_at ASC",
                (personas_updated_after,),
            ).fetchall()
            persona_rows = [dict(r) for r in prows]
            existing_keys = {
                _persona_key(dict(r))
                for r in conn.execute(
                    'SELECT "group", slug FROM personas'
                ).fetchall()
            }
            deleted_persona_keys = sorted(
                set(known_persona_keys or []).difference(existing_keys)
            )
    deleted = sorted(set(known_ids).difference(existing))
    return {
        "conversations": [dict(r) for r in rows],
        "deleted_conversation_ids": deleted,
        "personas": persona_rows,
        "deleted_persona_keys": deleted_persona_keys,
        "server_time": server_time,
    }
