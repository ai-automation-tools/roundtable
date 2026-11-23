"""seats.py — agent ids that can outnumber the CLI tools.

Historically an agent id *was* a CLI id: `claude-code` meant "the Claude Code
CLI", one seat per tool, five tools, five seats. A podcast with a host and four
guests fills every tool exactly, and there's no room for two personalities on
the same tool — which is a silly limit, because nothing about the message bus
cares what program is on the other end.

A **seat** decouples the two. Seat 1 of a tool keeps the bare CLI id, so every
existing conversation, config, and avatar keeps working untouched:

    claude-code      → tool 'claude-code', seat 1   (<seat root>/claude-code_agent1)
    claude-code-2    → tool 'claude-code', seat 2   (<seat root>/claude-code_agent2)

Identity still comes from config, not from the protocol: each seat folder holds
its own MCP config passing its own ``--agent-id``, and the CLI is launched from
that folder. The bus itself needs no change — conversation lookup matches
an exact string against the ``participants`` list, so `claude-code-2` is simply a
different participant from `claude-code`.

**Seat folders live outside the repo** (audit RT-01): a CLI loads every
CLAUDE.md / AGENTS.md above its launch folder, and the repo's tell a developer
agent to work on this codebase. :func:`seat_root` is the one place that says
where they go; ``scripts/lib/spawn-agents.ps1``'s ``Get-SeatRoot`` mirrors it.
The tracked ``agents/CLIs/<cli>_agent1/`` folders are templates that
``scripts/setup/add_agent_seat.py --materialize`` copies there.

**Parsing splits on the known tool list, not on a trailing-digits regex**, so a
tool whose own name ends in a digit (`gpt-5`, say) can never be mistaken for a
seat suffix.

New seat folders are created by ``scripts/setup/add_agent_seat.py``, which
clones seat 1's config and rewrites the agent id inside it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Overrides :func:`seat_root`. Mirrored by ``Get-SeatRoot`` in spawn-agents.ps1.
SEATS_DIR_ENV = "AGENT_CHAT_SEATS_DIR"

#: Files a CLI loads as instructions from any folder above where it starts.
INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")

# Supported CLI *tools*. Seat ids are derived from these — see seat_id().
# Re-exported by orchestrator.preflight, which is where callers have always
# imported it from.
SUPPORTED_CLIS: tuple[str, ...] = (
    "claude-code", "codex", "antigravity", "opencode",
)

# A conversation caps at 5 participants, so no tool can usefully hold more than
# 5 seats — and each one costs a config folder on disk.
MAX_SEATS_PER_CLI = 5


class SeatError(ValueError):
    """Invalid seat id or seat set. Callers render ``.args[0]``."""


def parse_seat(agent_id: str) -> Optional[tuple[str, int]]:
    """``'claude-code-2'`` → ``('claude-code', 2)``; ``None`` if not a seat.

    Matched against :data:`SUPPORTED_CLIS` longest-prefix-first rather than by
    regex, so a tool name that itself ends in a digit stays unambiguous.
    """
    aid = (agent_id or "").strip()
    if not aid:
        return None
    if aid in SUPPORTED_CLIS:
        return (aid, 1)
    for cli in sorted(SUPPORTED_CLIS, key=len, reverse=True):
        prefix = cli + "-"
        if aid.startswith(prefix):
            suffix = aid[len(prefix):]
            if suffix.isdigit():
                n = int(suffix)
                # "claude-code-1" is spelled "claude-code"; one spelling per seat
                # keeps participant lists and message senders comparable.
                if 2 <= n <= MAX_SEATS_PER_CLI:
                    return (cli, n)
            return None
    return None


def is_seat(agent_id: str) -> bool:
    """True when ``agent_id`` names a seat on a supported tool."""
    return parse_seat(agent_id) is not None


def seat_cli(agent_id: str) -> Optional[str]:
    """The tool behind a seat id, or ``None`` for an unrecognised id."""
    parsed = parse_seat(agent_id)
    return parsed[0] if parsed else None


def seat_index(agent_id: str) -> int:
    """1-based seat number; 1 for a bare CLI id, 0 for an unrecognised one."""
    parsed = parse_seat(agent_id)
    return parsed[1] if parsed else 0


def seat_id(cli: str, index: int = 1) -> str:
    """``('claude-code', 2)`` → ``'claude-code-2'``. Seat 1 is the bare id."""
    if cli not in SUPPORTED_CLIS:
        raise SeatError(f"unknown CLI {cli!r}; supported: {', '.join(SUPPORTED_CLIS)}")
    if not 1 <= index <= MAX_SEATS_PER_CLI:
        raise SeatError(f"seat index must be 1..{MAX_SEATS_PER_CLI}; got {index}")
    return cli if index == 1 else f"{cli}-{index}"


def seat_root() -> Path:
    """The folder holding every seat folder of this clone. Outside the repo.

    ``$AGENT_CHAT_SEATS_DIR`` if set; else ``%LOCALAPPDATA%`` (``$XDG_DATA_HOME``
    or ``~/.local/share`` off Windows) ``/Roundtable/seats/<clone folder name>``,
    so two clones don't share seats.
    """
    override = os.environ.get(SEATS_DIR_ENV)
    if override:
        return Path(os.path.abspath(os.path.expanduser(override)))
    base = (os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
            or str(Path.home() / ".local" / "share"))
    return Path(base) / "Roundtable" / "seats" / _REPO_ROOT.name


def seat_dir(agent_id: str) -> Path:
    """Where a seat launches from: ``seat_root() / seat_folder(agent_id)``."""
    return seat_root() / seat_folder(agent_id)


def template_dir(cli: str) -> Path:
    """The tracked seat-1 template for a tool: its role doc and MCP config."""
    return _REPO_ROOT / "agents" / "CLIs" / f"{cli}_agent1"


def instruction_files_above(path: Path) -> list[Path]:
    """CLAUDE.md / AGENTS.md / GEMINI.md / ``.git`` in ``path``'s ancestors.

    A seat launched under any of them would load it (or treat the folder as a
    repo). Empty is what a seat root should give.
    """
    found: list[Path] = []
    for parent in Path(path).resolve().parents:
        for name in (*INSTRUCTION_FILES, ".git"):
            if (parent / name).exists():
                found.append(parent / name)
    return found


def seat_folder(agent_id: str) -> str:
    """Folder name under :func:`seat_root` holding this seat's MCP config.

    ``claude-code`` → ``claude-code_agent1``, ``claude-code-2`` →
    ``claude-code_agent2``. Raises :class:`SeatError` on an unrecognised id.
    """
    parsed = parse_seat(agent_id)
    if parsed is None:
        raise SeatError(f"unrecognised agent id {agent_id!r}")
    cli, index = parsed
    return f"{cli}_agent{index}"


def seats_for(cli: str, count: int) -> list[str]:
    """The first ``count`` seat ids for a tool: ``['codex', 'codex-2', …]``."""
    return [seat_id(cli, i) for i in range(1, count + 1)]


def validate_seats(agent_ids: list[str]) -> None:
    """Check a participant list. Raises :class:`SeatError` on the first problem.

    Duplicate ids are the caller's business (``seed_conversation`` already
    rejects them); what's checked here is that each id names a real seat.
    """
    for aid in agent_ids:
        if parse_seat(aid) is None:
            raise SeatError(
                f"unknown agent id {aid!r} — expected a CLI "
                f"({', '.join(SUPPORTED_CLIS)}) or a numbered seat on one "
                f"(e.g. 'claude-code-2', up to -{MAX_SEATS_PER_CLI})"
            )


def display_seat(agent_id: str) -> str:
    """Human label for a seat — ``'codex (seat 2)'``, or the id for seat 1."""
    parsed = parse_seat(agent_id)
    if parsed is None:
        return str(agent_id)
    cli, index = parsed
    return cli if index == 1 else f"{cli} (seat {index})"
