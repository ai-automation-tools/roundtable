# Changelog

All notable changes to this repository. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

Earlier months: [October 2026](changelog/2026-10.md) · [September 2026](changelog/2026-09.md) · [August 2026](changelog/2026-08.md) · [July 2026](changelog/2026-07.md) · [June 2026](changelog/2026-06.md) · [May 2026](changelog/2026-05.md) — the [archive](changelog/README.md) holds one file per month.

## 2026-11-23 (latest)

### Added — a weekly backup copy on another disk

- `maintain-app.ps1 -OffDiskDir <folder>` copies that night's verified backup to another disk once a week, checks the hash, and keeps the newest 8. A missing or full disk fails the run (exit 1 and one alert), like a failed backup. Register it with `register-app-tasks.ps1 -OffDiskDir`.
- `scripts/run-hidden.vbs` now quotes extra arguments that contain a space.
- Audit item RT-12.

### Added — extension releases

- **`extension-v0.2.0`** is the first GitHub release: the AgentBattleground extension as a Chrome zip and a Firefox zip, for loading without a clone. `.github/workflows/extension-release.yml` publishes the next one when the version in both manifests changes on `main`.
- The logon task (`register-startup-task.ps1`) now starts through `scripts/run-hidden.vbs`, like the other app tasks, so no console flashes at sign-in. Re-run the script to pick it up.
- Audit item RT-32.

### Changed — CI must pass before a merge into `main`

- A repo ruleset (**Require CI**) makes `test`, `test-linux` and `lint` required checks on `main`; a PR with failing CI can't be merged.
- `ci.yml` runs on every PR again, including `homepage/`-only ones, so the required checks always report. Pushes to `main` still skip a `homepage/`-only change.
- GitHub now deletes a PR's branch when it merges.
- Audit items RT-11 and RT-32 (branch cleanup).

## 2026-11-22

### Added — choose the model for each seat

- **`/orchestrate`** has a *model* box under each chair; **`debate.ps1`** takes `-Model claude-code=sonnet,codex=gpt-5.4-mini` (a bare CLI name covers its seats, `claude-code-2=…` one seat). The seat launches with `--model <name>`. Blank keeps the CLI's default.
- A model name may only contain the characters model ids use; anything else is refused before seeding.
- Audit item RT-36.

### Fixed — docs that named a dead host, wrong counts and one machine's paths

- `/deploy-fly` and the bug template point at `roundtable-demo.ai-automation-tools.dev`; the old `agent-chat-demo` host answers 400.
- The README calls the app Roundtable (AgentBattleground is the extension) and its badge shows the MCP Python SDK it pins (2.3, not 1.27).
- `.env.example` covers every `AGENT_CHAT_*` setting, marking the five read only from the real environment.
- `tests/README.md` lists every suite; the setup log uses `<repo>` instead of an absolute path; a private file reference left `AGENTS.md`.
- Audit item RT-30.

### Changed — the mirror and the persona registry say what they do

- **Hosted mirror:** the home page's launch buttons read *Run a debate locally* (and podcast, collaboration), since they open the run-it-yourself explainer, and *+ New conversation* is gone.
- **Persona explorer:** after a search the page title reads *N of M — Browse* and focus moves to the result count, so a screen reader announces it; on a phone the three filters stack instead of truncating.
- **Registry:** the rail's *Persona registry* entry has its own icon (it shared *Personas*'), and the registry's header link is *← Roundtable*, same tab, back to the demo.
- **Homepage:** 76 seed personas, not 62 — the number a fresh clone imports, now checked by a test.
- Audit item RT-42.

### Fixed — database handles are closed; a path with an apostrophe launches

- **`with connect() as conn:` now closes the connection.** sqlite3's own `with` only commits, so every request, tool call and sync pass left a handle for the garbage collector. Python 3.13+ warns about each one; the suite produced 881 warnings and now produces none.
- **Seat windows launch from a folder named like `Mike's Projects`.** The launch command wrapped paths in `'…'` without escaping the apostrophe, so the command line broke.
- Audit item RT-37.

### Fixed — `wait_for_turn` fits inside every CLI's tool timeout

- The Codex config snippets set `tool_timeout_sec = 330`. `wait_for_turn` may block for 300 s and Codex abandons an MCP call at 300 s by default, so the longest wait could surface as a tool error. **If you registered Codex before this change, add that line to `[mcp_servers.roundtable]` in `~/.codex/config.toml`.** OpenCode v2 (12 h) and Claude Code have no short limit; the 180 s default fits all of them.
- The seat role docs' tool table said `wait_for_turn(timeout_seconds=60)`, contradicting the 180 s default two sections up; regenerated.
- Audit item RT-35.

### Changed — one copy of the process-flow diagram

- The generated diagram is committed once, in `docs/diagrams/`. The *Homepage* workflow copies it into the published site at deploy time and now also runs when the diagram changes. `build_diagram.py` no longer writes `homepage/diagram/`, and `--check` no longer compares a second copy (which, lacking `-text`, read as drift on a CRLF checkout).
- Audit item RT-33.

### Fixed — the hosted mirror stops describing its own container

- **Reads about the local machine are `404` on the mirror:** `/api/setup` (it listed container paths and `/root/.claude.json`), `/api/settings/*` and `/api/notifications`. Writes there are still the read-only `403`.
- The web UI's startup log prints `public read-only: on|off` next to `basic auth`.
- Audit item RT-31.

### Changed — the app's fonts match the homepage and the org's other sites

- **Inter for text, JetBrains Mono for code and numerals**, instead of IBM Plex Sans and IBM Plex Mono. One font stylesheet per page: the persona console no longer `@import`s a second one.
- Audit item RT-44.

### Changed — the docs every agent loads are a quarter of the size

- **`AGENTS.md` is 13 KB, down from 58 KB.** Every agent session, and every Claude Code seat, loads it. The per-area rules (database and MCP server, web UI, AgentBattleground, delivery, conversation types and personas, testing, docs/git/deploy) moved verbatim to [`docs/maintainers/`](maintainers/README.md), one file per area; `AGENTS.md` keeps the rule most often broken in each area and a link.
- **The roadmap lists open work only** (73 KB, from 279 KB). Finished phases and ticked items moved verbatim to [`docs/roadmap/`](roadmap/README.md). Items are still closed in place; a later trim moves them.
- **The changelog holds the current month** (51 KB, from 450 KB); each earlier month is a file in [`docs/changelog/`](changelog/README.md).
- Audit item RT-26.

### Added — a hard stop: close the seat windows, a time limit, a kill switch

