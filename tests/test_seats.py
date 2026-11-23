r"""Tests for multi-seat agent ids — two participants on the same CLI tool.

A seat id (`codex-2`) is a *string convention* that four separate layers have to
agree on, three of them in different languages:

- ``orchestrator/seats.py`` parses it and names the config folder,
- ``orchestrator/preflight.py`` checks that folder's MCP config,
- ``scripts/lib/spawn-agents.ps1`` resolves it to a launch directory (PowerShell),
- ``scripts/setup/add_agent_seat.py`` creates the folder in the first place.

Drift between them fails quietly — a seat launches from the wrong folder and
simply joins as the *other* seat, which looks like a turn-order bug three
layers away. Hence the parity checks at the bottom.

Runs under pytest *or* standalone with the project venv (no pytest needed):

    .\.venv\Scripts\python.exe tests\test_seats.py
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from orchestrator import preflight, seats  # noqa: E402


def _restore_env(name: str, value) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def _load_add_agent_seat():
    spec = importlib.util.spec_from_file_location(
        "_add_agent_seat_under_test", _ROOT / "scripts" / "setup" / "add_agent_seat.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# The id grammar
# ---------------------------------------------------------------------------

def test_bare_cli_ids_are_seat_one():
    for cli in seats.SUPPORTED_CLIS:
        assert seats.parse_seat(cli) == (cli, 1)
        assert seats.seat_id(cli, 1) == cli, "seat 1 must keep the bare id"


def test_numbered_seats_parse():
    assert seats.parse_seat("claude-code-2") == ("claude-code", 2)
    assert seats.parse_seat("codex-5") == ("codex", 5)
    assert seats.seat_id("codex", 3) == "codex-3"


def test_rejected_ids():
    # "-1" is not a spelling of seat 1 — one spelling per seat, so participant
    # lists and message senders stay comparable.
    assert seats.parse_seat("codex-1") is None
    assert seats.parse_seat("codex-6") is None      # past MAX_SEATS_PER_CLI
    assert seats.parse_seat("codex-0") is None
    assert seats.parse_seat("codex-x") is None
    assert seats.parse_seat("not-a-cli") is None
    assert seats.parse_seat("") is None
    assert seats.parse_seat("  ") is None


def test_a_tool_name_ending_in_a_digit_would_still_parse():
    """Parsing splits on the known tool list, not on a trailing-digit regex.

    Nothing in SUPPORTED_CLIS ends in a digit today; this pins the property so
    adding a `gpt-5`-style tool later doesn't silently turn it into seat 5 of
    a tool called `gpt`.
    """
    original = seats.SUPPORTED_CLIS
    try:
        seats.SUPPORTED_CLIS = original + ("gpt-5",)
        assert seats.parse_seat("gpt-5") == ("gpt-5", 1)
        assert seats.parse_seat("gpt-5-2") == ("gpt-5", 2)
    finally:
        seats.SUPPORTED_CLIS = original


def test_seat_folders():
    assert seats.seat_folder("claude-code") == "claude-code_agent1"
    assert seats.seat_folder("claude-code-2") == "claude-code_agent2"
    try:
        seats.seat_folder("nope")
    except seats.SeatError:
        pass
    else:
        raise AssertionError("expected SeatError for an unrecognised id")


def test_validate_seats_reports_the_bad_one():
    seats.validate_seats(["claude-code", "codex-2"])
    try:
        seats.validate_seats(["claude-code", "gpt-9"])
    except seats.SeatError as e:
        assert "gpt-9" in str(e)
    else:
        raise AssertionError("expected SeatError")


# ---------------------------------------------------------------------------
# Preflight routes a seat to its own config
# ---------------------------------------------------------------------------

def test_preflight_checks_each_seats_own_folder():
    """Seat 2 must be checked against seat 2's config, not seat 1's.

    Asserted on the reported ``config_path`` so this holds whether or not the
    operator has actually created the folder on this machine.

    Seat 1 is deliberately *not* asserted here: for Claude Code and Codex it may
    legitimately resolve to a machine-wide config instead of the seat folder —
    see ``test_claude_code_seat_one_accepts_a_user_scope_registration``.
    """
    results = {r.cli: r for r in preflight.run_preflight(
        ["claude-code-2", "opencode-3"]
    )}
    assert "claude-code_agent2" in results["claude-code-2"].config_path
    assert "opencode_agent3" in results["opencode-3"].config_path


def _claude_entry(launcher: Path, agent_id: str) -> dict:
    return {"command": "pwsh",
            "args": ["-NoProfile", "-File", str(launcher), agent_id]}


def test_claude_code_seat_one_accepts_a_user_scope_registration(monkeypatch=None):
    """`claude mcp add --scope user` is a valid way to register roundtable.

    Claude Code was project-scope-only while Codex seat 1 had always read the
    global ``~/.codex/config.toml``. An operator who consolidates their MCP
    servers at user level should not have seat 1 disappear from /orchestrate.
    """
    launcher = _ROOT / "scripts" / "run-mcp-server.ps1"
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / ".claude.json").write_text(
            json.dumps({"mcpServers": {"roundtable": _claude_entry(launcher, "claude-code")}}),
            encoding="utf-8",
        )
        real_home, real_root = Path.home, os.environ.get(seats.SEATS_DIR_ENV)
        Path.home = staticmethod(lambda: home)      # type: ignore[assignment]
        # Point project scope at an empty tree, so only user scope can satisfy
        # the check — and so this does not depend on which seat folders happen
        # to exist in the working copy.
        os.environ[seats.SEATS_DIR_ENV] = str(home)
        try:
            r = preflight.check_claude_code("claude-code")
        finally:
            Path.home = real_home
            _restore_env(seats.SEATS_DIR_ENV, real_root)
    # Either scope may satisfy it; what matters is that a user-scope-only
    # machine passes rather than reporting no_mcp_entry.
    assert r.ok, [f.code for f in r.failures]


def test_claude_code_seat_two_will_not_take_the_user_scope_entry():
    """User scope carries ONE agent id, so it can only ever serve seat 1.

    A seat 2 that silently inherited seat 1's registration would launch a second
    window posting as ``claude-code`` — two seats, one identity, broken turn
    order. It must be told to register in project scope instead.
    """
    launcher = _ROOT / "scripts" / "run-mcp-server.ps1"
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / ".claude.json").write_text(
            json.dumps({"mcpServers": {"roundtable": _claude_entry(launcher, "claude-code")}}),
            encoding="utf-8",
        )
        real_home, real_root = Path.home, os.environ.get(seats.SEATS_DIR_ENV)
        Path.home = staticmethod(lambda: home)      # type: ignore[assignment]
        # Isolate project scope too. Creating a real claude-code_agent2 is now
        # possible (add_agent_seat synthesizes its config from the user-scope
        # entry), and reading the live tree made this assert on the machine
        # rather than on the rule.
        os.environ[seats.SEATS_DIR_ENV] = str(home)
        try:
            r = preflight.check_claude_code("claude-code-2")
        finally:
            Path.home = real_home
            _restore_env(seats.SEATS_DIR_ENV, real_root)
    assert not r.ok
    assert "claude-code_agent2" in r.config_path
    assert "project" in r.failures[0].detail.lower()


def test_a_config_registered_with_the_wrong_agent_id_fails():
    """Identity is config-only, so a mismatched id is impersonation, not a typo.

    Every other check would pass this entry — the command resolves, the launcher
    exists — and the seat would simply post under someone else's name.
    """
    launcher = _ROOT / "scripts" / "run-mcp-server.ps1"
    r = preflight._check_mcp_entry(
        "codex-2", Path("somewhere/.mcp.json"), _claude_entry(launcher, "claude-code")
    )
    assert not r.ok
    codes = [f.code for f in r.failures]
    assert "agent_id_mismatch" in codes, codes

    ok = preflight._check_mcp_entry(
        "codex-2", Path("somewhere/.mcp.json"), _claude_entry(launcher, "codex-2")
    )
    assert ok.ok, [f.code for f in ok.failures]


def test_agent_id_extraction_covers_every_documented_shape():
    """And returns None rather than guessing when there is no id to read."""
    ex = preflight._extract_agent_id
    assert ex("pwsh", ["-NoProfile", "-File", "D:/x/run-mcp-server.ps1", "codex"]) == "codex"
    assert ex("D:/x/run-mcp-server.sh", ["claude-code-2"]) == "claude-code-2"
    # An explicit flag wins over positional inference.
    assert ex("python", ["-m", "agent_chat_mcp", "--agent-id", "codex-2"]) == "codex-2"
    # Unknown is not wrong — no id to read must not raise or invent one.
    assert ex("pwsh", ["-NoProfile", "-File", "D:/x/run-mcp-server.ps1"]) is None


def test_no_seat_config_carries_the_wrong_agent_id():
    """Guards the configs this repo ships against an identity mix-up.

    Deliberately narrower than "preflight passes": CI has no MCP registration
    at all, so asserting `ok` here would be asserting a property of the
    developer's machine. A *mismatched* id, on the other hand, is a real defect
    wherever it is found — a config edited to the wrong seat, or a launcher
    rename that shifted the trailing argument.
    """
    for cli in seats.SUPPORTED_CLIS:
        r = preflight._CHECKS[cli](cli)
        assert "agent_id_mismatch" not in [f.code for f in r.failures], \
            f"{cli}: {[f.detail for f in r.failures]}"


def test_preflight_rejects_a_non_seat():
    (result,) = preflight.run_preflight(["definitely-not-a-cli"])
    assert not result.ok
    assert result.failures[0].code == "unknown_cli"


def test_codex_seats_get_their_own_codex_home():
    """Codex ignores per-folder config, so seat 2+ relocates CODEX_HOME."""
    assert preflight.codex_home("codex") is None, "seat 1 uses the global config"
    home = preflight.codex_home("codex-2")
    assert home is not None and home.name == ".codex"
    assert "codex_agent2" in str(home)
    # ...and preflight looks there rather than at ~/.codex.
    (result,) = preflight.run_preflight(["codex-2"])
    assert "codex_agent2" in result.config_path


# ---------------------------------------------------------------------------
# Seats inherit their tool's identity where they have none of their own
# ---------------------------------------------------------------------------

def test_seat_avatars_fall_back_to_the_tools_brand_art():
    from web.avatars import _art_slugs

    assert _art_slugs("codex") == ["codex"]
    assert _art_slugs("codex-2") == ["codex-2", "codex"]
    # A persona slug is not a seat and must never acquire a fallback.
    assert _art_slugs("crypto-chad") == ["crypto-chad"]


def test_seat_model_cards_fall_back_to_the_tools_card():
    """`codex-2` runs the same model as `codex`, so it shows the same card."""
    import tempfile

    import web.db as webdb
    from orchestrator import model_personas

    tmp = Path(tempfile.mkdtemp(prefix="agentchat-seats-")) / "chat.db"
    webdb.set_db_path(str(tmp))   # also exports AGENT_CHAT_DB, which personas reads
    webdb.db_init()
    model_personas.ensure_model_personas()

    entries = model_personas.model_persona_entries(["codex", "codex-2"])
    assert set(entries) == {"codex", "codex-2"}
    assert entries["codex-2"]["persona_name"] == entries["codex"]["persona_name"]
    # The fallback must not invent a card for something that isn't a seat.
    assert model_personas.model_persona_entries(["not-a-cli"]) == {}


# ---------------------------------------------------------------------------
# Cross-layer parity
# ---------------------------------------------------------------------------

def test_every_supported_cli_can_be_preflighted_and_seated():
    add_agent_seat = _load_add_agent_seat()
    assert set(preflight._CHECKS) == set(seats.SUPPORTED_CLIS), \
        "preflight._CHECKS and SUPPORTED_CLIS have drifted"
    assert set(add_agent_seat.SHAPES) == set(seats.SUPPORTED_CLIS), \
        "add_agent_seat.SHAPES and SUPPORTED_CLIS have drifted — a tool with no " \
        "shape entry can never get a second seat"


def test_powershell_resolver_shares_the_folder_convention():
    """`Resolve-AgentSeat` in PowerShell must derive the same folder names.

    The seat cap and CODEX_HOME are checked textually; the folder itself is
    checked for real by ``test_powershell_and_python_agree_on_the_seat_root``.
    """
    ps1 = (_ROOT / "scripts" / "lib" / "spawn-agents.ps1").read_text(encoding="utf-8")
    assert "function Resolve-AgentSeat" in ps1
    assert '"$($cli)_agent$seat"' in ps1, \
        "the PowerShell seat resolver no longer derives <cli>_agent<N>"
    assert f"$seat -gt {seats.MAX_SEATS_PER_CLI}" in ps1, \
        f"PowerShell seat cap disagrees with MAX_SEATS_PER_CLI={seats.MAX_SEATS_PER_CLI}"
    assert "CODEX_HOME" in ps1, "Codex seat 2+ needs its CODEX_HOME set at launch"
    for cli in seats.SUPPORTED_CLIS:
        assert seats.template_dir(cli).is_dir(), f"{cli} has no tracked seat template"


# ---------------------------------------------------------------------------
# Seat folders live outside the repo (audit RT-01)
# ---------------------------------------------------------------------------

def test_the_seat_root_is_outside_the_repo_and_overridable():
    """A CLI loads every CLAUDE.md/AGENTS.md above where it starts; the repo's
    tell a developer agent to work on this codebase."""
    real = os.environ.pop(seats.SEATS_DIR_ENV, None)
    try:
        root = seats.seat_root()
        assert not root.resolve().is_relative_to(_ROOT.resolve()), root
        assert root.name == _ROOT.name and root.parent.name == "seats", root
        assert _ROOT.resolve() not in [p.parent for p in seats.instruction_files_above(root)]
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[seats.SEATS_DIR_ENV] = tmp
            assert seats.seat_root() == Path(os.path.abspath(tmp))
            assert seats.seat_dir("codex-2") == Path(os.path.abspath(tmp)) / "codex_agent2"
    finally:
        _restore_env(seats.SEATS_DIR_ENV, real)


def test_powershell_and_python_agree_on_the_seat_root():
    """One rule, two languages: Resolve-AgentSeat's Dir == seats.seat_dir()."""
    pwsh = shutil.which("pwsh")
    if not pwsh:
        print("SKIP  no pwsh")
        return
    lib = _ROOT / "scripts" / "lib" / "spawn-agents.ps1"
    ids = ("claude-code", "codex-2", "opencode-5")
    script = (f". '{lib}'; foreach ($s in {', '.join(repr(i) for i in ids)}) "
              f"{{ (Resolve-AgentSeat -AgentId $s -RepoRoot '{_ROOT}').Dir }}")
    real = os.environ.pop(seats.SEATS_DIR_ENV, None)
    try:
        for override in (None, tempfile.mkdtemp(prefix="agentchat-seatroot-")):
            env = {k: v for k, v in os.environ.items() if k != seats.SEATS_DIR_ENV}
            if override:
                env[seats.SEATS_DIR_ENV] = override
                os.environ[seats.SEATS_DIR_ENV] = override
            out = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", script],
                                 capture_output=True, text=True, env=env, timeout=60)
            assert out.returncode == 0, out.stderr
            want = [str(seats.seat_dir(s)) for s in ids]
            assert out.stdout.splitlines() == want, (override, out.stdout, want)
    finally:
        _restore_env(seats.SEATS_DIR_ENV, real)


