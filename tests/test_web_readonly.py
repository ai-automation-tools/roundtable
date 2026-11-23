r"""Tests for the public read-only gate + middleware wiring in ``web_ui``.

Covers the security fix that makes the hosted Fly mirror read-only:

* :class:`web_ui.ReadOnlyMiddleware` rejects browser mutations (403) while
  leaving GETs and the bearer-gated ``/api/ingest`` sync realm open.
* :func:`web_ui._build_middleware` assembles the stack from the
  ``AGENT_CHAT_PUBLIC_READONLY`` and ``AGENT_CHAT_BASIC_AUTH_PASSWORD``
  env flags (both off by default).

Runs under pytest *or* standalone with the project venv (no pytest needed):

    .\.venv\Scripts\python.exe tests\test_web_readonly.py

Uses an isolated temp ``chat.db`` — never touches the real ``db/chat.db``.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
import tempfile
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
# The Host allowlist (web.security) refuses TestClient's default "testserver".
LOCAL = "http://127.0.0.1:8765"

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import web_ui  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Middleware behaviour, in isolation (no DB, no real routes)
# ---------------------------------------------------------------------------

def _isolated_client() -> TestClient:
    """A tiny app wrapping ReadOnlyMiddleware around stand-in routes."""

    async def ok(request):
        return JSONResponse({"ok": True})

    async def mutate(request):
        return JSONResponse({"mutated": True})

    async def ingest(request):
        # Stand-in for the real bearer-gated handler.
        return JSONResponse({"ingested": True})

    app = Starlette(
        routes=[
            Route("/conversations", ok, methods=["GET"]),
            Route("/api/personas", mutate, methods=["POST"]),
            Route("/api/conversations/1/delete", mutate, methods=["POST"]),
            Route("/api/ingest", ingest, methods=["POST"]),
        ],
        middleware=[Middleware(web_ui.ReadOnlyMiddleware)],
    )
    return TestClient(app, base_url=LOCAL)


def test_readonly_allows_get():
    client = _isolated_client()
    resp = client.get("/conversations")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_readonly_allows_head():
    # Starlette auto-serves HEAD for GET routes; the gate must not block it.
    client = _isolated_client()
    resp = client.head("/conversations")
    assert resp.status_code == 200


def test_readonly_blocks_post_mutations():
    client = _isolated_client()
    for path in ("/api/personas", "/api/conversations/1/delete"):
        resp = client.post(path)
        assert resp.status_code == 403, path
        assert resp.json()["error"] == "read-only deployment", path


def test_readonly_allows_ingest_bearer_realm():
    # /api/ingest is exempt: it authenticates itself in the route handler,
    # so the local->Fly sidecar keeps pushing even on a read-only mirror.
    client = _isolated_client()
    resp = client.post("/api/ingest")
    assert resp.status_code == 200
    assert resp.json() == {"ingested": True}


# ---------------------------------------------------------------------------
# 2. _env_truthy + _build_middleware wiring (no DB)
# ---------------------------------------------------------------------------

def test_env_truthy_variants(monkeypatch=None):
    truthy = ["1", "true", "TRUE", "Yes", "on", "  on  "]
    falsy = ["", "0", "false", "no", "off", "nope"]
    for val in truthy:
        os.environ["AGENT_CHAT_TEST_FLAG"] = val
        assert web_ui._env_truthy("AGENT_CHAT_TEST_FLAG") is True, repr(val)
    for val in falsy:
        os.environ["AGENT_CHAT_TEST_FLAG"] = val
        assert web_ui._env_truthy("AGENT_CHAT_TEST_FLAG") is False, repr(val)
    os.environ.pop("AGENT_CHAT_TEST_FLAG", None)
    assert web_ui._env_truthy("AGENT_CHAT_TEST_FLAG") is False


def _build_with_env(**env) -> list:
    """Call _build_middleware with a clean copy of the relevant env vars."""
    saved = {}
    keys = (
        "AGENT_CHAT_PUBLIC_READONLY",
        "AGENT_CHAT_BASIC_AUTH_PASSWORD",
        "AGENT_CHAT_BASIC_AUTH_USER",
    )
    for k in keys:
        saved[k] = os.environ.pop(k, None)
    try:
        for k, v in env.items():
            os.environ[k] = v
        return web_ui._build_middleware()
    finally:
        for k in keys:
            os.environ.pop(k, None)
            if saved[k] is not None:
                os.environ[k] = saved[k]


def test_build_middleware_default_is_cors_only():
    # Both gates off, but the AgentBattleground CORS layer is unconditional —
    # it only ever acts on /api/battleground/* with a chrome-extension origin.
    assert [m.cls for m in _build_with_env()] == [
        TrustedHostMiddleware,
        GZipMiddleware,
        web_ui.SecurityHeadersMiddleware,
        web_ui.RegistryHostMiddleware,
        web_ui.ExtensionCorsMiddleware,
        web_ui.CrossSiteWriteGuard,
        web_ui.WriteSecretMiddleware,
    ]


def test_build_middleware_readonly_only():
    stack = _build_with_env(AGENT_CHAT_PUBLIC_READONLY="1")
    assert [m.cls for m in stack] == [
        TrustedHostMiddleware,
        GZipMiddleware,
        web_ui.SecurityHeadersMiddleware,
        web_ui.RegistryHostMiddleware,
        web_ui.ExtensionCorsMiddleware,
        web_ui.CrossSiteWriteGuard,
        web_ui.ReadOnlyMiddleware,
    ]


def test_build_middleware_basic_auth_only():
    stack = _build_with_env(AGENT_CHAT_BASIC_AUTH_PASSWORD="secret")
    assert [m.cls for m in stack] == [
        TrustedHostMiddleware,
        GZipMiddleware,
        web_ui.SecurityHeadersMiddleware,
        web_ui.RegistryHostMiddleware,
        web_ui.ExtensionCorsMiddleware,
        web_ui.CrossSiteWriteGuard,
        web_ui.BasicAuthMiddleware,
        web_ui.WriteSecretMiddleware,
    ]


def test_build_middleware_both_auth_outermost():
    stack = _build_with_env(
        AGENT_CHAT_PUBLIC_READONLY="true",
        AGENT_CHAT_BASIC_AUTH_PASSWORD="secret",
    )
    # Basic auth before read-only so unauthenticated requests are challenged
    # before the read-only check runs — and CORS outside even that, so a
    # browser preflight (no Authorization header, by spec) isn't challenged.
    assert [m.cls for m in stack] == [
        TrustedHostMiddleware,
        GZipMiddleware,
        web_ui.SecurityHeadersMiddleware,
        web_ui.RegistryHostMiddleware,
        web_ui.ExtensionCorsMiddleware,
        web_ui.CrossSiteWriteGuard,
        web_ui.BasicAuthMiddleware,
        web_ui.ReadOnlyMiddleware,
    ]


def _guarded_client() -> TestClient:
    """The always-on layers (headers + cross-site write guard) around stand-ins."""

    async def mutate(request):
        return JSONResponse({"mutated": True})

    app = Starlette(
        routes=[Route("/api/settings/delivery", mutate, methods=["GET", "POST"])],
        middleware=[
            Middleware(web_ui.SecurityHeadersMiddleware),
            Middleware(web_ui.CrossSiteWriteGuard),
        ],
    )
    return TestClient(app, base_url="http://127.0.0.1:8765")


def test_cross_site_post_is_refused():
    r = _guarded_client().post("/api/settings/delivery", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403, r.status_code
    r = _guarded_client().post("/api/settings/delivery", headers={"Origin": "null"})
    assert r.status_code == 403, r.status_code


def test_same_origin_and_originless_posts_pass():
    c = _guarded_client()
    for headers in (
        {"Origin": "http://127.0.0.1:8765"},
        {"Origin": "https://box.tailnet.ts.net", "X-Forwarded-Host": "box.tailnet.ts.net"},
        {},
    ):
        r = c.post("/api/settings/delivery", headers=headers)
        assert r.status_code == 200, (headers, r.status_code)


def test_extension_origin_is_refused_off_the_bridge():
    """Until 2026-11-12 every chrome-extension:// / moz-extension:// origin was
    exempt on every route, so any installed extension could rewrite delivery
    settings (and through them run commands). Now only the configured
    AgentBattleground id is exempt, and only under /api/battleground/."""
    saved = os.environ.get("AGENT_CHAT_EXTENSION_IDS")
    os.environ["AGENT_CHAT_EXTENSION_IDS"] = "abcdef"
    try:
        c = _guarded_client()
        for origin in ("chrome-extension://otherid", "moz-extension://otherid",
                       "chrome-extension://abcdef"):
            r = c.post("/api/settings/delivery", headers={"Origin": origin})
            assert r.status_code == 403, (origin, r.status_code)
    finally:
        if saved is None:
            os.environ.pop("AGENT_CHAT_EXTENSION_IDS", None)
        else:
            os.environ["AGENT_CHAT_EXTENSION_IDS"] = saved


def test_security_headers_are_set():
    r = _guarded_client().get("/api/settings/delivery")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "strict-transport-security" not in r.headers  # plain http
    r = _guarded_client().get("/api/settings/delivery", headers={"X-Forwarded-Proto": "https"})
    assert "max-age=" in r.headers["strict-transport-security"]


def test_mutation_body_must_be_json():
    """The three content types a no-cors page may send are refused with a body;
    a JSON body and a body-less POST (stop/delete) pass."""
    c = _guarded_client()
    for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"):
        r = c.post("/api/settings/delivery", content=b'{"a":1}', headers={"Content-Type": ctype})
        assert r.status_code == 415, (ctype, r.status_code)
    r = c.post("/api/settings/delivery", content=b'{"a":1}')  # no Content-Type at all
    assert r.status_code == 415, r.status_code
    r = c.post("/api/settings/delivery", json={"a": 1})
    assert r.status_code == 200, r.status_code
    r = c.post("/api/settings/delivery", content=b"{}",
               headers={"Content-Type": "application/json; charset=utf-8"})
    assert r.status_code == 200, r.status_code
    r = c.post("/api/settings/delivery")  # body-less
    assert r.status_code == 200, r.status_code


def _hosted_stack_client(host: str, allowed: str | None = None) -> TestClient:
    """The real middleware stack (from _build_middleware) around one stand-in
    route, with ``AGENT_CHAT_ALLOWED_HOSTS`` set to *allowed* while it's built."""

    async def mutate(request):
        return JSONResponse({"mutated": True})

    saved = os.environ.pop("AGENT_CHAT_ALLOWED_HOSTS", None)
    try:
        # "" (not unset) so a developer's own .env can't leak into the test.
        os.environ["AGENT_CHAT_ALLOWED_HOSTS"] = allowed or ""
        app = Starlette(
            routes=[Route("/api/settings/delivery", mutate, methods=["GET", "POST"])],
            middleware=web_ui._build_middleware(),
        )
    finally:
        os.environ.pop("AGENT_CHAT_ALLOWED_HOSTS", None)
        if saved is not None:
            os.environ["AGENT_CHAT_ALLOWED_HOSTS"] = saved
    return TestClient(app, base_url=f"http://{host}")