- **Stop can close the windows.** Each seat window `/orchestrate` or `debate.ps1` opens records its PID and start time when it starts. After **Stop**, the page offers to close those windows; only a process with that PID *and* that start time is ended, so a reused PID is never touched. Stopping alone only reaches an agent at its next MCP call.
- **Time limit.** `--max-minutes N` on `start_conversation.py`, or *Time limit* on `/orchestrate`, ends the run with `time limit (N min)` on the first agent call after N minutes. **Schema:** new nullable `conversations.max_minutes` (migrated in place, synced to the mirror; deploy the web app before restarting the sidecar, which the merge does).
- **Kill switch.** While `config/NO_SPAWN` exists, nothing spawns: `/orchestrate` refuses an auto-spawn launch before seeding, and the PowerShell launchers refuse before opening a window.
- Audit item RT-21.

### Fixed — transcripts paint in half the time on a phone

- **Nothing blocks first paint.** highlight.js and its theme load only when a transcript has a code block, after the page renders, with integrity hashes; the web-font stylesheet is preloaded and applied when it arrives. On a throttled phone profile a transcript's largest paint went from 3.3 s to 1.3 s.
- **HTML is compressed.** The hosted mirror's edge already did this; a local or tailnet instance sent ~270 KB per transcript raw. Live streams are not compressed.
- **The 30-second poll is ~2% of its old size.** The chrome asks `/api/conversations` for just the four fields it shows, and an unchanged answer comes back as a `304`.
- Audit item RT-41.

### Fixed — page structure a screen reader can navigate

- **One `h1` per page and no skipped heading levels.** The persona explorer, persona manager, orchestrate, settings, battleground and extension pages and both 404s had no `h1`; a conversation had one per cast card; the home page jumped from `h2` to `h4`.
- **Messages and persona cards nest their headings under the page's.** A message's `# Heading` now renders beneath its speaker, a card's beneath its section, at the same visual size as before.
- **The transcript is a live log.** Each message is an `article` named by its speaker, and messages that arrive over the stream are announced.
- **Form fields have names.** The orchestrate title and brief, the format and sub-type choices, and the notification and delivery settings fields are labelled. Lighthouse accessibility is 100 on the home page, `/orchestrate`, the notifications tab and a long transcript.
- Audit item RT-40.

### Fixed — the AgentBattleground side panel works with a screen reader

- Status lines (capture, arena, hand-off, auto re-capture, settings) are announced as they change. The bridge indicator says *Connected* or *Offline* in words, not only in colour, and the settings toggle has a name and reports whether it's open.
- The disclosure-line field and the auto re-capture seconds field have their own labels; the seconds field no longer sits inside the checkbox's label.
- Contrast: white-on-accent buttons use a darker orange (5.4:1), accent text a per-scheme shade, and hint text the muted colour instead of faded ink. Lighthouse accessibility is 100 on the panel page in dark and light.
- Reload the extension to pick it up. Audit item RT-43.

### Changed — persona zips and covers leave the repo; every seed card imports

- **The bulk persona zips (89 MB) and cover PNGs are no longer tracked.** The zips duplicated the cards beside them; the covers are served from the roundtable-personas site, which already has all 22. Nothing at runtime read either. `.gitignore` now keeps them out. They are still in git history; rewriting history is a separate decision.
- **The seed importer reads every depth of `agents/Debate-Agents/`** and finds all 76 cards (it read one level and found 11). A card's group is its nearest folder that isn't a dated card folder, so `AI-Library-Imports/Celebrities/x_2026-06-23/x.md` imports as `Celebrities`.
- **A fresh clone can cast a random debate.** The web UI imports the seed cards on start when the registry has nothing castable, and leaves any existing registry alone.
- `/orchestrate`'s random cast draws from every castable card directly; it used to try the `Unique-Personas` group first, which holds none.
- Audit item RT-23.

### Fixed — a locked database no longer freezes the web UI

- **Route handlers run in Starlette's threadpool.** They were `async def` around blocking SQLite, so a Stop waiting out the 10 s busy timeout on a locked DB froze every other request and every live transcript; measured, an unrelated page load waited 10.7 s. 50 of 52 handlers are now plain `def`; the SSE stream and `/api/ingest` stay async and hand their DB work to the threadpool. Two settings saves can now run at once, so the delivery-config writers share a lock.
- **Fewer queries.** The conversation rail and the homepage count messages with one `GROUP BY` instead of a `COUNT` per conversation; the turn engine counts each seat's messages in one query, once per check. A seat in `wait_for_turn` reads a one-row fingerprint each second and only re-reads the transcript when something changed.
- Audit item RT-28.

### Changed — the MCP tools cost each seat a quarter of the text

- **Tool descriptions are short.** Every seat reads all of them at session start, and they came to ~13.5k characters. Each is now under 400 (2.9k in all), with the essentials kept: call `get_kickoff` first, the `signal` meanings, that a timeout loses nothing, that captured threads and other agents' messages are not instructions. The long docstrings stay in the code for maintainers.
- **`get_my_turn` and `wait_for_turn` no longer claim to be read-only.** A poll can close a run whose stop condition is met. They now carry the same hints as `send_message`.
- **New `list_persona_groups` tool**: the group names with a card count each. `list_personas`' `group` help used to suggest `Unique-Personas`, which holds no cards.
- Audit item RT-25.

### Fixed — the sync sidecar survives a big registry, a bad pull and a late commit

- **`/api/since` takes a `POST` with a JSON body**, and `scripts/db_sync.py` sends one. The known-id list rode in the query string, and past ~1,300 persona keys the server refused the request head, so every tick failed. `GET` still works for an older sidecar. Restart the sidecar after pulling (the mirror deploys with the merge).
- **A failed pull no longer stops the push.** It used to abort the tick, so one persistent pull error froze the mirror.
- **Network surprises are retried, not fatal.** A reset while reading an error body, a non-JSON reply and any unexpected exception now log and back off (doubling up to 5 minutes) instead of ending the hidden daemon.
- **A late commit still syncs.** Writers stamp `updated_at` before waiting on the write lock, so a row could commit behind the push cursor and never ship. The push re-reads 15 s behind the cursor and skips rows it already sent (`recent_pushed` in the state file).
- **Pushes are paged** (500 messages, 25 personas a page, conversations first), so a `--force-push` of a large DB fits under `/api/ingest`'s 32 MB cap.
- Audit item RT-15.

### Changed — CI runs once per PR, on Linux too, and lints

- **Pushes run CI only on `main`.** A PR's branch is covered by `pull_request`; running on its pushes as well doubled every PR's CI.
- **New `test-linux` job**: the suites on Ubuntu / Python 3.14, the runtime the hosted mirror uses (the existing `test` job is Windows / 3.12). **New `lint` job**: `ruff check --select E9,F`. Both gate the Fly deploy with `test`. The 15 existing findings (unused imports, one unused variable) are fixed.
- 20-minute timeouts (the default was six hours), every action pinned to a commit SHA, and Dependabot now offers action major bumps.
- The persona explorer's *Newest* sort breaks ties by slug, so cards imported in one batch keep a stable order.
- Audit item RT-29.

