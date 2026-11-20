r"""Tests for the launch command a spawned seat gets: an allowlist, never a bypass.

Owner's security audit (2026-10-30), Roadmap row "Default orchestrated agents
to approvals on": persona and topic text is untrusted input to an agent, so

1. ``/orchestrate`` renders its approvals box UNticked;
2. ticked, a Claude Code seat launches with ``--allowedTools mcp__roundtable``
   (and ``--add-dir`` for its prompt-file folder), placed after the prompt;
3. no seat on any CLI ever launches with a blanket bypass
   (``--dangerously-skip-permissions``, ``--yolo``, ``--auto``) — the CLIs with
   no verified allowlist flag get no flag at all and keep asking.

Cases 2-3 run the real ``scripts/orchestrate-debate.ps1 -DryRun`` (it builds
the launch plan through ``scripts/lib/spawn-agents.ps1`` and prints each
command, writing no prompt file and opening no window), so they need ``pwsh``
and skip without it. They need no venv and no DB.

    .\.venv\Scripts\python.exe tests\test_spawn_allowlist.py
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_WRAPPER = _ROOT / "scripts" / "orchestrate-debate.ps1"
_PWSH = shutil.which("pwsh")
_BYPASS = ("--dangerously-skip-permissions", "--yolo", "--auto",
           "--dangerously-bypass-approvals-and-sandbox")
_SEATS = ["claude-code", "codex", "antigravity", "opencode", "claude-code-2"]


def _plan(skip: bool) -> dict[str, str]:
    """Run the wrapper's dry run; return {agent id: its launch command}."""
    tmp = Path(tempfile.mkdtemp(prefix="agentchat-allowlist-"))
    spec = tmp / "assign.json"
    spec.write_text(json.dumps({
        "conversation_id": 7, "topic": "Allowlist smoke", "skip_permissions": skip,
        "agents": [{"cli": c, "persona_name": "", "persona_body": ""} for c in _SEATS],
    }), encoding="utf-8")
    out = subprocess.run(
        [_PWSH, "-NoProfile", "-NonInteractive", "-File", str(_WRAPPER),
         "-AssignmentsFile", str(spec), "-DryRun"],
        capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    cmds = dict(re.findall(r"#\s+(\S+)\s*\n.*?\n\s*pwsh -NoExit -Command \"(.+)\"", out.stdout))
    assert set(cmds) == set(_SEATS), out.stdout
    return cmds


def test_the_form_renders_the_approvals_box_unticked() -> None:
    from web.render.orchestrate import _render_orchestrate

    page = _render_orchestrate([])
    box = re.search(r"<input[^>]*name=\"skip_permissions\"[^>]*>", page)
    assert box, "skip_permissions checkbox missing"
    assert "checked" not in box.group(0), box.group(0)
    assert 'id="orch-skip-warn"' in page


def test_ticked_claude_code_gets_the_allowlist_after_the_prompt() -> None:
    if not _PWSH:
        return
    cmds = _plan(skip=True)
    for seat in ("claude-code", "claude-code-2"):
        cmd = cmds[seat]
        assert "--allowedTools mcp__roundtable --add-dir '" in cmd, cmd
        # variadic flags must come after the prompt or they swallow it
        assert cmd.index("Read the file") < cmd.index("--allowedTools"), cmd


def test_no_seat_ever_gets_a_blanket_bypass() -> None:
    if not _PWSH:
        return
    for skip in (True, False):
        for seat, cmd in _plan(skip).items():
            for flag in _BYPASS:
                assert f" {flag}" not in cmd, f"{seat} (skip={skip}): {cmd}"
            if not skip:
                assert "--allowedTools" not in cmd, cmd


def _main() -> int:
    if not _PWSH:
        print("NOTE  pwsh not on PATH: the launch-plan cases pass vacuously")
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {fn.__name__}: {exc!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_main())
