"""The /orchestrate form page (local) and its hosted read-only explainer."""

from __future__ import annotations

import html

from orchestrator import delivery as orch_delivery
from orchestrator import preflight as orch_preflight
from orchestrator import seats as orch_seats
from orchestrator.seeding import TOPIC_MAX_CHARS
from orchestrator.conv_types import CONV_TYPES, CONV_TYPE_KEYS, DEFAULT_CONV_TYPE
from presets import (PRESETS, PRESET_NAMES, deliverable_for, preset_label,
                     presets_for)

from web.assets import json_script, stylesheets
from web.assets import script as js_script
from web.render.common import GITHUB_URL as _REPO, _layout

# Text formats the Brief file picker accepts. Read with FileReader in the
# browser and dropped straight into the textarea — nothing is uploaded, so this
# is a UI filter, not a trust boundary. Binary formats (.pdf/.docx) would need a
# server-side extractor; paste those instead.
BRIEF_EXTENSIONS = (".md", ".markdown", ".txt", ".text", ".json", ".csv", ".yaml", ".yml")
# Refuse a file bigger than this. A brief is a prompt, not a corpus, and the
# whole thing rides the /api/orchestrate JSON body and then a DB row.
BRIEF_MAX_BYTES = 200_000

# A persona card uploaded on this form is used for ONE run and is never written
# to the registry — see `_resolve_personas`. Markdown only: the importer on
# /personas is the place that takes zips and avatars.
PERSONA_EXTENSIONS = (".md", ".markdown", ".txt")
PERSONA_MAX_BYTES = 100_000

_PLUS_SVG = ('<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" '
             'stroke="currentColor" stroke-width="1.5" stroke-linecap="round">'
             '<path d="M8 3.5v9M3.5 8h9"/></svg>')


# Display order for the tools. Extra seats are interleaved after their own tool
# by ``_seat_order()``; anything preflight discovers that isn't listed here still
# renders (appended), so a newly supported CLI can't silently drop off the form.
_ORCH_CLI_IDS = ("claude-code", "codex", "antigravity", "opencode")

# Seats checked by default — a two-agent debate, the historical default.
_DEFAULT_CHECKED = ("claude-code", "codex")


# What the lead seat is for, in the operator's words. Keyed by conv_type with
# a generic fallback, so a type added to the registry renders something sane
# here before anyone writes it copy. UI wording lives here rather than on
# ConvType — the registry is the domain model, not the phrasebook.
_LEAD_HINTS: dict[str, str] = {
    "debate": (
        "Adds a host that opens the debate, keeps turns on track, asks "
        "follow-ups, and wraps up \u2014 it does not argue a side. Runs on its "
        "<strong>own</strong> seat (not one of the debaters), speaks first, "
        "then interjects each round."
    ),
    "podcast": (
        "The host runs the room: opens the show, asks the questions, brings in "
        "quiet guests, and closes. It does not answer its own questions. Runs "
        "on its <strong>own</strong> seat and speaks first."
    ),
    # No entry for `collaborate` on purpose: its facilitator is one of the
    # collaborators (ConvType.lead_needs_own_seat=False), so this whole section
    # is hidden for it and any copy here would be unreachable and go stale.
    # What the facilitator does is said next to the First speaker field instead
    # — see `firstHint` in the JS payload below.
}


def _lead_hint(key: str) -> str:
    """Operator-facing description of a type's lead seat."""
    t = CONV_TYPES[key]
    return _LEAD_HINTS.get(key) or (
        f"The {t.lead_label.lower()} holds the lead seat: it speaks first and "
        f"runs on its <strong>own</strong> seat, not one of the "
        f"{t.members_label.lower()}."
    )


def _type_blurb(key: str) -> str:
    """One-line description of a type's seat shape, for the radio label."""
    t = CONV_TYPES[key]
    if t.lead_required and not t.lead_needs_own_seat:
        # The lead is one of them, so quoting a member range on top of a lead
        # would read as one seat more than the operator actually picks.
        return (f"{t.min_participants}–{t.max_participants} "
                f"{t.members_label.lower()}; the first speaks as "
                f"{t.lead_label.lower()}")
    lead = (f"a {t.lead_label.lower()} plus "
            if t.lead_required else
            f"optional {t.lead_label.lower()}, ")
    return (f"{lead}{t.min_members}–{t.max_members} "
            f"{t.members_label.lower()}")


# What each sub-type hands back, in the operator's words — the whole point of
# picking one, so it belongs on the card rather than in a doc. Keyed by preset
# name with a generic fallback, so a preset added to `presets.py` renders
# something sane here before anyone writes it copy.
_PRESET_BLURBS: dict[str, str] = {
    "debate": "Positions argued and pushed on.",
    "podcast": "A host interviews; guests answer at length.",
    "collaborate": "Whatever you asked for, written out in full.",
    "brainstorm": "A ranked shortlist — and what got dropped.",
    "plan": "Numbered steps, owners, definition of done.",
    "decide": "The call — plus why every other option lost.",
    "solve": "Root cause, the evidence for it, and the fix.",
    "code-review": "A verdict, with blocking issues kept separate.",
    "audit": "A ranked findings register — issues and enhancements.",
    "design": "Components, interfaces, and the tradeoffs taken.",
    "validate": "Go / no-go, and the thing most likely to kill it.",
}


