"""Auth middleware + env-flag middleware-stack assembly.

Two independent gates, both off by default:
``AGENT_CHAT_BASIC_AUTH_PASSWORD`` (HTTP basic; required once
``AGENT_CHAT_ALLOWED_HOSTS`` names a non-loopback host, see
``exposure_error``) and ``AGENT_CHAT_PUBLIC_READONLY`` (reject browser
mutations — the hosted Fly-mirror posture).

Always on: a ``Host`` allowlist (``127.0.0.1``, ``localhost`` and
``AGENT_CHAT_ALLOWED_HOSTS``), the cross-site write guard, the baseline
security headers, and — wherever writes are possible — the per-install write
secret (``WriteSecretMiddleware``).
"""

from __future__ import annotations

import base64
import os
import secrets
import time
from pathlib import Path

from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response


# ---------------------------------------------------------------------------
# Host allowlist — always on
# ---------------------------------------------------------------------------

# The repo-root .env (gitignored; names in .env.example). Same file
# scripts/db_sync.py reads. The real environment wins over it.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost")


def _env_file_value(name: str, path: Path = _ENV_FILE) -> str:
    """``name``'s value in a KEY=VALUE .env file; empty when absent."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return ""
    for line in lines:
        key, sep, value = line.strip().removeprefix("export ").partition("=")
        if sep and key.strip() == name:
            return value.strip().strip("\"'")
    return ""


def allowed_hosts() -> list[str]:
    """Host names this server answers to.

    Loopback always, plus the comma-separated ``AGENT_CHAT_ALLOWED_HOSTS``
    (environment first, then ``.env``): a ``tailscale serve`` MagicDNS name,
    the hosted mirror's domains. Without this list the cross-site write guard
    compares ``Origin`` against a ``Host`` the client chose, which is exactly
    what a DNS-rebinding page controls. A bare ``*`` is dropped rather than
    honoured — it would switch the check off.
    """
    raw = os.environ.get("AGENT_CHAT_ALLOWED_HOSTS") or _env_file_value(
        "AGENT_CHAT_ALLOWED_HOSTS"
    )
    extra = [h.strip().lower() for h in raw.split(",")]
    return [*_LOOPBACK_HOSTS, *(h for h in extra if h and h != "*")]


def basic_auth_password() -> str:
    """``AGENT_CHAT_BASIC_AUTH_PASSWORD``: the environment, then ``.env``.

    Read from ``.env`` too so the password needn't sit in the user
    environment, where every process the app spawns (agent seats included)
    would inherit it."""
    return os.environ.get("AGENT_CHAT_BASIC_AUTH_PASSWORD") or _env_file_value(
        "AGENT_CHAT_BASIC_AUTH_PASSWORD"
    )


def exposure_error() -> str | None:
    """Why this server must not start, or None.

    A non-loopback name in ``AGENT_CHAT_ALLOWED_HOSTS`` (a ``tailscale serve``
    MagicDNS name) means other machines can reach the control surface, which
    can launch agents and configure command sinks. That needs a password. The
    read-only mirror is exempt: it has no writes to protect and is public by
    design (audit RT-05).
    """
    remote = [h for h in allowed_hosts() if h not in _LOOPBACK_HOSTS]
    if not remote or basic_auth_password() or _is_public_readonly():
        return None
    return (
        f"AGENT_CHAT_ALLOWED_HOSTS names {', '.join(remote)}, which other machines "
        "can reach, but no AGENT_CHAT_BASIC_AUTH_PASSWORD is set. Add one to the "
        "repo's .env (docs/guides/remote-access.md) or remove the host."
    )


# ---------------------------------------------------------------------------
# Write secret — required on every local mutation (audit RT-05)
# ---------------------------------------------------------------------------

# Per install, generated on first use. config/ is gitignored.
WRITE_SECRET_FILE = Path(__file__).resolve().parents[2] / "config" / "web-write-secret"
WRITE_COOKIE = "rt_write"
WRITE_HEADER = "x-roundtable-write"
_write_secret_cache: dict[Path, str] = {}


def write_secret(path: Path = WRITE_SECRET_FILE) -> str:
    """This install's write secret, creating it on first call.

    Two processes may race to create it: ``open(..., "x")`` lets exactly one
    write, and the loser reads what the winner wrote."""
    if path in _write_secret_cache:
        return _write_secret_cache[path]
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as f:
            f.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    value = ""
    for _ in range(50):  # the winner may not have flushed yet
        value = path.read_text(encoding="utf-8").strip()
        if value:
            break
        time.sleep(0.01)
    if not value:
        raise RuntimeError(f"{path} is empty; delete it and restart the web UI")
    _write_secret_cache[path] = value
    return value


def has_write_secret(request: Request) -> bool:
    """True when the request carries this install's write secret, as the
    cookie this server sets on every page or as the ``X-Roundtable-Write``
    header (scripts)."""
    expected = write_secret().encode("utf-8")
    for given in (request.cookies.get(WRITE_COOKIE), request.headers.get(WRITE_HEADER)):
        if given and secrets.compare_digest(given.encode("utf-8"), expected):
            return True
    return False


class WriteSecretMiddleware(BaseHTTPMiddleware):
    """Refuse a mutation that doesn't carry the per-install write secret.

    The Host and Origin checks stop a page on another site, but a request
    with no ``Origin`` passes them: a blind POST from another local service,
    a webhook pointed at ``127.0.0.1``, a stray ``curl``. This makes every
    write prove it could first read one of this app's own responses.

    The secret reaches the browser as an ``HttpOnly``, ``SameSite=Strict``
    cookie set on any GET that lacks it, so the app's own pages need no
    change. A process that can GET a page, or read ``config/``, can still
    write; containing local agents is the seat sandbox's job, not this one.

    Exempt: ``/api/ingest`` (its own bearer realm) and the AgentBattleground
    bridge, whose handler requires the bridge token or a same-origin request
    carrying this secret (``battleground._authorized``). Not installed on the
    read-only mirror, which refuses every browser write anyway.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method in _SAFE_METHODS:
            response = await call_next(request)
            if request.cookies.get(WRITE_COOKIE) != write_secret():
                https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
                response.set_cookie(
                    WRITE_COOKIE, write_secret(), max_age=400 * 86400, path="/",
                    httponly=True, samesite="strict", secure=https,
                )
            return response
        if (path in _BEARER_REALM_PATHS or path.startswith(_BATTLEGROUND_PREFIX)
                or has_write_secret(request)):
            return await call_next(request)
        return JSONResponse(
            {
                "error": "missing write secret",
                "detail": (
                    "Reload the page and try again. Scripts send the value of "
                    "config/web-write-secret as the X-Roundtable-Write header."
                ),
            },
            status_code=401,
        )


