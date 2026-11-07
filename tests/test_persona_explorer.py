r"""Tests for the public persona explorer — /personas, /personas/{slug}, and the
card / zip downloads.

What's worth pinning:

* **The grid excludes the reserved AI-Models group** — same rule as random
  casting; those are reference cards, not cast.
* **Filters are server-side GET params** (q / group / cat / tag / sort), so a
  filtered view is a URL and these HTML-string tests see what a browser sees.
* **A cover never renders broken** — every cover <img> falls back to the avatar.
* **The downloads round-trip**: the .zip the explorer hands out re-imports
  through POST /api/personas/import with its avatar, and the .md alone re-imports
  with the same name, tags and category.
* **It works on the read-only demo** — every explorer route is a GET.

Runs under pytest *or* standalone with the project venv:

    .\.venv\Scripts\python.exe tests\test_persona_explorer.py

Uses an isolated temp DB — never touches the real ``db/chat.db``.
"""

from __future__ import annotations

import base64
import importlib
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

from starlette.testclient import TestClient

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYAAAAAYAAjCB"
    "0C8AAAAASUVORK5CYII="
)


def _seed() -> None:
    """Fresh temp DB with three cast personas and one AI-Models card."""
    tmp = Path(tempfile.mkdtemp(prefix="agentchat-explorer-")) / "chat.db"
    import web.db as webdb

    webdb.set_db_path(str(tmp))
    webdb.db_init()
    from orchestrator import personas
    from web import avatars

    avatars.invalidate_index()
    personas.create_persona(
        name='Crypto "Chad"', group="Podcasters", tags=["crypto", "bro"],
        category="System_Prompts", subcategory="Podcast_Personalities",
        body="# Crypto Chad\n\n## Purpose\nTo the **moon**, always.\n",
        avatar=base64.b64encode(PNG_1PX).decode("ascii"),
    )
    personas.create_persona(
        name="Gordon Grill", group="Comedians", tags=["food"],
        category="System_Prompts", subcategory="Chefs",
        body="Shouts about risotto and lamb sauce.",
    )
    personas.create_persona(
        name="Zz Quiet Tester", group="Comedians", tags=["deadpan", "food"],
        body="Says very little. Means all of it.",
    )
    personas.create_persona(
        name="Claude Code", group="AI-Models", tags=["cli"], body="A reference card.",
    )


def _client() -> TestClient:
    import web_ui

    return TestClient(web_ui.app)


def _grid(page: str) -> str:
    """Everything from the result count down: the cards, or the empty state."""
    return page[page.index('class="px-count"'):]


def test_explorer_renders_cast_and_excludes_ai_models() -> None:
    _seed()
    page = _client().get("/personas").text
    grid = _grid(page)
    for name in ("Crypto &quot;Chad&quot;", "Gordon Grill", "Zz Quiet Tester"):
        assert name in grid, name
    assert "Claude Code" not in grid
    assert "AI-Models" not in page  # not even offered as a group filter
    assert 'href="/personas/manage"' in page


def test_cover_uses_media_url_and_falls_back_to_avatar() -> None:
    _seed()
    os.environ["PERSONA_MEDIA_URL"] = "https://media.example/rt/"
    try:
        page = _client().get("/personas").text
    finally:
        os.environ.pop("PERSONA_MEDIA_URL", None)
    assert 'src="https://media.example/rt/covers/gordon-grill.webp"' in page
    covers = page.count("/covers/")
    assert covers == 3
    # Every cover carries its own avatar fallback, so a missing cover is never broken.
    assert page.count("this.onerror=null;this.src='/avatars/") == covers
    from web.render.persona_explorer import DEFAULT_PERSONA_MEDIA_URL, media_url
    assert media_url() == DEFAULT_PERSONA_MEDIA_URL


def test_filters_search_group_category_tag_and_sort() -> None:
    _seed()
    c = _client()
    # full-text over the card body, every term must match
    g = _grid(c.get("/personas", params={"q": "lamb risotto"}).text)
    assert "Gordon Grill" in g and "Zz Quiet Tester" not in g
    g = _grid(c.get("/personas", params={"q": "risotto deadpan"}).text)
    assert "No persona matches" in g
    g = _grid(c.get("/personas", params={"group": "Comedians"}).text)
    assert "Gordon Grill" in g and "Zz Quiet Tester" in g and "Chad" not in g
    g = _grid(c.get("/personas", params={"cat": "System_Prompts/Chefs"}).text)
    assert "Gordon Grill" in g and "Chad" not in g
    g = _grid(c.get("/personas", params={"cat": "System_Prompts"}).text)
    assert "Gordon Grill" in g and "Chad" in g and "Zz Quiet Tester" not in g
    g = _grid(c.get("/personas", params={"tag": "food"}).text)
    assert "Gordon Grill" in g and "Zz Quiet Tester" in g and "Chad" not in g
    # name sort A–Z; newest puts the last-created cast persona first
    g = _grid(c.get("/personas").text)
    assert g.index("Crypto") < g.index("Gordon") < g.index("Zz Quiet")
    g = _grid(c.get("/personas", params={"sort": "newest"}).text)
    assert g.index("Zz Quiet") < g.index("Gordon") < g.index("Crypto")