# The long form of each sub-type, behind the card's "?" button. The card has
# room for one line; this is where "which one of these is mine?" actually gets
# answered, so each entry says what you hand IN, what comes back, and — the
# part a one-liner can never carry — which neighbouring sub-type to pick
# instead. Kept next to `_PRESET_BLURBS` rather than in a doc because an
# operator decides here, mid-form, and a link they have to leave the page for
# is a link they don't click. Trusted HTML authored in this file (never
# escaped at render time) — keep it to <strong>/<em>/<code>.
_PRESET_DETAILS: dict[str, str] = {
    "": (
        "Nothing is rendered for the agents at all — no tone, no "
        "deliverable instruction, no participation loop. You get a bare "
        "conversation row and paste your own opening prompt into each CLI. "
        "Pick this when you have a brief that is already written and don't "
        "want a template wrapped around it."
    ),
    "debate": (
        "<strong>Give it</strong> a proposition or a question with real sides "
        "to it. <strong>Get back</strong> a transcript, not an artifact — "
        "a debate exists to be read. Agents are told to take positions, make "
        "falsifiable predictions, and push back rather than converge, so "
        "don't pick it when you want the room to agree on something."
    ),
    "podcast": (
        "<strong>Give it</strong> a subject and a guest list. "
        "<strong>Get back</strong> an interview transcript: the host asks and "
        "never argues a side, the guests answer at length with specifics and "
        "stories. Longer default run (10 turns each) because answers are "
        "supposed to breathe."
    ),
    "collaborate": (
        "The generic flavour — <strong>the room does exactly what your "
        "topic asks and hands that back written out in full</strong>, not a "
        "summary of the discussion. Pick it when your topic already names the "
        "artifact you want, or when none of the specific sub-types fits. "
        "Everything else on this list is this one with sharper instructions "
        "about the shape of the output."
    ),
    "brainstorm": (
        "<strong>Give it</strong> a space to explore. <strong>Get back</strong> "
        "a ranked shortlist plus the ideas that were dropped and why. Runs in "
        "<code>continuous</code> mode on purpose: nobody waits for a turn "
        "while an idea is fresh, and the facilitator converges the room near "
        "the end. Use <strong>Decide</strong> instead when the options already "
        "exist and you just need to choose."
    ),
    "plan": (
        "<strong>Give it</strong> a goal you have already committed to. "
        "<strong>Get back</strong> numbered steps, each with an owner, what it "
        "depends on, and a definition of done, plus the risks and open "
        "unknowns. It plans the <em>work</em> — for the shape of the "
        "thing being built, pick <strong>Design</strong>."
    ),
    "decide": (
        "<strong>Give it</strong> the options, or a question with obvious "
        "candidates. <strong>Get back</strong> one committed choice, the "
        "criteria it was judged against, <strong>every option that lost and "
        "why</strong>, and what would have to change to flip it. Prioritising "
        "a backlog is this sub-type with the options supplied."
    ),
    "solve": (
        "<strong>Give it</strong> a symptom — something is broken or "
        "behaving wrong. <strong>Get back</strong> the root cause, the "
        "evidence for it, the fix, and the hypotheses that were ruled out. "
        "Agents are told to eliminate rather than accumulate and not to jump "
        "to a fix. One known problem, not a sweep for unknown ones — "
        "that's <strong>Audit</strong>."
    ),
    "code-review": (
        "<strong>Give it</strong> one artifact under review — a diff, a "
        "proposal, a document. <strong>Get back</strong> an explicit approve / "
        "request-changes verdict, then blocking issues as a numbered list, "
        "then non-blocking suggestions kept separate. Shortest default run (6 "
        "turns each). For a whole repo or system with no verdict to give, use "
        "<strong>Audit</strong>."
    ),
    "audit": (
        "<strong>Give it</strong> something that already exists and a lens to "
        "look through — a repo, a pipeline, a set of docs, a body of "
        "data. Agents examine it <strong>independently first</strong>, then "
        "reconcile: agreed findings, contested ones, and what one of them "
        "missed. <strong>Get back</strong> a findings register ranked by "
        "impact — defects and enhancements kept distinguishable, each "
        "with where it is, the evidence, and the recommended change — "
        "opening with what was and wasn't examined. This is the one for "
        "“go through my project and tell me what's wrong and what could "
        "be better”. It <em>finds</em> the work; run <strong>Plan</strong> "
        "afterwards to schedule it."
    ),
    "design": (
        "<strong>Give it</strong> requirements or constraints. "
        "<strong>Get back</strong> the design itself: components and what each "
        "owns, the interfaces between them, the data crossing them, and the "
        "failure modes — with the rejected alternative named for every "
        "significant choice. Structure, not schedule; pair it with "
        "<strong>Plan</strong> for the build order."
    ),
    "validate": (
        "<strong>Give it</strong> an idea, a pitch, or a plan you are about to "
        "commit to. <strong>Get back</strong> a go / no-go / not-yet call "
        "covering demand, competition, cost to run, and the assumptions "
        "underneath — plus the single thing most likely to kill it and "
        "the cheapest test that would find out. Someone is required to argue "
        "the case against."
    ),
}