def test_no_seat_template_carries_a_machine_path():
    """The templates name the launcher as <repo>/...; materialize fills it in."""
    configs = list((_ROOT / "agents" / "CLIs").glob("*_agent1/**/*.json"))
    configs += list((_ROOT / "agents" / "CLIs").glob("*_agent1/.agents/*.json"))
    assert configs, "no tracked seat config found"
    for cfg in configs:
        text = cfg.read_text(encoding="utf-8")
        assert "<repo>/scripts/run-mcp-server.ps1" in text, cfg
        assert ":/" not in text.replace("https://", ""), f"{cfg} carries an absolute path"


def test_materialize_fills_the_seat_root_keeps_local_state_and_trusts_once():
    mod = _load_add_agent_seat()
    launcher = (_ROOT / "scripts" / "run-mcp-server.ps1").as_posix()
    real_env, real_home = os.environ.get(seats.SEATS_DIR_ENV), Path.home
    with tempfile.TemporaryDirectory() as tmp:
        root, home = Path(tmp) / "seats", Path(tmp) / "home"
        (home / ".gemini" / "antigravity-cli").mkdir(parents=True)
        # A lone surrogate, as a real ~/.claude.json can hold: must round-trip.
        (home / ".claude.json").write_text('{"projects": {}, "other": 1, "half": "\\udc8f"}',
                                           encoding="utf-8")
        agy = home / ".gemini" / "antigravity-cli" / "settings.json"
        agy.write_text('{"trustedWorkspaces": ["X:/kept"]}', encoding="utf-8")
        codex = home / ".codex" / "config.toml"
        codex.parent.mkdir()
        codex.write_text('# keep me\nmodel = "x"\n', encoding="utf-8")
        os.environ[seats.SEATS_DIR_ENV] = str(root)
        Path.home = staticmethod(lambda: home)      # type: ignore[assignment]
        try:
            # A seat-2 folder made by a clone elsewhere: its launcher path moves.
            two = root / "claude-code_agent2"
            two.mkdir(parents=True)
            (two / ".mcp.json").write_text(json.dumps({"mcpServers": {"roundtable": {
                "command": "pwsh",
                "args": ["-NoProfile", "-File", "D:/old/clone/scripts/run-mcp-server.ps1",
                         "claude-code-2"]}}}), encoding="utf-8")
            done = mod.materialize(trust=False)
            assert "hasTrust" not in (home / ".claude.json").read_text(encoding="utf-8")
            assert seats.seat_dir("claude-code-2") in done and len(done) == 5, done

            ag = json.loads((root / "antigravity_agent1" / ".agents" / "mcp_config.json")
                            .read_text(encoding="utf-8"))["mcpServers"]["roundtable"]["args"]
            assert ag[-2:] == [launcher, "antigravity"], ag
            oc = json.loads((root / "opencode_agent1" / "opencode.json").read_text(encoding="utf-8"))
            assert oc["mcp"]["roundtable"]["command"][-2:] == [launcher, "opencode"], oc
            assert oc["permission"]["*"] == "deny", "the template's limits must carry over"
            c2 = json.loads((two / ".mcp.json").read_text(encoding="utf-8"))
            assert c2["mcpServers"]["roundtable"]["args"][-2:] == [launcher, "claude-code-2"], c2
            for cli, doc in (("claude-code", "claude.md"), ("codex", "AGENTS.md")):
                assert (root / f"{cli}_agent1" / doc).read_text(encoding="utf-8") == \
                    (seats.template_dir(cli) / doc).read_text(encoding="utf-8")

            # Local state survives later runs.
            local = root / "claude-code_agent1" / ".claude" / "settings.local.json"
            local.write_text(json.dumps({"permissions": {"allow": ["mcp__roundtable"]},
                                         "enabledMcpjsonServers": ["roundtable"],
                                         "env": {"KEEP": "1"}}), encoding="utf-8")
            (root / "codex_agent1" / ".codex").mkdir()
            (root / "codex_agent1" / ".codex" / "auth.json").write_text("{}", encoding="utf-8")
            mod.materialize()
            mod.materialize()
            assert json.loads(local.read_text(encoding="utf-8"))["env"] == {"KEEP": "1"}
            assert (root / "codex_agent1" / ".codex" / "auth.json").exists()

            claude = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
            for seat in ("claude-code", "claude-code-2"):
                key = mod.claude_trust_key(seats.seat_dir(seat))
                assert claude["projects"][key]["hasTrustDialogAccepted"] is True, claude
            assert claude["other"] == 1, "the rest of ~/.claude.json must survive"
            assert claude["half"] == "\udc8f", claude["half"]
            trusted = json.loads(agy.read_text(encoding="utf-8"))["trustedWorkspaces"]
            assert trusted == ["X:/kept", str(seats.seat_dir("antigravity"))], trusted
            # Codex shows its folder-access screen even with --sandbox set.
            text = codex.read_text(encoding="utf-8")
            assert text.startswith('# keep me\nmodel = "x"\n'), text
            import tomllib
            projects = tomllib.loads(text)["projects"]
            assert projects == {mod.codex_trust_key(seats.seat_dir("codex")):
                                {"trust_level": "trusted"}}, projects
        finally:
            Path.home = real_home
            _restore_env(seats.SEATS_DIR_ENV, real_env)


