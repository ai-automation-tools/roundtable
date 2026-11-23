# Roundtable — agent instructions

Project-specific instructions for every coding agent working on this repo (Codex, opencode, Antigravity and
others read this file; Claude Code reads it through `CLAUDE.md`, which imports it and adds the Claude-only
notes). These override generic guidance.

---

## What this project is

**Roundtable** (formerly Agent-Chat) is a local MCP server that lets two or more CLI agents — Claude Code, Codex, Antigravity, OpenCode — hold structured, turn-based conversations with each other. Each CLI registers the same `agent_chat_mcp.py` with a different `--agent-id` and the same `--db-path`; one SQLite-WAL file is the message bus. Conversations are seeded out-of-band by `start_conversation.py`. Agents call `get_my_turn()` to discover state and `send_message()` to reply. The server enforces turn order, per-agent message caps, and `done` / `blocked` stop signals. No daemon, no port, no auth — identity is config-only.

- **Repo root:** the clone directory (`<repo>` below). Every script and generated
  config derives its own absolute paths from its location, so a clone works anywhere.
- **Remote:** https://github.com/ai-automation-tools/roundtable · **Default branch:** `main` (working branch is often `mike_desktop`)
- **Status:** experimental / single-developer

---

## Repo map

`docs/repo-layout.md` carries the full annotated tree and `src/README.md` the module tour — this is the short version.

```
src/
├── agent_chat_mcp.py        # The MCP server (MCPServer + sqlite3)
├── schema.py                # THE schema: DDL, migrations, synced column lists, arena/draft statuses
├── start_conversation.py    # argparse wrapper around orchestrator.seeding
├── inspect_conversations.py # CLI: list / show / tail / stop
├── presets.py               # Named kickoff presets (tone + mode + max_turns)
├── web_ui.py                # Web-UI ENTRYPOINT only: page routes + route table + app assembly + main()
├── web/                     # Web-UI implementation: db.py (SQL + set_db_path) · security.py
│                            #   (auth/read-only middleware) · assets.py (CSS/JS) · avatars.py ·
│                            #   topics.py · render/ (per-page HTML) · api/ (/api/* handlers)
└── orchestrator/            # seeding.py (single source of truth for seeding) · availability.py
                             #   (which CLIs this machine has + seat planner) · conv_types.py ·
                             #   seats.py (agent-id grammar) · preflight.py · personas.py ·
                             #   model_personas.py · media_prompts.py · export.py (bundle contract) ·
                             #   delivery.py (push a finished conversation out — off by default) ·
                             #   watchdog.py (notice a stalled run — reuses delivery's sinks) ·
                             #   killswitch.py (config/NO_SPAWN + close a run's seat windows)

agents/         # CLIs/<cli>_agent1|2 = one folder per SEAT (role doc + MCP config; make new
                #   seats with scripts/setup/add_agent_seat.py). The four role docs are
                #   GENERATED — edit scripts/setup/gen_agent_role_docs.py, not the output.
                #   A seat is a full-stack developer that can also join a conversation.
                #   Debate-Agents/ = one-time seed cards; live personas are DB rows.
db/ config/     # chat.db at runtime; available-clis.json written by /setup. Both gitignored.
docs/           # app/ · maintainers/ (the rules per area) · guides/ · diagrams/ · setup/ · cli-mcp-config/ · testing/ · chat-topics/ · mcp-server.md ·
                #   Local/ (operator-only, gitignored) · ROADMAP.md · CHANGELOG.md
prompts/        # Reusable operator prompts: Kickoff/ · Auto-Debate/ · Manage-Debates/ · Battleground/
skills/         # Agent Skills read by the PARTICIPATING CLIs at runtime
homepage/       # Static product homepage (roundtable.ai-automation-tools.dev) — GitHub Pages via
                #   .github/workflows/homepage.yml. Not the app: the hosted app is the -demo host on Fly.
extension/      # AgentBattleground MV3 extension (Chrome + Firefox manifests, src/panel/lib/ modules)
scripts/        # Operator helpers — debate.ps1, db_sync.py, run-mcp-server.ps1,
                #   lib/spawn-agents.ps1 (shared CLI registry), setup/ (one-per-clone helpers)
tests/          # pytest-compatible AND standalone-runnable
.claude/        # Claude Code config. agents/ + commands/ + skills/ are TRACKED; the rest is local.
```

