"""The /setup page (local) and its hosted read-only explainer.

"Which CLI tools do you have?" — the question the app used to never ask, and
then answered wrongly on the operator's behalf by offering all of them. See
:mod:`orchestrator.availability` for the model: detect, let them override,
persist.
"""

from __future__ import annotations

import html

from orchestrator import availability as avail
from orchestrator import seats as orch_seats

from web.assets import script as js_script
from web.assets import stylesheets
from web.render.common import _layout

_DOCS = "https://github.com/ai-automation-tools/roundtable/blob/main/docs/cli-mcp-config"

# Display name + where to get it, per tool. The per-CLI registration doc is the
# answer to "it's installed but the config check fails".
_CLI_META: dict[str, tuple[str, str, str]] = {
    # cli -> (display name, vendor, install/home URL)
    "claude-code": ("Claude Code", "Anthropic", "https://github.com/anthropics/claude-code"),
    "codex": ("Codex CLI", "OpenAI", "https://github.com/openai/codex"),
    "antigravity": ("Antigravity", "Google", "https://antigravity.google"),
    "opencode": ("OpenCode", "SST", "https://github.com/sst/opencode"),
}

_DOC_SLUG = {
    "claude-code": "claude.md",
    "codex": "codex.md",
    "antigravity": "antigravity.md",
    "opencode": "opencode.md",
}


def _status_row(s: avail.CliStatus) -> str:
    """One tool: a tick the operator owns, plus the two probe results."""
    name, vendor, home = _CLI_META.get(s.cli, (s.cli, "", ""))
    checked = " checked" if s.available else ""
    bin_names = " / ".join(s.binaries)
    if s.detected:
        bin_html = (
            '<span class="su-pill ok" title="'
            + html.escape(str(s.binary_path), quote=True)
            + '">on PATH</span>'
        )
    else:
        bin_html = f'<span class="su-pill off">no <code>{html.escape(bin_names)}</code></span>'
    if s.config_ok:
        cfg_html = '<span class="su-pill ok">MCP config OK</span>'
    else:
        cfg_html = (
            '<span class="su-pill warn">MCP config '
            f'{html.escape(s.failure_code or "failed")}</span>'
        )
    detail = ""
    if not s.config_ok and s.failure_detail:
        doc = f"{_DOCS}/per-cli/{_DOC_SLUG.get(s.cli, 'README.md')}"
        detail = (
            '<p class="su-detail">'
            f"{html.escape(s.failure_detail)} "
            f'<a href="{doc}" target="_blank" rel="noopener noreferrer">'
            "How to register it &#8599;</a></p>"
        )
    dep = ' <em class="su-dep">deprecated</em>' if s.deprecated else ""
    return (
        f'<div class="su-row" data-cli="{html.escape(s.cli, quote=True)}">'
        '<label class="su-main">'
        f'<input type="checkbox" name="cli" value="{html.escape(s.cli, quote=True)}"{checked}>'
        '<span class="su-names">'
        f'<span class="su-name">{html.escape(name)}{dep}</span>'
        f'<span class="su-sub">{html.escape(vendor)} &middot; '
        f'<code>{html.escape(s.cli)}</code></span>'
        "</span>"
        f'<span class="su-pills">{bin_html}{cfg_html}</span>'
        "</label>"
        f"{detail}"
        f'<p class="su-links">'
        f'<a href="{home}" target="_blank" rel="noopener noreferrer">Get {html.escape(name)} &#8599;</a>'
        "</p>"
        "</div>"
    )