def test_materialize_refuses_a_seat_root_inside_the_repo():
    mod = _load_add_agent_seat()
    real = os.environ.get(seats.SEATS_DIR_ENV)
    os.environ[seats.SEATS_DIR_ENV] = str(_ROOT / "agents" / "CLIs")
    try:
        mod.materialize(trust=False)
    except mod.SeatSetupError as e:
        assert "inside the repo" in str(e), e
    else:
        raise AssertionError("a seat root inside the repo must be refused")
    finally:
        _restore_env(seats.SEATS_DIR_ENV, real)


# ---------------------------------------------------------------------------
# Seat 2 from a tool that keeps no seat-1 file
# ---------------------------------------------------------------------------
# A seat is created by cloning seat 1's config and rewriting the agent id. Two
# tools have no seat-1 file to clone: Codex's seat 1 *is* ~/.codex/config.toml,
# and Claude Code's may be a user-scope entry in ~/.claude.json with no project
# .mcp.json at all — which is the documented, recommended setup here, because a
# project-scope file makes Claude Code prompt for approval on every launch and
# silently stall a spawned agent. Cloning a file that must not exist raised
# "seat 1's config not found" on every machine, including a fresh clone (where
# .mcp.json is gitignored too), so the flagship CLI could not have a second seat.


_FAKE_USER_ENTRY = {
    "type": "stdio",
    "command": "pwsh",
    "args": ["-NoProfile", "-File", "C:/repo/scripts/run-mcp-server.ps1", "claude-code"],
    "env": {},
}


