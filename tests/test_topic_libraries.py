r"""Tests for the debate and collaboration topic libraries in ``docs/chat-topics/``.

``Podcast-Topics.md`` has its own suite (``test_podcast_topics.py``). This one
covers the other two:

* ``Debate-Topics.md`` is parsed by ``scripts/debate.ps1``, so its
  ``N. Title`` + ``- Debaters: N`` shape is load-bearing, and the launcher's
  default must point at it (it was renamed from ``Topics.md``).
* ``Collaboration-Topics.md`` uses the same shape with ``- Seats: N`` (total,
  facilitator included) and a ``- Preset:`` line that must name a real
  collaborate preset. Its entries are tasks, so none may read as a yes/no
  proposition.

Runs under pytest *or* standalone with the project venv (no pytest needed):

    .\.venv\Scripts\python.exe tests\test_topic_libraries.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from orchestrator.conv_types import CONV_TYPES  # noqa: E402
from presets import PRESETS  # noqa: E402

_DIR = _ROOT / "docs" / "chat-topics"
_DEBATE = _DIR / "Debate-Topics.md"
_COLLAB = _DIR / "Collaboration-Topics.md"

# Same as debate.ps1's $rxTopic.
_RX_TOPIC = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$")
_RX_KEY = re.compile(r"^\s*-\s*([A-Za-z]+):\s*(.+?)\s*$")
_PROPOSITION = re.compile(
    r"^(should|is|are|will|does|do|did|has|have|can|could|would)\b", re.I
)


def _parse(path: Path) -> list[tuple[int, str, dict[str, str]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    topics: list[tuple[int, str, dict[str, str]]] = []
    for i, line in enumerate(lines):
        mt = _RX_TOPIC.match(line)
        if not mt:
            continue
        keys: dict[str, str] = {}
        for nxt in lines[i + 1 : i + 6]:
            if not nxt.strip():
                break
            mk = _RX_KEY.match(nxt)
            if mk:
                keys[mk.group(1)] = mk.group(2)
        title = re.sub(r"✅.*$", "", mt.group(2)).strip()
        topics.append((int(mt.group(1)), title, keys))
    return topics


def _check_common(path: Path) -> None:
    topics = _parse(path)
    assert topics, f"parsed 0 topics from {path.name}"
    numbers = [n for n, _, _ in topics]
    assert numbers == list(range(1, len(numbers) + 1)), f"{path.name}: {numbers}"
    titles = [t.lower() for _, t, _ in topics]
    assert len(titles) == len(set(titles)), f"{path.name} has duplicate titles"


# --- Debate-Topics.md ------------------------------------------------------

def test_debate_library_shape() -> None:
    _check_common(_DEBATE)
    debate = CONV_TYPES["debate"]
    for n, title, keys in _parse(_DEBATE):
        assert "Debaters" in keys, f"#{n} {title!r} has no '- Debaters: N' line"
        count = int(keys["Debaters"])
        assert debate.min_participants <= count <= debate.max_participants, (
            f"#{n} asks for {count} debaters"
        )


def test_debate_launcher_defaults_to_the_renamed_library() -> None:
    script = (_ROOT / "scripts" / "debate.ps1").read_text(encoding="utf-8")
    assert "docs/chat-topics/Debate-Topics.md" in script
    assert "'docs/chat-topics/Topics.md'" not in script


# --- Collaboration-Topics.md -----------------------------------------------

def test_collaboration_library_shape() -> None:
    _check_common(_COLLAB)
    collab = CONV_TYPES["collaborate"]
    for n, title, keys in _parse(_COLLAB):
        assert "Seats" in keys, f"#{n} {title!r} has no '- Seats: N' line"
        seats = int(keys["Seats"])
        assert collab.min_participants <= seats <= collab.max_participants, (
            f"#{n} asks for {seats} seats; a collaboration seats "
            f"{collab.min_participants}-{collab.max_participants}"
        )


def test_collaboration_presets_exist_and_fit_the_type() -> None:
    for n, title, keys in _parse(_COLLAB):
        preset = keys.get("Preset")
        assert preset, f"#{n} {title!r} has no '- Preset:' line"
        assert preset in PRESETS, f"#{n} names unknown preset {preset!r}"
        assert "collaborate" in PRESETS[preset].get("for_types", ("collaborate",)), (
            f"#{n} preset {preset!r} isn't a collaborate sub-type"
        )


def test_collaboration_entries_are_tasks_not_propositions() -> None:
    for n, title, _ in _parse(_COLLAB):
        assert not title.endswith("?"), f"#{n} {title!r} is a question, not a task"
        assert not _PROPOSITION.match(title), f"#{n} {title!r} reads as a proposition"


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