def test_the_readonly_mirror_takes_a_posted_pull():
    """/api/since is a read the sidecar POSTs (its id list outgrew a query
    string, RT-15), so the read-only gate and the write secret let it by;
    the handler checks the bearer token. Any other POST is still refused."""

    async def ok(request):
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[Route("/api/since", ok, methods=["POST"]),
                Route("/api/settings/delivery", ok, methods=["POST"])],
        middleware=_build_with_env(AGENT_CHAT_PUBLIC_READONLY="1"),
    )
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    assert c.post("/api/since", json={}).status_code == 200
    assert c.post("/api/settings/delivery", json={}).status_code == 403


def test_foreign_host_is_refused_on_every_method():
    c = _hosted_stack_client("evil.example:8765")
    assert c.get("/api/settings/delivery").status_code == 400
    assert c.post("/api/settings/delivery", json={}).status_code == 400
    # A DNS-rebinding page is same-origin with its own name: Origin == Host,
    # which the cross-site guard alone would wave through.
    r = c.post("/api/settings/delivery", json={}, headers={"Origin": "http://evil.example:8765"})
    assert r.status_code == 400, r.status_code


def test_loopback_hosts_pass():
    for host in ("127.0.0.1:8765", "localhost:8765"):
        c = _hosted_stack_client(host)
        assert c.get("/api/settings/delivery").status_code == 200, host
        assert c.post("/api/settings/delivery", json={}).status_code == 200, host


