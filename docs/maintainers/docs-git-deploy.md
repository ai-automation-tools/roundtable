# Documentation, git and deploying

> The rules for docs, skills, the diagram, branches, commits and the Fly deploy. Moved out of `AGENTS.md` verbatim on 2026-11-22 (audit RT-26) so every agent session doesn't load it; `AGENTS.md` keeps a one-line pointer.

## Documentation rules

- **README.md** is the public face — accurate, concrete, Windows-first, matching the existing tone.
- **docs/ROADMAP.md** is the source of truth for priorities. Closing an item ticks it **in place** (`- [x] … — done YYYY-MM-DD: …`); partial work stays `- [ ]` with a dated note. Never delete items. `/close-roadmap-item` is the procedure.
- **docs/CHANGELOG.md** is reverse-chronological — add an entry for any user-visible behavior change, schema change, or new doc.
- **docs/setup/INITIAL_SETUP.md** must change in the same PR as any setup step.
- **Docs are a tree of `README.md` indexes.** Every doc-bearing folder has one listing its immediate children, with a centered footer nav back to its parent: root → `docs/README.md` → each section index → the documents. **Adding a doc means adding its row to that folder's README** — an unlinked doc is unreachable. A new doc-bearing folder gets an index and a row in its parent. Single-document folders (`docs/setup/`, `docs/testing/`) are linked directly. Down-links point at a child's index, never past it to a leaf.
- **`skills/` must stay in sync with behavior** — the CLI agents read it at runtime, so stale guidance silently misleads a live debate. On any big update, change the relevant SKILL.md in the same commit:
  - a new/changed MCP tool or its semantics → `agent-chat`
  - `debate.ps1` flags, the persona group model, or how a debate is launched → `start-debate` (plus `agent-chat`'s tool table / `debate-mode`'s persona section if tool or persona behavior shifted)
  - conversation types, seat roles, or the per-seat briefs → the matching `<type>-mode` skill (`podcast-mode`, `collaborate-mode`) **and** `_ROLE_BRIEFS` in `agent_chat_mcp.py`. **Two places, not three** — `New-AgentPrompt` in `spawn-agents.ps1` used to carry a per-role copy and no longer does; it is role-agnostic and points every agent at `get_kickoff()`'s `role_brief`, so adding a seat touches no PowerShell. `_ROLE_BRIEFS` is the single source and reaches CLIs without skills and hand-seeded runs without a launch prompt.
  - Don't reference persona slugs or group names that can be deleted. New skills auto-wire via `scripts/setup/setup-skill-links.ps1`, **but `.gitignore` needs a line** — the `.claude/skills/<name>/` exclusions are listed by name, and without one the junction gets committed as duplicate files full of this machine's paths.

- **The homepage's process-flow diagram is generated and pinned to code.** `docs/diagrams/process-flow.json` cites line ranges in `agent_chat_mcp.py`, `orchestrator/{seeding,availability,delivery,watchdog}.py` and `web/api/conversations.py`. When a change touches a conversation's life (seeding, CLI launch, kickoff, the turn loop, commit/rotation, SSE, watchdog, delivery), or CI's *Diagram drift* step warns, update the diagram in the same PR: commit the code, re-read the changed ranges, fix the JSON (line ranges, labels, edges, cards), then `.\.venv\Scripts\python.exe scripts\build_diagram.py --pin-head`, which also copies the HTML and PNG into `homepage/diagram/`. Never hand-edit the `.html`/`.png` (either copy). Steps: `docs/diagrams/README.md`.

Don't create new top-level docs unless asked; new project docs go under `docs/`.

## Git workflow

- Feature branches off `main`. Confirm the current branch with `git status` — it's often `mike_desktop`.
- **Commit style:** short imperative subject, body when needed, plain English. Conventional commits are **not** used here.
- **Never commit:** `.venv/`, `db/*.db*`, `.env*`, `__pycache__/`, `.mcp.json`, local `.claude/` state (`settings.local.json`, `local-vs-public.md`, `images/`, `rules/`, `temp/`), any nested per-CLI `.claude/`, or a seat 2+ folder (`agents/CLIs/*_agent[2-9]/` — generated per machine by `add_agent_seat.py` / `/settings` / `/orchestrate`, carries this machine's launcher path; seat 1 stays tracked). Tracked despite the mostly-ignored tree: this file and `CLAUDE.md`, plus `.claude/agents/` + `.claude/commands/` + `.claude/skills/` — except the skill entries `setup-skill-links.ps1` junctions from `skills/`, since Windows would commit those as files full of this machine's `D:` paths.
- **PRs:** small and focused, one Roadmap item each, referencing the Roadmap row. **Don't push to `main` directly** unless it's a doc-only typo fix or you're told to.

### Deploying to Fly after a push

The hosted mirror (`agent-chat-mikesailab` → `roundtable-demo.ai-automation-tools.dev`) runs **only the web UI**. **CI's `deploy` job deploys it on every push to `main`** that touches `src/web_ui.py` or `src/web/`, `requirements.txt`, `fly.toml`/`Dockerfile`, or `images/AgentChat-Avatars/` (since 2026-10-21, Mike's call: a Dependabot or sweep merge used to leave the mirror on its old image) — **only after the `test`, `test-linux` (Ubuntu / Python 3.14, the mirror's runtime) and `lint` (`ruff --select E9,F`) jobs pass** (since 2026-11-22; `ci.yml` calls `deploy-fly.yml`, which then curls the mirror's health). A PR touching those paths also builds and boots the image (`image` job), and `fly.toml`'s http check fails a deploy whose machine doesn't serve. It needs the `FLY_API_TOKEN` repo secret, a deploy token scoped to this app (`fly tokens create deploy -a agent-chat-mikesailab`); without it the job fails loudly. So **merging a web change to `main` is the deploy**. Treat it as outward-facing. By hand, for a re-run or a push the path filter misses:

```powershell
fly deploy --app agent-chat-mikesailab   # or: gh workflow run deploy-fly.yml
```

Then confirm with `fly status --app agent-chat-mikesailab` (the machine's `LAST UPDATED` should be this deploy). The workflow retries a failed deploy once.

**Ordering matters when a synced column is added:** `/api/ingest` names every synced column in its `INSERT`, so a sidecar sending a new column fails against a mirror that doesn't have it yet. Deploy the web app **before** restarting the sidecar.

**Skip the deploy** for pushes touching only docs, `scripts/`, the MCP server, `start_conversation.py`, `agents/`, or persona/DB data — none of that runs on Fly, and data reaches the mirror through the sidecar sync (`scripts/db_sync.py`), never a deploy. A manual deploy is outward-facing — confirm with the user first unless they've said to proceed.

---

<p align="center">
  <a href="README.md">↩ Maintainer rules</a> ·
  <a href="../../AGENTS.md">AGENTS.md</a> ·
  <a href="../README.md">Docs home</a>
</p>