def setup_body(statuses: list[avail.CliStatus], declared: bool) -> str:
    """The CLI-tools form, without the page shell.

    Split out so `/settings` can render it inside its tab strip. The tabs are
    server-side (`?tab=`), so only one tab's markup and script are ever on the
    page — which is what keeps three independent forms from colliding on
    element ids.
    """
    rows = "".join(_status_row(s) for s in statuses)
    max_seats = orch_seats.MAX_SEATS_PER_CLI

    intro_state = (
        "Saved &mdash; this is what the rest of the app offers you."
        if declared else
        "Nothing saved yet, so the ticks below are just what was <em>detected</em>. "
        "Correct them and save."
    )

    body = f"""
<div class="orch-shell su-shell">
  <header class="orch-head">
    <h1>Which CLI tools do you have?</h1>
    <p>Roundtable doesn't need all four. It needs <strong>one</strong> &mdash; a seat is
       configuration, not a program, so a single install can argue with itself. Tick what
       you actually have and everything else in the app (the orchestrate form, the
       launcher, the seat planner) will offer only those. {intro_state}</p>
  </header>

  <form id="su-form" class="orch-form">
    <section>
      <span class="lbl">Your CLIs</span>
      <p class="hint">Two probes per tool: is the launcher binary on your <code>PATH</code>,
         and does its <code>roundtable</code> MCP entry pass preflight. Your tick wins over
         both &mdash; check a tool you're about to install, uncheck one you'll never use.</p>
      <div class="su-rows">{rows}</div>
    </section>

    <section>
      <span class="lbl">What that gives you</span>
      <div class="su-plan" id="su-plan"></div>
    </section>

    <div id="su-error" class="orch-error hidden"></div>

    <button type="submit" class="orch-submit">Save my CLI setup</button>
    <p class="hint su-foot">Stored in <code>config/available-clis.json</code> (gitignored,
       this machine only). Nothing here installs anything or edits your CLI configs &mdash;
       when a tool needs registering, follow its
       <a href="{_DOCS}/README.md" target="_blank" rel="noopener noreferrer">MCP setup doc &#8599;</a>.</p>
  </form>
</div>

{js_script("setup", max_seats=str(max_seats))}
"""
    return body


#: Stylesheets this tab's markup needs, in order.
SETUP_TAB_CSS = ("orchestrate", "setup")


def _render_setup(statuses: list[avail.CliStatus], declared: bool) -> str:
    """Standalone CLI-setup page. Kept for direct callers and tests; the route
    itself now renders through `/settings`."""
    return _layout(
        "CLI setup", "", setup_body(statuses, declared),
        head_extras=stylesheets(*SETUP_TAB_CSS),
        active="settings",
    )


def _render_setup_readonly() -> str:
    """Hosted /setup — the question only has an answer on your own machine."""
    body = """
<div class="orch-shell">
  <header class="orch-head">
    <h1>CLI setup happens on your machine</h1>
    <p>This hosted site is a <strong>read-only demo</strong>. It has no CLI tools, no
       <code>PATH</code> to probe, and nothing to save &mdash; which CLIs you have is a
       fact about your own computer, so this page only does something on a local
       instance.</p>
  </header>

  <div class="orch-ro-card">
    <h2>You need exactly one CLI to start</h2>
    <p>Claude Code, Codex, Antigravity or OpenCode &mdash; any one of them. A
       participant seat is configuration rather than a separate program, so a single
       install can hold both chairs in a debate: <code>claude-code</code> against
       <code>claude-code-2</code>, two personas, one tool.</p>
  </div>

  <div class="orch-ro-card">
    <h2>Then run this page locally</h2>
    <pre><code>.\\.venv\\Scripts\\python.exe src\\web_ui.py
# then open http://127.0.0.1:8765/setup</code></pre>
    <p>It probes each tool (binary on <code>PATH</code>, MCP config valid), lets you
       correct the result, and remembers the answer.</p>
  </div>

  <p class="orch-ro-foot">Registration snippets per CLI are in the
    <a href="https://github.com/ai-automation-tools/roundtable/blob/main/docs/cli-mcp-config/README.md"
       target="_blank" rel="noopener noreferrer">MCP config reference</a>,
    or start from the
    <a href="https://github.com/ai-automation-tools/roundtable#readme" target="_blank" rel="noopener noreferrer">README</a>.</p>
</div>
"""
    return _layout(
        "CLI setup", "", body,
        head_extras=stylesheets("orchestrate", "orch-readonly"),
        active="setup",
    )