def test_configured_proxy_host_passes():
    allowed = " Box.Tailnet.ts.net , roundtable-demo.ai-automation-tools.dev,*"
    c = _hosted_stack_client("box.tailnet.ts.net", allowed)
    from web.security import WRITE_HEADER, write_secret
    r = c.post("/api/settings/delivery", json={},
               headers={"Origin": "http://box.tailnet.ts.net", WRITE_HEADER: write_secret()})
    assert r.status_code == 200, r.status_code
    assert _hosted_stack_client("roundtable-demo.ai-automation-tools.dev", allowed) \
        .get("/api/settings/delivery").status_code == 200
    # A bare "*" in the list must not switch the check off.
    assert _hosted_stack_client("evil.example", allowed) \
        .get("/api/settings/delivery").status_code == 400


def test_local_write_needs_the_write_secret():
    """Host + Origin alone don't authorize a write any more (audit RT-05): a
    blind POST with a matching Origin, or none, is 401. A GET hands the
    browser the secret as a strict cookie; a script may send the header."""
    from web.security import WRITE_COOKIE, WRITE_HEADER, write_secret
    c = _hosted_stack_client("127.0.0.1:8765")
    origin = {"Origin": "http://127.0.0.1:8765"}
    assert c.post("/api/settings/delivery", json={}, headers=origin).status_code == 401
    assert c.post("/api/settings/delivery", json={}).status_code == 401
    assert c.post("/api/settings/delivery", json={},
                  headers={WRITE_HEADER: "wrong"}).status_code == 401
    # /api/ingest keeps its own bearer realm: not refused here (404 = no route).
    assert c.post("/api/ingest", json={}).status_code == 404

    page = c.get("/api/settings/delivery")
    cookie = page.headers["set-cookie"]
    assert cookie.startswith(f"{WRITE_COOKIE}=") and "HttpOnly" in cookie, cookie
    assert "samesite=strict" in cookie.lower(), cookie
    assert c.post("/api/settings/delivery", json={}, headers=origin).status_code == 200
    # Once the browser holds it, pages stop re-sending it.
    assert "set-cookie" not in c.get("/api/settings/delivery").headers

    fresh = _hosted_stack_client("127.0.0.1:8765")
    assert fresh.post("/api/settings/delivery", json={},
                      headers={WRITE_HEADER: write_secret()}).status_code == 200


def test_write_secret_is_made_once_per_install():
    from web import security
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config" / "web-write-secret"
        first = security.write_secret(path)
        security._write_secret_cache.clear()
        assert security.write_secret(path) == first == path.read_text(encoding="utf-8")
        assert len(first) >= 40
    security._write_secret_cache.clear()


def test_a_tailnet_host_needs_a_password():
    """A non-loopback AGENT_CHAT_ALLOWED_HOSTS without basic auth refuses to
    start; the read-only mirror is exempt (audit RT-05)."""
    from web import security
    keys = ("AGENT_CHAT_ALLOWED_HOSTS", "AGENT_CHAT_BASIC_AUTH_PASSWORD",
            "AGENT_CHAT_PUBLIC_READONLY")
    saved = {k: os.environ.pop(k, None) for k in keys}
    real_env_file = security._env_file_value
    security._env_file_value = lambda name, path=None: ""  # ignore a developer's .env
    argv = sys.argv
    try:
        assert security.exposure_error() is None
        os.environ["AGENT_CHAT_ALLOWED_HOSTS"] = "localhost,box.tailnet.ts.net"
        err = security.exposure_error()
        assert err.split(", which")[0] == "AGENT_CHAT_ALLOWED_HOSTS names box.tailnet.ts.net", err
        assert "AGENT_CHAT_BASIC_AUTH_PASSWORD" in err
        sys.argv = ["web_ui.py"]
        try:
            web_ui.main()
            raise AssertionError("main() started with an unauthenticated tailnet host")
        except SystemExit as exc:
            assert "refused to start" in str(exc), exc
        os.environ["AGENT_CHAT_PUBLIC_READONLY"] = "1"
        assert security.exposure_error() is None
        del os.environ["AGENT_CHAT_PUBLIC_READONLY"]
        os.environ["AGENT_CHAT_BASIC_AUTH_PASSWORD"] = "pw"
        assert security.exposure_error() is None
    finally:
        sys.argv = argv
        security._env_file_value = real_env_file
        for k in keys:
            os.environ.pop(k, None)
            if saved[k] is not None:
                os.environ[k] = saved[k]


def test_remote_access_guide_keeps_the_password_out_of_the_environment():
    guide = (Path(__file__).resolve().parent.parent / "docs" / "guides"
             / "remote-access.md").read_text(encoding="utf-8")
    assert "setx" not in guide


def test_allowed_hosts_reads_the_env_file():
    from web import security
    with tempfile.TemporaryDirectory() as tmp:
        env = Path(tmp) / ".env"
        env.write_text('# c\nAGENT_CHAT_ALLOWED_HOSTS="box.tailnet.ts.net"\n', encoding="utf-8")
        assert security._env_file_value("AGENT_CHAT_ALLOWED_HOSTS", env) == "box.tailnet.ts.net"
        assert security._env_file_value("OTHER", env) == ""
    assert security._env_file_value("X", Path(tmp) / "missing") == ""