# ---------------------------------------------------------------------------
# Auth (HTTP Basic) — only active when AGENT_CHAT_BASIC_AUTH_PASSWORD is set
# ---------------------------------------------------------------------------

class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Single shared-credential gate for the public Fly deploy.

    Off by default. Enable by setting AGENT_CHAT_BASIC_AUTH_PASSWORD
    (and optionally AGENT_CHAT_BASIC_AUTH_USER, which defaults to
    "admin"). For real multi-user auth, replace this with whatever
    your platform fronts you with (Cloudflare Access, a Tailscale
    identity policy, etc.). For phone access to a *local* instance,
    ``tailscale serve`` over the loopback bind is the answer and this
    gate is the optional second factor — docs/guides/remote-access.md.
    """

    def __init__(self, app, username: str, password: str) -> None:
        super().__init__(app)
        self._user_b = username.encode("utf-8")
        self._pwd_b = password.encode("utf-8")

    async def dispatch(self, request: Request, call_next):
        # /api/ingest is a separate auth realm (bearer token, validated in
        # the route handler). Skip the basic-auth gate so machine-to-machine
        # clients don't have to also know the human basic-auth password.
        # /favicon.svg and /avatars/* are static, non-sensitive assets — let
        # browsers fetch them for the auth-challenge tab itself so images show.
        path = request.url.path
        if (path in ("/api/ingest", "/api/since", "/favicon.svg")
                or path.startswith("/avatars/")):
            return await call_next(request)
        header = request.headers.get("authorization", "")
        if header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:]).decode("utf-8", "replace")
                user, _, pwd = decoded.partition(":")
                if (
                    secrets.compare_digest(user.encode("utf-8"), self._user_b)
                    and secrets.compare_digest(pwd.encode("utf-8"), self._pwd_b)
                ):
                    return await call_next(request)
            except Exception:
                pass
        return Response(
            "Authentication required.\n",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="agent_chat"'},
            media_type="text/plain",
        )


# ---------------------------------------------------------------------------
# Read-only public mode — reject browser mutations when
# AGENT_CHAT_PUBLIC_READONLY is set (the posture for the hosted Fly mirror)
# ---------------------------------------------------------------------------

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# POST routes that carry their own bearer-token auth (the sidecar sync realm)
# and must keep working even when the public site is read-only. /api/since is
# a read, POSTed so its known-id list can't outgrow a request head (RT-15).
_BEARER_REALM_PATHS = frozenset({"/api/ingest", "/api/since"})

# Reads about *this machine* — CLI probes and config/ files. On the mirror
# they described the container (``/root/.claude.json``), so a read gets 404
# there; a write still gets the read-only 403 (RT-31). Not /api/battleground:
# its healthz is the Fly and CI health check, and its arenas never sync.
_LOCAL_ONLY_PREFIXES = ("/api/setup", "/api/settings", "/api/notifications")


def _is_local_only(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in _LOCAL_ONLY_PREFIXES)


def _env_truthy(name: str) -> bool:
    """True when env var *name* is set to a truthy string (1/true/yes/on)."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _is_public_readonly() -> bool:
    """True on the hosted public mirror (AGENT_CHAT_PUBLIC_READONLY set).

    Route handlers use this to render hosted-appropriate UI — e.g. /orchestrate
    becomes a local-only explainer instead of a form that can't spawn local
    CLIs. The actual mutation block is enforced by ReadOnlyMiddleware; this is
    just for presentation."""
    return _env_truthy("AGENT_CHAT_PUBLIC_READONLY")


