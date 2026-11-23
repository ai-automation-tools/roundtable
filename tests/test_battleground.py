r"""Tests for AgentBattleground — the arena bridge and the agent-side loop.

Covers the three things that would break the feature silently:

* **The bridge contract** (``/api/battleground/*``): capture → arena → draft →
  verdict, including the input scrubbing that stands between a hostile web
  page and the DB.
* **The human-in-the-loop gate**: a draft is born ``pending``, and only an
  explicit operator verdict moves it. Nothing in the server can post.
* **Re-capture merging**: known post ids refresh in place, new ones append —
  the property that lets an operator re-capture a live thread mid-argument
  without duplicating the backlog the agent has already read.

Runs under pytest *or* standalone with the project venv (no pytest needed):

    .\.venv\Scripts\python.exe tests\test_battleground.py

Uses an isolated temp ``chat.db`` — never touches the real ``db/chat.db``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

from starlette.testclient import TestClient
# The Host allowlist (web.security) refuses TestClient's default "testserver".
LOCAL = "http://127.0.0.1:8765"

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import web_ui  # noqa: E402
from web import db as web_db  # noqa: E402


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

TOKEN = "test-bridge-token"
EXT_ID = "abcdefghijklmnopabcdefghijklmnop"
EXT = f"chrome-extension://{EXT_ID}"

# Set for the length of an _Env, restored after: the bridge token is required
# (since 2026-11-12) and only the listed extension id is trusted.
_BRIDGE_ENV = {"AGENT_CHAT_BATTLEGROUND_TOKEN": TOKEN, "AGENT_CHAT_EXTENSION_IDS": EXT_ID}


class _Env:
    """Temp DB + TestClient carrying the bridge token, restoring the module's
    DB path and the bridge env vars on exit."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._saved_db = web_db.DB_PATH
        self._saved_env = os.environ.get("AGENT_CHAT_DB")
        self._saved_bridge = {k: os.environ.get(k) for k in _BRIDGE_ENV}
        self.db_path = str(Path(self._tmp.name) / "chat.db")

    def __enter__(self) -> _Env:
        os.environ.update(_BRIDGE_ENV)
        web_ui.set_db_path(self.db_path)
        web_ui.db_init()
        self.client = TestClient(
            web_ui.app, base_url=LOCAL, headers={"Authorization": f"Bearer {TOKEN}"}
        )
        return self

    def __exit__(self, *exc) -> None:
        for k, v in self._saved_bridge.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if self._saved_db:
            web_ui.set_db_path(self._saved_db)
        elif self._saved_env is None:
            os.environ.pop("AGENT_CHAT_DB", None)
        self._tmp.cleanup()


_THREAD = [
    {"id": "t1", "author": "op", "text": "Rust is strictly better than Go for services.", "depth": 0},
    {"id": "t2", "author": "gopher", "text": "Compile times say otherwise.", "depth": 1},
]