def _preset_detail(name: str) -> str:
    """Long-form help for a sub-type card; '' when none is written."""
    return _PRESET_DETAILS.get(name, "")


def _preset_blurb(name: str) -> str:
    """One line on what this sub-type produces."""
    return _PRESET_BLURBS.get(name) or deliverable_for(name)[:70] or ""


def _preset_meta(name: str) -> str:
    """The mode/turn defaults, shown so a switch isn't a surprise."""
    p = PRESETS[name]
    return f'{p["mode"]}/{p["max_turns"]} turns'


def _preset_help(name: str, label: str) -> str:
    """The card's "?" and the tooltip it reveals on hover.

    Pure CSS: the panel is a sibling shown by ``:hover``/``:focus-visible`` on
    the button, absolutely positioned so it **floats over** the card rather
    than growing it — an expanding panel reflowed the whole grid, which is a
    lot of movement for a glance. The button stays a real <button> so it is
    keyboard-reachable, and the JS cancels a click on it: it sits inside the
    card's <label>, and reading about a sub-type must not select it.
    """
    detail = _preset_detail(name)
    if not detail:
        return ""
    safe = html.escape(label or "this sub-type", quote=True)
    slug = html.escape(name or "none", quote=True)
    return (
        f'<button type="button" class="orch-preset-help"'
        f' aria-describedby="orch-help-{slug}" aria-label="What is {safe}?">?</button>'
        f'<span class="orch-preset-detail" id="orch-help-{slug}" role="tooltip">'
        f'{detail}</span>'
    )


def _preset_radio(name: str) -> str:
    """One sub-type card. Hidden by the JS when its format isn't selected."""
    label = preset_label(name)
    return (
        f'<label class="orch-preset" data-preset="{html.escape(name, quote=True)}">'
        f'<input type="radio" name="preset" value="{html.escape(name, quote=True)}" />'
        f'<span class="orch-preset-name">{html.escape(label)}</span>'
        f'<span class="orch-preset-hint">{html.escape(_preset_blurb(name))}</span>'
        f'<span class="orch-preset-meta">{html.escape(_preset_meta(name))}</span>'
        f'{_preset_help(name, label)}'
        "</label>"
    )


def _seat_order(available: list[str]) -> list[str]:
    """Discovered seats in display order: registry order, seats within a tool."""
    ranked = {cli: i for i, cli in enumerate(_ORCH_CLI_IDS)}
    return sorted(
        available,
        key=lambda s: (ranked.get(orch_seats.seat_cli(s) or s, len(ranked)),
                       orch_seats.seat_index(s), s),
    )


def _availability_notice(availability: dict | None, seat_ids: list[str]) -> str:
    """The banner above the participant list, or ``""`` when there's nothing to say.

    Three states worth interrupting for, in descending order of urgency: no CLI
    at all (the form can't do anything), exactly one seat (it can seed a
    conversation with nobody to talk to), and never-declared (the list below is
    a guess from detection, not an answer). A settled two-plus-seat setup gets
    silence — the point of the setup page is to stop nagging people who are set up.
    """
    if availability is None:
        return ""
    clis = list(availability.get("clis") or [])
    declared = bool(availability.get("declared"))
    if not clis:
        return (
            '<div class="orch-avail warn">'
            "<strong>No CLI tools available.</strong> Nothing was detected on your "
            "<code>PATH</code> and you haven't declared anything, so there's no one to "
            'seed a conversation with. <a href="/setup">Set up your CLIs &rarr;</a>'
            "</div>"
        )
    if len(seat_ids) < 2:
        return (
            '<div class="orch-avail warn">'
            f"<strong>Only one seat available.</strong> A conversation needs at least two. "
            f"You have <code>{html.escape(clis[0])}</code> — one tool is enough, but it "
            f"needs a second seat to argue with itself. "
            '<a href="/setup">Create one on the setup page &rarr;</a>'
            "</div>"
        )
    if not declared:
        return (
            '<div class="orch-avail">'
            f"Showing the <strong>{len(clis)}</strong> CLI"
            f"{'' if len(clis) == 1 else 's'} detected on this machine. "
            '<a href="/setup">Confirm or correct that &rarr;</a>'
            "</div>"
        )
    return ""


