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
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
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


def test_every_seat_is_contained_ticked_or_not() -> None:
    """Audit 2026-11-22 (RT-01): a seat reads text anyone could have written,
    so containment doesn't depend on the approvals box. Claude Code gets a
    built-in tool ALLOWLIST (--tools Read: a Bash deny-list was tried, and the
    seat used the PowerShell tool) plus a roundtable-only MCP config; Codex a
    read-only sandbox with its config.toml servers switched off; every window
    drops the sync/bridge secrets before the CLI starts."""
    if not _PWSH:
        return
    for skip in (True, False):
        cmds = _plan(skip)
        for seat in ("claude-code", "claude-code-2"):
            cmd = cmds[seat]
            assert "--tools Read --strict-mcp-config --mcp-config '" in cmd, cmd
            assert f"conv7-{seat}.mcp.json'" in cmd, cmd
            assert cmd.index("Read the file") < cmd.index("--tools"), cmd
        codex = cmds["codex"]
        assert "--sandbox read-only --ask-for-approval on-request @off" in codex, codex
        assert codex.index("$off = @(") < codex.index("codex \""), codex
        for seat, cmd in cmds.items():
            assert "Remove-Item Env:AGENT_CHAT_INGEST_TOKEN," in cmd, (seat, cmd)
            assert cmd.index("Remove-Item Env:") < cmd.index("Read the file"), (seat, cmd)


def test_the_opencode_seat_denies_everything_but_roundtable() -> None:
    cfg = json.loads((_ROOT / "agents" / "CLIs" / "opencode_agent1" / "opencode.json")
                     .read_text(encoding="utf-8"))
    perm = cfg["permission"]
    assert perm["*"] == "deny", perm
    assert perm["read"] == "allow" and perm["roundtable_*"] == "allow", perm
    assert perm["external_directory"]["*"] == "deny", perm
    assert list(cfg["mcp"]) == ["roundtable"], cfg["mcp"]


# ---------------------------------------------------------------------------
# Audit RT-21: the hard stop
# ---------------------------------------------------------------------------

def test_every_window_records_its_pid_first() -> None:
    if not _PWSH:
        return
    for seat, cmd in _plan(False).items():
        assert cmd.startswith("Set-Content -LiteralPath '"), (seat, cmd)
        assert f"conv7-{seat}.pid'" in cmd, (seat, cmd)
        assert "StartTime.ToFileTimeUtc()" in cmd, (seat, cmd)
        assert cmd.index(".pid'") < cmd.index("Set-Location"), (seat, cmd)


def test_a_seat_model_becomes_a_model_flag() -> None:
    """Audit RT-36: a seat given a model launches with --model <name>; the rest
    keep their CLI's default; a name with shell characters is refused."""
    if not _PWSH:
        return
    lib = _ROOT / "scripts" / "lib" / "spawn-agents.ps1"
    launch = Path(tempfile.mkdtemp(prefix="agentchat-model-"))

    def plan(model: str) -> subprocess.CompletedProcess:
        script = (
            f". '{lib}'; "
            "$plan = New-AgentLaunchPlan -Assignments @("
            f"[pscustomobject]@{{ Cli = 'claude-code'; Model = '{model}' }}, "
            "[pscustomobject]@{ Cli = 'codex' }) -Topic 't' -ConvId 7 "
            f"-LaunchDir '{launch}' -RepoRoot '{_ROOT}' -DryRun; "
            "$plan | ForEach-Object { $_.Cli + ' :: ' + $_.Command }")
        return subprocess.run([_PWSH, "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, text=True, encoding="utf-8", timeout=120)

    out = plan("claude-sonnet-4-5")
    assert out.returncode == 0, out.stdout + out.stderr
    lines = dict(ln.split(" :: ", 1) for ln in out.stdout.splitlines() if " :: " in ln)
    assert "claude --model 'claude-sonnet-4-5' " in lines["claude-code"], lines
    assert "--model" not in lines["codex"], lines
    bad = plan("x;calc")
    assert bad.returncode != 0 or "invalid model name" in (bad.stdout + bad.stderr), bad.stdout
    assert "invalid model name" in (bad.stdout + bad.stderr), bad.stdout + bad.stderr


def test_no_spawn_refuses_a_launch() -> None:
    if not _PWSH:
        return
    flag = Path(tempfile.mkdtemp(prefix="agentchat-nospawn-")) / "NO_SPAWN"
    lib = _ROOT / "scripts" / "lib" / "spawn-agents.ps1"
    script = (f". '{lib}'; try {{ Invoke-AgentLaunch -LaunchPlan @() ; 'launched' }} "
              "catch { 'refused: ' + $_ }")
    env = {**os.environ, "AGENT_CHAT_NO_SPAWN_FILE": str(flag)}
    run = lambda: subprocess.run([_PWSH, "-NoProfile", "-NonInteractive", "-Command", script],
                                 capture_output=True, text=True, env=env, timeout=60).stdout
    assert "launched" in run()
    flag.write_text("", encoding="utf-8")
    assert "refused: spawning is switched off" in run()


def test_close_windows_ends_the_recorded_process_and_nothing_else() -> None:
    """Stop only reaches an agent at its next MCP call; "close windows" ends
    the seat's process tree. A PID file whose start time doesn't match the live
    process (a reused PID) is never acted on."""
    if not _PWSH or sys.platform != "win32":
        return
    sys.path.insert(0, str(_ROOT / "src"))
    from orchestrator import killswitch
    launch = Path(tempfile.mkdtemp(prefix="agentchat-pids-"))
    pid_file = launch / "conv9-codex.pid"
    record = (f"Set-Content -LiteralPath '{pid_file}' -Value "
              '("$PID " + (Get-Process -Id $PID).StartTime.ToFileTimeUtc()); ')
    seat = subprocess.Popen([_PWSH, "-NoProfile", "-Command", record + "Start-Sleep 120"])
    try:
        for _ in range(100):
            if pid_file.exists() and pid_file.read_text(encoding="utf-8-sig").strip():
                break
            time.sleep(0.1)
        # A stale file pointing at a live process with another start time.
        (launch / "conv9-claude-code.pid").write_text(f"{os.getpid()} 123", encoding="utf-8")
        got = killswitch.close_seat_windows(9, launch)
        assert got == {"codex": "closed", "claude-code": "gone"}, got
        seat.wait(timeout=20)
        assert killswitch.pid_files(9, launch) == []
    finally:
        if seat.poll() is None:
            seat.kill()


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
