"""The /personas/manage management console page (/personas is the explorer)."""

from __future__ import annotations

import html
from typing import Any

from orchestrator import personas as personas_registry

from web.assets import json_script, stylesheets
from web.assets import script as js_script
from web.avatars import DEFAULT_AVATAR_URL, avatar_url
from web.render.common import PUBLIC_REGISTRY_HOST, PUBLIC_REGISTRY_URL, REGISTRY_URL, _initials, _layout, _pm_svg


def _group_select(current: str, groups: list[str], cls: str) -> str:
    """Render a <select> of existing group folders + a "new group" escape hatch.

    ``current`` is pre-selected (and added as an option if it isn't already in
    ``groups``, e.g. the default group on a fresh DB). A trailing ``__new__``
    option reveals a sibling text input client-side so a brand-new group can be
    created inline at persona-creation/import time (groups are just distinct
    ``"group"`` values, so a group materializes when its first persona lands)."""
    opts: list[str] = []
    seen = False
    for g in groups:
        sel = " selected" if g == current else ""
        seen = seen or g == current
        opts.append(f'<option value="{html.escape(g, quote=True)}"{sel}>{html.escape(g)}</option>')
    if current and not seen:
        opts.insert(0, f'<option value="{html.escape(current, quote=True)}" selected>{html.escape(current)}</option>')
    opts.append('<option value="__new__">+ Create new group…</option>')
    return f'<select class="{cls}">{"".join(opts)}</select>'

def _pm_glabel(g: str) -> str:
    """Display label for a group folder name (hyphens/underscores → spaces)."""
    return g.replace("-", " ").replace("_", " ")


def _registry_promo() -> str:
    """The persona-registry card in the empty detail pane: the first thing an
    operator sees on this page, so it advertises the public registry with its
    real size and a few of its faces. Counts the same cast the registry shows
    (no AI-Models reference cards); a registry/DB hiccup just drops the numbers."""
    try:
        cast = list(personas_registry.list_debater_personas())
    except Exception:  # noqa: BLE001 — the ad degrades, the console doesn't
        cast = []
    faces = "".join(
        f'<img src="{html.escape(avatar_url(p.slug), quote=True)}" alt="" loading="lazy" '
        f'data-on-error="remove">'
        for p in [p for p in cast if p.has_avatar][:5]
    )
    n_groups = len({p.group for p in cast})
    size = (
        f'<strong class="pm-promo-title">{len(cast)} ready-made characters'
        f'<span> in {n_groups} groups</span></strong>'
        if cast else '<strong class="pm-promo-title">Ready-made characters</strong>'
    )
    return (
        f'<a class="pm-promo" href="{PUBLIC_REGISTRY_URL}" target="_blank" rel="noopener">'
        + (f'<span class="pm-promo-faces" aria-hidden="true">{faces}</span>' if faces else '')
        + '<span class="pm-promo-eyebrow">Persona registry</span>'
        + size
        + '<span class="pm-promo-copy">Browse the whole cast, read each card, and download one '
        'with its avatar as a <code>.zip</code> that <b>Import</b> reads back here.</span>'
        '<span class="btn btn-primary pm-promo-cta">Browse the registry &#8599;</span>'
        f'<span class="pm-promo-host mono">{PUBLIC_REGISTRY_HOST}</span>'
        '</a>'
    )


