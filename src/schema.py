"""The database contract, defined once.

Every process that opens ``db/chat.db`` (the MCP server, the web UI, seeding,
the persona registry, the sync sidecar) imports its DDL, migrations, synced
column lists and battleground status values from here. Stdlib only, so the
MCP server, ``scripts/db_sync.py`` and ``orchestrator/personas.py`` (run as a
script by ``debate.ps1``) can import it without pulling in the web stack.

Adding a column: put it in ``SCHEMA``, add a ``MIGRATIONS`` row so existing
files upgrade in place, and add it to the matching ``*_COLUMNS`` tuple if it
should reach the Fly mirror (deploy the web app before restarting the sidecar).
``tests/test_conv_types.py`` pins the column lists against the real tables.

It also owns the one state change several processes race on: a conversation
leaving ``active`` (``complete_conversation``), plus ``write_txn`` for a
check-then-write that must not interleave with another process.
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent


def resolve_db_path(explicit: str | None = None, *, relative_ok: bool = True) -> str:
    """The one rule for which database file a process opens (audit RT-20):
    ``--db-path`` > ``$AGENT_CHAT_DB`` > ``<repo>/db/chat.db``. Always absolute.

    ``relative_ok=False`` refuses a relative ``--db-path`` (the MCP server: a
    CLI starts it from its own seat folder, so a relative path names a
    different, empty database there). Raises ValueError; entrypoints turn that
    into an exit message.

    ``$AGENT_CHAT_DB`` must be absolute and point into a folder that exists.
    It is inherited by agents launched from their own seat folders, so a
    relative value silently points each one at a different, empty database
    (conversation #52, 2026-08-26), and a missing folder means a stale value
    from before a repo move, where opening it would start an empty DB
    (2026-09-22). Resolving either here would only make the wrong path
    absolute: the cwd that gives it meaning belongs to whoever exported it.
    """
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            if not relative_ok:
                raise ValueError(
                    f"--db-path must be an absolute path; got {explicit!r}. This "
                    "process runs from a seat folder, where a relative path names "
                    "a different, empty database.")
            # abspath, not resolve(): see web.db.set_db_path for why.
            path = Path(os.path.abspath(explicit))
        return str(path)
    env_db = os.environ.get("AGENT_CHAT_DB")
    if env_db:
        if not Path(env_db).is_absolute():
            raise ValueError(
                f"AGENT_CHAT_DB must be an absolute path; got {env_db!r}. "
                f"It is inherited by agents launched from their own seat "
                f"folders, so a relative path silently points each one at a "
                f"different, empty database. Export a resolved path "
                f"(web.db.set_db_path() does this for you), or pass --db-path.")
        if not Path(env_db).parent.is_dir():
            raise ValueError(
                f"AGENT_CHAT_DB points into a folder that does not exist: "
                f"{env_db!r}. It is probably stale (repo moved?) — restart the "
                f"shell or CLI that exported it, or pass --db-path.")
        return env_db
    return str(REPO_ROOT / "db" / "chat.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    topic             TEXT NOT NULL,
    participants      TEXT NOT NULL,         -- JSON array of agent ids
    mode              TEXT NOT NULL,         -- 'turns' | 'continuous'
    max_turns         INTEGER NOT NULL,      -- per-agent cap
    current_turn      TEXT,                  -- agent id whose turn it is (turns mode)
    status            TEXT NOT NULL,         -- 'active' | 'complete'
    end_reason        TEXT,                  -- why it ended, if complete
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    preset            TEXT,                  -- sub-type / tone; see src/presets.py. NULL = paste-the-prompt flow
    kickoff_template  TEXT,                  -- rendered template body returned by get_kickoff()
    participant_personas TEXT,               -- JSON: {agent_id: {persona_slug, persona_name, persona_body}} (debate-mode casts)
    conv_type         TEXT NOT NULL DEFAULT 'debate',  -- structure: see orchestrator/conv_types.py
    participant_roles TEXT,                  -- JSON: {agent_id: <role>} — roles per type, see orchestrator/conv_types.py
    max_minutes       INTEGER,               -- wall-clock cap from created_at; NULL = none (audit RT-21)
    publish           INTEGER NOT NULL DEFAULT 0  -- 1 = the sidecar may copy it to the public mirror (audit RT-07)
);

CREATE TABLE IF NOT EXISTS messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id  INTEGER NOT NULL REFERENCES conversations(id),
    sender           TEXT NOT NULL,          -- agent id, or 'system' for kickoff
    content          TEXT NOT NULL,
    signal           TEXT,                   -- optional: 'done', 'blocked', 'result'
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS personas (
    "group"      TEXT NOT NULL,          -- folder/group name (e.g. Unique-Personas)
    slug         TEXT NOT NULL,          -- file-stem style id (e.g. crypto-chad)
    name         TEXT NOT NULL,          -- display name
    tags         TEXT,                   -- JSON array
    category     TEXT,
    subcategory  TEXT,
    body         TEXT NOT NULL,          -- the personality card prompt body
    avatar_mime  TEXT,                   -- uploaded avatar's image/* type (NULL = none)
    avatar_data  TEXT,                   -- uploaded avatar, base64 (see web/avatars.py)
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY ("group", slug)
);

CREATE INDEX IF NOT EXISTS idx_personas_updated ON personas(updated_at);

-- AgentBattleground: a debate captured from a real webpage that an agent
-- argues in. Local-only — deliberately NOT carried by the Fly sidecar sync.
CREATE TABLE IF NOT EXISTS battleground_arenas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL,          -- page the debate lives on
    site          TEXT NOT NULL,          -- adapter label; see KNOWN_SITES in web/api/battleground.py
    title         TEXT NOT NULL,          -- thread / page title
    thread        TEXT NOT NULL,          -- JSON array of captured posts
    stance        TEXT,                   -- operator brief: which side to argue
    reply_to      TEXT,                   -- captured post id the operator picked (NULL = agent's choice)
    agent_id      TEXT,                   -- CLI assigned to this arena (NULL = any)
    persona_slug  TEXT,
    persona_name  TEXT,
    persona_body  TEXT,                   -- snapshot of the card at capture time
    disclosure    TEXT,                   -- the AI-disclosure line the panel appends; '' or NULL = off (audit RT-22)
    status        TEXT NOT NULL,          -- 'open' | 'closed'
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS battleground_drafts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    arena_id      INTEGER NOT NULL REFERENCES battleground_arenas(id),
    agent_id      TEXT NOT NULL,
    reply_to      TEXT,                   -- captured post id answered (NULL = top level)
    content       TEXT NOT NULL,          -- what the agent wrote
    rationale     TEXT,                   -- agent's private note to the operator
    status        TEXT NOT NULL,          -- 'pending' | 'approved' | 'rejected' | 'posted'
    verdict_note  TEXT,                   -- operator feedback (revision request / reason)
    posted_text   TEXT,                   -- text that actually went on the page
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bg_arenas_status ON battleground_arenas(status, id);
CREATE INDEX IF NOT EXISTS idx_bg_drafts_arena ON battleground_drafts(arena_id, id);
"""

# Columns added after the initial schema: (table, column, ddl). ensure_schema()
# applies each one only when PRAGMA table_info lacks the column, so a file from
# any older build upgrades in place.
MIGRATIONS = (
    ("conversations", "preset",           "ALTER TABLE conversations ADD COLUMN preset TEXT"),
    ("conversations", "kickoff_template", "ALTER TABLE conversations ADD COLUMN kickoff_template TEXT"),
    ("conversations", "participant_personas", "ALTER TABLE conversations ADD COLUMN participant_personas TEXT"),
    # NOT NULL + DEFAULT is the backfill: every row that predates the column
    # becomes a 'debate', which is what all of them were.
    ("conversations", "conv_type",
     "ALTER TABLE conversations ADD COLUMN conv_type TEXT NOT NULL DEFAULT 'debate'"),
    ("conversations", "participant_roles",
     "ALTER TABLE conversations ADD COLUMN participant_roles TEXT"),
    ("conversations", "max_minutes",
     "ALTER TABLE conversations ADD COLUMN max_minutes INTEGER"),
    # Publishing is opt-in (audit RT-07), but every row that predates the column
    # was already being mirrored, so the backfill is 1: nothing public goes
    # private and nothing private goes public. The DEFAULT also stays 1 on a
    # migrated file, which is why seed_conversation() always writes the column.
    ("conversations", "publish",
     "ALTER TABLE conversations ADD COLUMN publish INTEGER NOT NULL DEFAULT 1"),
    ("battleground_arenas", "reply_to", "ALTER TABLE battleground_arenas ADD COLUMN reply_to TEXT"),
    ("battleground_arenas", "disclosure", "ALTER TABLE battleground_arenas ADD COLUMN disclosure TEXT"),
    ("personas", "avatar_mime", "ALTER TABLE personas ADD COLUMN avatar_mime TEXT"),
    ("personas", "avatar_data", "ALTER TABLE personas ADD COLUMN avatar_data TEXT"),
)

# Columns the sidecar sync carries (scripts/db_sync.py) and /api/ingest accepts
# (web/db.py). Order is the wire order. The battleground tables are absent on
# purpose: captured third-party content never reaches the public mirror.
CONV_COLUMNS = (
    "id", "topic", "participants", "mode", "max_turns",
    "current_turn", "status", "end_reason", "created_at", "updated_at",
    "preset", "kickoff_template", "participant_personas",
    "conv_type", "participant_roles", "max_minutes",
)
# conversations columns that never sync: the mirror only ever holds published
# rows, so it has no use for the flag (audit RT-07).
CONV_LOCAL_COLUMNS = ("publish",)
MSG_COLUMNS = (
    "id", "conversation_id", "sender", "content", "signal", "created_at",
)
# "group" is a SQL reserved word: generated SQL must quote every identifier
# (PERSONA_COLS_SQL), a bare ",".join emits `group` unquoted and fails to parse.
PERSONA_COLUMNS = (
    "group", "slug", "name", "tags", "category", "subcategory",
    "body", "avatar_mime", "avatar_data", "created_at", "updated_at",
)
# The weekly content job's holding group: its rows never sync (audit RT-22,
# see orchestrator/personas.py PENDING_GROUP).
PENDING_PERSONA_GROUP = "Pending-Review"
PERSONA_COLS_SQL = ",".join(f'"{c}"' for c in PERSONA_COLUMNS)

# messages.sender: an agent id (`codex`, `claude-code-2`) or `system`. The web
# UI puts it in class names and the mirror takes it from /api/ingest, so it is
# a token, never markup (audit RT-18). Checked at MCP startup and at ingest.
SENDER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
# messages.signal: NULL or one of these (send_message refuses anything else).
SIGNALS = ("done", "blocked", "result")

# battleground_arenas.status / battleground_drafts.status values.
ARENA_OPEN = "open"
ARENA_CLOSED = "closed"

DRAFT_PENDING = "pending"
DRAFT_APPROVED = "approved"
DRAFT_REJECTED = "rejected"
DRAFT_POSTED = "posted"
# Verdicts the operator can hand down on a draft. 'rejected' means "not this
# one" (with an optional note the agent reads as a revision brief); 'posted'
# means the text made it onto the page.
DRAFT_VERDICTS = (DRAFT_APPROVED, DRAFT_REJECTED, DRAFT_POSTED)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create any missing table or index, then apply missing column migrations.

    Idempotent, and safe when two processes boot at once: both may see a column
    missing, and the loser's ALTER fails with "duplicate column name", which
    means the column is there, so it is ignored."""
    conn.executescript(SCHEMA)
    for table, column, ddl in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column in cols:
            continue
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc):
                raise


class ClosingConnection(sqlite3.Connection):
    """A connection that ``with conn:`` also closes.

    sqlite3's own ``__exit__`` commits or rolls back and leaves the connection
    open, so every ``with connect() as conn:`` in this app leaked a handle
    until the garbage collector found it — a ``ResourceWarning`` from Python
    3.13 on (audit RT-37). Pass ``factory=ClosingConnection`` to
    ``sqlite3.connect``."""

    def __exit__(self, *exc):
        try:
            return super().__exit__(*exc)
        finally:
            self.close()


@contextmanager
def write_txn(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` … ``COMMIT`` (``ROLLBACK`` on an exception).

    Takes the write lock up front, so everything read inside the block is still
    true when the block writes: no other process can commit in between. Needs an
    autocommit connection (``isolation_level=None``), which every caller uses.
    A ``return`` inside the block commits whatever was written."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def complete_conversation(conn: sqlite3.Connection, cid: int, reason: str) -> bool:
    """Move a conversation from ``active`` to ``complete``, once.

    True only for the caller whose UPDATE made the change, so the send path, the
    web UI's Stop and the CLI's ``stop`` can each fire the ``complete`` delivery
    on True and never deliver twice. A row that is already complete is left
    byte-identical (``end_reason`` and ``updated_at`` included)."""
    cur = conn.execute(
        "UPDATE conversations SET status = 'complete', end_reason = ?, "
        "current_turn = NULL, updated_at = ? WHERE id = ? AND status = 'active'",
        (reason, datetime.now(timezone.utc).isoformat(), cid),
    )
    return cur.rowcount == 1
