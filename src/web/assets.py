"""Static assets for the web UI: the files under ``web/static/`` and the tags
that load them, plus the brand mark.

Every stylesheet and script lives in ``web/static/css`` and ``web/static/js``
as a real file (audit RT-34), so it can be linted and the pages can carry a
strict Content-Security-Policy: no inline ``<script>`` or ``<style>`` and no
inline event handlers. Render functions emit tags through the helpers here:

* :func:`stylesheets` — ``<link rel="stylesheet">`` for each named sheet;
* :func:`script` — ``<script src>`` carrying this request's CSP nonce;
* :func:`json_script` — a ``<script type="application/json">`` data block for
  the per-page values a script needs, escaped so the payload can't close the tag.

URLs are fingerprinted (``?v=<content hash>``) and served by
:class:`CachedStaticFiles` as immutable for a year, so a deploy that changes a
file changes its URL and busts every cache.
"""

from __future__ import annotations

import hashlib
import html
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from starlette.staticfiles import StaticFiles

from web.security import csp_nonce

STATIC_DIR = Path(__file__).resolve().parent / "static"


@lru_cache(maxsize=None)
def _digest(rel: str, mtime_ns: int, size: int) -> str:
    """Content hash for one file, keyed on its stat so an edit re-hashes."""
    return hashlib.sha256((STATIC_DIR / rel).read_bytes()).hexdigest()[:12]


def static_url(rel: str) -> str:
    """``/static/<rel>?v=<hash>`` — the cache-busting URL for one static file."""
    st = (STATIC_DIR / rel).stat()
    return f"/static/{rel}?v={_digest(rel, st.st_mtime_ns, st.st_size)}"


def static_text(rel: str) -> str:
    """A static file's text (tests read the stylesheets and scripts this way)."""
    return (STATIC_DIR / rel).read_text(encoding="utf-8")


def stylesheets(*names: str) -> str:
    """``<link rel="stylesheet">`` tags for ``css/<name>.css``, in order."""
    return "".join(
        f'<link rel="stylesheet" href="{static_url(f"css/{n}.css")}">' for n in names
    )


def script(name: str, **data: str) -> str:
    """A ``<script src>`` for ``js/<name>.js`` with this request's nonce.

    Not deferred: it runs where it is placed, exactly as the inline block it
    replaced did. ``data`` becomes ``data-*`` attributes (``data_x`` →
    ``data-x``), read by the script off ``document.currentScript``."""
    attrs = "".join(
        f' data-{k.replace("_", "-")}="{html.escape(str(v), quote=True)}"'
        for k, v in data.items()
    )
    return (f'<script src="{static_url(f"js/{name}.js")}" '
            f'nonce="{csp_nonce()}"{attrs}></script>')


def json_dumps_for_script(data: Any) -> str:
    """JSON safe inside a ``<script>`` element: ``<``, ``>`` and ``&`` are
    \\u-escaped, so no value (a persona named ``</script>``) can end the tag."""
    return (json.dumps(data)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def json_script(el_id: str, data: Any) -> str:
    """Per-page data for a static script: ``JSON.parse(el.textContent)``."""
    return (f'<script type="application/json" id="{html.escape(el_id, quote=True)}" '
            f'nonce="{csp_nonce()}">{json_dumps_for_script(data)}</script>')


class CachedStaticFiles(StaticFiles):
    """StaticFiles with cache headers. A fingerprinted URL (``?v=``) is
    immutable for a year — the hash changes when the file does. A bare URL is
    ``no-cache`` (revalidate with the ETag every time)."""

    def file_response(self, full_path, stat_result, scope, status_code=200):  # type: ignore[override]
        response = super().file_response(full_path, stat_result, scope, status_code)
        versioned = b"v=" in scope.get("query_string", b"")
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if versioned else "no-cache")
        return response


# The shared mikesailab.com icon family (adopted 2026-10-14): a near-black
# plate, a thin ring in a darker shade of the app colour, and the app's
# pictogram stroked in its colour (cyan #22d3ee for Roundtable — the same
# glyph and colour as its tile on the homepage). Every site's icon is built
# the same way; the canonical set lives in the Documents vault at
# Mikes-AI-Lab/Custom-Domains/Shared-Hosting/Icons/ (agent-chat.svg is this one).
# It replaced "Panel", the three-figure emerald mark from 2026-08-13.
#
# Mirror any change into
# images/AgentChat-Images/icons/dark/favicon-agents-06-panel-dark.svg.
#
# ``_MARK_ART`` is the artwork alone (no <svg> wrapper), so the tab icon
# (``FAVICON_SVG``, served at /favicon.svg) and the topbar mark
# (``MARK_SVG``, inlined into every page's left corner) cannot drift apart.
_MARK_ART = (
    "<rect width='32' height='32' rx='7' fill='#0b0b0e'/>"
    "<rect x='1' y='1' width='30' height='30' rx='6' fill='none'"
    " stroke='#137483' stroke-width='2'/>"
    "<g transform='translate(6 6) scale(0.8333)' fill='none' stroke='#22d3ee'"
    " stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'>"
    "<path d='M4 5h10v7H8l-3 3V5z'/><path d='M20 11v7h-3v3l-3-3h-4'/>"
    "</g>"
)

FAVICON_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    f"{_MARK_ART}"
    "</svg>"
).encode("utf-8")

# The same mark, inlined into the topbar by ``render.common._topbar``. No
# xmlns (it's inline HTML, not a standalone document) and no explicit size —
# ``.topbar .mark .glyph svg`` in css/topbar.css sizes it.
MARK_SVG = f'<svg viewBox="0 0 32 32" aria-hidden="true">{_MARK_ART}</svg>'
