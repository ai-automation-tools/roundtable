# Antigravity CLI — `roundtable` integration

> **Nav:** [Registration hub ↑](../README.md) · **Antigravity** deep dive · siblings: [Claude Code](claude.md) · [Codex](codex.md) · [OpenCode](opencode.md)

Register the `roundtable` MCP server with the **Antigravity** CLI (binary: `agy`) and bring it into a conversation alongside Claude Code and Codex.

> [!NOTE]
> **Antigravity replaced the Gemini CLI.** Google deprecated the Gemini CLI; Antigravity is its successor, and Roundtable's Google seat. Its seat folder is `<seat root>\antigravity_agent1\`, outside the repo, where `<seat root>` is `%LOCALAPPDATA%\Roundtable\seats\<clone folder name>\` ([where seat folders live](../../app/cli-setup.md#where-seat-folders-live)); it is copied from the template `agents/CLIs/antigravity_agent1/`. Agent-id `antigravity`.

---

## 📂 Where Antigravity reads MCP config

| Scope | File | Notes |
|:--|:--|:--|
| **project** | `.agents/mcp_config.json` (relative to launch dir) | per-folder; for this seat `<seat root>/antigravity_agent1/.agents/mcp_config.json`, written from the template `agents/CLIs/antigravity_agent1/.agents/mcp_config.json` |
| **global** | `~/.gemini/config/mcp_config.json` | shared by Antigravity 2.0, the IDE, and the CLI |

Both use a top-level `mcpServers` object. As of `agy` v1.1.16, `agy mcp add` / `remove` / `list` / `enable` / `disable` exist — but they manage the **global** `~/.gemini/config/mcp_config.json` only. The **project**-scope file this repo actually uses still has no CLI command: edit the JSON directly, or use the `/mcp` slash command (the "MCP server manager") inside an `agy` session.

In this repo, `.agents/mcp_config.json` is the one file in `.agents/` that's **tracked in git** (it holds the `roundtable` config) — so any secret in it (e.g. GitHub) **must** use `${ENV_VAR}` substitution, never an inlined key. The rest of `.agents/` is gitignored.

> [!IMPORTANT]
> Any other server in this `mcp_config.json` that needs a token reads it via `${ENV_VAR}` — e.g. `github` uses `${GITHUB_TOKEN}`. Set those env vars (e.g. `$env:GITHUB_TOKEN = "..."`) or remove the servers you don't use — an unset variable makes that server fail to start.

---

## Project-level registration

Add `roundtable` inside the `mcpServers` object of the template `agents/CLIs/antigravity_agent1/.agents/mcp_config.json` (preserve any other servers). `add_agent_seat.py --materialize` rewrites the seat copy from the template with this clone's launcher path, so edit the template, not the copy:

```json
"roundtable": {
  "command": "pwsh",
  "args": [
    "-NoProfile",
    "-File",
    "<repo>/scripts/run-mcp-server.ps1",
    "antigravity"
  ]
}
```

Launching `agy` from `<seat root>/antigravity_agent1/` is what activates it. `.\.venv\Scripts\python.exe scripts\setup\add_agent_seat.py --materialize` prints the folder.

> [!NOTE]
> The launcher resolves the venv interpreter and server script relative to its own location, so the launcher path is the only hardcoded string. `--db-path` is optional (defaults to `<repo>/db/chat.db`; `$env:AGENT_CHAT_DB` overrides); append it after `"antigravity"` in `args` to set one explicitly.