def test_detail_page_renders_card_markdown_and_actions() -> None:
    _seed()
    c = _client()
    page = c.get("/personas/crypto-chad", params={"group": "Podcasters"}).text
    assert "<strong>moon</strong>" in page  # the body, rendered as Markdown
    assert 'href="/orchestrate?persona=crypto-chad"' in page
    assert "/personas/crypto-chad/card.md?group=Podcasters" in page
    assert "/personas/crypto-chad/bundle.zip?group=Podcasters" in page
    assert 'download="crypto-chad-avatar.png"' in page
    # no art of its own → no avatar download (the silhouette isn't theirs)
    assert "-avatar." not in c.get("/personas/zz-quiet-tester").text.split('class="px-dl"')[1].split("</div>")[0]
    assert c.get("/personas/nobody-here").status_code == 404


def test_card_md_reimports_with_its_metadata() -> None:
    _seed()
    from orchestrator import personas

    text = _client().get("/personas/crypto-chad/card.md").text
    p = personas.parse_card_text(text, "crypto-chad", "X")
    assert p.name == 'Crypto "Chad"'
    assert p.tags == ["crypto", "bro"]
    assert (p.category, p.subcategory) == ("System_Prompts", "Podcast_Personalities")
    assert "To the **moon**" in p.body
    # an empty category must not come back as the string "[]"
    q = personas.parse_card_text(_client().get("/personas/zz-quiet-tester/card.md").text, "q", "X")
    assert q.category == "" and q.subcategory == ""


def test_bundle_zip_round_trips_through_the_importer() -> None:
    _seed()
    c = _client()
    blob = c.get("/personas/crypto-chad/bundle.zip").content
    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    assert sorted(names) == ["crypto-chad/crypto-chad-avatar.png", "crypto-chad/crypto-chad.md"]
    res = c.post("/api/personas/import", json={
        "group": "Reimported",
        "zips": [{"filename": "crypto-chad.zip", "b64": base64.b64encode(blob).decode("ascii")}],
    }).json()
    assert res["ok"] and res["imported"] == 1 and res["avatars"] == 1, res
    from orchestrator import personas
    back = personas.get_persona("crypto-chad", "Reimported")
    assert back is not None and back.has_avatar and back.tags == ["crypto", "bro"]
    assert back.name == 'Crypto "Chad"'


def test_explorer_works_on_the_read_only_demo() -> None:
    import web_ui

    os.environ["AGENT_CHAT_PUBLIC_READONLY"] = "1"
    try:
        importlib.reload(web_ui)
        _seed()
        c = TestClient(web_ui.app)
        for url in ("/personas", "/personas?q=moon", "/personas/crypto-chad",
                    "/personas/crypto-chad/card.md", "/personas/crypto-chad/bundle.zip"):
            assert c.get(url).status_code == 200, url
        page = c.get("/personas/crypto-chad").text
        assert "Debates run on your own machine" in page
    finally:
        os.environ.pop("AGENT_CHAT_PUBLIC_READONLY", None)
        importlib.reload(web_ui)


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


def test_console_advertises_the_registry_with_its_real_cast() -> None:
    # The empty detail pane on /personas/manage carries a card for the public
    # registry. Its count is the cast the registry shows (no AI-Models cards),
    # and only personas with an uploaded avatar appear in its face stack.
    from web.render.common import PUBLIC_REGISTRY_URL

    _seed()
    page = _client().get("/personas/manage").text
    promo = page[page.index('class="pm-promo"'):]
    promo = promo[:promo.index("</a>")]
    assert f'href="{PUBLIC_REGISTRY_URL}"' in page[page.index('<a class="pm-promo"'):][:200]
    assert "3 ready-made characters" in promo
    assert "in 2 groups" in promo
    assert promo.count("<img ") == 1  # only Crypto "Chad" has an upload
    assert "Browse the registry" in promo


if __name__ == "__main__":
    raise SystemExit(_main())