### Changed — maintainer skills caught up with the code

- The three skills installed from `agent-skills` (`agent-chat-conv-types`, `agent-chat-delivery`, `agent-chat-run-triage`) are re-installed from its `main`; the copies here had fallen two upstream revisions behind.
- `agent-chat-add-cli` documents the spawn registry's real `Allow` / `Deny` fields and the no-bypass rule instead of the removed `SkipPerm`; `agent-chat-schema` lists `SENDER_RE` / `SIGNALS` and `resolve_db_path`; `docs/UPSTREAMS.md` records the containment flags each CLI is launched with rather than bypass flags; the OpenCode page drops a stale `--auto` note.
- Audit item RT-24 (repo side).

### Fixed — one rule for which database a process opens; the MCP server's persona tools follow `--db-path`

- **`schema.resolve_db_path()` replaces five copies** (MCP server, web UI, `inspect_conversations`, seeding, personas, delivery): `--db-path` > `$AGENT_CHAT_DB` > `<repo>/db/chat.db`, always absolute. Only the MCP server's copy used to check the environment value; now every process refuses a relative `AGENT_CHAT_DB` or one pointing into a missing folder.
- **The MCP server's `list_personas` / `get_persona` read the server's own database.** With `--db-path X` they followed `$AGENT_CHAT_DB` instead, so they served personas from a different file than the conversation. The server also exports the path it settled on, and refuses a relative `--db-path` (a CLI starts it from its seat folder, where that names an empty database).
- Tests: `tests/test_conv_types.py`. Audit item RT-20.

### Changed — notification URLs are parsed, not prefix-matched

- **Settings → Notifications parses every URL it takes.** The ntfy/Gotify server and the Discord, Slack and raw webhook URLs must be `http(s)://` with a host (Discord and Slack `https://`). The server fields weren't checked at all, and Python's `urllib` will open `file://`. `post_webhook()` now refuses any non-http(s) URL, so a hand-edited config can't do it either.
- **The service of a hand-written sink is read from the URL's host**, so `https://n8n.example/discord.com/` is a raw webhook, not Discord.
- **Send test reports the HTTP status only**, not the first 200 bytes of whatever the URL answered.
- Tests: `tests/test_notifications.py`. Audit item RT-19.

### Changed — message senders and signals are escaped and checked; ingest validates rows

- **The transcript escapes a message's `sender` and `signal`** where they become CSS class names, on the server and in the live-append script. Both used to be pasted in raw.
- **One sender grammar**, `schema.SENDER_RE` (letters, digits, `-`, `_`, `.`, up to 64): the MCP server refuses to start with an `--agent-id` outside it, and `/api/ingest` refuses a message whose sender doesn't match or whose signal isn't `done`/`blocked`/`result`.
- **`/api/ingest` checks a batch before applying it**: integer ids, string content, and a 32 MB body cap (`413`). A bad row is a `400` naming it, and nothing in the batch is stored. Every sender and signal already in a local database passes.
- Tests: `tests/test_web_readonly.py`. Audit item RT-18.

### Fixed — the live stream no longer drops a run's final message

- **The SSE stream sends every message before `complete`.** It read new messages and then the conversation's status; a final send landing between the two reads closed the stream without that message (often the closing statement or the deliverable) until a reload. It now reads the status first: since the send commits its message and the close together, a `complete` read means every message is already visible.
- **`?since=` must be a message id**: anything else is a `400`, not a `500` with a traceback.
- **Open streams are capped**: 100 per process and 10 per client (`Fly-Client-IP` on the mirror), else `429` with `Retry-After`. `fly.toml` adds a 200-connection hard limit at Fly's proxy. A browser opens at most ~6 connections to a host, so a reader never meets the per-client cap.
- Tests: `tests/test_web_readonly.py`. Audit item RT-17.

### Fixed — a slow delivery sink no longer stalls the agent; a failed stall notice is retried

