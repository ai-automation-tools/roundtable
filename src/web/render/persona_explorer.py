"""The public persona explorer: GET /personas (the cast grid) and
GET /personas/{slug} (one persona, its card rendered, its downloads).

Read-only by construction: nothing here POSTs, so it works unchanged on the
hosted demo, where ReadOnlyMiddleware 403s every mutation. Filtering is
server-side over GET params (``q``, ``group``, ``cat``, ``tag``, ``sort``) —
links and one form, no client script — so a filtered view is a shareable URL
and the HTML-string tests see exactly what a browser sees.

Replaced the static Persona Registry on the AI-Automation-Library site
(retired 2026-11-06). The management console moved to /personas/manage.
"""

from __future__ import annotations

import html
import os
from collections import Counter
from urllib.parse import quote, urlencode

from orchestrator import personas as personas_registry
from orchestrator.personas import Persona

from web.assets import EXPLORER_CSS
from web.avatars import avatar_url, raster_avatar
from web.render.common import _layout, render_markdown
from web.security import _is_public_readonly

# Where the 2:3 cover portraits live: {PERSONA_MEDIA_URL}/covers/<slug>.webp,
# a GitHub Pages site of its own (images don't belong in this repo or the DB).
# Not every persona has one — the <img> falls back to the avatar on error.
DEFAULT_PERSONA_MEDIA_URL = "https://ai-automation-tools.dev/roundtable-personas"

_SORTS = (("name", "Name A–Z"), ("newest", "Newest"))
_TAG_CLOUD_MAX = 30


def media_url() -> str:
    return (os.environ.get("PERSONA_MEDIA_URL") or DEFAULT_PERSONA_MEDIA_URL).rstrip("/")


def cover_url(slug: str) -> str:
    return f"{media_url()}/covers/{quote(slug)}.webp"


def persona_href(p: Persona) -> str:
    return f"/personas/{quote(p.slug)}?{urlencode({'group': p.group})}"


def _e(s: str) -> str:
    return html.escape(s, quote=True)


def _cover_img(p: Persona, cls: str) -> str:
    """The cover, degrading to the avatar when the persona has no cover (or
    the media site is down) — never a broken-image icon."""
    av = _e(avatar_url(p.slug))
    return (
        f'<span class="{cls}"><img src="{_e(cover_url(p.slug))}" alt="" '
        f'loading="lazy" decoding="async" '
        f"onerror=\"this.onerror=null;this.src='{av}';"
        f"this.parentNode.classList.add('is-avatar')\"></span>"
    )


def explorer_personas() -> list[Persona]:
    """The browsable cast: every persona except the reserved AI-Models
    reference cards (same exclusion random casting uses)."""
    return personas_registry.list_debater_personas()


def _cat_label(p: Persona) -> str:
    return " / ".join(x.replace("_", " ") for x in (p.category, p.subcategory) if x)


def filter_personas(
    personas: list[Persona], *, q: str = "", group: str = "", cat: str = "",
    tag: str = "", sort: str = "name",
) -> list[Persona]:
    """Apply the explorer's filters. ``q`` matches name + slug + tags + group +
    category + the whole card body; every space-separated term must hit.
    ``cat`` is a category, or ``category/subcategory`` for the narrower one."""
    terms = q.lower().split()
    out = []
    for p in personas:
        if group and p.group.lower() != group.lower():
            continue
        if cat:
            c, _, sub = cat.partition("/")
            if p.category != c or (sub and p.subcategory != sub):
                continue
        if tag and tag.lower() not in (t.lower() for t in p.tags):
            continue
        if terms:
            blob = " ".join(
                [p.name, p.slug, p.group, p.category, p.subcategory, *p.tags, p.body]
            ).lower()
            if not all(t in blob for t in terms):
                continue
        out.append(p)
    if sort == "newest":
        out.sort(key=lambda p: p.created_at, reverse=True)
    else:
        out.sort(key=lambda p: p.name.lower())
    return out


def _href(params: dict[str, str], **change: str) -> str:
    merged = {k: v for k, v in {**params, **change}.items() if v}
    return "/personas" + (f"?{urlencode(merged)}" if merged else "")


