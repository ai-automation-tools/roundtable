"""Hard stop for spawned seats: the NO_SPAWN switch and "close the windows".

Marking a conversation complete stops agents at their next MCP call, but an
agent in the middle of a tool call keeps running, and nothing tracked the
windows this app opened (audit RT-21). So:

- **`config/NO_SPAWN`** — while the file exists, nothing spawns: ``POST
  /api/orchestrate`` refuses a spawn before seeding, and ``debate.ps1`` /
  ``orchestrate-debate.ps1`` refuse before launching. Delete it to re-enable.
- **Seat PIDs** — each seat window writes ``<pid> <start time>`` to
  ``db/launch/conv<id>-<seat>.pid`` as its first command (``New-AgentLaunchPlan``
  in ``scripts/lib/spawn-agents.ps1``). ``close_seat_windows()`` ends each
  window's process tree, but only when that PID still belongs to a process
  started at the recorded time, so a reused PID is never killed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# Overridable so tests never have to create the operator's real switch.
NO_SPAWN_FILE = Path(os.environ.get("AGENT_CHAT_NO_SPAWN_FILE")
                     or REPO_ROOT / "config" / "NO_SPAWN")
LAUNCH_DIR = REPO_ROOT / "db" / "launch"

_STOP_ONE = (
    "$p = Get-Process -Id {pid} -ErrorAction SilentlyContinue; "
    "if ($p -and $p.StartTime.ToFileTimeUtc() -eq {started}) "
    "{{ taskkill /PID {pid} /T /F | Out-Null; 'closed' }} else {{ 'gone' }}"
)


def spawn_disabled() -> bool:
    return NO_SPAWN_FILE.exists()


def pid_files(cid: int, launch_dir: Path | None = None) -> list[Path]:
    return sorted((launch_dir or LAUNCH_DIR).glob(f"conv{int(cid)}-*.pid"))


def close_seat_windows(cid: int, launch_dir: Path | None = None) -> dict[str, str]:
    """End the process tree of every recorded seat window of conversation
    ``cid``. Returns ``{seat: "closed" | "gone" | "error: …"}`` and removes the
    PID files it handled. Windows only (seats only spawn there); never raises."""
    out: dict[str, str] = {}
    if sys.platform != "win32":
        return out
    for f in pid_files(cid, launch_dir):
        seat = f.stem.split("-", 1)[1]
        try:
            pid, started = (int(x) for x in f.read_text(encoding="utf-8-sig").split()[:2])
            r = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command",
                 _STOP_ONE.format(pid=pid, started=started)],
                capture_output=True, text=True, timeout=30,
            )
            out[seat] = (r.stdout.strip().splitlines() or ["gone"])[-1]
            f.unlink(missing_ok=True)
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            out[seat] = f"error: {e}"
    return out