def test_fly_toml_allows_the_mirror_hosts():
    """Merging a web change to main deploys it, so the mirror's own names must
    ship with the allowlist or every hosted page answers 400."""
    text = (Path(__file__).resolve().parents[1] / "fly.toml").read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if l.strip().startswith("AGENT_CHAT_ALLOWED_HOSTS"))
    for host in ("roundtable-demo.ai-automation-tools.dev", "agent-chat.mikesailab.com",
                 "agent-chat-mikesailab.fly.dev"):
        assert host in line, host


# ---------------------------------------------------------------------------
# 3. End-to-end against the real route table with the flag on
# ---------------------------------------------------------------------------

def _reload_app_readonly(tmp_db: Path):
    """Reload web_ui so ``app`` is rebuilt with the read-only flag, pointed at
    an isolated temp DB."""
    os.environ["AGENT_CHAT_PUBLIC_READONLY"] = "1"
    importlib.reload(web_ui)
    web_ui.set_db_path(str(tmp_db))
    web_ui.db_init()
    return web_ui.app


def test_a_bare_url_renders_as_a_link():
    """Guards the optional dependency that silently broke every transcript.

    `gfm-like` enables linkify, and markdown-it-py raises at RENDER time — not
    at import — when `linkify-it-py` is missing. The homepage carries no URLs,
    so it kept answering 200 while every conversation page 500'd, and the
    health check called the app healthy throughout. `web/render/common.py` now
    proves the renderer on a URL at import and refuses to serve otherwise; this
    pins the behaviour that check is protecting.
    """
    from web.render.common import render_markdown

    out = render_markdown("see https://example.com for details")
    assert '<a href="https://example.com"' in out, out
    assert 'target="_blank"' in out, out


def test_real_routes_readonly_end_to_end():
    saved = os.environ.get("AGENT_CHAT_PUBLIC_READONLY")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        tmp_db = Path(d) / "chat.db"
        try:
            app = _reload_app_readonly(tmp_db)
            client = TestClient(app, base_url=LOCAL)

            # Reads still work against the live route table.
            assert client.get("/conversations").status_code == 200
            assert client.get("/api/conversations").status_code == 200
            # GET /api/personas shares its path with the POST create route.
            # Pin that the method split survives read-only mode: the topbar
            # command palette needs this index on the hosted mirror, and a
            # regression here would silently empty its persona results while
            # every other page kept working.
            assert client.get("/api/personas").status_code == 200

            # Every browser mutation route is blocked before reaching its
            # handler (so no DB row is touched).
            blocked = [
                ("POST", "/api/conversations/1/stop"),
                ("POST", "/api/conversations/1/delete"),
                ("POST", "/api/orchestrate"),
                ("POST", "/api/personas"),
                ("POST", "/api/personas/import"),
                ("POST", "/api/personas/bulk-delete"),
                ("POST", "/api/personas/some-slug"),
                ("POST", "/api/personas/some-slug/delete"),
                # Declaring which CLIs you have, and creating seat folders for
                # them, are facts about a local machine — the mirror has no
                # business recording either.
                ("POST", "/api/setup"),
                ("POST", "/api/setup/seats"),
                # Notifications write config/delivery.json, which exists only
                # on a machine that runs conversations — and the test route
                # would have the mirror POST to somebody's phone.
                ("POST", "/api/notifications"),
                ("POST", "/api/notifications/test"),
                # Delivery writes a path on this machine's disk and can run a
                # command against it. Neither is anything the mirror should do.
                ("POST", "/api/settings/delivery"),
                # AgentBattleground is local-only: its arenas hold captured
                # third-party page content and never sync to the mirror, so
                # every write must 403 here too.
                ("POST", "/api/battleground/arenas"),
                ("POST", "/api/battleground/arenas/1"),
                ("POST", "/api/battleground/arenas/1/capture"),
                ("POST", "/api/battleground/arenas/1/delete"),
                ("POST", "/api/battleground/drafts/1/verdict"),
            ]
            for method, path in blocked:
                resp = client.request(method, path)
                assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}"
                assert resp.json()["error"] == "read-only deployment", path

            # Reads about this machine 404 on the mirror: /api/setup showed the
            # container's paths and /root/.claude.json (audit RT-31).
            for path in ("/api/setup", "/api/notifications", "/api/settings/delivery"):
                resp = client.get(path)
                assert resp.status_code == 404, f"GET {path} -> {resp.status_code}"
            # ...while a public page that shares a prefix still works, and so
            # does healthz: fly.toml and CI's image job health-check it.
            assert client.get("/settings").status_code == 200
            assert client.get("/api/battleground/healthz").status_code == 200
        finally:
            os.environ.pop("AGENT_CHAT_PUBLIC_READONLY", None)
            if saved is not None:
                os.environ["AGENT_CHAT_PUBLIC_READONLY"] = saved
            # Restore the module to its default (flag-off) state for any
            # later importers in the same process.
            importlib.reload(web_ui)


def test_orchestrate_is_local_only_when_readonly():
    """Hosted /orchestrate renders the local-only explainer (not the form),
    and the matching POST is blocked — while a local instance keeps the form."""
    saved = os.environ.get("AGENT_CHAT_PUBLIC_READONLY")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        tmp_db = Path(d) / "chat.db"
        try:
            # Hosted / read-only.
            app = _reload_app_readonly(tmp_db)
            client = TestClient(app, base_url=LOCAL)
            page = client.get("/orchestrate")
            assert page.status_code == 200
            assert "Debates run on your machine, not here" in page.text
            assert 'id="orch-form"' not in page.text
            assert client.post("/api/orchestrate").status_code == 403

            # Local / writable: form returns, explainer does not.
            os.environ.pop("AGENT_CHAT_PUBLIC_READONLY", None)
            importlib.reload(web_ui)
            web_ui.set_db_path(str(tmp_db))
            web_ui.db_init()
            local = TestClient(web_ui.app, base_url=LOCAL).get("/orchestrate")
            assert local.status_code == 200
            assert 'id="orch-form"' in local.text
            assert "Debates run on your machine, not here" not in local.text
        finally:
            os.environ.pop("AGENT_CHAT_PUBLIC_READONLY", None)
            if saved is not None:
                os.environ["AGENT_CHAT_PUBLIC_READONLY"] = saved
            importlib.reload(web_ui)