When you add a new top-level concern, update this map (here in `AGENTS.md`), `docs/repo-layout.md`, and the README's layout tree. When moving files under `docs/` or `agents/`, also update the README doc index, the `mikesailab` project memory (`project_mikesailab_design_system.md`), and relative `../` paths inside the moved files.

---

## Environment

- **Windows 11, PowerShell 7+ (pwsh).** Paths in commits, docs, and configs are Windows absolute paths with forward slashes. Use PowerShell syntax in docs; add a `> [!NOTE]` block for macOS/Linux equivalents rather than silently swapping.
- **Python 3.11+** in a local venv. Always invoke it explicitly: `.\.venv\Scripts\python.exe ...` — never rely on activation state. **On Windows that launcher re-execs the base interpreter**, so a running process reports `C:\Python312\python.exe` to WMI while being the venv (`sys.executable`/`sys.prefix` are the venv's). Never identify one of this app's processes by `ExecutablePath` — match the command line against this clone's path, as `healthcheck-app.ps1` / `startup-app.ps1` / `stop-app.ps1` do (pinned by `tests/test_availability.py`; `start.ps1` is exempt, it counts launchers).
- **Deps** are pinned exactly in `requirements.txt`. Upgrade by regenerating the full pin set with `pip freeze`, not by hand-editing lines. `requirements-dev.txt` adds the CI-only browser-test pins (Playwright) on top — if you installed it into `.venv`, take `playwright`, `greenlet` and `pyee` back out of a fresh freeze before it lands in `requirements.txt`.
- **Git user:** Mike, with the GitHub noreply address (`225616888+michaelschecht@users.noreply.github.com`). GitHub rejects pushes carrying a personal email (GH007).
- **Paths:** `scripts/run-mcp-server.ps1` resolves the venv and server relative to itself, and the DB defaults to `<repo>/db/chat.db` (override with `$AGENT_CHAT_DB`), so the launcher path is the only absolute path left in each MCP config. Others still live in the README install blocks, the per-CLI configs under `agents/CLIs/`, the global `~/.codex/config.toml`, `docs/setup/INITIAL_SETUP.md`, and the CHANGELOG. Don't add **new** hardcoded paths; if you touch existing ones, change all sites in one PR.

---

## Working with the code

### Python conventions

- Type hints on all signatures; `pathlib.Path` over `os.path`; Pydantic v2 models for tool input/output shapes; `argparse` for CLI entrypoints, matching the existing flag style (`--db-path`, `--agent-id`, `--topic`).
- **Never `print()` to stdout in `src/agent_chat_mcp.py`** — stdout is the JSON-RPC stream. Use `logging` or `sys.stderr`.

### The rules by area — read the full file before changing that area

Each line is the part most often broken; [`docs/maintainers/`](docs/maintainers/README.md) holds the detail.

- **Database + MCP server** → [`sqlite-and-mcp.md`](docs/maintainers/sqlite-and-mcp.md). DDL lives **only** in `src/schema.py` (a test fails on `CREATE TABLE` elsewhere); a column change needs a `MIGRATIONS` row, the `*_COLUMNS` list if it syncs, every reader, and a CHANGELOG note. A conversation leaves `active` only through `schema.complete_conversation()`; check-then-write runs in `schema.write_txn()`. One rule picks the DB file: `schema.resolve_db_path()`. Tools resolve the conversation through `my_conversation()`; turn payloads carry a history delta; the per-agent cap ends a run when **every** seat is spent.
- **Web UI** → [`web-ui.md`](docs/maintainers/web-ui.md) and the `agent-chat-web-ui` skill. Starlette only; `web_ui.py` is the entrypoint and holds the route table. Handlers are plain `def` (read a body with `web.api.request_json`). Bind `127.0.0.1` only — never `0.0.0.0`; remote access is `tailscale serve` + basic auth. Every local write needs the write secret; every `Host` is allowlisted (tests use `base_url="http://127.0.0.1:8765"`). One `h1` per page. `/orchestrate` seeds through `seeding.seed_conversation()` and picks **tools**, never seat ids. Export output is a frozen contract (`docs/app/export-format.md`).
- **AgentBattleground** → [`battleground.md`](docs/maintainers/battleground.md). It drafts, it **never posts**; nothing may reach a page without a human action. Every extension API call goes through `ext`. The arena tables never sync. Nothing under `extension/` runs in a browser test — say so when reporting.
- **Delivery + watchdog** → [`delivery.md`](docs/maintainers/delivery.md). Off unless `config/delivery.json` exists; `deliver()` never raises; every way a run ends calls it, outside the write transaction, only when `complete_conversation()` returned True (`deliver_later()` on an event loop). The watchdog is read-only and never touches an agent.
- **Conversation types, presets, personas** → [`conv-types-and-personas.md`](docs/maintainers/conv-types-and-personas.md). A `conv_type` only when the seats differ; a flavour is a preset. A deliverable is `signal='result'`, last one wins. Random casting goes through `list_debater_personas()`.
- **Testing** → [`testing.md`](docs/maintainers/testing.md). Every `tests/test_*.py` is pytest-compatible and standalone-runnable; CI runs them on Windows/3.12 and Ubuntu/3.14 plus `ruff --select E9,F`. Use a temp DB (`AGENT_CHAT_DB`), never `db/chat.db`, and **do not mock SQLite**.

---

## Docs, git and deploying

Full rules: [`docs-git-deploy.md`](docs/maintainers/docs-git-deploy.md).

- **README.md** is the public face. **`docs/ROADMAP.md`** is the priority list of *open* items: close one in place (`- [x] … — done YYYY-MM-DD: …`, `/close-roadmap-item`), never delete one; done items are archived in [`docs/roadmap/`](docs/roadmap/README.md). **`docs/CHANGELOG.md`** holds the current month, newest first; earlier months are in [`docs/changelog/`](docs/changelog/README.md). Add an entry for any user-visible or schema change.
- Docs are a tree of `README.md` indexes — a new doc gets a row in its folder's README. `docs/setup/INITIAL_SETUP.md` changes with any setup step.
- **`skills/` must stay in sync with behaviour** (the CLIs read it at runtime); a new skill also needs its `.gitignore` line. Role briefs live in `_ROLE_BRIEFS` plus the `<type>-mode` skill.
- **The process-flow diagram is pinned to code.** When conversation-life code moves, fix `docs/diagrams/process-flow.json`'s ranges and run `scripts/build_diagram.py --pin-head` after committing the code.
- **Git:** feature branches off `main` (the working branch is often `mike_desktop`); short imperative subjects, no conventional commits; one Roadmap item per PR; never push to `main` directly. Never commit `.venv/`, `db/*.db*`, `.env*`, `.mcp.json`, local `.claude/` state, or a seat 2+ folder.
- **Deploy:** CI deploys the hosted mirror on every push to `main` touching `src/web_ui.py`, `src/web/`, `requirements.txt`, `fly.toml`/`Dockerfile` or the avatars, after `test`, `test-linux` and `lint` pass — so **merging a web change is the deploy**. A manual `fly deploy` is outward-facing: confirm first. A new synced column: deploy the web app before restarting the sidecar.

---

## Security & operational notes

- **No auth on the MCP server.** Anything running it with `--agent-id X` *is* X. Fine for local CLIs you control; don't propose network exposure without an auth design.
- **No secrets in repo.** `.mcp.json` uses `${...}` substitution — never inline a key.

---

## Where everything is

| Read this | For |
|:---|:---|
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | **Priorities — read first.** |
| [`docs/maintainers/`](docs/maintainers/README.md) | The full rules per area, and the complete "where everything is" table. |
| [`README.md`](README.md) · [`docs/repo-layout.md`](docs/repo-layout.md) · [`src/README.md`](src/README.md) | Tour, annotated tree, module map. |
| [`docs/app/`](docs/app/README.md) | Per-feature reference, including the export contract. |
| [`docs/mcp-server.md`](docs/mcp-server.md) | Every MCP tool, env var and the install line. |

**Two skill trees:** [`skills/`](skills/) is read by the participating CLIs at runtime; [`.claude/skills/`](.claude/skills/) by Claude Code working on this repo. `agent-chat-conv-types`, `agent-chat-delivery` and `agent-chat-run-triage` are installed copies owned by [`ai-automation-tools/agent-skills`](https://github.com/ai-automation-tools/agent-skills) — edit them there.

For ambiguous tasks, ask one clarifying question rather than guess — the codebase is small enough that a wrong assumption costs a six-file edit.