def render_explorer(params: dict[str, str]) -> str:
    q = params.get("q", "").strip()
    group = params.get("group", "")
    cat = params.get("cat", "")
    tag = params.get("tag", "")
    sort = params.get("sort", "name")
    if sort not in dict(_SORTS):
        sort = "name"
    state = {"q": q, "group": group, "cat": cat, "tag": tag,
             "sort": "" if sort == "name" else sort}

    everyone = explorer_personas()
    shown = filter_personas(everyone, q=q, group=group, cat=cat, tag=tag, sort=sort)

    groups = sorted({p.group for p in everyone}, key=str.lower)
    cats: dict[str, set[str]] = {}
    for p in everyone:
        if p.category:
            cats.setdefault(p.category, set())
            if p.subcategory:
                cats[p.category].add(p.subcategory)

    def opt(value: str, label: str, current: str) -> str:
        sel = " selected" if value == current else ""
        return f'<option value="{_e(value)}"{sel}>{html.escape(label)}</option>'

    group_sel = opt("", "All groups", group) + "".join(
        opt(g, g.replace("-", " ").replace("_", " "), group) for g in groups)
    cat_sel = opt("", "All categories", cat)
    for c in sorted(cats, key=str.lower):
        cl = c.replace("_", " ")
        cat_sel += f'<optgroup label="{_e(cl)}">' + opt(c, f"All {cl}", cat)
        cat_sel += "".join(opt(f"{c}/{s}", s.replace("_", " "), cat)
                           for s in sorted(cats[c], key=str.lower))
        cat_sel += "</optgroup>"
    sort_sel = "".join(opt(k, label, sort) for k, label in _SORTS)

    # Selects re-submit on change; the button covers no-JS and the search box.
    autosubmit = ' onchange="this.form.submit()"'
    controls = (
        '<form class="px-controls" method="get" action="/personas" role="search">'
        '<label class="px-search"><span class="sr-only">Search personas</span>'
        f'<input type="search" name="q" value="{_e(q)}" '
        'placeholder="Search names, tags, the whole card&hellip;" autocomplete="off"></label>'
        f'<label><span class="sr-only">Group</span><select name="group"{autosubmit}>{group_sel}</select></label>'
        f'<label><span class="sr-only">Category</span><select name="cat"{autosubmit}>{cat_sel}</select></label>'
        f'<label><span class="sr-only">Sort</span><select name="sort"{autosubmit}>{sort_sel}</select></label>'
        + (f'<input type="hidden" name="tag" value="{_e(tag)}">' if tag else "")
        + '<button type="submit" class="btn btn-primary">Search</button>'
        '</form>'
    )

    counts = Counter(t for p in everyone for t in p.tags)
    cloud = "".join(
        f'<a class="px-tag{" on" if t == tag else ""}" '
        f'href="{_e(_href(state, tag="" if t == tag else t))}">{html.escape(t)}'
        f'<span>{n}</span></a>'
        for t, n in counts.most_common(_TAG_CLOUD_MAX)
    )
    active = ""
    if q or group or cat or tag:
        bits = [f"<strong>{len(shown)}</strong> of {len(everyone)}"]
        if tag:
            bits.append(f'tag <a class="px-tag on" href="{_e(_href(state, tag=""))}" '
                        f'title="Remove tag filter">{html.escape(tag)} &times;</a>')
        active = (f'<p class="px-count" role="status">{" · ".join(bits)} &middot; '
                  '<a href="/personas">clear filters</a></p>')
    else:
        active = f'<p class="px-count" role="status"><strong>{len(everyone)}</strong> personas</p>'

    cards = []
    for p in shown:
        tags = "".join(f"<span>{html.escape(t)}</span>" for t in p.tags[:3])
        cards.append(
            f'<a class="px-card" href="{_e(persona_href(p))}">'
            + _cover_img(p, "px-cover")
            + '<span class="px-cbody">'
            f'<strong class="px-name">{html.escape(p.name)}</strong>'
            f'<span class="px-kick">{html.escape(p.group.replace("-", " "))}</span>'
            f'<span class="px-ctags">{tags}</span></span></a>'
        )
    grid = (
        f'<div class="px-grid">{"".join(cards)}</div>' if cards else
        '<p class="px-empty">No persona matches that. <a href="/personas">Clear the filters</a></p>'
    )

    manage = '<a class="btn" href="/personas/manage">Manage personas</a>'
    body = (
        '<div class="px">'
        '<header class="px-head"><div>'
        '<h2 class="page-title">Agent Personas</h2>'
        '<p class="page-sub">Every persona an agent can play. Read a card exactly as the '
        'model reads it, download it, or put it in a debate.</p></div>'
        f'{manage}</header>'
        f'{controls}<nav class="px-cloud" aria-label="Tags">{cloud}</nav>{active}{grid}'
        '</div>'
    )
    return _layout("Agent Personas", "<strong>Agent Personas</strong>", body,
                   head_extras=EXPLORER_CSS, active="registry")


