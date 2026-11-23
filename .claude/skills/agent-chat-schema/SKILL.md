---
name: agent-chat-schema
description: Use when changing the Roundtable SQLite schema — adding/renaming/dropping a column or table, adding a migration, or touching db_init()/db_connect() pragmas. The schema is declared once, in src/schema.py, and is the contract between processes. Triggered by work on src/schema.py, SCHEMA, MIGRATIONS, the synced *_COLUMNS lists, db_init()/ensure_schema(), "add a column", "migrate the DB", "new table".
---

# Roundtable schema changes

The DB **is** the contract between processes: the MCP server, the web UI, the
seeder, the persona registry and the sync sidecar all open the same SQLite-WAL
file. There is no ORM; there is **one module**, `src/schema.py` (stdlib only),
and every process boots a file through `schema.ensure_schema(conn)`.

## What `src/schema.py` holds

| Name | What |
|:---|:---|
| `SCHEMA` | DDL for all five tables + indexes |
| `MIGRATIONS` | `(table, column, ddl)` triples for columns added later |
| `CONV_COLUMNS` / `MSG_COLUMNS` / `PERSONA_COLUMNS` (+ `PERSONA_COLS_SQL`) | what the sidecar sync carries; read by `/api/ingest` *and* `scripts/db_sync.py` |
| `ARENA_*` / `DRAFT_*` / `DRAFT_VERDICTS` | battleground status values |
| `ensure_schema(conn)` | `executescript(SCHEMA)` + each missing migration; a concurrent "duplicate column name" is ignored |

Migrations are gated on `PRAGMA table_info({table})` so they stay idempotent:

```python
("conversations", "preset", "ALTER TABLE conversations ADD COLUMN preset TEXT"),
```

> [!IMPORTANT]
> `CLAUDE.md` tells you to update `start_conversation.py` and
> `inspect_conversations.py` on a schema change. **That guidance is stale** —
> neither declares schema. `start_conversation.py` is argparse-only and delegates
> to `orchestrator.seeding`; `inspect_conversations.py` only has `connect()` plus
> raw SELECT/UPDATE. Update them only if you changed a *column they query*.

## Checklist for a schema change

1. **Additive only, by default.** New columns are safe: add to `SCHEMA` in
   `src/schema.py` and append a `(table, column, ddl)` row to `MIGRATIONS` so
   existing `db/chat.db` files upgrade in place. Renames and drops need an explicit
   migration plan — SQLite can't drop a column on older versions, and every
   running CLI holds the old shape.
2. **Never declare DDL anywhere else.** `tests/test_conv_types.py` fails on a
   `CREATE TABLE` outside `src/schema.py`. If the column should reach the Fly
   mirror, add it to the matching `*_COLUMNS` tuple too (the same test pins the
   lists against the tables).
3. **Update every reader of the changed column** — `inspect_conversations.py`,
   `web/db.py` helpers, `orchestrator/export.py`, the SSE payload in
   `web/api/conversations.py`, and the `/api/ingest` + `/api/since` sync path
   (a column the sidecar doesn't carry won't reach the Fly mirror).
4. **Note it in `docs/CHANGELOG.md`.** Schema changes are always changelog-worthy.
5. **Verify against a real DB**, never a mock — the WAL multi-process behaviour
   is the thing under test:
   ```powershell
   .\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'src'); import agent_chat_mcp"
   .\.venv\Scripts\python.exe tests\test_web_readonly.py
   ```
   Then seed a `--max-turns 2` conversation against a **temp** DB and confirm it
   reaches `status='complete'`.

## Connection rules

WAL is mandatory (`PRAGMA journal_mode=WAL`) — two processes write the same file.
Connections use `timeout=10.0` and `isolation_level=None`. Parameterize every
query; no string-concatenated SQL.

Pragmas are **not** uniform today, which is worth knowing before you "fix" one:

| Site | Notes |
|:---|:---|
| `agent_chat_mcp.db_connect()` | the full set: WAL + `synchronous=NORMAL` + `foreign_keys=ON` |
| `web/db.py:_connect()` | WAL only, and **omits `isolation_level=None`** — deviates from CLAUDE.md |
| `seeding.py` / `personas.py` / `inspect_conversations.py` | WAL + `isolation_level=None` |

## Current shape

- **`conversations`** — `id`, `topic`, `participants` (JSON array), `mode`
  (`turns`|`continuous`), `max_turns`, `current_turn`, `status`
  (`active`|`complete`), `end_reason`, `created_at`, `updated_at`, `preset`,
  `kickoff_template`, `participant_personas` (JSON
  `{agent_id: {persona_slug, persona_name, persona_body}}`), `conv_type`
  (`NOT NULL DEFAULT 'debate'` — the default is the backfill for every
  pre-2026-08-11 row; validated against `orchestrator/conv_types.py`),
  `participant_roles` (JSON `{agent_id: 'moderator'|'debater'|'host'|'guest'}`).
- **`messages`** — `id`, `conversation_id` → conversations(id), `sender`,
  `content`, `signal` (`done`|`blocked`), `created_at`.
- **`personas`** — `"group"` (quoted — SQL reserved word), `slug`, `name`,
  `tags` (JSON), `category`, `subcategory`, `body`, `avatar_mime`, `avatar_data`
  (base64 upload), `created_at`, `updated_at`; `PRIMARY KEY ("group", slug)`.
  `personas.py`'s `_ensure_table()` calls `schema.ensure_schema()` itself —
  the registry is reachable without any server booting (debate.ps1 runs it as a
  script), so it can't rely on `db_init()` having run. Reads go through `_PERSONA_READ_COLS` (everything
  except `avatar_data`), so listing the roster doesn't haul the images.
- Indexes: `idx_messages_conv ON messages(conversation_id, id)`,
  `idx_personas_updated ON personas(updated_at)`.