def test_the_mirror_offers_no_launch_it_cannot_do():
    """On the mirror every launch CTA opened the "runs on your machine"
    explainer: they now say "locally", "+ New conversation" is gone, and the
    registry's way back is a same-tab link to the demo (audit RT-42)."""
    saved = os.environ.get("AGENT_CHAT_PUBLIC_READONLY")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        tmp_db = Path(d) / "chat.db"
        try:
            client = TestClient(_reload_app_readonly(tmp_db), base_url=LOCAL)
            home = client.get("/").text
            assert "Run a debate locally" in home and "Launch a debate" not in home
            assert "+ New conversation" not in client.get("/conversations").text
            reg = client.get("/personas").text
            assert 'class="reg-out" href="https://roundtable-demo.' in reg
            assert 'target="_blank"' not in reg.split('class="reg-out"')[1].split(">")[0]

            os.environ.pop("AGENT_CHAT_PUBLIC_READONLY", None)
            importlib.reload(web_ui)
            web_ui.set_db_path(str(tmp_db))
            web_ui.db_init()
            local = TestClient(web_ui.app, base_url=LOCAL)
            assert "Launch a debate" in local.get("/").text
            assert "+ New conversation" in local.get("/conversations").text
            assert 'class="reg-out" href="/"' in local.get("/personas").text
        finally:
            os.environ.pop("AGENT_CHAT_PUBLIC_READONLY", None)
            if saved is not None:
                os.environ["AGENT_CHAT_PUBLIC_READONLY"] = saved
            importlib.reload(web_ui)


def test_an_explorer_search_says_how_many_it_found():
    """A search reloads the page: the count goes in <title> and gets focus, so
    a screen reader hears it (audit RT-42)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        web_ui.set_db_path(str(Path(tmp) / "chat.db"))
        web_ui.db_init()
        c = TestClient(web_ui.app, base_url=LOCAL)
        plain = c.get("/personas").text
        assert "<title>Browse — Agent Personas</title>" in plain
        assert "data-focus-on-load" not in plain
        hit = c.get("/personas?q=zzzz-nothing").text
        assert re.search(r"<title>0 of \d+ — Browse — Agent Personas</title>", hit), hit[:400]
        assert 'id="px-count" data-focus-on-load' in hit


def test_phones_get_the_transcript_before_the_list():
    """On a phone the conversation list used to stack above the reader, so a
    shared link opened ~700px of list before the title (audit RT-38). The
    detail and 404 pages opt in with ``cv-reading``; the index keeps the list
    first, since there the list is the page."""
    from orchestrator import seeding
    from web.assets import static_text
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "chat.db"
        cid = seeding.seed_conversation(
            db_path=str(db), topic="phone layout", participants=["codex", "claude-code"],
            mode="turns", max_turns=1, first="codex").conversation_id
        web_ui.set_db_path(str(db))
        web_ui.db_init()
        client = TestClient(web_ui.app, base_url=LOCAL)
        assert 'class="cv2 cv-reading"' in client.get(f"/conversations/{cid}").text
        missing = client.get("/conversations/99999")
        assert missing.status_code == 404 and 'class="cv2 cv-reading"' in missing.text
        assert 'class="cv2 cv-reading"' not in client.get("/conversations").text
    conv_css = static_text("css/conversations.css")
    mobile = conv_css[conv_css.index("@media (max-width:900px)"):]
    mobile = mobile[:mobile.index("\n}")]
    assert ".cv2.cv-reading .cv-rail { order:2;" in mobile
    assert ".cv-convo-box" in mobile and ".cv2.cv-reading .cv-read > * { order:2; }" in mobile


def test_a_write_waiting_on_a_lock_does_not_stall_other_requests():
    """Handlers were async def around blocking SQLite: a Stop waiting out the
    busy timeout on a locked DB froze every other request, SSE included
    (audit RT-28). Real uvicorn, because TestClient serializes requests."""
    import socket
    import sqlite3
    import threading
    import time
    import urllib.request

    import uvicorn

    from orchestrator import seeding
    from web.security import WRITE_HEADER, write_secret
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "chat.db"
        cid = seeding.seed_conversation(
            db_path=str(db), topic="lock", participants=["a", "b"],
            mode="turns", max_turns=1).conversation_id
        web_ui.set_db_path(str(db))
        web_ui.db_init()
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        server = uvicorn.Server(uvicorn.Config(web_ui.app, host="127.0.0.1", port=port,
                                               log_level="critical"))
        threading.Thread(target=server.run, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        lock = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
        try:
            deadline = time.time() + 10
            while not server.started and time.time() < deadline:
                time.sleep(0.05)
            lock.execute("BEGIN IMMEDIATE")          # every writer now waits
            stop = urllib.request.Request(
                f"{base}/api/conversations/{cid}/stop", method="POST",
                headers={WRITE_HEADER: write_secret()})
            stopped: dict = {}
            t = threading.Thread(target=lambda: stopped.update(
                r=urllib.request.urlopen(stop, timeout=20).status))
            t.start()
            time.sleep(0.5)                          # the stop is now waiting
            t0 = time.monotonic()
            with urllib.request.urlopen(f"{base}/api/conversations", timeout=20) as r:
                assert r.status == 200
            took = time.monotonic() - t0
            time.sleep(1.5)
            lock.execute("COMMIT")
            t.join(20)
            assert took < 1.0, f"an unrelated GET waited {took:.1f}s behind a locked write"
            assert stopped.get("r") == 200, stopped
        finally:
            server.should_exit = True
            lock.close()


def test_the_transcript_page_counts_messages_once():
    """One GROUP BY for the rail's message counts, not a COUNT per row."""
    from orchestrator import seeding
    from web import db as web_db
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "chat.db"
        for i in range(4):
            cid = seeding.seed_conversation(
                db_path=str(db), topic=f"t{i}", participants=[f"a{i}", f"b{i}"],
                mode="turns", max_turns=1).conversation_id
        web_ui.set_db_path(str(db))
        web_ui.db_init()
        sql: list[str] = []
        real = web_db._connect

        def traced():
            conn = real()
            conn.set_trace_callback(sql.append)
            return conn

        web_db._connect = traced
        try:
            r = TestClient(web_ui.app, base_url=LOCAL).get(f"/conversations/{cid}")
        finally:
            web_db._connect = real
        assert r.status_code == 200
        per_row = [q for q in sql if "COUNT(*) FROM messages WHERE conversation_id" in q]
        assert per_row == [], per_row
        assert sum("GROUP BY conversation_id" in q for q in sql) == 1, sql


