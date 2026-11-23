# The database and the MCP server

> Read before changing `src/schema.py`, any SQL, or `src/agent_chat_mcp.py`. Moved out of `AGENTS.md` verbatim on 2026-11-22 (audit RT-26) so every agent session doesn't load it; `AGENTS.md` keeps a one-line pointer.

## SQLite layer

> [!TIP]
> The `agent-chat-schema` skill carries this checklist plus current table shapes; it auto-loads when you touch a schema file.

The DB is the **contract** between processes, and it is declared **once**, in `src/schema.py` (stdlib only, since 2026-11-22): `SCHEMA` (all five tables + indexes), `MIGRATIONS` (`(table, column, ddl)` triples), the synced column lists `CONV_COLUMNS` / `MSG_COLUMNS` / `PERSONA_COLUMNS` (read by both `/api/ingest` and `scripts/db_sync.py`), and the `ARENA_*` / `DRAFT_*` status values. Every process boots a file through `schema.ensure_schema(conn)`, which is idempotent and tolerates two processes migrating at once. **Never declare DDL anywhere else** — `tests/test_conv_types.py` fails on a `CREATE TABLE` outside `schema.py`, and pins the column lists and every `INSERT`'s column names against the real tables.

Any schema change requires: additive columns (renames/drops need a migration plan) · a `MIGRATIONS` row so existing `db/chat.db` files upgrade in place · the column in the matching `*_COLUMNS` tuple if it should reach the mirror · updating every **reader** of a changed column — `inspect_conversations.py`, the `web/db.py` helpers, `orchestrator/export.py`, the SSE payload, and the `/api/ingest` + `/api/since` sync path (a column the sidecar doesn't carry never reaches the Fly mirror) · a CHANGELOG note. `start_conversation.py` and `inspect_conversations.py` declare no schema.

**A conversation leaves `active` only through `schema.complete_conversation()`** — a conditional `UPDATE … WHERE status='active'` that returns True only for the caller that moved it. The send path, the web UI's Stop and the CLI's `stop` all use it and fire `complete` only on True, so a race delivers once and a finished row is never rewritten (polls used to re-close it on every call). A check-then-write that another process could interleave runs inside `schema.write_txn(conn)` (`BEGIN IMMEDIATE`): `send_message`'s check → insert → advance → close, and the battleground thread merge. The arena claim is a conditional `UPDATE … AND agent_id IS NULL`. Pinned by `tests/test_mcp_turns.py` (since 2026-11-22, audit RT-09).

`messages.sender` and `messages.signal` are tokens, not text: `schema.SENDER_RE` / `schema.SIGNALS` are checked by the MCP server (`--agent-id` at startup, `signal` on send) and by `/api/ingest`, and the renderers still `html.escape` both where they become class names (audit RT-18). Other rules: WAL mode is mandatory — two processes write the same file. Connections use `isolation_level=None` and `timeout=10.0`; the write paths use explicit `BEGIN`/`COMMIT`/`ROLLBACK`, which is only correct in autocommit mode. Parameterize all queries. **One rule picks the database file: `schema.resolve_db_path()`** — `--db-path` > `$AGENT_CHAT_DB` > `<repo>/db/chat.db`, always absolute, an env value that is relative or points into a missing folder refused, and the MCP server refuses a relative `--db-path` too (its cwd is a seat folder). It is the only code that reads `$AGENT_CHAT_DB` (a test pins that; since 2026-11-22, audit RT-20). The process that owns a database tells `orchestrator.personas` directly: **`web.db.set_db_path()` sets `personas.DB_PATH` and exports `$AGENT_CHAT_DB`** (for the agents it spawns), and the MCP server exports it in `main()` and points the persona tools at its own `DB_PATH`, so a custom `--db-path` never reads conversations from one DB and personas from another.

## MCP server (`agent_chat_mcp.py`)

- Use `@mcp.tool()`; `get_my_turn`, `send_message`, `get_conversation_status` are the reference shape. Return types are Pydantic models — match the existing `model_config = ConfigDict(...)` patterns.
- `AGENT_ID` and `DB_PATH` are module globals populated in `main()` before `mcp.run()`. Don't read them at import time.
- **Turn payloads carry a history delta, not the transcript** (since 2026-11-22, audit RT-13). `get_my_turn` / `wait_for_turn` take `history` (`delta` default, `full`, `none`) and `since_id`; the delta is the other participants' messages above the session's mark in `_SEEN`, which `_reply()` advances only when a payload is actually returned — a `wait_for_turn` timeout carries no history and marks nothing, and a blind-first payload with hidden messages marks nothing either, so a reveal is never lost. `send_message` returns a delta too.
- **A session is bound to one conversation.** Every tool resolves it through `my_conversation()`, never `get_latest_conversation()` directly: the first call binds the newest conversation containing `AGENT_ID`, later calls stay on it (finished or not), and only `get_kickoff()` rebinds. "Newest containing me" alone let a second run on the same seat hijack the first (audit RT-08). The other half lives in `seed_conversation()`: a seat already in an **active** run is refused (`seat busy`), and `POST /api/orchestrate` asks `seeding.busy_seats()` before preflight (409 `seat_busy`). Pinned by `tests/test_mcp_turns.py` and `tests/test_conv_types.py`.
- New tools should be idempotent and read-mostly. Mutations belong in `send_message` or an explicitly-named write tool.
- **The per-agent cap ends a run when EVERY seat is spent, not the first.** `evaluate_stop()` used to return on the first agent at `max_turns`, which in a round-robin is always agent 1 — every later seat lost a turn, and a lead seated late lost the turn it was briefed to post `signal='result'` on. `next_turn_agent()` **skips spent seats** and returns None when nobody is left; the two are inseparable, since the stop rule alone parks the pointer on a finished agent and deadlocks the rotation. Pinned by `tests/test_mcp_turns.py`.

---

<p align="center">
  <a href="README.md">↩ Maintainer rules</a> ·
  <a href="../../AGENTS.md">AGENTS.md</a> ·
  <a href="../README.md">Docs home</a>
</p>