def test_a_second_claude_code_seat_is_built_from_the_user_scope_entry():
    """No seat-1 .mcp.json + a user-scope registration = a usable seat 2."""
    mod = _load_add_agent_seat()
    shape = dataclasses.replace(
        mod.SHAPES["claude-code"], user_scope_entry=lambda: _FAKE_USER_ENTRY
    )
    with tempfile.TemporaryDirectory() as tmp:
        # An empty seat-1 folder is the whole point: there is nothing to clone.
        text, label = mod._seat_one_config_text("claude-code", shape, Path(tmp))

    doc = json.loads(text)
    assert doc["mcpServers"]["roundtable"] == _FAKE_USER_ENTRY, doc
    assert "user-scope" in label, label
    # Only the roundtable entry crosses over — ~/.claude.json is the operator's
    # whole Claude Code state and none of the rest belongs in a seat folder.
    assert list(doc) == ["mcpServers"], doc
    assert list(doc["mcpServers"]) == ["roundtable"], doc

    # ...and the synthesized doc is something the id rewriter can work on.
    out = json.loads(mod._rewrite_json(text, shape, "claude-code", "claude-code-2"))
    assert out["mcpServers"]["roundtable"]["args"][-1] == "claude-code-2", out


def test_a_tool_registered_nowhere_names_the_two_places_it_looked():
    """The error has to be actionable: it used to name only a file that must not exist."""
    mod = _load_add_agent_seat()
    shape = dataclasses.replace(mod.SHAPES["claude-code"], user_scope_entry=lambda: None)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            mod._seat_one_config_text("claude-code", shape, Path(tmp))
        except mod.SeatSetupError as e:
            msg = str(e)
        else:
            raise AssertionError("expected SeatSetupError when nothing is registered")
    assert "user scope" in msg, msg
    assert ".mcp.json" in msg, msg