def test_the_polled_index_is_slim_and_revalidates():
    """The chrome polls /api/conversations every 30 s for four fields; full
    rows carry the kickoff and every persona card (audit RT-41)."""
    from orchestrator import seeding
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "chat.db"
        for i in range(3):
            seeding.seed_conversation(
                db_path=str(db), topic=f"t{i}", participants=[f"a{i}", f"b{i}"],
                mode="turns", max_turns=1, initial_system_message="x" * 5000)
        web_ui.set_db_path(str(db))
        web_ui.db_init()
        c = TestClient(web_ui.app, base_url=LOCAL)
        full = c.get("/api/conversations")
        url = "/api/conversations?fields=id,topic,status,participants"
        slim = c.get(url)
        assert slim.status_code == 200
        assert all(set(r) == {"id", "topic", "status", "participants"} for r in slim.json())
        assert len(slim.content) * 5 < len(full.content), (len(slim.content), len(full.content))
        etag = slim.headers["etag"]
        again = c.get(url, headers={"If-None-Match": etag})
        assert again.status_code == 304 and again.content == b""
        from web.assets import static_text
        assert ("/api/conversations?fields=id,topic,status,participants"
                in static_text("js/shell.js"))


def test_nothing_blocks_first_paint_and_html_is_compressed():
    """A phone waited ~1.2 s on the font CSS and highlight.js in <head>, and
    a local or tailnet instance sent 270 KB of HTML uncompressed (RT-41)."""
    from web.assets import static_text
    from web.render.common import FONTS_HEAD
    assert 'rel="stylesheet"' not in FONTS_HEAD.split("<noscript>")[0]
    assert 'rel="preload" as="style"' in FONTS_HEAD
    # highlight.js is fetched on demand by js/highlight.js, never linked up front.
    loader = static_text("js/highlight.js")
    assert "cdnjs" in loader and loader.count("integrity: 'sha512-") == 2
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        web_ui.set_db_path(str(Path(tmp) / "chat.db"))
        web_ui.db_init()
        c = TestClient(web_ui.app, base_url=LOCAL)
        r = c.get("/conversations", headers={"Accept-Encoding": "gzip"})
        assert r.headers.get("content-encoding") == "gzip"


def test_every_page_loads_one_font_stylesheet_in_the_house_pair():
    """The persona console @imported a second font sheet, and the app used IBM
    Plex while the homepage and org sites use Inter + JetBrains Mono (RT-44)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        web_ui.set_db_path(str(Path(tmp) / "chat.db"))
        web_ui.db_init()
        c = TestClient(web_ui.app, base_url=LOCAL)
        for path in ("/", "/conversations", "/personas", "/personas/manage", "/orchestrate",
                     "/settings"):
            page = c.get(path).text
            assert "@import" not in page, path
            assert "IBM Plex" not in page, path
            sheets = set(re.findall(
                r'href="(https://fonts\.googleapis\.com/css2[^"]+)"', page))
            assert len(sheets) == 1, (path, sheets)
            assert "family=Inter" in next(iter(sheets)), path

def _outline(html_text: str) -> list[int]:
    import re
    html_text = re.sub(r"<(script|style)\b.*?</\1>|<!--.*?-->", "", html_text, flags=re.S)
    return [int(x) for x in re.findall(r"<h([1-6])\b", html_text)]


def test_every_page_has_one_h1_and_no_skipped_heading_level():
    """Audit RT-40: five page types had no h1, a transcript had one per cast
    card, and home skipped h2 -> h4. Messages and cards render their markdown
    headings beneath the page's own."""
    from orchestrator import seeding
    from web.render.common import render_markdown
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "chat.db"
        cid = seeding.seed_conversation(
            db_path=str(db), topic="outline", participants=["a", "b"], mode="turns",
            max_turns=2, initial_system_message="## Background\n\n### Detail\n\ntext",
            participant_personas={"a": {"persona_name": "Ann",
                                        "persona_body": "# Ann\n\n## Voice\nDry."}},
        ).conversation_id
        web_ui.set_db_path(str(db))
        web_ui.db_init()
        c = TestClient(web_ui.app, base_url=LOCAL)
        for path in ("/", "/conversations", f"/conversations/{cid}", "/conversations/99999",
                     "/personas", "/personas/manage", "/orchestrate", "/settings",
                     "/settings?tab=notifications", "/settings?tab=delivery",
                     "/battleground", "/extension", "/no-such-page"):
            hs = _outline(c.get(path).text)
            assert hs.count(1) == 1, (path, hs)
            skips = [(a, b) for a, b in zip(hs, hs[1:]) if b > a + 1]
            assert not skips, (path, skips, hs)
        page = c.get(f"/conversations/{cid}").text
        assert 'id="transcript" class="transcript" role="log" aria-live="polite"' in page
        assert '<article class="msg ' in page and 'aria-labelledby="m' in page
        assert '<h3 class="who" id="m' in page
    # The content's top heading lands one level under the given one.
    assert render_markdown("## A\n### B", 3).startswith('<h4 class="md-h2">A</h4>\n<h5 class="md-h3">')
    assert render_markdown("# T", 2) == '<h3 class="md-h1">T</h3>\n'
    assert render_markdown("# plain") == "<h1>plain</h1>\n"