def _open_arena(client: TestClient, **overrides) -> dict:
    body = {
        "url": "https://reddit.com/r/programming/comments/abc/rust_vs_go",
        "site": "reddit",
        "title": "Rust vs Go",
        "thread": _THREAD,
        "stance": "Defend Go.",
        "agent_id": "claude-code",
    }
    body.update(overrides)
    resp = client.post("/api/battleground/arenas", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["arena"]


# ---------------------------------------------------------------------------
# 1. Arena lifecycle over the bridge
# ---------------------------------------------------------------------------

def test_create_arena_stores_thread_and_cast():
    with _Env() as env:
        arena = _open_arena(env.client)
        assert arena["status"] == "open"
        assert arena["site"] == "reddit"
        assert arena["agent_id"] == "claude-code"
        assert [p["id"] for p in arena["thread"]] == ["t1", "t2"]
        assert arena["stance"] == "Defend Go."


def test_create_arena_requires_url_and_posts():
    with _Env() as env:
        no_url = env.client.post(
            "/api/battleground/arenas", json={"thread": _THREAD}
        )
        assert no_url.status_code == 400
        assert "url is required" in no_url.json()["error"]

        no_posts = env.client.post(
            "/api/battleground/arenas",
            json={"url": "https://example.com", "thread": []},
        )
        assert no_posts.status_code == 400


def test_create_arena_rejects_unknown_agent_and_persona():
    with _Env() as env:
        bad_agent = env.client.post(
            "/api/battleground/arenas",
            json={"url": "https://example.com", "thread": _THREAD, "agent_id": "skynet"},
        )
        assert bad_agent.status_code == 400
        assert "supported" in bad_agent.json()

        bad_persona = env.client.post(
            "/api/battleground/arenas",
            json={
                "url": "https://example.com",
                "thread": _THREAD,
                "persona": "definitely-not-a-real-persona",
            },
        )
        assert bad_persona.status_code == 400


def test_capture_input_is_scrubbed():
    """A captured page is untrusted input: unknown keys are dropped, oversized
    text is clipped, empty nodes are skipped, and an unknown site falls back to
    'generic' rather than being stored verbatim."""
    with _Env() as env:
        arena = _open_arena(
            env.client,
            site="myspace",
            thread=[
                {"id": "a", "author": "x", "text": "y" * 20_000, "evil": "<script>"},
                {"id": "b", "author": "", "text": "   "},  # empty → dropped
                {"id": "c", "author": "z", "text": "real", "depth": 999},
            ],
        )
        assert arena["site"] == "generic"
        posts = arena["thread"]
        assert [p["id"] for p in posts] == ["a", "c"]
        assert len(posts[0]["text"]) == 8_000
        assert "evil" not in posts[0]
        assert posts[1]["author"] == "z"
        assert "depth" not in posts[1]  # 999 is out of range → not stored


def test_only_http_links_are_stored_or_rendered():
    """A captured page picks its own links. A ``javascript:`` permalink clicked
    on the console would run on the app's origin, where same-origin writes pass
    the cross-site guard — so non-http(s) schemes are dropped at the bridge,
    refused as an arena URL, and never rendered as an href."""
    with _Env() as env:
        bad = ["javascript:alert(1)", "JavaScript:alert(1)", " data:text/html,x", "vbscript:x"]
        arena = _open_arena(
            env.client,
            thread=[
                {"id": f"p{i}", "author": "a", "text": "t", "permalink": u}
                for i, u in enumerate(bad + ["https://example.com/c/1"])
            ],
        )
        links = [p.get("permalink") for p in arena["thread"]]
        assert links == [None] * len(bad) + ["https://example.com/c/1"]

        for u in ("javascript:alert(1)", "data:text/html,x", "file:///C:/x"):
            resp = env.client.post(
                "/api/battleground/arenas", json={"url": u, "thread": _THREAD}
            )
            assert resp.status_code == 400 and "http" in resp.json()["error"], u

        # A row written before the bridge checked schemes: render still refuses.
        conn = sqlite3.connect(env.db_path)
        conn.execute(
            "UPDATE battleground_arenas SET url = ?, thread = ? WHERE id = ?",
            (
                "javascript:alert(2)",
                json.dumps([{"id": "x", "author": "a", "text": "t", "permalink": "javascript:alert(3)"}]),
                arena["id"],
            ),
        )
        conn.commit()
        conn.close()
        page = env.client.get(f"/battleground/{arena['id']}").text
        assert 'href="javascript:' not in page.lower()
        assert "Open the thread" not in page


def test_extension_drops_non_http_permalinks_before_sending():
    src = (_SRC.parent / "extension" / "src" / "capture.js").read_text(encoding="utf-8")
    assert "permalink: httpOnly(extra.permalink)" in src
    assert r"/^https?:\/\//i" in src


def test_every_shipped_adapter_label_survives_a_capture():
    """The extension's adapters and the bridge's KNOWN_SITES have to agree.

    They live in different languages in different directories, so a new adapter
    whose label the bridge doesn't know is silently downgraded to 'generic' —
    the arena still works, but the site is wrong everywhere it's shown.
    """
    with _Env() as env:
        capture_js = (
            Path(__file__).resolve().parent.parent / "extension" / "src" / "capture.js"
        ).read_text(encoding="utf-8")

        for site in ("reddit", "x", "hackernews", "youtube", "linkedin",
                     "substack", "discourse", "disqus", "generic"):
            arena = _open_arena(env.client, site=site)
            assert arena["site"] == site, f"bridge downgraded {site!r}"
            assert f"'{site}'" in capture_js, f"no adapter in capture.js emits {site!r}"


def test_frame_namespaced_ids_merge_like_any_other():
    """Comments captured from a third-party iframe (Disqus and friends) carry
    a `<platform>:<id>` id so they can't collide with the host page's. They
    have to merge on re-capture exactly like a same-frame post."""
    with _Env() as env:
        arena = _open_arena(
            env.client,
            site="disqus",
            thread=[
                {"id": "page", "author": "news.example", "text": "Article lead."},
                {"id": "disqus:501", "author": "reader", "text": "First!"},
            ],
        )
        resp = env.client.post(
            f"/api/battleground/arenas/{arena['id']}/capture",
            json={
                "thread": [
                    {"id": "disqus:501", "author": "reader", "text": "First! (edited)"},
                    {"id": "disqus:502", "author": "other", "text": "A real reply."},
                ]
            },
        )
        assert resp.status_code == 200
        assert resp.json()["posts_added"] == 1
        thread = resp.json()["arena"]["thread"]
        assert [p["id"] for p in thread] == ["page", "disqus:501", "disqus:502"]
        assert thread[1]["text"].endswith("(edited)")


def test_recapture_merges_on_post_id():
    with _Env() as env:
        arena = _open_arena(env.client)
        resp = env.client.post(
            f"/api/battleground/arenas/{arena['id']}/capture",
            json={
                "thread": [
                    # t2 edited since first capture, t3 brand new
                    {"id": "t2", "author": "gopher", "text": "Compile times say otherwise. (edited)"},
                    {"id": "t3", "author": "rustacean", "text": "Skill issue."},
                ]
            },
        )
        assert resp.status_code == 200
        assert resp.json()["posts_added"] == 1
        thread = resp.json()["arena"]["thread"]
        assert [p["id"] for p in thread] == ["t1", "t2", "t3"]
        assert thread[1]["text"].endswith("(edited)")


def test_reply_target_round_trips_and_is_validated():
    """The operator can point the agent at one captured post.

    It has to name a post the arena actually holds — a stale id would reach the
    agent as a `reply_target` of null with no explanation.
    """
    with _Env() as env:
        arena = _open_arena(env.client, reply_to="t2")
        assert arena["reply_to"] == "t2"

        # Re-target.
        resp = env.client.post(
            f"/api/battleground/arenas/{arena['id']}", json={"reply_to": "t1"}
        )
        assert resp.status_code == 200
        assert resp.json()["arena"]["reply_to"] == "t1"

        # An id that isn't in the thread is refused, on create and on update.
        assert env.client.post(
            f"/api/battleground/arenas/{arena['id']}", json={"reply_to": "nope"}
        ).status_code == 400
        assert env.client.post(
            "/api/battleground/arenas",
            json={
                "url": "https://example.com/x",
                "thread": _THREAD,
                "reply_to": "nope",
            },
        ).status_code == 400

        # An empty string clears it; omitting it leaves it alone.
        env.client.post(
            f"/api/battleground/arenas/{arena['id']}", json={"stance": "unchanged"}
        )
        assert env.client.get(
            f"/api/battleground/arenas/{arena['id']}"
        ).json()["arena"]["reply_to"] == "t1"
        resp = env.client.post(
            f"/api/battleground/arenas/{arena['id']}", json={"reply_to": ""}
        )
        assert resp.json()["arena"]["reply_to"] is None


def test_healthz_answers_without_a_token():
    """/healthz exists to explain why the *other* calls are failing, so a bad
    or missing token must not be able to silence it."""
    with _Env() as env:
        os.environ["AGENT_CHAT_BATTLEGROUND_TOKEN"] = "s3cret"
        # Every other route is now challenged (the client sends TOKEN)...
        assert env.client.get("/api/battleground/roster").status_code == 401
        # ...but health still answers, and says a token is in play.
        resp = env.client.get("/api/battleground/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["db"] is True and body["schema"] is True
        assert body["token_required"] is True
        assert body["token_configured"] is True
        assert body["readonly"] is False

        # No token configured: health says so, everything else is refused.
        os.environ["AGENT_CHAT_BATTLEGROUND_TOKEN"] = ""
        body = env.client.get("/api/battleground/healthz").json()
        assert body["token_required"] is True and body["token_configured"] is False


def test_token_is_required_even_when_none_is_configured():
    """An unset token used to mean an open bridge, so any extension on the
    machine could drive it. Now it means a closed one, with the fix named."""
    with _Env() as env:
        os.environ["AGENT_CHAT_BATTLEGROUND_TOKEN"] = ""
        bare = TestClient(web_ui.app, base_url=LOCAL)
        for path in ("/api/battleground/roster", "/api/battleground/arenas"):
            r = bare.get(path)
            assert r.status_code == 401, (path, r.status_code)
            assert "AGENT_CHAT_BATTLEGROUND_TOKEN" in r.json()["error"]
        r = bare.post("/api/battleground/arenas", json={"url": "x", "thread": []})
        assert r.status_code == 401
        # Any bearer at all is refused too: there is nothing to match it against.
        assert env.client.get("/api/battleground/roster").status_code == 401


def test_configured_extension_reaches_the_bridge_with_its_token():
    with _Env() as env:
        r = env.client.post(
            "/api/battleground/arenas",
            headers={"Origin": EXT},
            json={"url": "https://example.com/t", "site": "generic", "thread": _THREAD},
        )
        assert r.status_code == 201, r.text
        assert r.headers["access-control-allow-origin"] == EXT
        # The right extension without the token is still refused.
        bare = TestClient(web_ui.app, base_url=LOCAL)
        assert bare.get("/api/battleground/roster", headers={"Origin": EXT}).status_code == 401


def test_other_extensions_are_just_another_site():
    """The extension exemption is one configured id, on the bridge only."""
    with _Env() as env:
        other = "chrome-extension://otheridotheridotheridotherid"
        # Another extension on the bridge — even holding the token — is refused,
        # and the refusal names the setting that would let it in.
        r = env.client.post(
            "/api/battleground/arenas", headers={"Origin": other},
            json={"url": "https://example.com/t", "thread": _THREAD},
        )
        assert r.status_code == 403
        assert "AGENT_CHAT_EXTENSION_IDS" in r.json()["error"]
        # Firefox's scheme is held to the same list.
        r = env.client.post(
            "/api/battleground/arenas", headers={"Origin": "moz-extension://1234-uuid"},
            json={"url": "https://example.com/t", "thread": _THREAD},
        )
        assert r.status_code == 403
        # Off the bridge, no extension is exempt — not even the configured one.
        for origin in (other, EXT):
            r = env.client.post(
                "/api/settings/delivery", headers={"Origin": origin}, json={}
            )
            assert r.status_code == 403, (origin, r.status_code)
            assert r.json()["error"] == "cross-site request refused"


def test_console_posts_same_origin_without_a_token():
    """The /battleground console's buttons post from this app's own page with
    no bearer token; that must keep working now the token is required. The
    page's write-secret cookie is what proves it (audit RT-05): ``Origin`` is
    a header any local process can send."""
    with _Env() as env:
        arena = _open_arena(env.client)
        forged = TestClient(web_ui.app, base_url=LOCAL).post(
            f"/api/battleground/arenas/{arena['id']}",
            headers={"Origin": LOCAL}, json={"status": "closed"},
        )
        assert forged.status_code == 401, forged.text
        bare = TestClient(web_ui.app, base_url=LOCAL)
        assert bare.get("/battleground").status_code == 200  # sets the cookie
        r = bare.post(
            f"/api/battleground/arenas/{arena['id']}",
            headers={"Origin": LOCAL}, json={"status": "closed"},
        )
        assert r.status_code == 200, r.text
        # Same request with no Origin (not a browser page): token needed.
        r = bare.post(f"/api/battleground/arenas/{arena['id']}", json={"status": "open"})
        assert r.status_code == 401


def test_roster_launch_commands_match_the_spawn_registry():
    """The panel's handoff card shows how to start the cast CLI. That string
    lives in Python, the real launcher table lives in PowerShell, and a drift
    between them sends the operator to a folder or binary that isn't there."""
    from web.api import battleground as bg

    registry = (
        Path(__file__).resolve().parent.parent / "scripts" / "lib" / "spawn-agents.ps1"
    ).read_text(encoding="utf-8")

    with _Env() as env:
        launch = env.client.get("/api/battleground/roster").json()["launch"]
        # Every supported CLI the map knows about is offered...
        assert set(launch) <= set(bg.CLI_LAUNCH)
        assert "claude-code" in launch and "codex" in launch
        from orchestrator import seats
        for cli, entry in launch.items():
            # The seat folder, outside the repo (audit RT-01) -- the same one
            # Resolve-AgentSeat launches from (test_seats pins that parity).
            assert entry["dir"] == str(seats.seat_dir(cli)), (cli, entry)
            assert f"Exe = '{entry['exe']}" in registry, (
                f"{cli}: launch exe {entry['exe']!r} is not in spawn-agents.ps1"
            )


def test_update_and_close_arena():
    with _Env() as env:
        arena = _open_arena(env.client)
        resp = env.client.post(
            f"/api/battleground/arenas/{arena['id']}",
            json={"stance": "Actually, defend Rust.", "status": "closed"},
        )
        assert resp.status_code == 200
        assert resp.json()["arena"]["status"] == "closed"
        assert resp.json()["arena"]["stance"] == "Actually, defend Rust."
        # Untouched fields survive a partial update.
        assert resp.json()["arena"]["agent_id"] == "claude-code"


def test_delete_arena_cascades_drafts():
    with _Env() as env:
        arena = _open_arena(env.client)
        web_db.bg_create_draft(
            arena_id=arena["id"], agent_id="claude-code", content="a reply"
        )
        resp = env.client.post(f"/api/battleground/arenas/{arena['id']}/delete")
        assert resp.status_code == 200
        assert resp.json()["cascaded_drafts"] == 1
        assert env.client.get(f"/api/battleground/arenas/{arena['id']}").status_code == 404


def test_missing_arena_is_404():
    with _Env() as env:
        assert env.client.get("/api/battleground/arenas/999").status_code == 404
        assert env.client.post(
            "/api/battleground/arenas/999/capture", json={"thread": _THREAD}
        ).status_code == 404


# ---------------------------------------------------------------------------
# 2. The human-in-the-loop gate
# ---------------------------------------------------------------------------

def test_draft_starts_pending():
    with _Env() as env:
        arena = _open_arena(env.client)
        draft = web_db.bg_create_draft(
            arena_id=arena["id"],
            agent_id="claude-code",
            content="Go's compile times are the point.",
            rationale="Leading with the concession.",
        )
        assert draft["status"] == "pending"
        assert draft["posted_text"] is None
        # And it surfaces to the panel on the arena read.
        data = env.client.get(f"/api/battleground/arenas/{arena['id']}").json()
        assert len(data["drafts"]) == 1
        assert data["drafts"][0]["rationale"] == "Leading with the concession."


def test_verdict_transitions():
    with _Env() as env:
        arena = _open_arena(env.client)
        draft = web_db.bg_create_draft(
            arena_id=arena["id"], agent_id="claude-code", content="draft one"
        )
        resp = env.client.post(
            f"/api/battleground/drafts/{draft['id']}/verdict",
            json={"verdict": "rejected", "note": "too smug"},
        )
        assert resp.status_code == 200
        assert resp.json()["draft"]["status"] == "rejected"
        assert resp.json()["draft"]["verdict_note"] == "too smug"

        resp = env.client.post(
            f"/api/battleground/drafts/{draft['id']}/verdict",
            json={"verdict": "posted", "posted_text": "draft one, edited by hand"},
        )
        assert resp.json()["draft"]["status"] == "posted"
        assert resp.json()["draft"]["posted_text"] == "draft one, edited by hand"


def test_bad_verdict_rejected():
    with _Env() as env:
        arena = _open_arena(env.client)
        draft = web_db.bg_create_draft(
            arena_id=arena["id"], agent_id="claude-code", content="x"
        )
        resp = env.client.post(
            f"/api/battleground/drafts/{draft['id']}/verdict",
            json={"verdict": "published"},
        )
        assert resp.status_code == 400
        assert env.client.post(
            "/api/battleground/drafts/999/verdict", json={"verdict": "approved"}
        ).status_code == 404


def test_no_drafting_into_a_closed_arena():
    with _Env() as env:
        arena = _open_arena(env.client)
        env.client.post(
            f"/api/battleground/arenas/{arena['id']}", json={"status": "closed"}
        )
        assert (
            web_db.bg_create_draft(
                arena_id=arena["id"], agent_id="claude-code", content="too late"
            )
            is None
        )


# ---------------------------------------------------------------------------
# 3. Listing + roster
# ---------------------------------------------------------------------------

def test_list_arenas_filters():
    with _Env() as env:
        mine = _open_arena(env.client, agent_id="claude-code")
        theirs = _open_arena(env.client, agent_id="codex")
        _open_arena(env.client, agent_id=None)  # unassigned: open to anyone

        all_open = env.client.get("/api/battleground/arenas?status=open").json()
        assert all_open["count"] == 3

        # An agent sees its own arenas plus the unassigned ones — never the
        # one another CLI is already fighting in.
        for_me = env.client.get("/api/battleground/arenas?agent=claude-code").json()
        ids = {a["id"] for a in for_me["arenas"]}
        assert mine["id"] in ids
        assert theirs["id"] not in ids
        assert for_me["count"] == 2

        assert env.client.get("/api/battleground/arenas?status=bogus").status_code == 400


def test_roster_excludes_ai_model_cards():
    with _Env() as env:
        from orchestrator import personas as reg

        reg.create_persona(name="Test Debater", body="Argue.", group="Testers")
        reg.create_persona(name="Claude Code", body="Reference card.", group="AI-Models")
        roster = env.client.get("/api/battleground/roster").json()
        slugs = {p["slug"] for p in roster["personas"]}
        assert "test-debater" in slugs
        assert "claude-code" not in slugs  # reserved group, never castable
        assert "claude-code" in roster["agents"]
        # The panel labels captures from this list, so it has to carry every
        # adapter the extension can pick.
        assert {"reddit", "youtube", "discourse", "disqus", "generic"} <= set(roster["sites"])


def test_persona_body_is_snapshotted_onto_the_arena():
    """Editing a persona later must not retroactively rewrite what the agent
    was told to be in an arena that's already running."""
    with _Env() as env:
        from orchestrator import personas as reg

        reg.create_persona(name="Stoic", body="Be terse.", group="Testers")
        arena = _open_arena(env.client, persona="stoic")
        assert arena["persona_name"] == "Stoic"
        assert arena["persona_body"] == "Be terse."

        reg.update_persona("stoic", body="Be verbose.")
        again = env.client.get(f"/api/battleground/arenas/{arena['id']}").json()
        assert again["arena"]["persona_body"] == "Be terse."


_REAL_CARD = """---
title: "Ada Example"
tags:
- maths
real_or_fictional: real
---

# Ada Example

You are Ada Example. Argue like a mathematician.
"""


def test_a_real_person_card_is_tagged_and_framed_once():
    """RT-22: `real_or_fictional: real` adds the tag and the parody line at
    parse time, and an exported card re-imports without a second line."""
    from orchestrator import personas as reg

    p = reg.parse_card_text(_REAL_CARD, "ada-example", "Testers")
    assert reg.REAL_PERSON_TAG in p.tags and "maths" in p.tags
    assert p.body.startswith(reg.PARODY_MARKER), p.body[:80]
    assert "It is not Ada Example" in p.body.splitlines()[0]
    assert not p.summary.startswith(">"), "the summary is about the person, not the frame"
    again = reg.parse_card_text(reg.card_text(p), "ada-example", "Testers")
    assert again.body.count(reg.PARODY_MARKER) == 1
    assert again.tags.count(reg.REAL_PERSON_TAG) == 1
    fiction = reg.parse_card_text(_REAL_CARD.replace("real\n", "fictional\n"), "x", "T")
    assert reg.REAL_PERSON_TAG not in fiction.tags
    assert not fiction.body.startswith(reg.PARODY_MARKER)


def test_submit_draft_refuses_a_real_person_without_disclosure():
    """RT-22: no draft in a real person's voice while the panel's AI
    disclosure is off or empty; turning it on lets the same arena draft."""
    import asyncio

    import agent_chat_mcp as mcp
    from orchestrator import personas as reg

    with _Env() as env:
        reg.import_persona_card(_REAL_CARD, group="Testers", filename="ada-example.md")
        reg.create_persona(name="Made Up", body="Be terse.", group="Testers")
        real = _open_arena(env.client, persona="ada-example", disclosure="")
        assert real["real_person"] is True
        made_up = _open_arena(env.client, persona="made-up", disclosure="",
                              agent_id="codex")
        assert made_up["real_person"] is False

        saved_agent, saved_db = mcp.AGENT_ID, mcp.DB_PATH
        mcp.AGENT_ID, mcp.DB_PATH = "claude-code", env.db_path
        try:
            def submit(aid: int) -> dict:
                return _mcp_json(asyncio.run(mcp.submit_draft(
                    mcp.SubmitDraftInput(arena_id=aid, content="A point."))))

            refused = submit(real["id"])
            assert refused["status"] == "error", refused
            assert "real person" in refused["message"]
            env.client.post(f"/api/battleground/arenas/{real['id']}",
                            json={"disclosure": "   "})
            assert submit(real["id"])["status"] == "error", "whitespace is not a disclosure"
            env.client.post(f"/api/battleground/arenas/{real['id']}",
                            json={"disclosure": "-- drafted by an AI"})
            assert submit(real["id"])["status"] == "submitted"

            mcp.AGENT_ID = "codex"
            assert submit(made_up["id"])["status"] == "submitted", \
                "a fictional persona drafts with disclosure off, as before"
        finally:
            mcp.AGENT_ID, mcp.DB_PATH = saved_agent, saved_db


def test_mark_real_persons_frames_old_rows_once():
    """Rows imported before cards carried the marker get the tag and the
    parody line (keeping the row's own body), once."""
    from orchestrator import personas as reg

    with _Env():
        reg.create_persona(name="Steve Jobs", body="You are Steve Jobs.",
                           group="Weekly-Additions/Tech Figures")
        first = reg.mark_real_persons()
        assert first["updated"] >= 1, first
        row = reg.get_persona("steve-jobs", "Weekly-Additions/Tech Figures")
        assert row is not None
        assert reg.REAL_PERSON_TAG in row.tags
        assert row.body.startswith(reg.PARODY_MARKER)
        assert row.body.endswith("You are Steve Jobs.")
        assert reg.mark_real_persons()["updated"] == 0


def test_a_pending_persona_stays_local_until_promoted():
    """RT-22: the content job's Pending-Review rows never sync and are never
    drawn at random; promote_pending() moves a merged card's row out."""
    import importlib.util

    from orchestrator import personas as reg

    spec = importlib.util.spec_from_file_location(
        "_db_sync_rt22", Path(__file__).resolve().parent.parent / "scripts" / "db_sync.py")
    db_sync = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = db_sync
    spec.loader.exec_module(db_sync)

    with _Env() as env:
        held = reg.import_persona_card(
            "---\ntitle: Steve Jobs\nreal_or_fictional: real\n---\n\nYou are Steve Jobs.\n",
            group=reg.PENDING_GROUP, filename="steve-jobs.md")
        assert held.group == reg.PENDING_GROUP
        assert db_sync.read_changed_personas(Path(env.db_path), "1970") == []
        assert db_sync.read_all_persona_keys(Path(env.db_path)) == []
        assert all(p.group != reg.PENDING_GROUP for p in reg.list_debater_personas())

        out = reg.promote_pending()
        assert out["promoted"] == 1, out
        moved = [r for r in db_sync.read_changed_personas(Path(env.db_path), "1970")
                 if r["slug"] == "steve-jobs"]
        assert len(moved) == 1 and moved[0]["group"] != reg.PENDING_GROUP
        assert moved[0]["body"].startswith(reg.PARODY_MARKER)
        assert reg.promote_pending()["promoted"] == 0


def test_custom_persona_instructions_cast_without_a_registry_row():
    """The panel's "✎ custom instructions…" option: a card typed for one arena.

    It has to land in the same snapshot columns a registry card does — that's
    what lets the agent treat both identically — while leaving `persona_slug`
    NULL, since there is no row to point at and a slug would imply one.
    """
    with _Env() as env:
        arena = _open_arena(
            env.client,
            persona_instructions="You are a bored ferry inspector. Be blunt.",
            persona_name="Ferry Inspector",
        )
        assert arena["persona_slug"] is None
        assert arena["persona_name"] == "Ferry Inspector"
        assert arena["persona_body"].startswith("You are a bored ferry inspector")

        # Nothing was added to the roster — casting an arena is not authoring
        # a persona, and a one-off card must not show up in the picker.
        roster = env.client.get("/api/battleground/roster").json()
        assert "ferry-inspector" not in {p["slug"] for p in roster["personas"]}


def test_custom_persona_defaults_its_name_and_refuses_a_double_cast():
    with _Env() as env:
        from orchestrator import personas as reg

        unnamed = _open_arena(env.client, persona_instructions="Argue in haiku.")
        assert unnamed["persona_name"] == "Custom persona"
        assert unnamed["persona_body"] == "Argue in haiku."

        # Two ways to cast in one request is ambiguous, and guessing which the
        # caller meant is how an arena ends up cast as the wrong character.
        reg.create_persona(name="Stoic", body="Be terse.", group="Testers")
        both = env.client.post(
            "/api/battleground/arenas",
            json={
                "url": "https://example.com",
                "thread": _THREAD,
                "persona": "stoic",
                "persona_instructions": "Be loud.",
            },
        )
        assert both.status_code == 400
        assert "not both" in both.json()["error"]


def test_recasting_onto_a_custom_card_drops_the_old_slug():
    """`bg_update_arena` skips None args so a partial patch can't blank the
    cast — which would leave a registry slug beside a custom name, an arena
    claiming to be one character and reading as another."""
    with _Env() as env:
        from orchestrator import personas as reg

        reg.create_persona(name="Stoic", body="Be terse.", group="Testers")
        arena = _open_arena(env.client, persona="stoic")
        assert arena["persona_slug"] == "stoic"

        patched = env.client.post(
            f"/api/battleground/arenas/{arena['id']}",
            json={"persona_instructions": "Be loud.", "persona_name": "Loudmouth"},
        )
        assert patched.status_code == 200
        row = patched.json()["arena"]
        assert row["persona_slug"] is None
        assert row["persona_name"] == "Loudmouth"
        assert row["persona_body"] == "Be loud."

        # And back the other way: a registry card restores its own slug.
        back = env.client.post(
            f"/api/battleground/arenas/{arena['id']}", json={"persona": "stoic"}
        )
        assert back.json()["arena"]["persona_slug"] == "stoic"


def test_mcp_get_arena_hands_over_a_custom_persona():
    """`get_arena` used to gate the persona on `persona_slug`, which is NULL
    for a typed-in card — the agent would have argued as nobody."""
    import asyncio

    import agent_chat_mcp as mcp

    with _Env() as env:
        arena = _open_arena(
            env.client,
            agent_id="codex",
            persona_instructions="You are a bored ferry inspector.",
            persona_name="Ferry Inspector",
        )
        saved_agent, saved_db = mcp.AGENT_ID, mcp.DB_PATH
        mcp.AGENT_ID, mcp.DB_PATH = "codex", env.db_path
        try:
            opened = _mcp_json(
                asyncio.run(mcp.get_arena(mcp.GetArenaInput(arena_id=arena["id"])))
            )
            assert opened["persona"] is not None
            assert opened["persona"]["slug"] is None
            assert opened["persona"]["name"] == "Ferry Inspector"
            assert "ferry inspector" in opened["persona"]["instructions"].lower()
            # A card the operator typed can't loosen the house rules.
            assert "do not impersonate a real person" in opened["rules"]
        finally:
            mcp.AGENT_ID, mcp.DB_PATH = saved_agent, saved_db


def test_no_persona_still_means_no_persona():
    """The gate moved from slug to body; an uncast arena must stay uncast."""
    import asyncio

    import agent_chat_mcp as mcp

    with _Env() as env:
        arena = _open_arena(env.client, agent_id="codex")
        assert arena["persona_body"] is None
        saved_agent, saved_db = mcp.AGENT_ID, mcp.DB_PATH
        mcp.AGENT_ID, mcp.DB_PATH = "codex", env.db_path
        try:
            opened = _mcp_json(
                asyncio.run(mcp.get_arena(mcp.GetArenaInput(arena_id=arena["id"])))
            )
            assert opened["persona"] is None
        finally:
            mcp.AGENT_ID, mcp.DB_PATH = saved_agent, saved_db


# ---------------------------------------------------------------------------
# 4. Extension CORS gate
# ---------------------------------------------------------------------------

def test_cors_only_for_extension_origins_on_battleground_paths():
    with _Env() as env:
        ext = EXT
        resp = env.client.get("/api/battleground/roster", headers={"Origin": ext})
        assert resp.headers.get("access-control-allow-origin") == ext

        # Nor is any extension but the configured one.
        stranger = env.client.get(
            "/api/battleground/roster",
            headers={"Origin": "chrome-extension://otheridotheridotheridotherid"},
        )
        assert "access-control-allow-origin" not in stranger.headers

        # A web page's origin is never echoed, so no site can read the bridge.
        page = env.client.get(
            "/api/battleground/roster", headers={"Origin": "https://evil.example"}
        )
        assert "access-control-allow-origin" not in page.headers

        # And the exemption doesn't leak to the rest of the app.
        other = env.client.get("/api/conversations", headers={"Origin": ext})
        assert "access-control-allow-origin" not in other.headers


def test_cors_preflight_answered():
    with _Env() as env:
        ext = EXT
        resp = env.client.options(
            "/api/battleground/arenas",
            headers={
                "Origin": ext,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.status_code == 204
        assert resp.headers["access-control-allow-origin"] == ext
        assert "POST" in resp.headers["access-control-allow-methods"]


# ---------------------------------------------------------------------------
# 5. Schema — one declaration (src/schema.py), local-only tables
# ---------------------------------------------------------------------------

def test_the_schema_creates_the_battleground_tables():
    """Every process boots the DB through schema.ensure_schema(), so whichever
    one opens a fresh file first, the arena tables exist."""
    import schema

    conn = sqlite3.connect(":memory:")
    schema.ensure_schema(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"battleground_arenas", "battleground_drafts"} <= names


def test_id_less_posts_keep_their_id_when_replies_land_above_them():
    """A positional fallback id made a re-capture overwrite whichever post now
    sat at that index. The fallback is a hash of author + text."""
    from web.api.battleground import _clean_posts

    old = {"author": "x", "text": "first take"}
    first = _clean_posts([old])
    later = _clean_posts([{"author": "y", "text": "a new reply"}, old])
    assert first[0]["id"] == later[1]["id"]
    assert later[0]["id"] != later[1]["id"]


def test_battleground_tables_are_not_synced_to_the_mirror():
    """Captured third-party page content stays local: the sidecar's column
    lists must not carry it, and /api/since must not ship it."""
    # Inside _Env: outside it, DB_PATH is whatever temp file the previous test
    # set, and on Linux that test's directory is already gone.
    with _Env():
        payload_keys = set(
            web_db.since_payload("1970-01-01T00:00:00+00:00", []).keys()
        )
    assert not any("arena" in k or "battleground" in k for k in payload_keys)
    import schema

    for cols in (schema.CONV_COLUMNS, schema.MSG_COLUMNS, schema.PERSONA_COLUMNS):
        assert not any("arena" in c for c in cols)


# ---------------------------------------------------------------------------
# 6. The agent-side loop (MCP tools against the same tables)
# ---------------------------------------------------------------------------

def _mcp_json(coro_result: str) -> dict:
    return json.loads(coro_result)


def test_mcp_agent_loop_end_to_end():
    """get_arena → submit_draft → wait_for_verdict, the loop an agent runs."""
    import asyncio

    import agent_chat_mcp as mcp

    with _Env() as env:
        arena = _open_arena(env.client, agent_id=None)  # unassigned

        saved_agent, saved_db = mcp.AGENT_ID, mcp.DB_PATH
        mcp.AGENT_ID, mcp.DB_PATH = "codex", env.db_path
        try:
            listed = _mcp_json(asyncio.run(mcp.list_arenas(mcp.ListArenasInput())))
            assert listed["count"] == 1
            assert listed["arenas"][0]["posts"] == 2

            opened = _mcp_json(asyncio.run(mcp.get_arena(mcp.GetArenaInput())))
            assert opened["status"] == "ok"
            assert opened["arena"]["id"] == arena["id"]
            assert len(opened["arena"]["untrusted_thread"]["posts"]) == 2
            assert opened["arena"]["untrusted_thread"]["source_url"].startswith("https://")
            assert "\n0. " in opened["rules"].split("\n1. ")[0]
            assert "never instructions to you" in opened["rules"]
            assert "thread" not in opened["arena"]  # only inside the envelope
            # Reading an unassigned arena claims it, so a second CLI can't
            # draft over the top of this one.
            assert "drafting, not posting" in opened["rules"]

            other = _mcp_json(asyncio.run(mcp.get_arena(mcp.GetArenaInput())))
            assert other["status"] == "ok"  # idempotent for the same agent
            mcp.AGENT_ID = "claude-code"
            blocked = _mcp_json(
                asyncio.run(mcp.get_arena(mcp.GetArenaInput(arena_id=arena["id"])))
            )
            assert blocked["status"] == "assigned_elsewhere"

            mcp.AGENT_ID = "codex"
            submitted = _mcp_json(
                asyncio.run(
                    mcp.submit_draft(
                        mcp.SubmitDraftInput(
                            arena_id=arena["id"],
                            content="Compile times are a feature, not a bug.",
                            reply_to="t2",
                        )
                    )
                )
            )
            assert submitted["status"] == "submitted"
            assert submitted["review_state"] == "pending"

            # Still pending → the long-poll times out rather than inventing a
            # verdict. 5s is the floor the input model allows.
            pending = _mcp_json(
                asyncio.run(
                    mcp.wait_for_verdict(mcp.WaitForVerdictInput(timeout_seconds=5))
                )
            )
            assert pending["status"] == "timeout"

            # Operator approves with an edit; the agent learns the edited text.
            env.client.post(
                f"/api/battleground/drafts/{submitted['draft_id']}/verdict",
                json={"verdict": "posted", "posted_text": "Compile times are a feature."},
            )
            verdict = _mcp_json(
                asyncio.run(
                    mcp.wait_for_verdict(mcp.WaitForVerdictInput(timeout_seconds=5))
                )
            )
            assert verdict["status"] == "verdict"
            assert verdict["verdict"] == "posted"
            assert verdict["operator_edited"] is True
            assert verdict["posted_text"] == "Compile times are a feature."
            assert len(verdict["untrusted_thread"]["posts"]) == 2
        finally:
            mcp.AGENT_ID, mcp.DB_PATH = saved_agent, saved_db


def test_mcp_get_arena_hands_over_the_operators_reply_target():
    """A post picked in the panel has to arrive as something the agent can act
    on — the id echoed on the arena, the post itself pulled out of the thread,
    and a `next` line that names it."""
    import asyncio

    import agent_chat_mcp as mcp

    with _Env() as env:
        arena = _open_arena(env.client, agent_id="codex", reply_to="t2")
        saved_agent, saved_db = mcp.AGENT_ID, mcp.DB_PATH
        mcp.AGENT_ID, mcp.DB_PATH = "codex", env.db_path
        try:
            opened = _mcp_json(
                asyncio.run(mcp.get_arena(mcp.GetArenaInput(arena_id=arena["id"])))
            )
            assert opened["arena"]["reply_to"] == "t2"
            assert opened["reply_target"]["author"] == "gopher"
            assert "reply_to='t2'" in opened["next"]

            # Cleared in the panel → the agent picks its own target again.
            env.client.post(
                f"/api/battleground/arenas/{arena['id']}", json={"reply_to": ""}
            )
            reopened = _mcp_json(
                asyncio.run(mcp.get_arena(mcp.GetArenaInput(arena_id=arena["id"])))
            )
            assert reopened["arena"]["reply_to"] is None
            assert reopened["reply_target"] is None
        finally:
            mcp.AGENT_ID, mcp.DB_PATH = saved_agent, saved_db


def test_mcp_reports_no_arena_cleanly():
    import asyncio

    import agent_chat_mcp as mcp

    with _Env() as env:
        saved_agent, saved_db = mcp.AGENT_ID, mcp.DB_PATH
        mcp.AGENT_ID, mcp.DB_PATH = "codex", env.db_path
        try:
            state = _mcp_json(asyncio.run(mcp.get_arena(mcp.GetArenaInput())))
            assert state["status"] == "no_arena"
            verdict = _mcp_json(
                asyncio.run(mcp.wait_for_verdict(mcp.WaitForVerdictInput()))
            )
            assert verdict["status"] == "not_found"
        finally:
            mcp.AGENT_ID, mcp.DB_PATH = saved_agent, saved_db


# ---------------------------------------------------------------------------
# 7. The /battleground arena console (the web-UI page, not the bridge)
# ---------------------------------------------------------------------------

def test_console_lists_arenas_and_counts_pending_drafts():
    with _Env() as env:
        arena = _open_arena(env.client)
        web_db.bg_create_draft(
            arena_id=arena["id"], agent_id="claude-code", content="Go compiles faster."
        )
        page = env.client.get("/battleground")
        assert page.status_code == 200
        assert "Rust vs Go" in page.text
        assert f'href="/battleground/{arena["id"]}"' in page.text
        # The count is what makes the list worth opening: it's the only place
        # that says a draft is waiting on you without opening every arena.
        assert "1 pending" in page.text
        assert "1 draft awaiting a verdict" in page.text


def test_console_empty_state_points_at_the_extension():
    # An empty console is the normal first state — arenas only exist once the
    # extension captures one, so the page has to say where they come from.
    with _Env() as env:
        page = env.client.get("/battleground").text
        assert "No arenas captured yet" in page
        assert 'href="/extension"' in page


def test_console_status_filter_narrows_the_list():
    with _Env() as env:
        open_arena = _open_arena(env.client, title="Still arguing")
        closed = _open_arena(env.client, title="Done arguing")
        env.client.post(
            f"/api/battleground/arenas/{closed['id']}", json={"status": "closed"}
        )

        only_open = env.client.get("/battleground?status=open").text
        assert "Still arguing" in only_open and "Done arguing" not in only_open

        only_closed = env.client.get("/battleground?status=closed").text
        assert "Done arguing" in only_closed and "Still arguing" not in only_closed

        # A typo'd filter shows everything rather than 400ing — this is a URL
        # an operator types, not an API call.
        both = env.client.get("/battleground?status=banana").text
        assert "Still arguing" in both and "Done arguing" in both

        assert open_arena["id"] != closed["id"]


def test_console_detail_renders_thread_drafts_and_escapes_page_content():
    """The whole point of the page: the captured thread + every draft with its
    verdict, without the original tab open.

    Also the security case. Every string on this page came off a third-party
    web page — the title, the authors, the post text — so a thread containing
    markup must reach the browser as text.
    """
    with _Env() as env:
        arena = _open_arena(
            env.client,
            title="<script>alert(1)</script>",
            thread=[
                {"id": "t1", "author": "op", "text": "a > b & <img src=x onerror=1>"},
                {"id": "t2", "author": "gopher", "text": "Compile times say otherwise."},
            ],
            reply_to="t2",
        )
        web_db.bg_create_draft(
            arena_id=arena["id"],
            agent_id="claude-code",
            content="Compile times are a real cost.",
            reply_to="t2",
            rationale="Private note to the operator.",
        )
        page = env.client.get(f"/battleground/{arena['id']}").text

        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
        assert "<img src=x onerror=1>" not in page
        assert "a &gt; b &amp;" in page

        assert "Compile times are a real cost." in page
        assert "Private note to the operator." in page
        # The operator's chosen reply target is marked in the thread.
        assert "reply target" in page


def test_console_verdict_buttons_track_draft_state():
    """Approve is offered on a pending draft; once approved the next honest
    action is "I posted this", because inserting the text needs the tab."""
    with _Env() as env:
        arena = _open_arena(env.client)
        draft = web_db.bg_create_draft(
            arena_id=arena["id"], agent_id="claude-code", content="Go compiles faster."
        )
        pending = env.client.get(f"/battleground/{arena['id']}").text
        assert "Approve" in pending
        assert "I posted this" not in pending

        env.client.post(
            f"/api/battleground/drafts/{draft['id']}/verdict",
            json={"verdict": "approved"},
        )
        approved = env.client.get(f"/battleground/{arena['id']}").text
        assert "I posted this" in approved
        assert 'class="bgc-pill approved"' in approved

        # A closed arena is history: the agent can't draft into it, so the page
        # stops offering verdicts on what's already there.
        env.client.post(
            f"/api/battleground/arenas/{arena['id']}", json={"status": "closed"}
        )
        shut = env.client.get(f"/battleground/{arena['id']}").text
        assert "Reopen arena" in shut
        assert "I posted this" not in shut


def test_console_never_offers_to_post_to_the_page():
    """The invariant, pinned on the surface most likely to erode it.

    The console has no tab and no composer, so nothing here may imply it can
    reach a website. It says the opposite in words, and the only endpoints its
    buttons call are the verdict/arena routes that already existed.
    """
    with _Env() as env:
        arena = _open_arena(env.client)
        web_db.bg_create_draft(
            arena_id=arena["id"], agent_id="claude-code", content="Go compiles faster."
        )
        detail = env.client.get(f"/battleground/{arena['id']}").text
        for page in (env.client.get("/battleground").text, detail):
            assert "Drafts, never posts." in page
            assert "it does not touch any web page" in page
        called = {
            line.split("post('")[1].split("'")[0]
            for line in detail.splitlines()
            if "post('/api/" in line
        }
        assert called <= {
            "/api/battleground/drafts/",
            "/api/battleground/arenas/",
        }, called


def test_console_detail_404s_for_an_unknown_arena():
    with _Env() as env:
        resp = env.client.get("/battleground/4242")
        assert resp.status_code == 404
        assert "No arena #4242" in resp.text


def test_console_cast_label_survives_a_custom_persona():
    """A card typed into the panel has a name and a body but no registry row.
    Reading ``persona_slug`` here would show a cast arena as uncast — the same
    NULL-slug trap ``get_arena`` has to dodge."""
    with _Env() as env:
        arena = _open_arena(
            env.client,
            persona_instructions="Argue like a compiler engineer.",
            persona_name="The Compiler Engineer",
        )
        assert arena["persona_slug"] is None
        for page in (
            env.client.get("/battleground").text,
            env.client.get(f"/battleground/{arena['id']}").text,
        ):
            assert "The Compiler Engineer" in page
            assert "not cast" not in page


def test_console_is_an_explainer_on_the_hosted_mirror():
    """The mirror has no arenas and never will — both tables are excluded from
    the sync — so an empty list there would say the opposite of the truth."""
    import importlib

    saved = os.environ.get("AGENT_CHAT_PUBLIC_READONLY")
    os.environ["AGENT_CHAT_PUBLIC_READONLY"] = "1"
    try:
        importlib.reload(web_ui)
        with _Env() as env:
            page = env.client.get("/battleground")
            assert page.status_code == 200
            assert "Arenas stay on the machine that captured them" in page.text
            assert "No arenas captured yet" not in page.text
            # The detail route takes the same door, so a shared link can't leak
            # a hosted arena list either.
            assert "Arenas stay on the machine" in env.client.get(
                "/battleground/1"
            ).text
    finally:
        os.environ.pop("AGENT_CHAT_PUBLIC_READONLY", None)
        if saved is not None:
            os.environ["AGENT_CHAT_PUBLIC_READONLY"] = saved
        importlib.reload(web_ui)


def test_console_is_reachable_from_the_nav_rail():
    # An unlinked page is an unreachable one; the rail is the app's navigation.
    with _Env() as env:
        page = env.client.get("/extension").text
        rail = page[page.index('<nav class="siderail"'):page.index("</nav>")]
        assert 'href="/battleground"' in rail


def test_panel_markup_keeps_its_accessibility_fixes():
    """The side panel has no browser test (audit RT-43 was checked with
    Lighthouse once), so pin the markup it relies on: status lines are live
    regions, every input has a name, the bridge state is words, not a colour."""
    import re as _re
    panel = Path(__file__).resolve().parent.parent / "extension" / "src" / "panel"
    html = (panel / "panel.html").read_text(encoding="utf-8")
    for el in ("settings-msg", "capture-summary", "arena-msg", "handoff-msg", "auto-status"):
        assert _re.search(rf'id="{el}" role="status"', html), el
    assert 'for="disclosure-text"' in html
    assert _re.search(r'id="auto-seconds"[^>]*aria-label=', html)
    auto = html[html.index('id="auto-recapture"'):]
    assert auto.index("</label>") < auto.index('id="auto-seconds"'), "number input inside the checkbox label"
    assert 'aria-controls="settings"' in html and 'aria-expanded="false"' in html
    assert html.count("<main>") == 1
    js = (panel / "panel.js").read_text(encoding="utf-8")
    assert "setAttribute('aria-expanded'" in js
    bridge = (panel / "lib" / "bridge.js").read_text(encoding="utf-8")
    assert "aria-label" in bridge and "Offline" in bridge
    css = (panel / "panel.css").read_text(encoding="utf-8")
    assert "background: var(--accent-fill)" in css and ".hint { color: var(--muted)" in css


def test_panel_reaches_the_extension_apis_through_the_ext_alias():
    """Firefox exposes ``chrome.*`` only as a callback-based porting aid — the
    promise-returning namespace on Gecko is ``browser.*``. Every panel call is
    awaited, so a bare ``chrome.`` yields ``undefined`` there and the panel dies
    on the first one (``chrome.tabs.query``, during init). The alias in
    ``lib/state.js`` is what keeps the same source working in both browsers, so
    a new bare call site is a Firefox regression that no Python test would see.

    ``background.js`` is exempt: it loads as a classic script on Gecko and must
    stay import-free, so it declares its own copy of the alias.
    """
    import re

    panel = Path(__file__).resolve().parent.parent / "extension" / "src" / "panel"
    api = re.compile(r"\bchrome\.(tabs|storage|permissions|scripting|runtime)\b")
    # `chrome.foo` inside a comment or a string is prose about the Chrome API.
    code_only = re.compile(r"^\s*(\*|//)")

    checked = 0
    for path in sorted(panel.rglob("*.js")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if code_only.match(line):
                continue
            assert not api.search(line), (
                f"{path.name}:{lineno} calls the extension API as `chrome.` — "
                f"import `ext` from state.js instead, or Firefox breaks: {line.strip()}"
            )
        checked += 1

    assert checked >= 9, f"expected the panel package, found {checked} files"
    state = (panel / "lib" / "state.js").read_text(encoding="utf-8")
    assert "export const ext = typeof browser !== 'undefined' ? browser : chrome;" in state


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