def test_a_claude_code_seat_pre_approves_agent_chat_and_keeps_existing_rules():
    """A generated seat must not prompt on send_message, nor clobber hand-added rules."""
    mod = _load_add_agent_seat()
    with tempfile.TemporaryDirectory() as tmp:
        seat = Path(tmp)
        path = mod._allow_agent_chat_tools(seat)          # fresh folder
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["permissions"]["allow"] == ["mcp__roundtable"], doc
        assert doc["enabledMcpjsonServers"] == ["roundtable"], doc

        path.write_text(json.dumps({
            "permissions": {"allow": ["Bash(git status)"]},
            "enabledMcpjsonServers": ["notion"],
            "env": {"X": "1"},
        }), encoding="utf-8")
        mod._allow_agent_chat_tools(seat)
        mod._allow_agent_chat_tools(seat)                 # idempotent
        doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["permissions"]["allow"] == ["Bash(git status)", "mcp__roundtable"], doc
    assert doc["enabledMcpjsonServers"] == ["notion", "roundtable"], doc
    assert doc["env"] == {"X": "1"}, doc


def test_a_seat_one_file_still_wins_over_the_user_scope_entry():
    """Project scope is authoritative when it exists — same precedence as preflight."""
    mod = _load_add_agent_seat()
    shape = dataclasses.replace(
        mod.SHAPES["claude-code"], user_scope_entry=lambda: _FAKE_USER_ENTRY
    )
    own = {"mcpServers": {"roundtable": {"command": "pwsh", "args": ["from-the-folder"]}}}
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / shape.config_rel).write_text(json.dumps(own), encoding="utf-8")
        text, label = mod._seat_one_config_text("claude-code", shape, Path(tmp))
    assert json.loads(text) == own, text
    assert "user-scope" not in label, label


