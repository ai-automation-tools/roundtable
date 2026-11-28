<h1 align="center">🛠️ Maintainer rules</h1>

<p align="center">
  <em>The detailed rules for changing this repo, one file per area.<br>
  <a href="../../AGENTS.md"><code>AGENTS.md</code></a> keeps the short version every agent session loads; read the file for the area you're changing.</em>
</p>

---

| Read | Before changing |
|:---|:---|
| [**The database and the MCP server**](sqlite-and-mcp.md) | the schema contract, transactions, `resolve_db_path`, history deltas, session binding, the per-agent cap |
| [**The web UI**](web-ui.md) | auth and the write secret, the read-only mirror, settings tabs, the orchestrate form, export, avatars |
| [**AgentBattleground**](battleground.md) | drafts-never-post, the panel package and `ext`, custom personas, re-capture, CORS |
| [**Delivery, notifications, the watchdog**](delivery.md) | sinks, the four call sites, `deliver_later`, opt-in scope, the read-only watchdog |
| [**Conversation types, presets, personas**](conv-types-and-personas.md) | types vs presets, roles and extra roles, deliverables, blind-first, reserved groups |
| [**Testing and validation**](testing.md) | every suite and what it covers |
| [**Docs, git and deploying**](docs-git-deploy.md) | README/ROADMAP/CHANGELOG rules, skill sync, the diagram, commits, PRs, the Fly deploy |

These were sections of `AGENTS.md` until 2026-11-22, moved here verbatim (audit RT-26: the file was 58 KB, loaded into every session and every seat).

---

## Security & operational notes

- **No auth.** Anything running the server with `--agent-id X` *is* X. Fine for local CLIs you control. Don't propose network exposure without an auth design first (the Roadmap's "shareable read-only links" item is local-LAN only by design).
- **No secrets in repo.** The root `.mcp.json` uses `${...}` env-var substitution for tokens — preserve that pattern, never inline a key.

---

## Where everything is

| Read this | For |
|:---|:---|
| [`docs/ROADMAP.md`](../ROADMAP.md) | **Priorities — read first.** Carefully maintained; closing an item ticks it in place. |
| [`docs/CHANGELOG.md`](../CHANGELOG.md) | What already changed. |
| [`README.md`](../../README.md) · [`docs/repo-layout.md`](../repo-layout.md) | End-to-end tour; the full annotated tree. |
| [`docs/diagrams/`](../diagrams/README.md) | The process-flow diagram (seed → turn loop → delivery), each node linked to its code. Rebuilt, not edited. |
| [`docs/app/how-it-works.md`](../app/how-it-works.md) | The WAL bus, turn enforcement, the long-poll, the no-auth model. |
| [`docs/app/web-ui.md`](../app/web-ui.md) | Routes, homepage design system, SSE, topic logos, avatars, export, auth, demo strip. |
| [`docs/app/export-format.md`](../app/export-format.md) | The export-bundle **contract** — read before touching `orchestrator/export.py`. |
| [`docs/app/cli-setup.md`](../app/cli-setup.md) | Which CLIs a machine has, the declaration file, and why one CLI is enough. |
| [`docs/app/personas.md`](../app/personas.md) · [`battleground.md`](../app/battleground.md) · [`kickoff-prompts.md`](../app/kickoff-prompts.md) | Persona registry; arenas + the draft gate; `get_kickoff` templates. |
| [`docs/app/settings.md`](../app/settings.md) · [`notifications.md`](../app/notifications.md) | The `/settings` tab shell and what isn't a setting; the four events and the two webhook body modes. |
| [`docs/guides/`](../guides/) | One front door per format — [debate](../guides/debate.md), [podcast](../guides/podcast.md), [online forums](../guides/online-forums.md) — each linking down to the launchers ([manual seed](../guides/start-new-chat.md) is the daily driver). Keep `ConvType.guide_url` pointed at the three. |
| [`docs/cli-mcp-config/README.md`](../cli-mcp-config/README.md) | MCP registration per CLI (project vs global) — canonical. |
| [`docs/mcp-server.md`](../mcp-server.md) | The MCP server at a glance: entry file, launcher, transport, every tool, env vars, install line. Update it when a tool is added or renamed. |
| `docs/Local/` | **Operator-only, gitignored:** the Fly deploy, the sidecar sync, logon autostart. |

**Two skill trees — don't confuse them.** [`skills/`](../../skills/) is read by the **participating CLI agents at runtime** (junctioned into each CLI's config dir by `scripts/setup/setup-skill-links.ps1`): `agent-chat` = the participation loop · `debate-mode` · `podcast-mode` · `collaborate-mode` · `battleground` · `start-debate`. [`.claude/skills/`](../../.claude/skills/) is read by **Claude Code working on this repo**: `roundtable-schema`, `roundtable-export-contract`, `roundtable-web-ui`, `roundtable-add-cli`, `roundtable-conv-types`, `roundtable-delivery`, `roundtable-run-triage` — plus `.claude/agents/agent-chat-docs-sync` (audits a diff for doc drift) and `.claude/commands/` (`/smoke-test`, `/deploy-fly`, `/close-roadmap-item`).

**Three more maintainer skills, owned here too since 2026-11-27.** `roundtable-conv-types` (conversation structure — types, presets, seat roles, deliverables), `roundtable-delivery` (sinks, notifications, the watchdog) and `roundtable-run-triage` (a live run that is stuck or misbehaving) sit in `.claude/skills/` with the other four. Until 2026-11-27 they were installed copies from `ai-automation-tools/agent-skills`; that repo no longer keeps project skills, so edit them here.

For ambiguous tasks, ask one clarifying question rather than guess — the codebase is small enough that a wrong assumption costs a six-file edit.

---

<p align="center">
  <a href="../README.md">↩ Docs home</a> ·
  <a href="../../AGENTS.md">AGENTS.md</a>
</p>