def find_persona(slug: str, group: str = "") -> Persona | None:
    """Exact-slug lookup for the explorer (``group`` narrows when two groups
    share a slug). AI-Models cards resolve too — a direct link is honoured;
    they're only kept out of the grid."""
    for p in personas_registry.list_personas(group or None):
        if p.slug == slug:
            return p
    return None


def render_persona_detail(p: Persona) -> str:
    gq = urlencode({"group": p.group})
    slug_q = quote(p.slug)
    art = raster_avatar(p.slug)
    ext = {"image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}.get(
        art[0], "png") if art else ""

    downloads = [
        f'<a class="btn" href="/personas/{slug_q}/card.md?{gq}" '
        f'download="{_e(p.slug)}.md">Card (.md)</a>'
    ]
    if art:
        downloads.append(
            f'<a class="btn" href="{_e(avatar_url(p.slug))}" '
            f'download="{_e(p.slug)}-avatar.{ext}">Avatar (.{ext})</a>')
    downloads.append(
        f'<a class="btn" href="/personas/{slug_q}/bundle.zip?{gq}" '
        f'download="{_e(p.slug)}.zip">{"Card + avatar" if art else "Card"} (.zip)</a>')

    # Hosted, /orchestrate is the "debates run on your machine" explainer —
    # still the right place to send someone who wants to start one.
    hosted = _is_public_readonly()
    use = (
        f'<a class="btn btn-primary" href="/orchestrate?persona={slug_q}">'
        'Use in a debate &rarr;</a>'
        + ('<p class="px-hint">Debates run on your own machine &mdash; the next page '
           'shows how. Download the .zip and import it into your copy.</p>'
           if hosted else '')
    )
    tags = "".join(
        f'<a class="px-tag" href="/personas?{urlencode({"tag": t})}">{html.escape(t)}</a>'
        for t in p.tags)
    meta_rows = [("Slug", f"<code>{html.escape(p.slug)}</code>"),
                 ("Group", f'<a href="/personas?{gq}">{html.escape(p.group)}</a>')]
    if p.category:
        meta_rows.append(("Category", html.escape(_cat_label(p))))
    if p.created_at:
        meta_rows.append(("Added", html.escape(p.created_at[:10])))
    meta = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in meta_rows)

    body = (
        '<div class="px px-detail">'
        '<p class="px-back"><a href="/personas">&larr; All personas</a></p>'
        '<div class="px-dgrid">'
        + _cover_img(p, "px-cover px-dcover") +
        '<section class="px-dmain">'
        '<div class="px-id">'
        f'<img class="px-av" src="{_e(avatar_url(p.slug))}" alt="" width="64" height="64">'
        f'<div><p class="px-kick">{html.escape(p.group.replace("-", " "))}</p>'
        f'<h2 class="page-title">{html.escape(p.name)}</h2></div></div>'
        + (f'<p class="px-summary">{html.escape(p.summary)}</p>' if p.summary else "")
        + (f'<div class="px-tags">{tags}</div>' if tags else "")
        + f'<div class="px-actions">{use}</div>'
        f'<div class="px-dl"><span class="px-dl-h">Download</span>{"".join(downloads)}</div>'
        f'<dl class="px-meta">{meta}</dl>'
        f'<p class="px-hint"><a href="/personas/manage?{urlencode({"group": p.group, "q": p.name})}">'
        'Edit in the manager</a></p>'
        '</section></div>'
        '<section class="px-card-body">'
        '<h3>The card <span>&mdash; exactly as the model reads it</span></h3>'
        f'<div class="msg-body">{render_markdown(p.body)}</div></section>'
        '</div>'
    )
    crumbs = f'<a href="/personas">Agent Personas</a> / <strong>{html.escape(p.name)}</strong>'
    return _layout(p.name, crumbs, body, head_extras=EXPLORER_CSS, active="registry")
