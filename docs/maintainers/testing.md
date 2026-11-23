# Testing and validation

> What each suite covers and how to validate a change by hand. Moved out of `AGENTS.md` verbatim on 2026-11-22 (audit RT-26) so every agent session doesn't load it; `AGENTS.md` keeps a one-line pointer.

## Testing & validation

Every file under `tests/` is pytest-compatible **and** standalone-runnable (`.\.venv\Scripts\python.exe tests\test_web_readonly.py`), so no test dep is pinned. Run them all after touching the web layer; `/smoke-test` does the whole checklist.

| Suite | Covers |
|:---|:---|
| `test_web_readonly.py` | auth + read-only middleware, orchestrate guard, **a bare URL renders as a link** (the optional `linkify-it-py` that silently 500'd every transcript) |
| `test_static_csp.py` | **Every HTML route, local and hosted, sends a nonce CSP** and carries no inline `<script>`, `<style>` or `on*=` handler; `/static` URLs serve immutable; JSON data blocks can't be closed by their data |
| `test_inspect_tail.py` | `inspect_conversations tail` completion guard |
| `test_topics.py` | topic→logo classification + tie-breaks |
| `test_model_personas.py` | AI-Models cards, reserved-group casting guard, Cast fallback |
| `test_battleground.py` | Arena bridge, capture scrubbing + merge, verdict gate, CORS, schema parity, launch-map ↔ `spawn-agents.ps1` parity, MCP loop, panel `ext`-alias guard |
| `test_persona_avatars.py` | Avatar validation, resolution order, edit-preserves-art, persona column parity `web/db.py` ↔ `scripts/db_sync.py` |
| `test_persona_explorer.py` | The read-only `/personas` explorer: excludes `AI-Models`, cover → avatar fallback + `PERSONA_MEDIA_URL`, server-side q/group/cat/tag/sort, detail page, `.md` metadata round-trip, **the `.zip` re-imports through `/api/personas/import` with its avatar**, every route serves on the read-only demo |
| `test_seats.py` | Agent-id grammar (`codex-2`), per-seat config paths, Codex `CODEX_HOME`, **the seat root outside the repo** (Python `seat_root()` == PowerShell `Get-SeatRoot`), `--materialize` keeping local state, rewriting the launcher and trusting each folder once, templates with no machine path, **seat 2 from a tool that keeps no seat-1 file** (Claude Code's user-scope entry; Codex's global config), parity across `preflight._CHECKS` ↔ `SUPPORTED_CLIS` ↔ `add_agent_seat.SHAPES` ↔ `Resolve-AgentSeat` |
| `test_availability.py` | CLI detect-vs-declare, `plan_seats` round-robin, the Settings CLI-tools tab + its legacy `/setup` redirect, `/orchestrate` filtering, demo strip, two-group rail, `CLI_BINARIES` ↔ `spawn-agents.ps1` parity, **lifecycle scripts match processes by command line not `ExecutablePath`** |
| `test_debate_launcher.py` | `debate.ps1 -Format podcast` and `-Format collaborate` run for real with `-DryRun`: host in seat one + `--host`, topic and guest count from `Podcast-Topics.md`; a collaboration's task, seat count and preset from `Collaboration-Topics.md`, facilitator first, no personas unless asked, `-Preset` override; debate seed line unchanged. **Skips without the project venv**, so CI skips it |
| `test_topic_libraries.py` | `docs/chat-topics/`: `Debate-Topics.md` and `Collaboration-Topics.md` keep the shape `debate.ps1` parses, seat counts inside each type's bounds, every collaboration `- Preset:` is a real collaborate preset, and the launcher defaults to `Debate-Topics.md` (`test_podcast_topics.py` covers the podcast file) |
| `test_media_prompts.py` | Image/audio prompt builders + the `/prompts/{kind}.md` route |
| `test_orchestrate_form.py` | `/orchestrate`'s JS (`static/js/orchestrate.js`) ↔ its markup, by string invariants — lookups resolve, conditional controls are null-guarded, no document-scope bulk query, bulk-hidden classes stay in their container. **Does not run the JS.** |
| `test_orchestrate_browser.py` | `/orchestrate`'s JS **run in headless Chromium** via Playwright, no server (`page.route` serves the page and captures the POST): derived seat ids, host picker visible, per-tool cap refused before POST, format clamping, the custom-card payload, approvals left on by default and the custom-card warning. **Skips without Playwright** — CI installs `requirements-dev.txt` |
| `test_spawn_allowlist.py` | The launch command a seat gets: `/orchestrate`'s approvals box renders unticked; the real `orchestrate-debate.ps1 -DryRun` plan gives Claude Code seats `--allowedTools mcp__roundtable` **after** the prompt and **never** gives any seat a blanket bypass flag; every seat `Set-Location`s into its folder outside the repo; Antigravity gets `--sandbox --settings` deny rules. Needs `pwsh` |
| `test_mcp_turns.py` | Turn rotation, the **per-agent cap rule** (all seats spent, not the first), spent-seat skipping, out-of-turn rejection, `done`/`blocked`/`result`, continuous mode, **transitions**: polls leave a finished row byte-identical, a Stop from another thread waits for an in-flight send and `complete` is delivered once, the CLI stop, the arena claim race |
| `test_mcp_stdio.py` | The server over real stdio: the 2026-07-28 protocol negotiated, the 2025 handshake still served, two server processes finishing a seeded run |
| `test_notifications.py` | The notify sink over a **real loopback HTTP server**: ntfy's text body + templated headers, the Discord/Slack one-key difference, seeding firing `started`, a dead endpoint not failing a seed, config merge preserving hand-written sinks |
| `test_maintain_app.py` | The nightly backup script run for real against temp paths: a good night checks integrity and prunes only its own `chat-YYYYMMDD-HHMMSS.db` copies; a failed one exits 1, leaves no bad copy and prunes nothing. Needs `pwsh` + the project venv |
| `test_delivery.py` | Delivery sinks; **folder output == `export.zip`, byte for byte**; off-unless-configured; failure isolation; all three completion paths call `deliver()` |
| `test_db_sync_watermarks.py` | Sidecar watermarks: push cursor on the **local** clock, pull cursor on the server's; a local edit behind `server_time` still pushes; the pulled-row echo terminates; `--force-push`; **`config/sync-exclude.json` keeps a conversation off the public mirror without deleting it locally** |
| `test_conv_types.py` | Seat rules, the `conv_type` backfill, **one schema declaration** (no `CREATE TABLE` outside `src/schema.py`), migrated DB == fresh DB, the synced column lists == the real tables, every `INSERT`'s columns exist, export Type/Role rows, the `signal='result'` deliverable, sub-type presets, and that the launch prompt stays role-agnostic |

Beyond that, validation is manual: import the server cleanly · `python -m json.tool` any `.mcp.json` you touch · seed a `--max-turns 2` conversation end-to-end and confirm the row reaches `status='complete'` · watch a live exchange append over SSE. New tests use `pytest` with an isolated tmp `db/chat.db` — **do not mock SQLite**, the WAL multi-process behavior is the thing under test.

---

<p align="center">
  <a href="README.md">↩ Maintainer rules</a> ·
  <a href="../../AGENTS.md">AGENTS.md</a> ·
  <a href="../README.md">Docs home</a>
</p>