def _render_personas_page() -> str:
    crumbs = '<strong>Personas</strong>'
    if not personas_registry.root_exists():
        body = (
            '<div class="pm-unavail">Persona storage is <strong>unavailable</strong> &mdash; '
            'the database can\'t be reached right now. Try again shortly.</div>'
        )
        return _layout("Personas", crumbs, body, head_extras=stylesheets("personas"),
                       active="personas")

    groups = personas_registry.discover_groups()
    default_group = personas_registry.DEFAULT_DEBATER_GROUP
    active_group = groups[0] if groups else default_group

    # Build, in one pass: the per-group row markup, the flat data blob the
    # detail pane reads bodies from, and the group counts for the rail.
    data_personas: list[dict[str, Any]] = []
    rows_by_group: list[str] = []
    group_counts: dict[str, int] = {}
    for g in groups:
        cards = personas_registry.list_personas(g)
        group_counts[g] = len(cards)
        gq = html.escape(g, quote=True)
        row_html: list[str] = []
        for p in cards:
            data_personas.append({
                "group": g, "slug": p.slug, "name": p.name,
                "tags": list(p.tags), "body": p.body,
                # The editor shows the persona's current picture and only
                # offers "Remove" when there's an upload to remove — file art
                # and the silhouette aren't the operator's to delete here.
                "avatar": avatar_url(p.slug), "has_avatar": p.has_avatar,
            })
            sq = html.escape(p.slug, quote=True)
            chips = "".join(
                f'<span class="pm-chip-sm">{html.escape(t)}</span>' for t in p.tags[:4]
            )
            search_blob = html.escape(
                " ".join([p.name, p.slug, " ".join(p.tags)]).lower(), quote=True
            )
            row_html.append(
                f'<div class="pm-row" data-group="{gq}" data-slug="{sq}" '
                f'data-search="{search_blob}">'
                f'<input type="checkbox" class="pm-sel" data-group="{gq}" data-slug="{sq}" '
                f'aria-label="Select {html.escape(p.name, quote=True)}">'
                f'<span class="pm-av avatar-has-img">'
                f'<img class="avatar-img" src="{html.escape(avatar_url(p.slug), quote=True)}" '
                f'alt="" loading="lazy" data-on-error="hide">'
                f'{html.escape(_initials(p.name))}</span>'
                f'<span class="pm-row-name">{html.escape(p.name)}</span>'
                f'<span class="pm-row-slug mono">{html.escape(p.slug)}</span>'
                f'<span class="pm-row-tags">{chips}</span>'
                f'<span class="pm-row-acts">'
                f'<button type="button" class="pm-iact pm-edit" title="Edit" aria-label="Edit">{_pm_svg("edit")}</button>'
                f'<button type="button" class="pm-iact pm-dup" title="Duplicate" aria-label="Duplicate">{_pm_svg("copy")}</button>'
                f'<button type="button" class="pm-iact pm-del" title="Delete" aria-label="Delete">{_pm_svg("trash")}</button>'
                f'</span></div>'
            )
        hidden = "" if g == active_group else " hidden"
        rows_by_group.append(
            f'<div class="pm-rows" data-group="{gq}"{hidden}>{"".join(row_html)}</div>'
        )

    # ---- Left rail: search + group navigator + new-group ----
    grp_btns = []
    for g in groups:
        act = " active" if g == active_group else ""
        grp_btns.append(
            f'<button type="button" class="pm-grp{act}" data-group="{html.escape(g, quote=True)}">'
            f'{_pm_svg("folder")}'
            f'<span class="pm-grp-name">{html.escape(_pm_glabel(g))}</span>'
            f'<span class="pm-grp-count">{group_counts[g]}</span></button>'
        )
    rail = (
        '<aside class="pm-rail">'
        f'<div class="pm-search">{_pm_svg("search")}'
        '<input type="text" id="pm-search" placeholder="Search personas" autocomplete="off"></div>'
        '<div class="pm-grps"><div class="pm-rail-h">Groups</div>'
        + "".join(grp_btns) +
        '</div>'
        '<div class="pm-rail-foot">'
        '<button type="button" class="btn btn-primary" id="pm-newgrp">+ New group</button>'
        f'<p class="pm-hint pm-reg">Find more personas in the persona registry: '
        f'<a href="{PUBLIC_REGISTRY_URL}" target="_blank" rel="noopener">{PUBLIC_REGISTRY_HOST}&nbsp;&#8599;</a></p>'
        '</div></aside>'
    )

    # ---- Center: persona list ----
    center = (
        '<section class="pm-center">'
        '<header class="pm-chead">'
        f'<h1 class="pm-ctitle" id="pm-ctitle">{html.escape(_pm_glabel(active_group).upper())}</h1>'
        '<div class="pm-ctools">'
        '<select class="pm-sort" id="pm-sort" aria-label="Sort personas">'
        '<option value="az">Name A&ndash;Z</option>'
        '<option value="za">Name Z&ndash;A</option></select>'
        '<button type="button" class="btn btn-primary" id="pm-new">+ New</button>'
        '<button type="button" class="btn" id="pm-import-open">Import</button>'
        # Out to the persona registry (a separate site), which is also where a
        # card and its avatar download as a .zip this console's Import reads back.
        f'<a class="btn pm-registry" href="{REGISTRY_URL}" target="_blank" rel="noopener" '
        'title="Browse, read and download persona cards">Persona registry &#8599;</a>'
        '<button type="button" class="btn pm-sel-toggle" id="pm-sel-toggle">Select</button>'
        '</div></header>'
        '<div class="pm-colhead"><span></span><span>Persona</span><span>Slug</span>'
        '<span>Tags</span><span></span></div>'
        '<div class="pm-scroll" id="pm-scroll">'
        + "".join(rows_by_group) +
        '<div class="pm-center-empty" id="pm-center-empty" hidden></div>'
        '</div></section>'
    )

    # ---- Right: detail / edit pane (one shared form, populated client-side) ----
    detail = (
        '<aside class="pm-detail" id="pm-detail">'
        '<div class="pm-detail-empty" id="pm-detail-empty">'
        + _registry_promo() +
        '<div class="pm-detail-start">'
        f'{_pm_svg("doc")}'
        '<p>Select a persona to edit,<br>or create a new one.</p>'
        '<button type="button" class="btn" id="pm-new-2">+ New persona</button>'
        '</div></div>'
        '<form class="pm-dform" id="pm-dform" data-mode="create" data-slug="" data-group="" hidden>'
        '<div class="pm-dhead">'
        '<h2 class="pm-dtitle" id="pm-dtitle">New persona</h2>'
        '<button type="button" class="pm-dclose" id="pm-dclose" aria-label="Close">&#10005;</button>'
        '</div>'
        '<div class="pm-dbody">'
        '<label class="pm-l">Display name</label>'
        '<input type="text" class="pm-d-name" id="pm-d-name" placeholder="e.g. Crypto Chad">'
        '<label class="pm-l">Group</label>'
        + _group_select(active_group, groups, "pm-d-group-select")
        + '<input type="text" class="pm-d-group-new" placeholder="New group name" '
        'style="display:none;margin-top:8px">'
        '<label class="pm-l">Avatar</label>'
        '<div class="pm-avrow">'
        f'<span class="pm-avprev"><img id="pm-d-avimg" src="{DEFAULT_AVATAR_URL}" alt=""></span>'
        '<div class="pm-avacts">'
        '<div class="pm-avbtns">'
        '<button type="button" class="btn" id="pm-d-avpick">Choose image&hellip;</button>'
        '<button type="button" class="btn pm-avclear" id="pm-d-avclear" hidden>Remove</button>'
        '</div>'
        '<input type="file" id="pm-d-avfile" accept="image/*" hidden>'
        '<p class="pm-hint" id="pm-d-avhint">PNG, JPEG, GIF, or WebP &mdash; '
        'squared off and scaled to 512px. Leave it empty to use the default '
        'silhouette.</p>'
        '</div></div>'
        '<label class="pm-l">Tags</label>'
        '<div class="pm-tagbox" id="pm-d-tags"><input class="pm-f-tags-input" type="text" '
        'placeholder="add a tag&hellip;"></div>'
        '<label class="pm-l">System prompt / bio</label>'
        '<div class="pm-tabs">'
        '<button type="button" class="pm-tab on" data-tab="edit">Edit</button>'
        '<button type="button" class="pm-tab" data-tab="preview">Preview</button></div>'
        '<textarea class="pm-d-body" id="pm-d-body" placeholder="Markdown personality card&hellip;"></textarea>'
        '<div class="pm-preview" id="pm-d-preview" hidden></div>'
        '</div>'
        '<div class="pm-detail-foot">'
        '<button type="button" class="btn btn-danger pm-d-delete" id="pm-d-delete">Delete</button>'
        '<button type="submit" class="btn btn-primary pm-d-save">Save</button>'
        '<span class="pm-msg pm-d-msg" id="pm-d-msg"></span>'
        '</div></form></aside>'
    )

    # ---- Import modal ----
    import_modal = (
        '<div class="pm-modal" id="pm-modal">'
        '<div class="pm-modal-card">'
        '<h3>Import personas</h3>'
        f'<p class="pm-hint">Don\'t have cards to import? The '
        f'<a href="{REGISTRY_URL}" target="_blank" rel="noopener">persona registry</a> '
        'downloads a card and its avatar as one <code>.zip</code>; drop it here.</p>'
        '<p class="pm-hint">Select one or more <code>.md</code> cards (seed-card '
        'frontmatter) and/or a <code>.zip</code> archive. The filename becomes the '
        'slug; title, tags, and category come from the frontmatter.</p>'
        '<p class="pm-hint">Pick up an <strong>avatar</strong> at the same time: '
        'an image named after its card (<code>crypto-chad.png</code> beside '
        '<code>crypto-chad.md</code>), or a zip holding both &mdash; either flat, '
        'or one folder per persona with a card and an image inside. Unmatched '
        'images are skipped.</p>'
        '<label class="pm-l">Target group</label>'
        + _group_select(active_group, groups, "pm-imp-group-select")
        + '<input class="pm-imp-group-new" type="text" placeholder="New group name" '
        'style="display:none;margin-top:8px">'
        '<label class="pm-l">Markdown files, images, or .zip</label>'
        # A drop zone around the picker, not instead of it. The copy above has
        # always said "drop both here"; without a handler the browser answers a
        # drop by navigating away from the page, which loses the modal and reads
        # as a crash. The drop writes into this same input, so the import code
        # below sees one source of files either way.
        '<div class="pm-imp-drop" id="pm-imp-drop">'
        '<span class="pm-imp-drop-hint">Drag cards, images or a <code>.zip</code> here'
        '<br><span class="pm-imp-drop-or">or</span></span>'
        '<input class="pm-imp-files" type="file" '
        'accept=".md,.markdown,.zip,.png,.jpg,.jpeg,.gif,.webp,text/markdown,'
        'application/zip,image/*" multiple>'
        '<span class="pm-imp-picked" aria-live="polite"></span>'
        '</div>'
        '<label class="pm-check" style="margin-top:12px"><input type="checkbox" '
        'class="pm-imp-overwrite"> Overwrite existing personas with the same slug</label>'
        '<div class="pm-detail-foot" style="border-top:0;padding:14px 0 0">'
        '<button type="button" class="btn pm-imp-cancel" style="margin-left:auto">Cancel</button>'
        '<button type="button" class="btn btn-primary pm-imp-btn">Import</button>'
        '<span class="pm-msg pm-imp-msg"></span>'
        '</div></div></div>'
    )

    # ---- Floating bulk-delete action bar ----
    select_actions = (
        '<div class="pm-selactions" hidden>'
        '<span class="pm-sel-count">0 selected</span>'
        '<button type="button" class="btn pm-sel-all">Select all</button>'
        '<button type="button" class="btn pm-sel-clear">Clear</button>'
        '<button type="button" class="btn btn-danger pm-sel-del" disabled>Delete selected</button>'
        '<button type="button" class="btn pm-sel-cancel">Cancel</button>'
        '<span class="pm-msg pm-sel-msg"></span>'
        '</div>'
    )

    # Persona bodies live in a JSON island the detail pane reads on selection
    # (lighter than embedding every body in a textarea per row). json_script
    # escapes "<", so a body containing "</script>" can't break out of it.
    # The default-silhouette URL is a Python constant (web.avatars), passed
    # along rather than duplicated as a literal inside js/personas.js.
    data_blob = json_script("pm-data", {"active": active_group, "personas": data_personas,
                                        "defaultAvatar": DEFAULT_AVATAR_URL})

    script = js_script("personas")

    body = (
        '<div class="pm3">'
        + rail + center + detail + import_modal + select_actions + data_blob + script
        + '</div>'
    )
    return _layout("Personas", crumbs, body, head_extras=stylesheets("personas"),
                   active="personas")
