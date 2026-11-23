r"""scripts/maintain-app.ps1 fails loudly and prunes only its own backups.

Audit 2026-11-22 (RT-12): the nightly task exited 0 whatever happened, so a
failed backup looked green in Task Scheduler, and its 14-day prune deleted
hand-made snapshots along with its own. Runs the real script against temp
paths; needs ``pwsh`` and the project venv, and skips without them.

    .\.venv\Scripts\python.exe tests\test_maintain_app.py
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "maintain-app.ps1"
_PWSH = shutil.which("pwsh")
_VENV = (_ROOT / ".venv" / "Scripts" / "python.exe").exists()
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _run(db: Path, backups: Path, logs: Path) -> subprocess.CompletedProcess:
    # No delivery config: the failure alert finds no sink and writes nothing.
    env = dict(os.environ, AGENT_CHAT_DELIVERY_CONFIG=str(logs / "none.json"))
    return subprocess.run(
        [_PWSH, "-NoProfile", "-NonInteractive", "-File", str(_SCRIPT),
         "-DbPath", str(db), "-BackupDir", str(backups), "-LogDir", str(logs),
         "-MaxLogLines", "0"],
        capture_output=True, text=True, timeout=120, env=env)


def _aged(path: Path, days: int) -> Path:
    path.write_bytes(b"old")
    t = time.time() - days * 86400
    os.utime(path, (t, t))
    return path


def test_a_good_backup_prunes_only_nightly_copies() -> None:
    if not (_PWSH and _VENV):
        return
    from orchestrator.seeding import seed_conversation
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp = Path(td)
        db, backups = tmp / "chat.db", tmp / "backups"
        backups.mkdir()
        seed_conversation(db_path=str(db), topic="t", participants=["a", "b"],
                          mode="turns", max_turns=2)
        nightly = _aged(backups / "chat-20200101-000000.db", 30)
        manual = _aged(backups / "chat-pre-migration.db", 30)
        out = _run(db, backups, tmp)
        assert out.returncode == 0, out.stdout + out.stderr
        assert "integrity ok" in out.stdout, out.stdout
        assert not nightly.exists(), "the old nightly copy should be pruned"
        assert manual.exists(), "a hand-made snapshot must never be pruned"
        fresh = [p for p in backups.glob("chat-*.db") if p not in (manual,)]
        assert len(fresh) == 1, fresh
        with contextlib.closing(sqlite3.connect(fresh[0])) as conn:
            assert conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 1


def test_a_failed_backup_exits_non_zero_and_prunes_nothing() -> None:
    if not (_PWSH and _VENV):
        return
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp = Path(td)
        db, backups = tmp / "chat.db", tmp / "backups"
        backups.mkdir()
        db.write_bytes(b"this is not a database" * 100)
        nightly = _aged(backups / "chat-20200101-000000.db", 30)
        out = _run(db, backups, tmp)
        assert out.returncode == 1, out.stdout + out.stderr
        assert "FAILED" in out.stdout, out.stdout
        assert nightly.exists(), "a failed night must not prune the good copies"
        assert sorted(p.name for p in backups.iterdir()) == [nightly.name], \
            "the failed copy was left behind"


def _main() -> int:
    if not (_PWSH and _VENV):
        print("NOTE  pwsh or the project venv missing: cases pass vacuously")
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
