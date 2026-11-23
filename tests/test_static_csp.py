r"""Static CSS/JS and the nonce Content-Security-Policy (audit RT-34).

Every page's stylesheets and scripts are files under ``src/web/static``, served
at ``/static`` with a content-hash query and a year-long immutable cache, and
every HTML response carries a CSP whose ``script-src`` is ``'self'`` plus a
per-request nonce — no ``'unsafe-inline'``. These pin, on the local app and on
the hosted read-only mirror:

1. every HTML route answers with that policy, and its nonce is fresh per request;
2. every ``<script>`` on every page carries the response's nonce and is either a
   ``/static`` file or a JSON data block — never inline code — and no page has
   a ``<style>`` block or an inline ``on*=`` handler;
3. every ``/static`` URL a page references is served, immutable when versioned
   and ``no-cache`` when not;
4. a JSON data block can't be closed early by the data inside it;
5. the persona registry host serves ``/static`` instead of bouncing it.

No test here runs a browser; ``tests/test_orchestrate_browser.py`` loads
/orchestrate in Chromium under CI. Uses a temp DB, never ``db/chat.db``.

    .\.venv\Scripts\python.exe tests\test_static_csp.py
"""

from __future__ import annotations

import importlib
import os
import re
import sys
import tempfile
from pathlib import Path

from starlette.routing import Route
from starlette.testclient import TestClient

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import web_ui  # noqa: E402

LOCAL = "http://127.0.0.1:8765"
_TMP = tempfile.mkdtemp(prefix="rt-csp-")


def _seeded_paths(db: Path) -> list[str]:
    """Every GET route in the table that renders a page, with real ids filled in."""
    from orchestrator import personas, seeding
    from web import db as web_db

    cid = seeding.seed_conversation(
        db_path=str(db), topic="csp", participants=["codex", "claude-code"],
        mode="turns", max_turns=1, first="codex").conversation_id
    web_ui.set_db_path(str(db))
    web_ui.db_init()
    personas.import_personas_from_files()
    slug = personas.list_debater_personas()[0].slug
    aid = web_db.bg_create_arena(
        url="https://example.com/t/1", site="reddit", title="An arena",
        thread=[{"id": "t1", "author": "op", "text": "hello"}])["id"]
    fill = {"cid": str(cid), "aid": str(aid), "slug": slug}
    paths = []
    for r in web_ui.routes:
        if not isinstance(r, Route) or "GET" not in (r.methods or ()):
            continue
        if r.path.startswith(("/api/", "/avatars", "/favicon")) or r.path.endswith((".md", ".zip")):
            continue
        paths.append(re.sub(r"\{(\w+)(?::\w+)?\}", lambda m: fill[m.group(1)], r.path))
    # Each settings tab renders different markup and script; the 404 page too.
    paths += ["/settings?tab=notifications", "/settings?tab=delivery",
              "/orchestrate?type=podcast", "/personas?q=a", "/no-such-page",
              "/conversations/99999", "/battleground/99999"]
    return paths


def _check_page(client: TestClient, path: str) -> list[str]:
    """Assert the CSP invariants on one page; return the /static URLs it uses."""
    r = client.get(path)
    if r.status_code in (301, 302):
        return []
    assert r.headers["content-type"].startswith("text/html"), (path, r.headers["content-type"])
    csp = r.headers.get("content-security-policy", "")
    m = re.search(r"script-src 'self' 'nonce-([A-Za-z0-9_-]{16,})'(;|$)", csp)
    assert m, (path, csp)
    assert "unsafe-inline" not in csp.split("script-src", 1)[1].split(";", 1)[0], (path, csp)
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp, csp
    nonce = m.group(1)
    page = r.text
    tags = re.findall(r"<script\b([^>]*)>(.*?)</script>", page, re.S)
    assert tags, path
    for attrs, body in tags:
        assert f'nonce="{nonce}"' in attrs, (path, attrs)
        if 'type="application/json"' in attrs:
            continue
        assert re.search(r'\bsrc="', attrs), (path, attrs, body[:80])
        assert not body.strip(), (path, "a script tag with both src and inline code")
    assert "<style" not in page, (path, "inline <style> block")
    handler = re.search(r"<[a-z][^>]*\son[a-z]+\s*=", page)
    assert not handler, (path, handler.group(0)[-80:])
    assert "javascript:" not in page, path
    return re.findall(r'(?:src|href)="(/static/[^"]+)"', page)