def _delivery_toggle_html() -> str:
    """The *save a copy locally* control for the Launch section.

    Three states, because pretending there are fewer would lie about one of
    them (see orchestrator.delivery.optin_offered):

    - delivery off        → a muted hint, no control. Discoverable without
                            implying a choice that does nothing.
    - a sink scoped "all" → ticked and disabled. Every conversation is
                            delivered whatever the operator clicks, so the box
                            must not suggest otherwise.
    - scoped "opt-in"     → a live checkbox. This is the interesting case, and
                            the one `deliver --init` now ships by default.
    """
    state = orch_delivery.optin_offered()
    if not state["available"]:
        return (
            '<p class="hint" id="orch-deliver-off">Local delivery is off — finished '
            'conversations stay in the database. Turn it on with '
            '<code>inspect_conversations deliver --init</code> '
            '(see <code>docs/app/delivery.md</code>).</p>'
        )
    label = html.escape(state["label"])
    if state["forced"]:
        return (
            '<label class="orch-toggle" id="orch-deliver-toggle">'
            '<input type="checkbox" name="deliver_locally" checked disabled />'
            f'<span>Deliver a copy when this finishes (<code>{label}</code>) — '
            '<strong>every</strong> conversation is delivered on this machine '
            '(<code>scope: all</code>)</span>'
            '</label>'
        )
    return (
        '<label class="orch-toggle" id="orch-deliver-toggle">'
        '<input type="checkbox" name="deliver_locally" />'
        f'<span>Deliver a copy when this finishes (<code>{label}</code>) — '
        'writes the same files as the <em>Export .zip</em> button, unzipped</span>'
        '</label>'
    )