def test_every_tool_whose_seat_one_lives_outside_the_folder_declares_a_fallback():
    """Parity: preflight's non-folder seat-1 sources ↔ SHAPES' clone sources.

    ``check_claude_code`` falls back to ~/.claude.json and ``check_codex`` reads
    ~/.codex/config.toml, so for those two a passing seat-1 preflight does NOT
    imply a file in the seat folder. Each must therefore declare where seat 2 is
    cloned from. Adding a CLI that registers globally means adding a fallback
    here too — otherwise its second seat fails the way Claude Code's did.
    """
    mod = _load_add_agent_seat()
    with_fallback = {
        cli for cli, shape in mod.SHAPES.items()
        if shape.source_override is not None or shape.user_scope_entry is not None
    }
    assert with_fallback == {"claude-code", "codex"}, with_fallback
    # And the rest must keep their config in the seat folder, since that is the
    # only place their preflight looks.
    for cli, shape in mod.SHAPES.items():
        if cli in with_fallback:
            continue
        assert shape.config_rel, cli


def test_generated_seat_folders_are_gitignored_and_seat_one_is_not():
    """Seat 2+ folders are written by the app on launch and hold this machine's
    launcher path, so git must ignore them; seat 1 is tracked on purpose.

    ``--no-index`` asks what the *rules* say rather than what the index holds,
    so tracked seat-1 files are checked against the pattern too. Skipped where
    there is no git checkout (the Fly image has none).
    """
    if not shutil.which("git") or not (_ROOT / ".git").exists():
        print("SKIP  no git checkout")
        return
    mod = _load_add_agent_seat()

    def ignored(rel: str) -> bool:
        return subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", rel], cwd=_ROOT,
        ).returncode == 0

    for cli, shape in mod.SHAPES.items():
        docs = [shape.config_rel, *shape.role_docs] if shape.config_rel else list(shape.role_docs)
        for n in range(2, seats.MAX_SEATS_PER_CLI + 1):
            folder = f"agents/CLIs/{cli}_agent{n}"
            for rel in docs:
                assert ignored(f"{folder}/{rel}"), f"{folder}/{rel} is not ignored"
    tracked = subprocess.run(
        ["git", "ls-files", "agents/CLIs"], cwd=_ROOT, capture_output=True, text=True,
    ).stdout.split()
    assert tracked, "no tracked seat-1 files found"
    for rel in tracked:
        assert not ignored(rel), f"tracked seat-1 file {rel} now matches an ignore rule"


# ---------------------------------------------------------------------------
# Standalone runner (no pytest required)
# ---------------------------------------------------------------------------

def _main() -> int:
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
