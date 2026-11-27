---
name: roundtable-web-ui
description: Use when editing the Roundtable web UI — src/web_ui.py or anything under src/web/ (db, security, assets, render/, api/). Covers where code belongs in the package split, the re-exports the tests import, the route table, write endpoints, the single SSE channel, seeding/export delegation, and the no-network-bind rule. Triggered by "add a route", "the conversations page", "the homepage", "SSE", "/orchestrate", "/personas", "web UI", "the CSS".
---

# Working in the Roundtable web UI

Starlette app, no framework beyond `starlette` + `sse-starlette` + `uvicorn`
(already pinned in `requirements.txt` — don't add a frontend dependency). Since
the 2026-07-10 split, `web_ui.py` is **only** the entrypoint: page routes, the
route table, app assembly, `main()`. Implementation lives in the package.

## Where code goes

| Concern | Module |
|:---|:---|
| SQL, `SCHEMA`/`_MIGRATIONS`, `set_db_path()` | `web/db.py` |
| BasicAuth / ReadOnly middleware, `_build_middleware()` | `web/security.py` |
| Stylesheets and scripts (never inline — the pages carry a nonce CSP) | `web/static/css/`, `web/static/js/`; tags via `web/assets.py` (`stylesheets()`, `script()`, `json_script()`) |
| Favicon / mark SVG | `web/assets.py` |
| Per-page HTML | `web/render/` — `common` (shell/markdown/icons), `home`, `conversations`, `orchestrate`, `personas` (the `/personas/manage` console), `persona_explorer` (the read-only `/personas` grid + detail — must stay GET-only), `setup`, `extension`, `battleground` (the arena console) |
| `/api/*` handlers | `web/api/` — `conversations` (+ SSE), `sync`, `orchestrate`, `personas`, `setup`, `battleground` (the extension bridge) |
| Topic→logo classification | `web/topics.py` |
| Persona avatar resolution (`avatar_url`/`avatar_response`, `GET /avatars/{slug}`, uploaded row → file art → default silhouette, `invalidate_index()`) | `web/avatars.py` |

Four rules that break things quietly:

- **One `h1` per page, no skipped levels** (audit RT-40, pinned by
  `test_every_page_has_one_h1_and_no_skipped_heading_level`). A page's title is
  its `h1`; sections are `h2`. Markdown rendered inside the page goes through
  `render_markdown(text, nest_under=N)` so its top heading becomes h(N+1):
  messages nest under the speaker `h3` (`MESSAGE_HEADING_LEVEL`), persona cards
  under an `h2` (`CARD_HEADING_LEVEL`). Style rendered headings by their
  `md-hN` class (the authored level), never by tag. A form field gets a real
  `<label for>` or `aria-labelledby`, and a radio set a `role="radiogroup"`
  with a label.

- **Handlers are plain `def`, not `async def`** (since 2026-11-22, audit RT-28).
  Starlette runs a sync endpoint in its threadpool, so SQLite's 10 s busy
  timeout, a file write or a webhook test holds one worker instead of the event
  loop every other request (SSE included) runs on. Read a body with
  `web.api.request_json(request)`, not `await request.json()`. Only the SSE
  stream and the streamed `/api/ingest` stay async, and they hand their DB work
  to `run_in_threadpool`. A read-merge-write of a `config/` file takes
  `delivery.config_locked`, since two saves can now run at once. A test that
  calls a handler directly runs it with
  `anyio.run(anyio.to_thread.run_sync, handler, request)`.

- **Route paths are defined only in `web_ui.py`.** Handlers live in the package;
  the table stays in the entrypoint.
- **Keep the `web_ui` re-exports working — the tests import them.**
  From `web.db`: `db_init`, `get_conversation`, `list_conversations`,
  `list_stats`, `set_db_path`. From `web.security`: `BasicAuthMiddleware`,
  `ReadOnlyMiddleware`, `_build_middleware`, `_env_truthy`, `_is_public_readonly`.
  From `web.render.common`: `_render_generic_404`, `render_markdown`.
  `tests/test_web_readonly.py` imports these by name.

## Delegate, don't reimplement

- **Seeding** — `/api/orchestrate` must go through
  `orchestrator.seeding.seed_conversation()`, the same function
  `start_conversation.py` calls. Never inline seeding SQL in a route handler.
- **Export** — render through `orchestrator/export.py`. Its output is a frozen
  contract with three external consumers; see the `roundtable-export-contract`
  skill.
- **Personas** — writes go through `orchestrator.personas`
  (`create_persona` / `update_persona` / `delete_persona`), not direct card-file
  or table writes from the handler.
- **Conversation mutations** must mirror the SQL the CLI inspector runs
  (`inspect_conversations.cmd_stop` ↔ `web/db.stop_conversation()`).

## Write endpoints

The app is **not** read-only. Current POSTs: `/api/conversations/{cid}/stop`,
`/api/conversations/{cid}/delete`, `/api/orchestrate`, `/api/personas`,
`/api/personas/import`, `/api/personas/bulk-delete`, `/api/personas/{slug}`,
`/api/personas/{slug}/delete`, and `/api/ingest` (the sidecar sync endpoint).
On the hosted mirror, `ReadOnlyMiddleware` + `AGENT_CHAT_PUBLIC_READONLY` 403s
browser mutations — new write routes are covered automatically, but add a case
to `tests/test_web_readonly.py`.

> [!NOTE]
> `AGENTS.md` says persona management is local-only and must gate on
> `personas.root_exists()`. **That is stale.** Personas now live in the synced
> `personas` table, so `root_exists()` no longer checks the `agents/` tree — it
> returns True whenever the DB is reachable, and persona management works on the
> hosted mirror too. The failure mode it guards is now "database unreachable"
> (404 + `persona storage unavailable`), not "no local cards".

## SSE

One channel, `GET /api/conversations/{cid}/stream?since=<id>`, in
`web/api/conversations.py`. Events: `message` (per new row; payload is the
message dict plus server-rendered `content_html` — there is no client-side
Markdown library), `turn` (`{"current_turn": …}`, emitted only when it changes),
`complete` (empty, then break). **New live-update features reuse this channel** —
do not open a second EventSource.

## Binding and auth

Binds `127.0.0.1:8765`. Do **not** add a `0.0.0.0` bind without an auth story —
the README explicitly warns this server is not network-safe, and anything running
with `--agent-id X` *is* X.

## Verify

```powershell
.\.venv\Scripts\python.exe tests\test_web_readonly.py
.\.venv\Scripts\python.exe tests\test_topics.py
# touched web/render/orchestrate.py? its inline JS has string invariants:
.\.venv\Scripts\python.exe tests\test_orchestrate_form.py
```
`test_orchestrate_form.py` only proves the script and the markup name the same
ids / classes / controls — **it never runs the JS**. `test_orchestrate_browser.py`
does (headless Chromium), but only for the chair engine, and it **skips** unless
you've run `pip install -r requirements-dev.txt` + `python -m playwright install
chromium` (CI always has). Either way, still open the page.
There's no hot reload — restart `web_ui.py` to see a change. Then open
`/conversations/<active_id>` during a live exchange and confirm rows arrive over
SSE.