def _render_orchestrate(
    initial_preflight: list[orch_preflight.PreflightResult],
    persona_roster: list[dict] | None = None,
    availability: dict | None = None,
    conv_type: str | None = None,
) -> str:
    """The /orchestrate form page.

    ``initial_preflight`` is the result of running preflight on the seats this
    machine may offer at page-load time. We surface OK / FAIL next to each
    checkbox so the operator can see config issues before submitting.
    The authoritative preflight runs again server-side on POST against the
    selected CLI subset — this lets the page-load preflight be advisory.

    ``persona_roster`` is ``[{"group": str, "personas": [{"slug", "name"}]}]``
    (from ``orchestrator.personas``) used to build the per-CLI persona picker.
    An empty/None roster still renders the picker (just the random/none choices).

    ``availability`` is ``{"declared": bool, "clis": [...], "seats": [...]}``
    from ``orchestrator.availability`` — used only for the notice above the
    participant list. ``None`` renders no notice, which is what a caller that
    doesn't care about onboarding gets.

    ``conv_type`` pre-selects a conversation-type radio (the homepage's
    "Launch a podcast" button arrives as ``/orchestrate?type=podcast``). An
    unknown or missing value falls back to ``DEFAULT_CONV_TYPE``; the JS runs
    ``updateConvType()`` on load, so the whole form re-labels itself from
    whichever radio is checked server-side.
    """
    checked_type = conv_type if conv_type in CONV_TYPES else DEFAULT_CONV_TYPE
    preflight_by_cli = {r.cli: r for r in initial_preflight}
    persona_roster = persona_roster or []
    # The form picks TOOLS, not seat ids: a chair's seat number is derived from
    # how many earlier chairs already run on that tool (claude-code, then
    # claude-code-2…), and POST /api/orchestrate creates any config folder that
    # doesn't exist yet. So everything below is keyed on the tool list, and a
    # one-CLI operator can fill every chair — which the old seat-per-checkbox
    # grid could not express.
    tool_ids = _seat_order([s for s in preflight_by_cli
                            if orch_seats.seat_index(s) == 1])
    avail_notice = _availability_notice(availability, tool_ids)
    seat_ids = tool_ids
    # A caller that passed no availability info keeps the historical behaviour
    # of listing the full registry rather than rendering an empty form.
    if not seat_ids and availability is None:
        seat_ids = tool_ids = list(_ORCH_CLI_IDS)

    # Shared <optgroup> block (the roster), reused by every persona <select>.
    optgroups = []
    for grp in persona_roster:
        cards = grp.get("personas") or []
        if not cards:
            continue
        optgroups.append(f'<optgroup label="{html.escape(str(grp.get("group", "")))}">')
        for p in cards:
            optgroups.append(
                f'<option value="{html.escape(str(p["slug"]))}">'
                f'{html.escape(str(p["name"]))}</option>'
            )
        optgroups.append("</optgroup>")
    optgroups_html = "".join(optgroups)

    # Debater select: none / random / roster.
    persona_opts_html = (
        '<option value="__none__" selected>none (no persona)</option>'
        '<option value="__random__">\U0001F3B2 random</option>'
        + optgroups_html
    )
    # Moderator persona select: built-in generic host / random host / roster.
    mod_persona_opts_html = (
        '<option value="__none__" selected>generic host (built-in)</option>'
        '<option value="__random__">\U0001F3B2 random host</option>'
        + optgroups_html
    )
    # One <option> per TOOL, shared by every chair and by the host. A tool whose
    # page-load preflight failed is still offered — the authoritative check runs
    # on submit — but says so, which a silently-missing entry never did.
    def _tool_note(cli: str) -> str:
        r = preflight_by_cli.get(cli)
        if r is not None and not r.ok:
            return f" — {r.failures[0].code}"
        return ""

    tool_opts_html = "".join(
        f'<option value="{html.escape(c, quote=True)}">'
        f'{html.escape(c)}{html.escape(_tool_note(c))}</option>'
        for c in tool_ids
    )
    mod_cli_opts_html = tool_opts_html

    persona_accept = html.escape(",".join(PERSONA_EXTENSIONS), quote=True)
    persona_max = PERSONA_MAX_BYTES
    # The chair rows are built in JS (they come and go), so the two option
    # blocks and the per-tool seat cap ride along as data. Each row still gets
    # its own file input rather than one shared picker: the chair a card lands
    # on is then a property of which control you clicked.

    delivery_toggle_html = _delivery_toggle_html()

    # Conversation-type radios, generated from the registry so a new type needs
    # no edit here. Each carries the seat rules the JS enforces client-side.
    type_radios = "".join(
        '<label class="orch-type">'
        f'<input type="radio" name="conv_type" value="{key}"'
        f'{" checked" if key == checked_type else ""} />'
        f'<span class="cli-name">{html.escape(CONV_TYPES[key].label)}</span>'
        f'<span class="orch-type-hint">{html.escape(_type_blurb(key))}</span>'
        "</label>"
        for key in CONV_TYPE_KEYS
    )
    conv_types_data = {
        key: {
            "label": t.label,
            "leadRole": t.lead_role,
            "leadLabel": t.lead_label,
            "leadRequired": t.lead_required,
            "memberLabel": t.member_label,
            "membersLabel": t.members_label,
            "minMembers": t.min_members,
            "maxMembers": t.max_members,
            "defaultPreset": t.default_preset,
            "guideUrl": t.guide_url,
            "guideLabel": t.guide_label,
            "leadHint": _lead_hint(key),
            "leadNeedsOwnSeat": t.lead_needs_own_seat,
            "minParticipants": t.min_participants,
            "maxParticipants": t.max_participants,
            "firstLabel": (
                f"First speaker ({t.lead_label.lower()})"
                if t.lead_required and not t.lead_needs_own_seat
                else "First speaker"
            ),
            "firstHint": (
                f"Whoever goes first is the {t.lead_label.lower()}: they frame "
                f"the goal, put decisions to the group, and write the "
                f"{t.deliverable_label.lower()} on their last turn. Leave it "
                f"on \u201c(first selected)\u201d and the top seat takes it."
                if t.lead_required and not t.lead_needs_own_seat
                else ""
            ),
            # Extra seats this format offers \u2014 a member seat re-briefed, not an
            # additional CLI window. Rendered as one dropdown each, populated
            # from the seats already checked. Empty for every type but
            # `collaborate` today, and an empty list hides the whole section.
            "extraRoles": [
                {"role": e.role, "label": e.label, "plural": e.plural,
                 "maxCount": e.max_count, "hint": e.hint}
                for e in t.extra_roles
            ],
            # Sub-types offered for this format. Presets are the sub-type axis
            # \u2014 see src/presets.py.
            "presets": list(presets_for(key)),
        }
        for key, t in CONV_TYPES.items()
    }
    # Server-rendered for the initially-checked type; the JS re-points it when
    # the operator switches format.
    guide_url = html.escape(CONV_TYPES[checked_type].guide_url, quote=True)
    guide_label = html.escape(CONV_TYPES[checked_type].guide_label)

    # EVERY preset is rendered; `updateConvType()` shows only the ones the
    # chosen format offers. Rendering all of them and toggling visibility beats
    # rebuilding innerHTML — the radios keep their identity, so a selection
    # survives a format switch that still offers it.
    #
    # A radio grid rather than a <select> on purpose: these sub-types ARE the
    # feature, and a dropdown hides them behind a click. The "none" card stays,
    # because it means something different from "Open collaboration" — it skips
    # kickoff rendering entirely (the paste-the-prompt flow).
    preset_radios = (
        '<label class="orch-preset" data-preset="">'
        '<input type="radio" name="preset" value="" />'
        '<span class="orch-preset-name">None</span>'
        '<span class="orch-preset-hint">No kickoff rendered — you paste the prompt yourself.</span>'
        '<span class="orch-preset-meta">paste-the-prompt</span>'
        + _preset_help("", "None")
        + "</label>"
    ) + "".join(_preset_radio(n) for n in PRESET_NAMES)

    # JS-side preset table: keep in sync with src/presets.py PRESETS.
    presets_data = {
        name: {
            "max_turns": PRESETS[name]["max_turns"],
            "mode": PRESETS[name]["mode"],
        }
        for name in PRESET_NAMES
    }

    # The title cap the form enforces is the SAME number `seed_conversation()`
    # rejects on, imported rather than repeated — a form that let you type past
    # the server's limit would fail preflight after you'd picked everything.
    topic_max = TOPIC_MAX_CHARS
    brief_accept = html.escape(",".join(BRIEF_EXTENSIONS), quote=True)
    brief_max = BRIEF_MAX_BYTES
    brief_max_kb = BRIEF_MAX_BYTES // 1000
    brief_exts_label = html.escape(", ".join(BRIEF_EXTENSIONS))

    # Everything js/orchestrate.js needs from the server, as one escaped JSON
    # block (audit RT-34 — the script is a static file, not an f-string).
    orch_data = json_script("orch-data", {
        "presets": presets_data,
        "convTypes": conv_types_data,
        "toolOpts": tool_opts_html,
        "personaOpts": persona_opts_html,
        "maxSeatsPerCli": orch_seats.MAX_SEATS_PER_CLI,
        "plusSvg": _PLUS_SVG,
        "personaAccept": persona_accept,
        "personaMax": persona_max,
        "topicMax": topic_max,
        "briefMax": brief_max,
    })

    body = f"""
<div class="orch-shell">
  <header class="orch-head">
    <!-- The standing paragraph that used to sit here explained preflight to
         someone reading it for the hundredth time. Same "?" the sub-type cards
         use: a floating tooltip, so revealing it reflows nothing, and a real
         <button> so it is keyboard-reachable. -->
    <h1>Orchestrate a conversation
      <span class="orch-head-tip">
        <button type="button" class="orch-head-help" aria-describedby="orch-what"
                aria-label="What happens when I launch?">?</button>
        <span class="orch-head-detail" id="orch-what" role="tooltip">
          <strong>Preflight runs first.</strong> Every selected CLI's MCP config is
          validated before anything is seeded, so a bad config aborts the whole run
          rather than leaving half a conversation behind. Failures come back inline
          and are written to <code>logs/orchestrator-&lt;timestamp&gt;.log</code>.
          <br><br>
          On success you land on the live transcript page &mdash; and if
          <strong>Spawn</strong> is ticked, one CLI window opens per seat.
        </span>
      </span>
    </h1>
  </header>

  <form id="orch-form" class="orch-form">
    <section>
      <label class="lbl" for="orch-topic">Title<em class="mark orch-count"><span id="orch-topic-count">0</span>/{topic_max}</em></label>
      <p class="hint" id="orch-topic-hint">One line &mdash; a question, a proposition, or a name for the run.
         This is the conversation's <em>title</em>: it becomes the page heading, the
         sidebar entry and the export's filename slug, so keep it short. Anything
         longer than a line &mdash; background, constraints, a whole spec &mdash; goes in
         <b>Brief</b> just below, where the agents still read it and it never crowds
         the transcript.</p>
      <textarea name="topic" id="orch-topic" aria-describedby="orch-topic-hint" required maxlength="{topic_max}" rows="2"
                placeholder="What should the agents discuss?"></textarea>
    </section>

    <!-- Sits directly under the Title box because that is where an operator
         reaches for it: the run that prompted this pasted a 4000-character
         brief into the title field, and a "put it here instead" that lives at
         the bottom of a long form is not an answer. Collapsed by default with
         `optional` on the summary, so the common case (a title and go) reads
         as one short field, and the offer is one click away rather than a wall
         of textarea. -->
    <section class="orch-brief-section">
      <details class="orch-brief" id="orch-brief-details">
        <!-- The flex lives on the inner <span>, NOT on <summary>. Chrome stops
             treating a summary as its details' disclosure once its `display`
             leaves the list-item/block family — the element renders, and
             clicking it does nothing. -->
        <summary>
          <span class="orch-brief-sum">
            <span class="lbl" id="orch-brief-label">Brief</span>
            <span class="orch-opt">optional &mdash; add a longer prompt or attach a file</span>
          </span>
        </summary>
        <p class="hint">Only if you want to. The <b>Title</b> above is enough to start a
           run &mdash; this is for when the agents need more than one line: background,
           constraints, requirements, a spec you already wrote. It's inserted as the
           conversation's <b>first message</b>, so every agent reads it alongside the title,
           and it stays out of the page heading.</p>
        <label class="orch-file">
          <span>Attach a file:</span>
          <input type="file" id="orch-brief-file" accept="{brief_accept}" />
        </label>
        <p class="hint">Optional. {brief_exts_label} up to {brief_max_kb} KB. The file is read
           <b>in your browser</b> and dropped into the box below so you can edit it before
           launching &mdash; nothing is uploaded or stored.</p>
        <span class="hint" id="orch-brief-file-name"></span>
        <textarea name="kickoff" id="orch-brief" aria-labelledby="orch-brief-label" rows="8"
                  placeholder="Leave blank for none — a title on its own is a valid run."></textarea>
      </details>
    </section>

    <section>
      <span class="lbl" id="orch-type-label">Format</span>
      <p class="hint" id="orch-type-hint">What kind of room this is — who each seat is for. Separate from
         the sub-type below, which decides what the room produces.</p>
      <div class="orch-types" role="radiogroup" aria-labelledby="orch-type-label" aria-describedby="orch-type-hint">
        {type_radios}
      </div>
      <!-- Guide for whichever format is selected. href/text are rewritten by
           updateConvType() from the convTypes map, so it always points at the
           doc for the checked radio — including the ?type= the homepage CTA
           arrives with. Rendered server-side for the initial type so it's
           correct with JS off. -->
      <p class="orch-guide">
        <a id="orch-guide-link" href="{guide_url}" target="_blank" rel="noopener noreferrer">
          {guide_label} &#8599;</a>
        <span class="hint">&mdash; the operator guide on GitHub: seeding, prompts, and what each seat does.</span>
      </p>
    </section>

    <section id="orch-preset-section">
      <span class="lbl" id="orch-preset-label">Sub-type</span>
      <p class="hint" id="orch-preset-hint">Your topic says <em>what</em> to work on; this says
         <em>what to hand back</em>. It sets the agents' instructions and the shape of the final
         deliverable — nothing else changes. Leave it on the default to just follow your topic.</p>
      <div class="orch-presets" id="orch-preset-grid" role="radiogroup" aria-labelledby="orch-preset-label" aria-describedby="orch-preset-hint">
        {preset_radios}
      </div>
    </section>

    <section>
      <span class="lbl" id="orch-participants-label">Participants<em class="mark">min 2</em></span>
      <p class="hint">One row per chair, one CLI window per row. Pick the tool each chair
         runs on &mdash; <b>the same tool can fill more than one chair</b>, so a single CLI is
         enough for a whole room: the second chair on a tool runs as
         <code>claude-code-2</code> and its config is created when you launch. Only tools you
         have are listed &mdash; change that on the <a href="/setup">setup page</a>.</p>
      {avail_notice}
      <div class="orch-seats" id="orch-seats"></div>
      <div class="orch-seat-actions">
        <button type="button" id="orch-add-seat" class="orch-seat-add">+ Add a seat</button>
        <button type="button" id="orch-cast-random" class="orch-cast-random"><svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.3"><rect x="2.1" y="2.1" width="11.8" height="11.8" rx="3"/><circle cx="5.6" cy="5.6" r="0.95" fill="currentColor" stroke="none"/><circle cx="10.4" cy="10.4" r="0.95" fill="currentColor" stroke="none"/><circle cx="8" cy="8" r="0.95" fill="currentColor" stroke="none"/></svg><span>Cast every chair randomly</span></button>
      </div>
    </section>

    <section id="orch-lead-section">
      <span class="lbl" id="orch-lead-label">Moderator / host<em class="mark">optional</em></span>
      <p class="hint" id="orch-lead-hint">Adds a host that opens the debate, keeps turns on track, asks follow-ups,
         and wraps up — it does not argue a side. Runs on its <strong>own</strong> seat (not one of
         the debaters), speaks first, then interjects each round. Adding a moderator keeps the
         conversation on orderly turn rotation.</p>
      <label class="orch-toggle" id="orch-mod-toggle">
        <input type="checkbox" name="mod_enable" />
        <span id="orch-mod-toggle-text">Add a moderator</span>
      </label>
      <div class="orch-persona-rows" id="orch-mod-fields" style="display:none">
        <label class="orch-persona-row">
          <span class="cli-name">Runs on</span>
          <select name="mod_cli">{mod_cli_opts_html}</select>
          <span class="seat-id" id="orch-mod-seat-id"></span>
        </label>
        <label class="orch-persona-row">
          <span class="cli-name" id="orch-mod-persona-label">Host persona</span>
          <select name="mod_persona">{mod_persona_opts_html}</select>
        </label>
      </div>
    </section>

    <section>
      <span class="lbl">Conversation</span>
      <div class="row">
        <label>
          <span class="orch-flabel">Max turns (per agent)</span>
          <input name="max_turns" type="number" min="1" max="50" value="8" />
        </label>
        <label>
          <span class="orch-flabel">Time limit (minutes)</span>
          <input name="max_minutes" type="number" min="1" max="1440" placeholder="none" />
        </label>
        <label>
          <span class="orch-flabel" id="orch-first-label">First speaker</span>
          <select name="first">
            <option value="">(first selected)</option>
          </select>
        </label>
      </div>
      <p class="hint" id="orch-first-hint" style="display:none"></p>
    </section>

    <p class="orch-fold">Tuning &mdash; every field below has a working default</p>

    <!-- Extra seats: a seat already checked above, re-briefed. Rendered by
         updateExtraSeats() from ConvType.extra_roles, so a new one costs no
         edit here; hidden entirely for a format that offers none. -->
    <section id="orch-extra-section" style="display:none">
      <span class="lbl" id="orch-extra-label">Special seats<em class="mark">optional</em></span>
      <p class="hint">Not an extra CLI window &mdash; one of the seats you already picked, briefed
         differently. It still contributes and still counts toward the room.</p>
      <div class="orch-persona-rows" id="orch-extra-rows"></div>
    </section>


    <section>
      <span class="lbl">Launch</span>
      <label class="orch-toggle">
        <input type="checkbox" name="spawn" checked />
        <span>Spawn one CLI window per agent automatically (local Windows only)</span>
      </label>
      <!-- Off by default (security audit 2026-10-30): persona and topic text is
           untrusted input to an agent. Ticked, a seat is allowlisted to the
           roundtable tools only, never given a blanket bypass; a CLI with no
           allowlist flag gets nothing and keeps asking. See ALLOW in
           scripts/lib/spawn-agents.ps1. -->
      <label class="orch-toggle">
        <input type="checkbox" name="skip_permissions" />
        <span>Let Claude Code seats use the roundtable tools without asking
          (other CLIs still ask for every tool)</span>
      </label>
      <p class="hint orch-skip-warn" id="orch-skip-warn" style="display:none">A custom persona
        card is seated. Its text reaches the agent as instructions &mdash; read it before you
        let that agent act without asking.</p>
      {delivery_toggle_html}
    </section>

    <div id="orch-error" class="orch-error hidden"></div>

    <!-- Sticky, and carrying a live readout of what is about to run. The
         control used to sit at the natural end of the form, three viewports
         down, with nothing on screen saying what the button would commit. -->
    <div class="orch-actions">
      <p class="orch-recap" id="orch-recap" aria-live="polite"></p>
      <button type="submit" class="orch-submit">Run preflight + start</button>
    </div>
  </form>
</div>

{orch_data}{js_script("orchestrate")}
"""
    return _layout("Orchestrate", "", body,
                   head_extras=stylesheets("orchestrate", "orchestrate-form"),
                   active="orchestrate")

