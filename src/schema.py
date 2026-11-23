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
"""

from __future__ import annotations

import sqlite3

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
    participant_roles TEXT                   -- JSON: {agent_id: <role>} — roles per type, see orchestrator/conv_types.py
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
    ("battleground_arenas", "reply_to", "ALTER TABLE battleground_arenas ADD COLUMN reply_to TEXT"),
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
    "conv_type", "participant_roles",
)
MSG_COLUMNS = (
    "id", "conversation_id", "sender", "content", "signal", "created_at",
)
# "group" is a SQL reserved word: generated SQL must quote every identifier
# (PERSONA_COLS_SQL), a bare ",".join emits `group` unquoted and fails to parse.
PERSONA_COLUMNS = (
    "group", "slug", "name", "tags", "category", "subcategory",
    "body", "avatar_mime", "avatar_data", "created_at", "updated_at",
)
PERSONA_COLS_SQL = ",".join(f'"{c}"' for c in PERSONA_COLUMNS)

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