class ReadOnlyMiddleware(BaseHTTPMiddleware):
    """Reject browser mutations when the deploy is in public read-only mode.

    Enabled by setting AGENT_CHAT_PUBLIC_READONLY (1/true/yes/on) — the
    intended posture for the hosted Fly mirror, which is a viewer, not a
    control surface. Any non-safe HTTP method (everything but GET/HEAD/
    OPTIONS) is answered with 403, *except* the bearer-token sync realm
    (/api/ingest), which authenticates itself in the route handler so the
    local->Fly sidecar keeps pushing. New mutation routes are covered
    automatically — the gate keys off the HTTP method, not a path list.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method in _SAFE_METHODS and _is_local_only(request.url.path):
            return JSONResponse({"error": "not found"}, status_code=404)
        if (
            request.method not in _SAFE_METHODS
            and request.url.path not in _BEARER_REALM_PATHS
        ):
            return JSONResponse(
                {
                    "error": "read-only deployment",
                    "detail": (
                        "This hosted mirror is read-only. Run conversations and "
                        "manage personas on your local instance."
                    ),
                },
                status_code=403,
            )
        return await call_next(request)


# ---------------------------------------------------------------------------
# Browser-extension CORS — narrowly scoped to the AgentBattleground bridge
# ---------------------------------------------------------------------------

_BATTLEGROUND_PREFIX = "/api/battleground/"
_EXTENSION_SCHEMES = ("chrome-extension://", "moz-extension://")


def extension_ids() -> frozenset[str]:
    """The AgentBattleground install(s) allowed to call the bridge.

    ``AGENT_CHAT_EXTENSION_IDS``, comma-separated (environment first, then
    ``.env``): the Chrome id from ``chrome://extensions``, or the Firefox
    *Internal UUID* from ``about:debugging`` — the host part of the origin the
    browser sends. Read per call (only for extension-scheme origins), so an
    edit to ``.env`` needs no restart. Unset means no extension is trusted.
    """
    raw = os.environ.get("AGENT_CHAT_EXTENSION_IDS") or _env_file_value(
        "AGENT_CHAT_EXTENSION_IDS"
    )
    return frozenset(i.strip().lower() for i in raw.split(",") if i.strip())


def is_configured_extension(origin: str) -> bool:
    """True when *origin* is ``chrome-extension://`` / ``moz-extension://``
    plus an id listed in ``AGENT_CHAT_EXTENSION_IDS``."""
    if not origin.startswith(_EXTENSION_SCHEMES):
        return False
    return origin.partition("://")[2].lower() in extension_ids()


def is_same_origin(request: Request) -> bool:
    """True when the browser says this request came from one of our own pages.

    ``Origin`` matches ``Host`` (or ``X-Forwarded-Host``, for ``tailscale
    serve``). A page can't forge ``Origin``; a non-browser client can, which
    is fine — it can open ``db/chat.db`` directly anyway.
    """
    origin = request.headers.get("origin")
    hosts = {request.headers.get("host"), request.headers.get("x-forwarded-host")}
    return origin is not None and origin.partition("://")[2] in hosts


class ExtensionCorsMiddleware(BaseHTTPMiddleware):
    """Let the AgentBattleground extension call ``/api/battleground/*``.

    The extension's service worker fetches this server cross-origin, so it
    needs CORS headers. Deliberately narrow on both axes rather than a
    blanket ``Access-Control-Allow-Origin: *``:

    * **Path** — only the battleground bridge. Every other route keeps
      today's posture, where a random page you're browsing can fire a
      no-CORS POST at localhost but can never read the response.
    * **Origin** — only ``chrome-extension://<id>`` for an id listed in
      ``AGENT_CHAT_EXTENSION_IDS``. A normal web page's origin, or any other
      extension's, is never echoed, so neither can read your local DB even if
      it guesses the port.

    Always on (no env flag): with no matching origin it adds nothing.
    """

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin", "")
        scoped = (
            request.url.path.startswith(_BATTLEGROUND_PREFIX)
            and origin.startswith("chrome-extension://")
            and is_configured_extension(origin)
        )
        if scoped and request.method == "OPTIONS":
            # Preflight: answer here so it never reaches the auth/read-only
            # gates below (a preflight carries no Authorization header).
            return Response(status_code=204, headers=_cors_headers(origin))
        response = await call_next(request)
        if scoped:
            response.headers.update(_cors_headers(origin))
        return response


def _cors_headers(origin: str) -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Max-Age": "600",
        "Vary": "Origin",
    }


# ---------------------------------------------------------------------------
# Cross-site write guard + security headers — always on
# ---------------------------------------------------------------------------

class CrossSiteWriteGuard(BaseHTTPMiddleware):
    """Refuse a browser mutation sent from another site (CSRF).

    ``request.json()`` doesn't check Content-Type, so any page you browse
    could fire a ``no-cors`` POST at the local instance and, through
    /api/settings/delivery or /api/orchestrate, end up running commands.
    Browsers always send ``Origin`` on a cross-origin POST, so a non-safe
    request whose Origin isn't this host is answered 403. The one exemption
    is the configured AgentBattleground extension (``AGENT_CHAT_EXTENSION_IDS``)
    and only under ``/api/battleground/`` — any other extension, or the right
    one on any other route, is just another site. No Origin at all (curl, the MCP server, the sidecar)
    passes: that is not a browser being tricked. ``X-Forwarded-Host`` counts
    as this host too (a reverse proxy such as ``tailscale serve``); a
    ``no-cors`` page can't set that header. ``Host`` itself is pinned by the
    allowlist layer outside this one.

    A mutation that carries a body must also say ``application/json``: every
    route that reads one parses JSON, and the three content types a ``no-cors``
    form or fetch may send (``text/plain``, form-encoded, multipart) are not
    it. A body-less POST (stop, delete) has nothing to declare and passes.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method in _SAFE_METHODS:
            return await call_next(request)
        origin = request.headers.get("origin")
        if origin is not None and not is_same_origin(request):
            bridge = request.url.path.startswith(_BATTLEGROUND_PREFIX)
            if not (bridge and is_configured_extension(origin)):
                error = "cross-site request refused"
                if bridge and origin.startswith(_EXTENSION_SCHEMES):
                    # The extension surfaces this text; tell the operator the fix.
                    error = (
                        f"extension {origin.partition('://')[2]} is not allowed: add "
                        "that id to AGENT_CHAT_EXTENSION_IDS in the repo's .env"
                    )
                return JSONResponse({"error": error}, status_code=403)
        has_body = (
            request.headers.get("content-length", "0") not in ("", "0")
            or "transfer-encoding" in request.headers
        )
        media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if has_body and media_type != "application/json":
            return JSONResponse(
                {"error": "request body must be application/json"}, status_code=415
            )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline response headers. ``setdefault`` so a route's own CSP wins
    (avatars set one). HSTS only when the request arrived over HTTPS."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        if request.headers.get("x-forwarded-proto", request.url.scheme) == "https":
            h.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response


class RegistryHostMiddleware(BaseHTTPMiddleware):
    """On the persona registry's own hostname, serve ONLY the registry.

    The registry is a separate site that happens to share this deployment
    (and so its database). ``/`` opens it; the explorer, its downloads and the
    avatars it shows are served; every other path — the console, the app,
    the API — redirects to the same path on the demo, so the registry host
    never turns into a second copy of the app.
    """

    async def dispatch(self, request: Request, call_next):
        from web.render.common import DEMO_URL, PUBLIC_REGISTRY_HOST

        if request.url.hostname != PUBLIC_REGISTRY_HOST:
            return await call_next(request)
        path = request.url.path
        if path == "/":
            return RedirectResponse("/personas", status_code=302)
        own = (path == "/personas" or path.startswith(("/personas/", "/avatars/"))
               or path == "/favicon.svg") and not path.startswith("/personas/manage")
        if own:
            return await call_next(request)
        q = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"{DEMO_URL}{path}{q}", status_code=302)


def _build_middleware() -> list[Middleware]:
    """Assemble the middleware stack from env-var feature flags.

    Both gates are off by default; local writes still need the write secret
    (``WriteSecretMiddleware``, innermost, absent on the read-only mirror):

    * AGENT_CHAT_BASIC_AUTH_PASSWORD → require HTTP basic auth on every route
      except the bearer/sync/static exceptions baked into BasicAuthMiddleware.
    * AGENT_CHAT_PUBLIC_READONLY → block browser mutations (403) while leaving
      GETs and the bearer-gated /api/ingest sync realm open.

    The hosted Fly deploy is expected to set at least the read-only flag.
    Basic auth is listed first so it forms the outermost layer (an
    unauthenticated request is challenged before the read-only check runs) —
    except for the always-on extension CORS layer, which sits outside even
    that so a browser preflight (no Authorization header, by spec) isn't
    challenged into failing. The Host allowlist is outermost of all, on every
    method: a request for a host this server doesn't serve gets 400 before
    anything else looks at it.
    """
    stack: list[Middleware] = [
        Middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts(), www_redirect=False),
        # A transcript page is ~270 KB of HTML. Fly's edge compresses the
        # mirror, but a local or tailnet instance sent it raw: 4.7 s on a slow
        # phone link (audit RT-41). Starlette's own gzip skips text/event-stream.
        Middleware(GZipMiddleware, minimum_size=1024),
        Middleware(SecurityHeadersMiddleware),
        Middleware(RegistryHostMiddleware),
        Middleware(ExtensionCorsMiddleware),
        Middleware(CrossSiteWriteGuard),
    ]
    password = basic_auth_password()
    if password:
        user = (os.environ.get("AGENT_CHAT_BASIC_AUTH_USER")
                or _env_file_value("AGENT_CHAT_BASIC_AUTH_USER") or "admin")
        stack.append(Middleware(BasicAuthMiddleware, username=user, password=password))
    if _env_truthy("AGENT_CHAT_PUBLIC_READONLY"):
        stack.append(Middleware(ReadOnlyMiddleware))
    else:
        stack.append(Middleware(WriteSecretMiddleware))
    return stack