def _render_orchestrate_readonly() -> str:
    """Hosted /orchestrate — explain that orchestration is local-only.

    The public mirror can't see local CLI configs or spawn agents, so instead of
    a dead form we render the exact local commands. (The POST endpoint is blocked
    by ReadOnlyMiddleware regardless; this is the matching GET-side UX.)

    The homepage's "Launch a debate" / "Launch a podcast" CTAs both land here on
    the mirror, so this page carries the per-format guide links too — it's the
    only "how do I run one" answer a hosted visitor gets.
    """
    guide_links = "".join(
        f'<a href="{html.escape(t.guide_url, quote=True)}" target="_blank" '
        f'rel="noopener noreferrer">{html.escape(t.guide_label)} &#8599;</a>'
        for t in CONV_TYPES.values()
    )
    body = f"""
<div class="orch-shell">
  <header class="orch-head">
    <h1>Debates run on your machine, not here</h1>
    <p>This hosted site is a <strong>read-only demo</strong> for viewing debates.
       It can't launch one — spawning CLI agents needs the CLIs, their auth, and
       the shared SQLite DB on your own computer.
       <a href="{_REPO}" target="_blank" rel="noopener noreferrer">Clone the repo &rarr;</a>
       and you can seed and watch your own in a couple of minutes; a local run
       mirrors back here within ~5s.</p>
  </header>

  <div class="orch-ro-card spot">
    <h2>Option A — one-command auto-debate</h2>
    <pre><code>.\\scripts\\debate.ps1</code></pre>
    <p>Picks a topic, casts personas, seeds the conversation, and spawns each CLI in character.</p>
  </div>

  <div class="orch-ro-card spot">
    <h2>Option B — this orchestrate form, locally</h2>
    <pre><code>.\\.venv\\Scripts\\python.exe src\\web_ui.py
# then open http://127.0.0.1:8765/orchestrate</code></pre>
    <p>The same form you'd see here, but with live preflight and the ability to spawn agents.</p>
  </div>

  <div class="orch-ro-card spot">
    <h2>The guides</h2>
    <p>One per format &mdash; what to seed, what each seat does, and the prompts to paste.</p>
    <div class="orch-ro-links">
      {guide_links}
      <a href="{_REPO}/blob/main/docs/guides/online-forums.md" target="_blank" rel="noopener noreferrer">How to participate in online forums &#8599;</a>
    </div>
  </div>

  <p class="orch-ro-foot">New here? Start with the
    <a href="{_REPO}#readme" target="_blank" rel="noopener noreferrer">README</a>,
    or <a href="/conversations">browse existing conversations &rarr;</a></p>
</div>
"""
    return _layout(
        "Orchestrate", "", body,
        head_extras=stylesheets("orchestrate", "orch-readonly"),
        active="orchestrate",
    )
