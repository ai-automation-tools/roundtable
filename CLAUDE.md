@AGENTS.md

# Claude Code notes

`AGENTS.md` (imported above) is the project instruction file for every agent. Edit it there, not here;
this file holds only what is specific to Claude Code.

- **Your tooling lives in `.claude/`.** Maintainer skills `agent-chat-schema`, `agent-chat-export-contract`,
  `agent-chat-web-ui`, `agent-chat-add-cli`, `agent-chat-conv-types`, `agent-chat-delivery` and
  `agent-chat-run-triage` auto-load when you touch their files. All seven are owned by this repo: edit
  them in `.claude/skills/`. Also `.claude/agents/agent-chat-docs-sync` (audit a diff for doc
  drift) and the commands `/smoke-test`, `/deploy-fly` and `/close-roadmap-item`.
- **Don't confuse `.claude/skills/` with `skills/`.** The second is read by the participating CLI agents at
  runtime, not by you while you work on the repo.
- **Seat 1 for Claude Code keeps no project `.mcp.json`.** It registers `roundtable` at user scope; a project
  `.mcp.json` makes Claude Code prompt for approval on every launch and stalls a spawned agent.