> [!WARNING]
> **Verify project-local loading in your installed version.** An upstream issue ([antigravity-cli #60](https://github.com/google-antigravity/antigravity-cli/issues/60)) reported a project-local `mcp_config.json` being *discovered but silently ignored*, with only the global file spawning servers. That report referenced an older path, so it may be stale — but smoke-test that a server defined **only** in `.agents/mcp_config.json` shows up under `/mcp`. If it doesn't, register globally instead.

<details>
<summary><b>macOS/Linux variant</b> — use the <code>.sh</code> launcher, no <code>pwsh</code> needed</summary>

```json
"roundtable": {
  "command": "/abs/path/to/roundtable/scripts/run-mcp-server.sh",
  "args": ["antigravity"]
}
```

The `.sh` ships with the +x bit set in the git index.

</details>

---

## Global-level registration

To make `roundtable` available to **every** Antigravity session, put the same `roundtable` block inside the `mcpServers` object of the global config:

```
~/.gemini/config/mcp_config.json
C:\Users\<you>\.gemini\config\mcp_config.json     # Windows
```

> [!NOTE]
> The global file lives under `~/.gemini/`, **not** `~/.antigravity/` — Antigravity inherited Gemini's config root. (A legacy pre-migration path `~/.gemini/antigravity-cli/mcp_config.json` still appears in older guides; newer official codelabs use `~/.gemini/config/mcp_config.json`.)

---

## ✅ Verify

Launch `agy` from the workspace and use the `/mcp` slash command (the "MCP server manager") to confirm `roundtable` is listed, or ask the agent directly:

> Do you see an MCP server called roundtable? List the tools it exposes.

You should get back the `roundtable` tools — `get_kickoff`, `wait_for_turn`, `get_my_turn`, `send_message`, `list_personas`, `get_persona`, `get_conversation_status`. If not, check:

1. The JSON parses — `python -m json.tool <seat root>/antigravity_agent1/.agents/mcp_config.json`.
2. `pwsh` resolves on PATH and the launcher path exists.
3. `db/chat.db` exists or can be auto-created.
4. You launched from the seat folder `<seat root>/antigravity_agent1/` — not the repo root or the template folder.

Editing the config likely needs a restart (hot-reload is undocumented).

---

## ▶️ Run a 3-agent conversation

<details>
<summary>Seed + drive a claude-code · codex · antigravity run</summary>

Once all three CLIs have `roundtable` registered:

1. Seed a 3-participant conversation:

   ```powershell
   .\.venv\Scripts\python.exe src\start_conversation.py `
     --topic "<your topic>" `
     --participants claude-code,codex,antigravity `
     --first claude-code --mode turns --max-turns 5
   ```
   (DB defaults to `<repo>/db/chat.db`; pass `--db-path` or set `$env:AGENT_CHAT_DB` to override.)

   The `--participants` order defines turn rotation. With `--first claude-code` the cycle is `claude-code → codex → antigravity → …`, and `wait_for_turn` blocks each agent until the pointer lands on it.

2. Open all three CLIs in separate terminals (each from its own seat folder, `<seat root>/<name>_agent1/`).
3. Ask each agent to call `get_kickoff()` once, then drive itself through the `wait_for_turn` → `send_message` loop (see `prompts/Kickoff/kickoff.md` / the `agent-chat` skill).
4. Start the `--first` agent first.
5. Watch live at `http://127.0.0.1:8765/` (run `src/web_ui.py` in a fourth terminal).

</details>

---

## 🤖 Headless / auto-spawn

The `scripts/debate.ps1` launcher registers `antigravity` (via `agy`) in its `$Clis` launch table. **Since 2026-11-23 every launch is contained (audit RT-01):** `agy -i "<prompt>" --sandbox --settings <file>`, where `<file>` (`db/launch/conv<id>-antigravity.agy-settings.json`) is a session-only settings layer `agy` never saves:

```json
{
  "toolPermission": "request-review",
  "enableTerminalSandbox": true,
  "permissions": {
    "allow": ["mcp(roundtable/*)", "read_file(<repo>\\db\\launch)"],
    "deny":  ["command(*)", "write_file(*)", "read_url(*)", "execute_url(*)", "mcp(<every other server>/*)"]
  }
}
```

Rules resolve Deny > Ask > Allow, so the other MCP servers are denied by name (read from `~/.gemini/antigravity-cli/mcp_config.json` and the seat's `.agents/mcp_config.json` at launch); one added later falls to Ask, a prompt, never a silent call. `request-review` overrides a global or seat-level `always-proceed`; `strict` would also prompt for the allowed roundtable tools. Verified live against `agy` 1.5.15: shell and file writes come back "Permission denied (matches user-configured deny rule)", a denied server's tool is refused, and the roundtable tools run without a prompt. Two gaps remain: `agy`'s built-in web **search** is not a `read_url` call and stays available, and `agy` can still write in its own scratch folder (`~/.gemini/antigravity-cli/scratch`). `-SkipPermissions` adds nothing for `agy`. An operator who accepts the risk on their own machine can still bypass approvals by hand, two ways:

- The `--dangerously-skip-permissions` flag, typed on your own launch command:
  ```powershell
  agy --dangerously-skip-permissions -i "Read the file at '...' and follow it."
  ```
- Persistently, via `.agents/settings.json` in the seat folder (`<seat root>/antigravity_agent1/.agents/settings.json`, outside the repo; `--materialize` leaves it alone). This is for a launch you type yourself: `debate.ps1` and `/orchestrate` start the seat with `--sandbox --settings <file>`, a session-only settings file whose deny rules block shell commands, file writes, URL reads and every MCP server but `roundtable`:
  ```json
  {
    "model": "gemini-3.5-flash",
    "toolPermission": "always-proceed",
    "artifactReviewPolicy": "always-proceed",
    "enableTerminalSandbox": false,
    "allowNonWorkspaceAccess": false,
    "colorScheme": "terminal",
    "verbosity": "high"
  }
  ```

---

## ⚠️ Known quirks

- **Config reload.** Editing `mcp_config.json` while Antigravity is running may not hot-reload the server list — relaunch after any change.
- **Three-way turn skipping.** With three participants the rotation must wrap correctly. Watch for `current_turn` landing on the wrong agent after a `send_message`.

---

## 📚 Vendor documentation

Antigravity is newer and its docs move; if this page stops matching, check the source:

- Antigravity docs — <https://antigravity.google/docs>
- MCP in Antigravity (codelab) — <https://codelabs.developers.google.com/developer-knowledge-mcp-antigravity>
- `antigravity-cli` issues (project-local config behavior) — <https://github.com/google-antigravity/antigravity-cli/issues>
