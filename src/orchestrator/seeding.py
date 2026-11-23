"""seed_conversation(): the single source of truth for creating a conversation row.

Extracted from ``src/start_conversation.py:main()`` so the CLI entrypoint and the
Web UI's ``POST /api/orchestrate`` handler both go through the same code path.
The CLI argparse layer (in ``start_conversation.py``) parses flags, applies
preset defaults, and then calls ``seed_conversation()``. The Web UI handler
parses form fields, runs preflight, and then calls the same function.

The schema comes from ``src/schema.py``, so this module can seed a fresh-clone
DB without the MCP server or the web UI having opened it first.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from presets import deliverable_for
from schema import ensure_schema, resolve_db_path, write_txn
from . import delivery
from .conv_types import (
    DEFAULT_CONV_TYPE,
    ConvTypeError,
    get_conv_type,
    lead_of,
    normalize_conv_type,
    validate_roles,
    validate_seat_counts,
)

# Match every ```text ... ``` fenced block inside a Markdown source.
_TEMPLATE_BLOCK_RE = re.compile(r"```text\n(.*?)\n```", re.DOTALL)

# The canonical kickoff template is the first ```text block that contains
# this marker. prompts/Kickoff/kickoff.md has multiple ```text fences (an example
# snippet near the top, the actual template lower down); {{TOPIC}} is the
# unique distinguishing element of the real template.
_TEMPLATE_MARKER = "{{TOPIC}}"

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_TEMPLATE_PATH = _REPO_ROOT / "prompts" / "Kickoff" / "kickoff.md"



@dataclass
class SeedResult:
    """Return value of ``seed_conversation()``.

    ``kickoff_rendered`` is the rendered kickoff body when a template was used
    (preset/tone/template_file supplied), else None — UI surfaces can use it
    to confirm the agent will receive instructions via ``get_kickoff()``.
    """
    conversation_id: int
    topic: str
    participants: list[str]
    mode: str
    max_turns: int
    first: str
    preset: Optional[str]
    kickoff_rendered: Optional[str]
    conv_type: str = DEFAULT_CONV_TYPE
    participant_roles: dict[str, str] = field(default_factory=dict)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_db_path() -> str:
    """$AGENT_CHAT_DB > <repo>/db/chat.db (``schema.resolve_db_path``)."""
    return resolve_db_path()


def load_template(path: Path) -> str:
    """Load a kickoff template body.

    Two source shapes supported:
    - Markdown with one or more ```text fenced blocks — first block containing
      ``{{TOPIC}}`` is returned (so example snippets elsewhere don't shadow).
    - Plain text — returned verbatim (stripped).
    """
    raw = path.read_text(encoding="utf-8")
    for m in _TEMPLATE_BLOCK_RE.finditer(raw):
        body = m.group(1).rstrip()
        if _TEMPLATE_MARKER in body:
            return body
    return raw.strip()


def render_kickoff(template: str, topic: str, tone: str, n_participants: int) -> str:
    """Substitute placeholders and rewrite the participant declaration for 3+ agents.

    The template's opening line declares the conversation as "with another AI
    agent" (singular). For N >= 3 participants we rewrite to "with (N-1) other
    AI agents".
    """
    body = template.replace("{{TOPIC}}", topic).replace("{{TONE_INSTRUCTION}}", tone)
    if n_participants >= 3:
        others = n_participants - 1
        body = body.replace("with another AI agent", f"with {others} other AI agents")
    return body


def deliverable_clause(conv_type: str, preset: Optional[str]) -> str:
    """The paragraph appended to the tone for a type that produces an artifact.

    A collaboration's whole point is the thing it makes, and the kickoff body is
    the only place the *shape* of that thing can be stated — the role brief in
    ``agent_chat_mcp._ROLE_BRIEFS`` is generic across every collaboration, so it
    says "the deliverable the kickoff asked for" and this supplies the rest.

    Returns ``''`` for a type that produces no deliverable, which is every type
    but ``collaborate`` today — so a debate's and a podcast's kickoff bodies are
    byte-for-byte what they were before deliverables existed.
    """
    t = get_conv_type(conv_type)
    if not t.produces_deliverable:
        return ""
    shape = deliverable_for(preset) or (
        "the artifact this room was convened to produce, written out in full "
        "rather than described."
    )
    return (
        f"\n\nThis conversation exists to produce something, not to be read. "
        f"On their final turn the {t.lead_label.lower()} writes the "
        f"{t.deliverable_label.lower()} and sends it with signal='result', and "
        f"it takes this shape: {shape} Everyone else: your job is to make that "
        f"{t.deliverable_label.lower()} good, not to have the last word."
    )


class SeedError(ValueError):
    """Raised on invalid seed_conversation() arguments. Caller renders the
    .args[0] string back to the operator (CLI: stderr; Web UI: form error)."""


def _busy(conn: sqlite3.Connection, participants: list[str]) -> dict[str, int]:
    """{seat: active conversation id} for each seat already in an active run."""
    busy: dict[str, int] = {}
    for row in conn.execute(
        "SELECT id, participants FROM conversations WHERE status = 'active' ORDER BY id"
    ):
        for seat in json.loads(row[1]):
            if seat in participants:
                busy.setdefault(seat, row[0])
    return busy


def busy_message(busy: dict[str, int]) -> str:
    """The operator-facing refusal for a seat that is already in a run."""
    parts = ", ".join(f"'{s}' (conversation #{cid})" for s, cid in busy.items())
    verb = "is" if len(busy) == 1 else "are"
    first = next(iter(busy.values()))
    return (
        f"seat busy: {parts} {verb} already in an active conversation. A seat can "
        "take part in one active conversation at a time, or its agent posts into "
        "the wrong one. "
        f"Stop that run first (Stop on its page, or "
        f"`inspect_conversations.py stop {first}`), or pick another seat."
    )


def busy_seats(db_path: str, participants: list[str]) -> dict[str, int]:
    """Which of ``participants`` are already in an active conversation. Lets
    ``POST /api/orchestrate`` refuse before spending preflight on a launch that
    seed_conversation() would refuse anyway. A missing DB has no busy seats."""
    if not os.path.exists(db_path):
        return {}
    conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
    try:
        ensure_schema(conn)
        return _busy(conn, participants)
    finally:
        conn.close()


# A topic longer than this is a brief, not a title. It would render as a
# multi-line 27px page heading, an ellipsised rail entry and a runaway `# `
# heading in the export bundle. Seed-time only — rows already in the DB are
# untouched (the reader clamps those in CSS).
TOPIC_MAX_CHARS = 300