- **Delivery runs on a background thread** wherever the caller is on an event loop: the MCP server's `send_message`, the web UI's Stop, and seeding's `started` event (which `/api/orchestrate` triggers). A webhook can take its whole timeout and a command sink up to two minutes; inline, either froze the MCP server, so the agent's `send_message` and every other call to that server waited on it. A run's `result` and `complete` still go out in that order, and the thread isn't a daemon, so `start_conversation.py` finishes a delivery before it exits. `inspect_conversations stop` and `deliver` stay inline, since they print each sink's result.
- **The watchdog retries a stall whose notice failed.** It used to count any attempted delivery, so a dead ntfy or n8n endpoint marked the stall notified and it was never sent again. Now at least one sink has to succeed.
- Tests: `tests/test_mcp_turns.py` (a 3 s sink doesn't hold up the send), `tests/test_delivery.py` (a failed stall notice is retried), `tests/test_notifications.py`. Audit item RT-14.

### Changed — a conversation opens on its transcript on phones

- **At 900px and below, a conversation page (and its not-found page) shows the transcript first.** The conversation list now follows the reader instead of stacking above it, and the Actions and kickoff panels follow the transcript: topic → cast → transcript → actions → list. On a 375×812 screen the title moved from y≈760 to ≈150 and the first message from ≈1420 to ≈550; the not-found message is on the first screen. `/conversations` keeps the list first, and desktop is unchanged. Test: `tests/test_web_readonly.py`. Audit item RT-38.

### Changed — local writes need a per-install secret; a tailnet host needs a password

- **Every write to the local web UI must carry this install's write secret.** It is generated on first use into `config/web-write-secret` (gitignored). Any page GET sets it as an `HttpOnly`, `SameSite=Strict` cookie (`rt_write`), so the app's own pages work unchanged; a script sends it as the `X-Roundtable-Write` header. A write without it gets `401 missing write secret` (reload the page). `/api/ingest` keeps its bearer token, and the AgentBattleground bridge keeps its own: the `/battleground` console's same-origin pass now also needs the cookie. The read-only mirror is unaffected.
- **The web UI refuses to start** when `AGENT_CHAT_ALLOWED_HOSTS` names a host other than `127.0.0.1`/`localhost` (a `tailscale serve` name) and no `AGENT_CHAT_BASIC_AUTH_PASSWORD` is set. The password and user are now read from `.env` as well as the environment, and `docs/guides/remote-access.md` puts them there instead of `setx`, which handed the password to every process the app spawns. The startup line `basic auth:` now reports the real state.
- Tests: `tests/test_web_readonly.py`, `tests/test_battleground.py`. Audit item RT-05.

### Changed — turn tools return only the messages an agent hasn't seen

- **`get_my_turn`, `wait_for_turn` and `send_message` return a history delta.** Every call used to carry the whole transcript, including each 180-second wait timeout: by the end of run #51 (28 messages, 213k characters) that was about 53k tokens per call, so cost grew with the square of run length. `history` now holds the other participants' messages this session hasn't been shown (`history_mode: "delta"`, with `history_since_id` and `last_message_id`). The server keeps the mark per process and conversation, and only advances it when a payload is actually returned.
- **`history="full"`** returns the whole transcript (after a restart, a restarted server starts from the beginning anyway); **`history="none"`** returns none; **`since_id=N`** returns everything after message N. A `timeout` carries no history and marks nothing as seen. Under blind-first, a payload with hidden messages marks nothing, so the reveal arrives in full.
- The `agent-chat` and `collaborate-mode` skills, the kickoff template, the spawn launch prompt and the generated seat docs say so (the seat docs also had `wait_for_turn`'s default as 60 s; it is 180). Tests: `tests/test_mcp_turns.py`, `tests/test_mcp_stdio.py`. Audit item RT-13.

### Fixed — a second run on a busy seat no longer hijacks the first

- **Each MCP session stays in the conversation it joined.** Every tool used to resolve "the newest conversation that includes my agent id", so seeding a second run that reused a seat moved that seat's agent into it mid-debate: its next message landed in the new run and the old one sat on its turn forever. The server now binds the session on its first call (`get_kickoff()` rebinds, since that is how an agent joins a run). A finished run that has a newer one waiting says so (`newer_conversation_id` + a hint to call `get_kickoff()`).
- **Seeding refuses a seat that is busy in an active conversation** — `start_conversation.py`, `debate.ps1`, and `/orchestrate`, which now answers `409 seat_busy` before spending preflight on it. The error names the run and how to stop it.
- Tests: `tests/test_mcp_turns.py` (the audit's hijack, binding, the refusal, the newer-run hint), `tests/test_conv_types.py` (the 409 before preflight). Audit item RT-08.

### Fixed — a Stop racing a send, polls rewriting finished runs, and two agents claiming one arena

- **A send is one transaction.** `send_message` checked the row, inserted, then moved the turn pointer as separate autocommit statements, so an operator Stop (web UI, `inspect_conversations stop`, or a stop pulled from the mirror) could land in between: the message was appended to a stopped run, the finished row got `current_turn` set again, and `complete` was delivered twice. The whole sequence now runs under `BEGIN IMMEDIATE`, so the Stop waits for it.
- **A conversation is closed once.** Every close goes through `schema.complete_conversation()`, a conditional `UPDATE … WHERE status='active'` that reports whether this caller made the change; only that caller fires the `complete` delivery.
- **Polls no longer rewrite finished rows.** `get_my_turn` / `wait_for_turn` re-closed a complete conversation on every call, moving `updated_at` (so the sidecar re-shipped it) and turning an operator's "stopped by operator" into "max_turns reached". A finished row is now left byte-identical.
- **Battleground:** claiming an arena is conditional (`AND agent_id IS NULL`), so the second of two CLIs is told `assigned_elsewhere` instead of both getting "ok". A re-capture merges under `BEGIN IMMEDIATE`. A post its adapter gave no id gets one hashed from author + text instead of its position, so new replies above it no longer overwrite it on the next capture.
- Tests: `tests/test_mcp_turns.py` (a Stop from another thread during a send; polls on a finished row; CLI stop; the arena claim race). Audit item RT-09.

### Changed — the database schema is declared once, in `src/schema.py`

- **One module replaces four copies.** The DDL used to be pasted into `agent_chat_mcp.py`, `web/db.py`, `orchestrator/seeding.py` and (personas only) `orchestrator/personas.py`, each with its own migration list, and the sync column lists lived in both `web/db.py` and `scripts/db_sync.py`. Now `src/schema.py` (stdlib only) holds `SCHEMA`, `MIGRATIONS`, `CONV_COLUMNS` / `MSG_COLUMNS` / `PERSONA_COLUMNS` and the arena/draft status values, and every process boots a file through `schema.ensure_schema(conn)`. No column changed; existing databases need nothing.
- **Two processes migrating at once no longer crash the loser.** Both could see a column missing and both `ALTER TABLE`; the second now treats "duplicate column name" as done.
- Tests (`tests/test_conv_types.py`): a `CREATE TABLE` outside `src/schema.py` fails the suite; a migrated DB matches a fresh one; the synced lists equal the `conversations`, `messages` and `personas` tables; every `INSERT INTO` in `src/` (including both battleground tables) names columns that exist. Audit item RT-27.

### Fixed — a deliverable's `##` sections no longer split the exported transcript

- **`transcript.md` demotes a message body's own headings two levels** (`#` → `###`, `##` → `####`; fenced code untouched). The export contract says the `## sender — timestamp` lines are the only `##` lines a parser splits turns on, but bodies were emitted verbatim, so a collaboration result written with `## Risks` sections added a fake turn for every consumer (the delivery folder, the `.zip`, scripts). This changes the transcript bytes of any run whose messages contain headings; `docs/app/export-format.md` records it. Test: `tests/test_deliverable_flow.py`.
### Fixed — web UI accessibility quick wins

- **Dark-theme secondary text clears WCAG AA.** `--muted-2` goes from `#71717a` (4.1:1 on the page background, 3.1:1 on raised panels) to `#909099` (6.4:1 and 4.7:1), and the conversation page's hard-coded greys (`#6b7280`, `#52555c`, `#5f6470`, `#71717a`) now use the token, so the time stamps, run details and cast hints that failed Lighthouse pass. Light theme unchanged.
- **The focused "Skip to content" link sits below the fixed source bar** instead of mostly under it.
- **The search button's accessible name matches what it shows** ("Search Ctrl K", with `aria-keyshortcuts`), keeps a name on phones where the word hides, and the palette's input has a label.
- **Bigger targets:** "Run details" is 24px tall and the jump-to-latest pill 32px.
- **Every app page has a `meta description`**; a conversation page's names its topic.
- Lighthouse on a local run of this change: `/conversations` 100 (desktop); a mobile transcript 99, with heading order left for the next item. Test: `tests/test_web_readonly.py`.

### Changed — a failed backup or a failed restart now says so

- **`scripts/maintain-app.ps1` fails loudly.** It used to exit 0 whatever happened, so a failed backup looked green in Task Scheduler. Now each copy is checked with `PRAGMA integrity_check`; a backup that errors or fails the check deletes the bad copy, skips the prune, exits **1**, and sends one alert. **The prune keeps hand-made snapshots:** it removes only its own `chat-YYYYMMDD-HHMMSS.db` files, where it used to delete every `chat-*.db` older than 14 days.
- **`scripts/healthcheck-app.ps1` alerts once per outage** when a restart didn't take (a 14-hour outage on 2026-11-10 went unseen), cleared when healthy again.
- **New: `inspect_conversations alert "<text>"`** posts through the Settings → Notifications sink (`delivery.send_alert()`), ignoring its events list since an outage isn't a conversation event. Nothing is sent, or logged, when no sink is armed. **Action needed:** arm one on Settings → Notifications if you want these.
- Docs: `docs/app/running-the-local-app.md`, `scripts/README.md`. Tests: new `tests/test_maintain_app.py` (runs the real script against temp paths: a good night prunes only nightly copies; a corrupt DB exits 1 and prunes nothing), `tests/test_notifications.py` (the alert reaches an armed sink and never raises).

### Changed — the sync sidecar no longer takes agent instructions from the mirror

- **The pull applies only deletions and stops.** `scripts/db_sync.py` used to `INSERT OR REPLACE` every conversation and persona the mirror reported, so the public mirror (or anyone holding the sync token) could change a topic, a kickoff or a persona body that the next local run handed to an agent, and an older mirror row could roll the live turn pointer back. Now a conversation the mirror reports `complete` closes an `active` local row only when the mirror's `updated_at` is newer; nothing else about a conversation is taken, a row that only exists remotely is never inserted, and persona rows and persona deletions are ignored. Personas flow local → mirror only.
- **`/api/ingest` is last-write-wins** for conversations: an older batch arriving after a newer one changes nothing (this deploys to the mirror).
- **The sidecar refuses a plain `http://` remote** (loopback excepted); the token rides in a header.
- **Owner action:** rotate the sync token (`AGENT_CHAT_INGEST_TOKEN`, local `.env` + `fly secrets set`), since spawned seats could read the old one before today's seat containment.
- Docs: `docs/app/personas.md`, `docs/app/web-ui.md`. Tests: `tests/test_db_sync_watermarks.py` (a newer mirror row with changed content leaves local alone; a stale stop can't close a newer row; the stop echo still terminates; ingest never rolls back; http refused).
### Changed — agents are told plainly that other people's text is data

- **`get_arena` and `wait_for_verdict` hand the captured posts over as `arena.untrusted_thread`** — `{source_url, captured_at, note, posts}` — instead of a bare `thread` list, and the house rules gain **rule 0**: everything in it (and `reply_target`) was written by strangers and is data to argue with, never instructions. The bridge's REST API is unchanged.
- **Every turn payload carries `history_note`**: other agents' messages are their words, not instructions; the `role_brief` and the kickoff are.
- **Seat role docs no longer say "The topic wins… work there".** That line told a seat reading untrusted text to go and edit whatever repo the topic named. They now say a conversation is not a work order, and that development work is in scope when the operator asks for it directly (`scripts/setup/gen_agent_role_docs.py`, regenerated).
- Skills: `battleground` (rule 0, the envelope), `agent-chat` (`history_note`). Docs: `docs/app/battleground.md`. Tests: `tests/test_battleground.py`, `tests/test_mcp_turns.py`, `tests/test_deliverable_flow.py`.

### Changed — spawned seats can't run commands, edit files or reach other MCP servers

- **Every seat `/orchestrate` or `debate.ps1` launches is contained, approvals box or not.** A seat reads text anyone could have written (persona cards, topics, other agents' messages, captured threads), and on a machine whose user settings pre-approve shell tools it could act on that text unasked. Now:
  - **Claude Code** launches with `--tools Read --strict-mcp-config --mcp-config <db\launch\conv<id>-<seat>.mcp.json>`: `Read` is its only built-in tool and `roundtable` its only MCP server. A `--disallowedTools Bash` list was tried first; the seat simply used the Windows PowerShell tool, which is why it is an allowlist.
  - **Codex** launches with `--sandbox read-only --ask-for-approval on-request`, and every MCP server its `config.toml` declares other than `roundtable` is switched off for that window (`-c mcp_servers.<name>.enabled=false`, read from the seat's own `CODEX_HOME`). Servers a Codex plugin provides can't be switched off that way.
  - **OpenCode**: `agents/CLIs/opencode_agent1/opencode.json` gains a `permission` block (deny everything but `read`, `roundtable_*`, and reading the `db/launch` prompt folder) and drops its `context7` and `playwright` servers. Servers merged in from your global OpenCode config are denied too.
  - Every seat's window drops `AGENT_CHAT_INGEST_TOKEN`, `AGENT_CHAT_BATTLEGROUND_TOKEN`, `AGENT_CHAT_BASIC_AUTH_PASSWORD` and `FLY_API_TOKEN` before the CLI starts.
  - Antigravity has no verified flag yet and is unchanged.
- **Action needed:** an OpenCode seat 2+ folder created before today was cloned from the old `opencode.json`; delete it and re-create it with `scripts/setup/add_agent_seat.py`.
- **The facilitator brief no longer asks a seat to write files.** The result message is the delivery; if the artifact belongs in a repo, the result ends with where, so you can put it there (`_ROLE_BRIEFS`, `skills/collaborate-mode`).
- Checked headless on this machine: a Claude Code seat asked to run `whoami` had no shell tool and listed only `Read` and the roundtable tools; an OpenCode seat could read its `db/launch` prompt but nothing else outside its folder and had no shell; a read-only Codex could not create a file. Docs: `docs/app/web-ui.md`, `docs/cli-mcp-config/per-cli/opencode.md`, `skills/start-debate`. Tests: `tests/test_spawn_allowlist.py`, `tests/test_deliverable_flow.py`.

### Changed — the Fly mirror deploys only after CI passes

- **A push to `main` deploys only once the test suites pass.** `deploy-fly.yml` no longer runs on the push itself (three red or cancelled builds had reached production that way); `ci.yml` calls it as a `deploy` job with `needs: test`, still only for pushes touching the web paths. CI on `main` no longer cancels an in-flight run, so a newer push can't kill a deploy half way. `gh workflow run deploy-fly.yml` still works by hand.
- **A PR touching the image builds and boots it.** New `image` job: `docker build`, run it read-only, and require `/api/battleground/healthz` and `/` to answer.
- **Health checks.** `fly.toml` gains an http check on `/api/battleground/healthz`, and the deploy job curls the public hostname afterwards and fails if it doesn't answer `ok`.
- Docs: `AGENTS.md` › Deploying to Fly, `.claude/commands/deploy-fly.md`.

### Fixed — battleground links are http(s) only

- **The bridge, the extension and the `/battleground` console accept only `http`/`https` links.** A captured post's permalink with any other scheme is dropped at capture and at the bridge; an arena whose URL isn't http(s) is refused with a 400; and the console renders no link for a stored row that predates the check. Tests: `tests/test_battleground.py`.

### Changed — the delivery command sink no longer puts the topic on the command line

- **`{topic}` is no longer substituted into a command sink's argv.** Only `{dir}`, `{cid}` and `{event}` are. The command reads the topic and status from the new `ROUNDTABLE_TOPIC` / `ROUNDTABLE_STATUS` environment variables (beside `ROUNDTABLE_CID`, `ROUNDTABLE_EVENT`, `ROUNDTABLE_DIR`). **Action needed if your `config/delivery.json` command uses `{topic}`:** it is now refused with an error in `logs/delivery.log`; switch to the environment variable.
- **A shell evaluating a string is refused** — `pwsh`/`powershell`/`cmd`/`bash`/`sh` with `-Command`, `-c`, `/c` or `-EncodedCommand`. Call a script file (`pwsh -NoProfile -File hook.ps1 {dir}`) or add `"allow_shell": true` to the sink by hand; the Settings → Delivery form refuses to save one without it and keeps the flag when it's there. The starter config and the form's placeholder now show the `-File` form. Docs: `docs/app/delivery.md`. Tests: `tests/test_delivery.py`, `tests/test_notifications.py`.

### Added — audit follow-ups on the roadmap

- `docs/ROADMAP.md` gains an *Audit follow-ups, 2026-11-22* section: 44 items from a full audit, one PR each.

### Changed — the GitHub About names all four CLIs

- The repo description named two CLI agents. It now lists Claude Code, Codex CLI, Antigravity and OpenCode, and says what they do on the bus (debates, podcasts, collaborations). Closes the roadmap's Metadata item.

## 2026-11-20

### Changed — docs sweep

- **The docs hub names all four formats.** `docs/README.md` gains a Collaborate row and says four formats, not three. The CLI role docs, `agents/README.md`, the setup guide and the per-CLI MCP configs say Roundtable where they said Agent-Chat in prose.

## 2026-11-19

### Changed — spawned agents ask before acting unless you allowlist them

- **The `/orchestrate` approvals box is off by default.** It used to be ticked, so every run the form launched gave each CLI a blanket skip-all-approvals flag (`--dangerously-skip-permissions`, `--yolo`, `--auto`) while a persona card and the topic, both text anyone could have written, went in as the agent's instructions. Now the box is unticked and reads *Let Claude Code seats use the roundtable tools without asking*.
- **Ticked, it is an allowlist, not a bypass.** A Claude Code seat launches with `--allowedTools mcp__roundtable --add-dir '<repo>\db\launch'` after the prompt: the `roundtable` tools run without asking, the seat can read its own prompt file, and every other tool still asks. **Codex, Antigravity and OpenCode get no flag at all** and ask for every tool, because none of them has a per-tool allowlist flag that could be checked without a live run. **Action needed if you ran those hands-off:** answer their prompts in their windows. The same applies to `scripts/debate.ps1 -SkipPermissions`, which shares the launch table.
- **A warning when it matters most.** Tick the box while a chair holds a custom persona card and the form tells you to read the card first.
- The `$Clis` table in `scripts/lib/spawn-agents.ps1` swaps its `SkipPerm` field for `Allow`, the one place a CLI's allowlist goes. Docs: `docs/app/web-ui.md`, `docs/guides/orchestrate-form.md`, `docs/guides/auto-debate.md`, `docs/guides/debate.md`, `docs/testing/debate-launch-walkthrough.md`, the Claude Code, Antigravity and OpenCode pages under `docs/cli-mcp-config/per-cli/`, `skills/start-debate/SKILL.md`. Tests: new `tests/test_spawn_allowlist.py` (the box renders unticked; the real launch plan gives Claude Code seats the allowlist after the prompt and never gives any seat a bypass flag), and `tests/test_orchestrate_browser.py` (an untouched form posts `skip_permissions: false`; the custom-card warning shows and hides). No live CLI was launched.

## 2026-11-16

### Fixed — homepage guide links are phone-sized tap targets

- **The *Guides:* links on the home page were 16px tall and, where the row wrapped on a phone, *Online forums* split across both lines and sat on top of the others** (Local App Checks, *usable on a phone*, WCAG 2.5.8). `.guides a` in `src/web/assets.py` is now `inline-block` with 4px of vertical padding: 24px tall and never split.

## 2026-11-12

### Changed — the battleground bridge trusts one extension and requires its token

- **Only the extension you name is exempt from the cross-site guard, and only on the bridge.** Until today `CrossSiteWriteGuard` waved through every `chrome-extension://` and `moz-extension://` origin on every route, so any extension installed in your browser could POST to `/api/settings/delivery` (and through a command sink, run something) or `/api/orchestrate`. Now an extension origin passes only when its id is listed in the new `AGENT_CHAT_EXTENSION_IDS` (comma-separated: the ID on `chrome://extensions`, or Firefox's Internal UUID from `about:debugging`), and only under `/api/battleground/`. Every other extension, and the right one anywhere else, gets the same 403 a website gets. `ExtensionCorsMiddleware` echoes only the listed ids too.
- **`AGENT_CHAT_BATTLEGROUND_TOKEN` is required.** With no token configured the bridge now refuses every call with a 401 that names the setting, where it used to be open. **Action needed if you use the extension:** add both lines to the repo's `.env` (see `.env.example`) and paste the token into the panel's Settings. Both are read per request, from the environment and then `.env`, so no restart is needed. `/healthz` still answers without a token and adds `token_configured`; `token_required` is now always `true`.
- **The `/battleground` console keeps working without a token.** Its buttons post from the app's own page, so a same-origin request (`Origin` matches `Host`) passes the token check. Before this, setting a token broke the console's verdict and close buttons.
- **The panel says what to set.** Its Settings notice now appears when the server has no token and gives both `.env` lines with this install's id filled in, and *Test connection* names the id when it is refused. The `/extension` page's bridge check and install steps say the same. None of the extension changes ran in a browser.
- Docs: `docs/app/battleground.md` › Auth + CORS, `docs/app/web-ui.md`'s always-on layers table, `docs/app/settings.md`, `docs/guides/battleground.md` (setup + troubleshooting), `docs/guides/online-forums.md`, `extension/README.md`, `AGENTS.md`, `src/README.md`. Tests: `tests/test_battleground.py` (the token required with none configured, the configured extension reaching the bridge with its token, another extension refused on and off the bridge, the console's same-origin post), `tests/test_web_readonly.py` (an extension origin on `/api/settings/delivery` is refused).

## 2026-11-11

### Changed — roadmap rechecked against the org's 2026-11 requirements

- **`docs/ROADMAP.md` rechecked against the org's 2026-11 requirements.** The intro names the job that works it (`agent-chat-roadmap`) instead of a disabled task and its day. New items: a Cronsole catalog for the scheduled jobs (🔒 Needs owner until the template scope and the `-SkipPermissions` default are decided), a demo build stamp, the `roundtable.theme` key, a `-TaskPath` parameter on the task scripts, a carried security item (no credential hint in logs, no raw DB errors) and the About text (🔒). *Arm stall notifications on this machine* is marked 🔒 Needs owner; progress notes narrow *Favicon and basic site polish* (Open Graph on conversation pages is what's left) and *Dependency + deploy hygiene* (Dependabot shipped 2026-09-29), and *Explore remote debate kickoff* is scoped to the remote trigger only.
- **Ticked *Web UI: dark mode*** *(After public release · Low)*: it shipped 2026-10-05 as the light theme and the light/dark switch on every page (`cadd9e3`).

### Fixed — the persona registry answers on its own hostname again

- **`personas.ai-automation-tools.dev` returned `400 Invalid host header`** from the 2026-11-10 deploy on. The Host allowlist (#251) and the standalone registry site (#257) landed in separate PRs, and `fly.toml`'s `AGENT_CHAT_ALLOWED_HOSTS` never got the registry's name. It is listed now, and `test_fly_allows_every_public_host` (`tests/test_availability.py`) fails when a hostname the code serves (`PUBLIC_REGISTRY_HOST`, `DEMO_URL`) is missing from it.
- **CI on `main` is green again.** `tests/test_persona_explorer.py` used TestClient's default `testserver` host, which the allowlist refuses; it now uses loopback like the other suites. The registry-host test allows that host for its own run.

## 2026-11-10

### Fixed: the extension folds non-breaking spaces again

- **`extension/src/capture.js` `clean()` turns non-breaking spaces into plain spaces again** (security sweep, CodeQL `js/identity-replacement`). The pattern had lost its literal NBSP somewhere along the way and was replacing a space with a space. It is now written as `\u00a0`, so an editor can't flatten it again.

### Changed — upstream check

- **OpenCode 2's MCP shape is noted, not adopted.** `docs/cli-mcp-config/per-cli/opencode.md` gains a quirk: OpenCode 2 documents servers under `mcp.servers` (with `disabled` for `enabled`) and still reads the v1 shape this repo writes. The move is queued as a Low Roadmap item. `docs/UPSTREAMS.md`: every row re-read and dated 2026-11-10, the Antigravity `agy mcp add` note flagged as unverified, and the OpenCode row's config shape and `--auto` evidence recorded.

## 2026-11-07

### Changed — process-flow diagram re-pinned

- **`docs/diagrams/process-flow.json` re-pinned to `6a1837c1`** (org upkeep). The only cited file that moved, `src/orchestrator/delivery.py`, changed one docstring line outside the cited range (`resolve_db_path`); the Delivery Sinks node (lines 1-56) and every other node are still true. Rebuilt with `--pin-head`, which also refreshes `homepage/diagram/`.

### Changed — the persona console advertises the registry

- **A registry card fills the console's empty detail pane** (`_registry_promo` in `src/web/render/personas.py`): five faces from the cast, *N ready-made characters in M groups* (the same cast the registry shows, no AI-Models cards), what you can do there (read a card, download it with its avatar as a `.zip` that Import reads back), and a *Browse the registry ↗* button to `personas.ai-automation-tools.dev`. The "Select a persona to edit" prompt sits below it, its button now secondary. Pinned by `tests/test_persona_explorer.py`.
- **The group title no longer collapses to "P…".** `.pm-ctitle` keeps its natural width (`flex:1 1 auto`), so the toolbar wraps to its own row when the two don't fit.

### Changed — the persona registry is a standalone site

- **`personas.ai-automation-tools.dev` serves only the registry.** `RegistryHostMiddleware` (`src/web/security.py`) opens `/personas` at `/`, serves the explorer, its downloads and avatars, and redirects every other path (the app, `/personas/manage`, the API) to the same path on `roundtable-demo`. It shares the mirror's deployment and database, but it no longer reads as a second copy of the demo.
- **The explorer has its own chrome** (`_registry_layout` in `src/web/render/common.py`): the source bar and a slim *Agent Personas* header with a *Roundtable ↗* link and the theme switch. No app sidebar, search palette or live pill.
- **The app links out to it:** the *Persona registry* rail row, the console's toolbar button and Import hint, and the home page's *Browse all* link all open `https://personas.ai-automation-tools.dev` in a new tab.

### Changed — Personas opens the console; the registry gets its own address

- **The rail's *Personas* row now opens `/personas/manage`**, the page you actually edit cards on. The read-only explorer at `/personas` is a new **Persona registry** row under *Resources*, and lights that row instead.
- **The registry has a hostname without "demo" in it: `https://personas.ai-automation-tools.dev`.** It is a second Fly cert on the same mirror; `GET /` on that host redirects to `/personas` (`web_ui.homepage`, pinned by `tests/test_availability.py`). Every other path serves as usual.
- **Advertised in more places:** the management console's group rail links the registry and its public address; the static homepage links it from the top nav, the hero, the *At a glance* facts and the Resources grid; the README and the persona docs point at the new hostname.

## 2026-11-06

### Added — the persona explorer (the Persona Registry moves in-app)

The AI-Automation-Library's static Persona Registry is retired; browsing the cast is now part of Roundtable, and works on the read-only demo.

- **`/personas` is now a read-only explorer.** A grid of every persona except the reserved `AI-Models` group, each card showing its 2:3 cover, name, group and tags. Search covers name, tags and the whole card body (every word must match); filter by group, category / subcategory or tag; sort by name or newest. Filters are plain GET parameters, so a filtered view is a link you can share, and nothing on the page needs a script to work.
- **A page per persona** at `/personas/<slug>`: cover, avatar, metadata, and the card rendered as Markdown exactly as the model reads it. Downloads: the card `.md`, the avatar (when the persona has art of its own), and a `.zip` of both laid out as `<slug>/<slug>.md` + `<slug>/<slug>-avatar.png`, which the Import modal re-imports with its picture.
- **Use in a debate** opens `/orchestrate?persona=<slug>`, which now seats that persona in the first chair. On the demo the same button reaches the "debates run on your machine" page.
- **Covers** load from `{PERSONA_MEDIA_URL}/covers/<slug>.webp` (default `https://ai-automation-tools.dev/roundtable-personas`, override with the `PERSONA_MEDIA_URL` env var). A persona with no cover shows its avatar instead, never a broken image.
- **The management console moved to `/personas/manage`.** Unchanged otherwise. Its *Get more cards ↗* button is now **Browse the cast**, back to the explorer. The command palette opens a persona's explorer page and lists *Manage personas* as its own page.
- **Persona Registry links removed:** the *Persona Registry ↗* rail row and palette entry are gone, `REGISTRY_URL` now points at `/personas`, and the README, the homepage resources, the static `homepage/`, `docs/guides/add-a-persona.md` and `docs/app/` point at the explorer.
- New `orchestrator.personas.card_text()` (the inverse of `parse_card_text()`), `Persona.created_at`, and `web.avatars.raster_avatar()`. New `tests/test_persona_explorer.py`; `tests/test_availability.py` now checks the rail has no off-site registry row and that the explorer and console link to each other.

### Removed — the Debate Chat Theater integration and the publish-to-library pipeline

The Debate Chat Theater on the AI-Automation-Library site is being decommissioned, so Roundtable no longer feeds it or links to it.

- **Publish pipeline gone.** `scripts/publish_debate.py`, the runtime skill `skills/publish-debate/`, and the `prompts/Auto-Debate/Debate-And-Publish/` prompts are deleted. The *publish a keeper* prompt is cut from `Manage-Debates/Review-And-Export/`, `start-debate` now points at the Export MD / Export ZIP buttons after a run, and the skills, scripts, prompts, repo-layout and agent docs no longer mention publishing into `My-Library/Content/Agent-Debates/`. Re-run `scripts/setup/setup-skill-links.ps1` (or delete the dangling `publish-debate` junction) on any other clone.
- **Theater links gone.** `THEATER_URL`, the *Theater* rail row, the *Debate Chat Theater* command-palette entry, *Watch in Theater ↗* on the homepage's Featured runs panel, the `.feat-theater` / `.btn-thea` styles and the `thea` icon are removed, as are the link on the static `homepage/` and the README's Companion sites row. The Persona Registry link stays.
- **Export format unchanged.** `/export.md` and `/export.zip` render exactly as before. `docs/app/export-format.md` and the code comments now name the consumers that remain — the downloads and the delivery folder sink. The generated image and audio prompts no longer suggest an `Agent-Debates/<slug>/` folder.
- Roadmap: *Contain `publish_debate.py --category`* and *Cross-links between the three debate properties* are marked dropped.

### Fixed — docs links and headers

- Four in-page links now point at headings that exist (the README "Four ways to run one" nav link, the add-a-cli step 2 link, the INITIAL_SETUP link to the README quick start, and the `src/README.md` `web/` package link). `AGENTS.md` no longer links the gitignored `docs/Local/`. `docs/UPSTREAMS.md` is linked from the docs index.
- Centred headers and footers that mixed Markdown into HTML blocks (`docs/mcp-server.md`, three `docs/app/` pages, `docs/cli-mcp-config/README.md`, `extension/README.md`, the Practitioners card index) are plain HTML now, and `skills/README.md` gets the standard section header.

## 2026-11-05

### Security — the web UI answers only to host names it knows, and write bodies must be JSON

- Every request whose `Host` isn't `127.0.0.1`, `localhost` or a name in the new **`AGENT_CHAT_ALLOWED_HOSTS`** setting now gets `400 Invalid host header`, on every method (Starlette's `TrustedHostMiddleware`, outermost in `_build_middleware()`). The cross-site write guard compared `Origin` with a `Host` the client chose, so a DNS-rebinding page, same-origin with its own name, got through it.
- `AGENT_CHAT_ALLOWED_HOSTS` is comma-separated, read at startup from the environment or the repo-root `.env` (documented in `.env.example`). **If you reach your local UI through `tailscale serve` and the phone shows `Invalid host header`, add the MagicDNS name there and restart the web UI** ([remote access](guides/remote-access.md), step 4). Same for a LAN address bound with `--host`.
- The hosted mirror's three names (`roundtable-demo.ai-automation-tools.dev`, `agent-chat.mikesailab.com`, `agent-chat-mikesailab.fly.dev`) are in `fly.toml`'s `[env]`, so it keeps answering after the deploy. A new custom domain needs adding there first.
- A POST that carries a body must now be `Content-Type: application/json`, or it gets `415`. Every route that reads a body parses JSON, and the web UI, the extension and the sidecar already send it; body-less POSTs (stop, delete) are unchanged. This is what a `no-cors` page can't fake.
- Tests: six new cases in `tests/test_web_readonly.py`. The other web suites now point their test client at `127.0.0.1:8765`, since the allowlist refuses its default `testserver` host.

### Changed — one topic library per conversation type

- `docs/chat-topics/Topics.md` is renamed **`Debate-Topics.md`**, so each library's name says which type it serves. `scripts/debate.ps1` now defaults to it (still overridable with `-TopicsGlob`); the start-debate skill, the debate/auto-debate guides, the launch walkthrough and the prompt library point at the new name. ✅ markers carried over unchanged.
- New **`Collaboration-Topics.md`**: 40 tasks for a collaboration, five per sub-type (`brainstorm`, `plan`, `decide`, `solve`, `design`, `validate`, `audit`, open `collaborate`). Each has a `- Seats: N` line (2–5, facilitator included) and the `- Preset:` it was written for.
- More topics: the debate library grows from 100 to 120 (*Creators, Tools & the AI Maker Economy* and *Everyday Life & Ethics*), and the podcast library from 40 to 50 (*Making Things in the Age of AI* and *Sport, Play & Competition*). The debate file gains a header explaining its format and how the ✅ marker works.
- **`scripts/debate.ps1 -Format collaborate`**: the one-command launcher now covers collaborations. With no `-Topic` it picks an unused task from `Collaboration-Topics.md` and takes its seat count and preset; the first seat facilitates. New `-Preset` flag overrides the sub-type. No personas are cast unless `-Personalities` or `-Group` asks, so no personas file is written or passed to the seed. Debate and podcast launches are unchanged. Closes the collaboration half of the Roadmap row's sub-item (d) and the matching open question.
- **Fixed: `debate.ps1 -Cli` now refuses a seat with no config folder**, before seeding, and prints the `add_agent_seat.py` command that creates it. The check used to run only when the launcher planned the seats itself, so an explicit `-Cli claude-code,claude-code-2,claude-code-3` with no seat-3 folder launched that CLI anyway; it fell back to the user-scope MCP entry and joined as `claude-code` (seat 1), able to post as the host (conversation #65). The check is now one function, `Assert-SeatFolders` in `scripts/lib/spawn-agents.ps1`, used by both paths.
- `docs/chat-topics/README.md` lists all three libraries side by side (type, line shape, what picks from it) with a launch example for each. New `tests/test_topic_libraries.py` pins the debate and collaboration shapes, checks every `- Preset:` names a real collaborate preset, and checks the launcher points at `Debate-Topics.md`.