def test_form_fields_have_names():
    """Audit RT-40 (UX-06): the topic, brief and notification fields had no
    accessible name, and the radio sets no group label."""
    c = TestClient(web_ui.app, base_url=LOCAL)
    orch = c.get("/orchestrate").text
    if 'id="orch-topic"' in orch:  # the local form, not the hosted explainer
        assert '<label class="lbl" for="orch-topic">' in orch
        assert 'aria-labelledby="orch-brief-label"' in orch
        assert 'role="radiogroup" aria-labelledby="orch-type-label"' in orch
    nt = c.get("/settings?tab=notifications").text
    for needle in ('for="nt-target"', 'for="nt-server"', 'aria-labelledby="nt-svc-label"'):
        assert needle in nt, needle
    dl = c.get("/settings?tab=delivery").text
    for needle in ('for="dl-folder-path"', 'for="dl-cmd-argv"', 'for="dl-cmd-timeout"'):
        assert needle in dl, needle


def test_no_spawn_refuses_an_orchestrated_spawn_before_seeding():
    """Audit RT-21: config/NO_SPAWN is a global kill switch."""
    from orchestrator import killswitch
    from web.security import WRITE_HEADER, write_secret
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        web_ui.set_db_path(str(Path(tmp) / "chat.db"))
        web_ui.db_init()
        flag = Path(tmp) / "NO_SPAWN"
        flag.write_text("", encoding="utf-8")
        real = killswitch.NO_SPAWN_FILE
        killswitch.NO_SPAWN_FILE = flag
        try:
            c = TestClient(web_ui.app, base_url=LOCAL)
            r = c.post("/api/orchestrate", headers={WRITE_HEADER: write_secret()},
                       json={"topic": "t", "participants": ["codex", "claude-code"], "spawn": True})
        finally:
            killswitch.NO_SPAWN_FILE = real
        assert r.status_code == 409 and r.json()["kind"] == "spawn_disabled", r.text
        assert c.get("/api/conversations").json() == []


def test_close_windows_is_a_local_write():
    c = _hosted_stack_client("127.0.0.1:8765")
    assert c.post("/api/conversations/1/close-windows").status_code == 401  # no write secret


def test_sse_stream_sends_the_final_message_before_complete():
    """The stream read messages, then the status: a send landing between the
    two reads closed the stream without its final message (audit RT-17).
    Forced here by inserting the final turn inside the status read."""
    import asyncio
    import sqlite3

    from orchestrator import seeding
    from web.api import conversations as api
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "chat.db"
        cid = seeding.seed_conversation(
            db_path=str(db), topic="sse", participants=["a", "b"],
            mode="turns", max_turns=1).conversation_id
        web_ui.set_db_path(str(db))
        web_ui.db_init()
        # The stream reads in a worker thread (RT-28), so this writer is shared.
        w = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
        real, poll = api.conversation_turn_state, api.POLL_INTERVAL_SECONDS
        calls = {"n": 0}

        def racing_state(c):
            calls["n"] += 1
            if calls["n"] == 2:
                w.execute("BEGIN IMMEDIATE")
                w.execute("INSERT INTO messages (conversation_id, sender, content, created_at) "
                          "VALUES (?, 'b', 'FINAL', '2026-01-01T00:00:00+00:00')", (cid,))
                w.execute("UPDATE conversations SET status='complete', current_turn=NULL "
                          "WHERE id=?", (cid,))
                w.execute("COMMIT")
            return real(c)

        class Req:
            path_params = {"cid": cid}
            query_params = {"since": "0"}
            headers: dict = {}
            client = None

            async def is_disconnected(self):
                return False

        async def collect():
            resp = await api.api_stream(Req())
            return [ev async for ev in resp.body_iterator]

        api.conversation_turn_state, api.POLL_INTERVAL_SECONDS = racing_state, 0.01
        try:
            events = asyncio.run(collect())
        finally:
            api.conversation_turn_state, api.POLL_INTERVAL_SECONDS = real, poll
            w.close()
        kinds = [e["event"] for e in events]
        assert kinds[-1] == "complete", kinds
        assert any('"FINAL"' in e["data"] for e in events if e["event"] == "message"), kinds
        assert api._streams == {}, api._streams   # the slot was given back


def test_sse_stream_refuses_a_bad_since_and_too_many_streams():
    from web.api import conversations as api
    client = TestClient(web_ui.app, base_url=LOCAL)
    r = client.get("/api/conversations/1/stream?since=abc")
    assert r.status_code == 400, r.status_code
    saved = dict(api._streams)
    try:
        api._streams.clear()
        api._streams["testclient"] = api.MAX_STREAMS_PER_CLIENT
        r = client.get("/api/conversations/1/stream")
        assert r.status_code == 429 and r.headers["retry-after"], r.status_code
        api._streams.clear()
        api._streams["203.0.113.9"] = api.MAX_STREAMS
        assert client.get("/api/conversations/1/stream").status_code == 429
        # On the mirror every request comes from Fly's proxy; the cap is per
        # Fly-Client-IP, not per proxy address.
        assert api._stream_client(type("R", (), {
            "headers": {"fly-client-ip": "198.51.100.7"}, "client": None})()) == "198.51.100.7"
    finally:
        api._streams.clear()
        api._streams.update(saved)


def test_a_hostile_sender_renders_inert():
    """sender and signal went into class="..." unescaped, so a row that came
    in through ingest could break out of the attribute (audit RT-18)."""
    from web.render.conversations import _render_message
    out = _render_message({
        "id": 7, "sender": 'codex"><img src=x onerror=alert(1)>',
        "signal": 'result"><b>x</b>', "content": "hi",
        "created_at": "2026-01-01T00:00:00+00:00"})
    assert "<img src=x" not in out and "<b>x</b>" not in out, out
    assert 'class="msg sender-codex&quot;&gt;&lt;img' in out, out
    # The live-append path builds the same markup in JS: escaped there too.
    from web.assets import static_text
    src = static_text("js/conversation.js")
    assert "'sender-' + esc(m.sender" in src and "'signal-' + esc(m.signal)" in src