def seed_conversation(
    *,
    db_path: str,
    topic: str,
    participants: list[str],
    mode: str,
    max_turns: int,
    first: Optional[str] = None,
    preset: Optional[str] = None,
    tone: Optional[str] = None,
    kickoff_template_file: Optional[str] = None,
    initial_system_message: Optional[str] = None,
    participant_personas: Optional[dict] = None,
    conv_type: Optional[str] = None,
    participant_roles: Optional[dict[str, str]] = None,
    max_minutes: Optional[int] = None,
    publish: bool = False,
) -> SeedResult:
    """Insert a conversation row, optionally rendering a kickoff template body.

    Validation matches the original ``start_conversation.py:main()`` behaviour:
    - at least 2 participants, all unique
    - ``first`` (if set) must be in ``participants``
    - ``max_turns >= 1``
    - if any of preset/tone/kickoff_template_file is set, a tone is required
      and the template file must exist

    ``conv_type`` (default ``'debate'``) and ``participant_roles`` are checked
    against the type's seat rules in ``orchestrator.conv_types`` — participant
    cap, member count, and one-lead-at-most. Omitting ``participant_roles``
    derives them from seat order: ``participants[0]`` takes the lead role for a
    type that requires one (matching the ``--first``-speaker convention), and
    everyone else is a member.

    For a ``conv_type`` that produces a deliverable, the rendered kickoff body
    also carries :func:`deliverable_clause` — the artifact's shape, taken from
    the preset. Both seeding callers (``start_conversation.py`` and
    ``POST /api/orchestrate``) come through here, so neither has to know.

    ``publish`` (default False) lets the sync sidecar copy the conversation to
    the public mirror; left off, it stays on this machine (audit RT-07).

    Returns a :class:`SeedResult`. Raises :class:`SeedError` on validation
    failure (caller renders the message). The DB connection is opened with the
    same isolation/WAL settings as the rest of the codebase and closed before
    return.
    """
    # ---- normalisation --------------------------------------------------
    # Collapse every whitespace run (newlines and tabs included) to one space.
    #
    # The /orchestrate topic field is a <textarea>, so a pasted brief can carry
    # newlines — and `render_export_overview()` emits the topic as `# {topic}`.
    # A newline there ends the Markdown heading early and dumps the remainder
    # into the body, which is an **export-contract** break: three external
    # consumers parse that heading (docs/app/export-format.md). Fixing it here
    # rather than in the route covers `start_conversation.py` too.
    topic = " ".join((topic or "").split())

    # ---- validation -----------------------------------------------------
    if not topic:
        raise SeedError("topic is required")
    if len(topic) > TOPIC_MAX_CHARS:
        raise SeedError(
            f"topic is {len(topic)} characters; the limit is {TOPIC_MAX_CHARS}. "
            "The topic is the run's NAME — it becomes the page heading, the rail "
            "entry, the export slug and the `# ` heading in topic.md. Put a long "
            "brief in the initial system message instead (the /orchestrate form's "
            "brief box, or --kickoff on start_conversation.py), where every agent "
            "still reads it as the conversation's first message."
        )
    if len(participants) < 2:
        raise SeedError("need at least 2 participants")
    if len(set(participants)) != len(participants):
        raise SeedError("participant ids must be unique")
    if mode not in ("turns", "continuous"):
        raise SeedError(f"mode must be 'turns' or 'continuous', got {mode!r}")
    if max_turns < 1:
        raise SeedError("max_turns must be >= 1")

    first_speaker = first or participants[0]
    if first_speaker not in participants:
        raise SeedError(f"first speaker {first_speaker!r} is not in participants")

    # ---- conversation type + seat roles ---------------------------------
    try:
        resolved_type = normalize_conv_type(conv_type)
        resolved_roles = validate_roles(resolved_type, participants, participant_roles)
        validate_seat_counts(resolved_type, participants, resolved_roles)
    except ConvTypeError as e:
        raise SeedError(str(e)) from e

    # Whoever runs the room opens it. Every caller already seeds the lead first
    # (orchestrate puts the moderator at the head of the list); this keeps a
    # hand-rolled call from producing a host who speaks third.
    lead = lead_of(resolved_type, resolved_roles)
    if lead is not None and first_speaker != lead:
        raise SeedError(
            f"the {resolved_type}'s lead seat ({lead!r}) must speak first; "
            f"got first={first_speaker!r}"
        )

    # ---- optional kickoff template rendering ----------------------------
    kickoff_rendered: Optional[str] = None
    if preset or tone or kickoff_template_file:
        if not tone:
            raise SeedError(
                "tone is required when a custom template is provided without a preset "
                "(no tone to inject otherwise)"
            )
        template_path = Path(kickoff_template_file) if kickoff_template_file else _DEFAULT_TEMPLATE_PATH
        if not template_path.exists():
            raise SeedError(f"template file not found: {template_path}")
        template_body = load_template(template_path)
        kickoff_rendered = render_kickoff(
            template_body,
            topic,
            tone + deliverable_clause(resolved_type, preset),
            n_participants=len(participants),
        )

    # ---- DB write -------------------------------------------------------
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        ensure_schema(conn)
        with write_txn(conn):
            # Under the write lock, so two launches can't both find a seat free.
            busy = _busy(conn, participants)
            if busy:
                raise SeedError(busy_message(busy))

            current_turn = first_speaker if mode == "turns" else None
            ts = now_iso()
            personas_json = json.dumps(participant_personas) if participant_personas else None
            cur = conn.execute(
                """
                INSERT INTO conversations
                    (topic, participants, mode, max_turns, current_turn, status,
                     end_reason, created_at, updated_at, preset, kickoff_template,
                     participant_personas, conv_type, participant_roles, max_minutes,
                     publish)
                VALUES (?, ?, ?, ?, ?, 'active', NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (topic, json.dumps(participants), mode, max_turns,
                 current_turn, ts, ts, preset, kickoff_rendered, personas_json,
                 resolved_type, json.dumps(resolved_roles), max_minutes,
                 # Always written: a migrated file's column DEFAULT is 1.
                 1 if publish else 0),
            )
            conv_id = cur.lastrowid

            if initial_system_message:
                conn.execute(
                    "INSERT INTO messages (conversation_id, sender, content, signal, created_at) "
                    "VALUES (?, 'system', ?, NULL, ?)",
                    (conv_id, initial_system_message, ts),
                )
    finally:
        conn.close()

    # Outside the transaction, after the connection is closed — the same rule
    # the three completion call sites follow. deliver() never raises, so a
    # notification sink cannot fail a seed; at worst it logs. Nothing is
    # delivered unless a sink lists "started" in its events, which the default
    # list does not: at this point the bundle has no messages in it. On a
    # background thread, because /api/orchestrate calls this from the web UI's
    # event loop (audit RT-14).
    delivery.deliver_later(int(conv_id), ["started"], db_path)

    return SeedResult(
        conversation_id=int(conv_id),
        topic=topic,
        participants=participants,
        mode=mode,
        max_turns=max_turns,
        first=first_speaker,
        preset=preset,
        kickoff_rendered=kickoff_rendered,
        conv_type=resolved_type,
        participant_roles=resolved_roles,
    )