def _check_app(client: TestClient, paths: list[str]) -> None:
    static: set[str] = set()
    for p in paths:
        static.update(_check_page(client, p))
    assert any("/static/js/boot.js" in u for u in static), sorted(static)
    for url in sorted(static):
        r = client.get(url)
        assert r.status_code == 200, url
        assert r.headers["cache-control"] == "public, max-age=31536000, immutable", url


def test_every_local_page_has_a_nonce_csp_and_no_inline_code():
    db = Path(_TMP) / "local.db"
    paths = _seeded_paths(db)
    assert len(paths) >= 15, paths
    _check_app(TestClient(web_ui.app, base_url=LOCAL), paths)


def test_every_hosted_page_has_the_same_policy():
    """The read-only mirror renders different bodies (explainers instead of
    forms) and loads the consent script; the policy and invariants hold there too."""
    saved = os.environ.get("AGENT_CHAT_PUBLIC_READONLY")
    try:
        os.environ["AGENT_CHAT_PUBLIC_READONLY"] = "1"
        importlib.reload(web_ui)
        paths = _seeded_paths(Path(_TMP) / "hosted.db")
        client = TestClient(web_ui.app, base_url=LOCAL)
        _check_app(client, paths)
        home = client.get("/").text
        assert re.search(r'<script src="https://ai-automation-tools\.dev/consent\.js" defer nonce="', home)
    finally:
        os.environ.pop("AGENT_CHAT_PUBLIC_READONLY", None)
        if saved is not None:
            os.environ["AGENT_CHAT_PUBLIC_READONLY"] = saved
        importlib.reload(web_ui)


def test_the_nonce_is_fresh_per_request():
    web_ui.set_db_path(str(Path(_TMP) / "fresh.db"))
    web_ui.db_init()
    c = TestClient(web_ui.app, base_url=LOCAL)
    a, b = (c.get("/conversations").headers["content-security-policy"] for _ in range(2))
    assert a != b


def test_non_html_keeps_the_bare_frame_policy():
    web_ui.set_db_path(str(Path(_TMP) / "json.db"))
    web_ui.db_init()
    c = TestClient(web_ui.app, base_url=LOCAL)
    assert c.get("/api/conversations").headers["content-security-policy"] == "frame-ancestors 'none'"


def test_static_cache_headers():
    from web.assets import static_url

    c = TestClient(web_ui.app, base_url=LOCAL)
    url = static_url("js/shell.js")
    assert re.fullmatch(r"/static/js/shell\.js\?v=[0-9a-f]{12}", url), url
    versioned = c.get(url)
    assert versioned.status_code == 200
    assert versioned.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert versioned.headers["content-type"].startswith(("text/javascript", "application/javascript"))
    bare = c.get("/static/css/base.css")
    assert bare.status_code == 200 and bare.headers["cache-control"] == "no-cache"
    assert bare.headers["content-type"].startswith("text/css")
    assert c.get("/static/css/nope.css").status_code == 404
    assert c.get("/static/../web_ui.py").status_code == 404


def test_the_version_follows_the_content():
    """A deploy that changes a file changes its URL: the query is its hash."""
    import hashlib

    from web.assets import STATIC_DIR, static_url

    data = (STATIC_DIR / "css/light.css").read_bytes()
    assert static_url("css/light.css").endswith("?v=" + hashlib.sha256(data).hexdigest()[:12])


def test_a_json_block_cannot_be_closed_by_its_data():
    from web.assets import json_script

    out = json_script("x", {"name": "</script><script>alert(1)</script>", "a": "&<>"})
    assert out.count("</script>") == 1 and out.endswith("</script>")
    assert "<script>alert" not in out
    import json
    body = out[out.index(">") + 1:-len("</script>")]
    assert json.loads(body)["name"] == "</script><script>alert(1)</script>"


def test_the_registry_host_serves_static_files():
    from web.assets import static_url
    from web.render.common import PUBLIC_REGISTRY_HOST

    os.environ["AGENT_CHAT_ALLOWED_HOSTS"] = PUBLIC_REGISTRY_HOST
    try:
        importlib.reload(web_ui)
        c = TestClient(web_ui.app, base_url=f"https://{PUBLIC_REGISTRY_HOST}")
        r = c.get(static_url("css/explorer.css"), follow_redirects=False)
        assert r.status_code == 200, r.status_code
    finally:
        os.environ.pop("AGENT_CHAT_ALLOWED_HOSTS", None)
        importlib.reload(web_ui)


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