def test_ingest_checks_rows_and_caps_the_body():
    from web.api import sync
    token = "t" * 32
    saved = os.environ.get("AGENT_CHAT_INGEST_TOKEN")
    os.environ["AGENT_CHAT_INGEST_TOKEN"] = token
    cap = sync.MAX_INGEST_BYTES
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            web_ui.set_db_path(str(Path(tmp) / "chat.db"))
            web_ui.db_init()
            client = TestClient(web_ui.app, base_url=LOCAL,
                                headers={"Authorization": f"Bearer {token}"})
            conv = {"id": 1, "topic": "t", "participants": "[]", "status": "complete",
                    "mode": "turns", "max_turns": 2, "conv_type": "debate",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00"}
            msg = {"id": 1, "conversation_id": 1, "sender": "codex", "content": "hi",
                   "signal": None, "created_at": "2026-01-01T00:00:00+00:00"}

            def post(**over):
                return client.post("/api/ingest", json={
                    "conversations": [conv], "messages": [{**msg, **over}]})

            assert post(sender='x"><img src=x>').status_code == 400
            assert post(signal="pwned").status_code == 400
            assert post(id="1").status_code == 400
            assert post(content=None).status_code == 400
            ok = post()
            assert ok.status_code == 200, ok.text
            sync.MAX_INGEST_BYTES = 200
            assert post(content="x" * 500).status_code == 413
    finally:
        sync.MAX_INGEST_BYTES = cap
        os.environ.pop("AGENT_CHAT_INGEST_TOKEN", None)
        if saved is not None:
            os.environ["AGENT_CHAT_INGEST_TOKEN"] = saved


def test_mcp_server_refuses_a_markup_agent_id():
    import subprocess
    server = Path(__file__).resolve().parent.parent / "src" / "agent_chat_mcp.py"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        r = subprocess.run(
            [sys.executable, str(server), "--agent-id", 'codex"><b>',
             "--db-path", str(Path(tmp) / "chat.db")],
            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert r.returncode == 2 and "--agent-id" in r.stderr, (r.returncode, r.stderr)


def test_notifications_page_is_local_only_when_readonly():
    """Hosted /notifications renders the explainer, not the form. The events it
    would notify about fire in whichever process drives the CLI windows, which
    is never this one, and its config file doesn't exist here. Both POSTs are
    covered in the blocked list above."""
    saved = os.environ.get("AGENT_CHAT_PUBLIC_READONLY")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        tmp_db = Path(d) / "chat.db"
        try:
            app = _reload_app_readonly(tmp_db)
            client = TestClient(app, base_url=LOCAL)
            page = client.get("/settings?tab=notifications")
            assert page.status_code == 200
            assert "Settings live on your own machine" in page.text
            assert "Send test notification" not in page.text

            os.environ.pop("AGENT_CHAT_PUBLIC_READONLY", None)
            importlib.reload(web_ui)
            web_ui.set_db_path(str(tmp_db))
            web_ui.db_init()
            local = TestClient(web_ui.app, base_url=LOCAL).get("/settings?tab=notifications")
            assert local.status_code == 200
            assert "Send test notification" in local.text
            assert "Settings live on your own machine" not in local.text
        finally:
            os.environ.pop("AGENT_CHAT_PUBLIC_READONLY", None)
            if saved is not None:
                os.environ["AGENT_CHAT_PUBLIC_READONLY"] = saved
            importlib.reload(web_ui)


def test_battleground_console_is_local_only_when_readonly():
    """Hosted /battleground renders the local-only explainer instead of an
    arena list — the two arena tables never sync, so a list there would be
    permanently empty and would read as "nothing captured" rather than "this
    stays on your machine". The console adds no write route of its own: its
    buttons call the bridge POSTs already covered above."""
    saved = os.environ.get("AGENT_CHAT_PUBLIC_READONLY")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        tmp_db = Path(d) / "chat.db"
        try:
            app = _reload_app_readonly(tmp_db)
            client = TestClient(app, base_url=LOCAL)
            page = client.get("/battleground")
            assert page.status_code == 200
            assert "Arenas stay on the machine that captured them" in page.text
            assert "No arenas captured yet" not in page.text

            os.environ.pop("AGENT_CHAT_PUBLIC_READONLY", None)
            importlib.reload(web_ui)
            web_ui.set_db_path(str(tmp_db))
            web_ui.db_init()
            local = TestClient(web_ui.app, base_url=LOCAL).get("/battleground")
            assert local.status_code == 200
            assert "No arenas captured yet" in local.text
            assert "Arenas stay on the machine that captured them" not in local.text
        finally:
            os.environ.pop("AGENT_CHAT_PUBLIC_READONLY", None)
            if saved is not None:
                os.environ["AGENT_CHAT_PUBLIC_READONLY"] = saved
            importlib.reload(web_ui)


def test_accessibility_quick_fixes_hold():
    """RT-39 (Lighthouse, 2026-11-22): every app page carries a description,
    the search button's name contains its visible label, the palette input is
    named, the focused skip link clears the fixed source bar, and the dark
    muted token clears 4.5:1."""
    from web.assets import static_text
    from web.render.common import _layout
    base_css = static_text("css/base.css")
    tokens_css = static_text("css/tokens.css")
    page = _layout("T", "", "<p>x</p>")
    assert '<meta name="description" content="' in page
    assert 'aria-label="Search Ctrl K"' in page and "<kbd>Ctrl K</kbd>" in page
    assert '<input id="cmdk-input"' in page and 'aria-label="Search Roundtable"' in page
    assert ".skip-link:focus { top: var(--srcbar-h);" in base_css
    assert "--muted-2: #909099;" in tokens_css


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
