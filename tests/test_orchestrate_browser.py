r"""Tests for the ``/orchestrate`` form's browser JS — run in a real headless Chromium.

``tests/test_orchestrate_form.py`` pins that the inline script and the markup
refer to the same page; it never *runs* the script. This file does. It loads the
page the route renders into Playwright's Chromium, drives the chair engine the
way an operator would, and asserts on what the browser shows and posts:

1. two chairs on one tool derive ``tool`` and ``tool-2``;
2. the host seat picker is visible for a podcast (the 2026-09 bug hid it), and a
   host on a guest's tool takes the first seat number;
3. a tool asked for more than ``MAX_SEATS_PER_CLI`` seats is refused before any
   POST leaves the page;
4. switching format clamps the chair list to the new format's bounds;
5. a launch posts the derived seat ids and a custom persona card read off disk.

No server runs. Every request goes through ``page.route``: the page itself is
``_render_orchestrate()``'s output, ``POST /api/orchestrate`` is captured and
answered with a refusal (so nothing navigates), and anything else is aborted.

**Playwright is optional** (Mike's call, 2026-10-12): it lives in
``requirements-dev.txt``, never in ``requirements.txt``, and this suite SKIPS
cleanly when the package or its Chromium is missing. CI installs both.

    .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
    .\.venv\Scripts\python.exe -m playwright install chromium
    .\.venv\Scripts\python.exe tests\test_orchestrate_browser.py
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from orchestrator.conv_types import CONV_TYPES  # noqa: E402
from orchestrator.seats import MAX_SEATS_PER_CLI  # noqa: E402
from web.render.orchestrate import _render_orchestrate  # noqa: E402

_ORIGIN = "http://orchestrate.test"


def _skip_reason() -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "playwright not installed (pip install -r requirements-dev.txt)"
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            return "playwright's Chromium not installed (python -m playwright install chromium)"
    return None


_SKIP = _skip_reason()

if __name__ != "__main__" and _SKIP:  # under pytest, skip like the runner does
    import pytest

    pytest.skip(_SKIP, allow_module_level=True)


class _Form:
    """One loaded /orchestrate page plus whatever it POSTed."""

    def __init__(self, page: Any) -> None:
        self.page = page
        self.posts: list[dict] = []

    def rows(self) -> Any:
        return self.page.locator("#orch-seats .orch-seat")

    def tools(self) -> list[str]:
        return self.page.locator("select[name=mod_cli] option").evaluate_all(
            "os => os.map(o => o.value)")

    def set_tool(self, i: int, tool: str) -> None:
        self.rows().nth(i).locator(".seat-tool").select_option(tool)

    def seat_id_text(self, i: int) -> str:
        return self.rows().nth(i).locator(".seat-id").inner_text().strip()

    def add_chair(self) -> None:
        self.page.click("#orch-add-seat")

    def pick_type(self, key: str) -> None:
        self.page.check(f"input[name=conv_type][value={key}]")

    def submit(self, topic: str = "Browser smoke") -> None:
        self.page.fill("textarea[name=topic]", topic)
        self.page.click("button[type=submit]")


@contextmanager
def _form(conv_type: str | None = None) -> Iterator[_Form]:
    from playwright.sync_api import sync_playwright

    page_html = _render_orchestrate([], conv_type=conv_type)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_default_timeout(5000)
            form = _Form(page)
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))

            def handle(route: Any) -> None:
                req = route.request
                if req.url.startswith(_ORIGIN + "/orchestrate"):
                    route.fulfill(status=200, content_type="text/html", body=page_html)
                elif req.url == _ORIGIN + "/api/orchestrate" and req.method == "POST":
                    form.posts.append(json.loads(req.post_data or "{}"))
                    route.fulfill(status=200, content_type="application/json",
                                  body=json.dumps({"ok": False, "kind": "captured",
                                                   "error": "captured by the test"}))
                else:
                    route.abort()

            page.route("**/*", handle)
            page.goto(_ORIGIN + "/orchestrate", wait_until="domcontentloaded")
            yield form
            assert not errors, f"the page threw: {errors}"
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# The chair engine
# ---------------------------------------------------------------------------

def test_two_chairs_on_one_tool_derive_a_second_seat_id() -> None:
    with _form() as f:
        tool = f.tools()[0]
        assert f.rows().count() == 2, "a debate opens with two chairs"
        f.set_tool(0, tool)
        f.set_tool(1, tool)
        assert f.seat_id_text(0) == "", "the first chair on a tool is the plain tool id"
        assert f.seat_id_text(1) == f"runs as {tool}-2"


def test_the_host_seat_picker_is_visible_for_a_podcast() -> None:
    """The shipped bug: updatePersonaRows() display:none'd the host's own row."""
    with _form("podcast") as f:
        host = f.page.locator("select[name=mod_cli]")
        assert f.page.locator("#orch-mod-fields").is_visible(), "host fields hidden"
        assert host.is_visible() and host.is_enabled(), "host tool picker hidden or disabled"
        # The host is seated first, so a guest sharing its tool is the -2.
        tool = f.tools()[0]
        host.select_option(tool)
        f.set_tool(0, tool)
        assert f.seat_id_text(0) == f"runs as {tool}-2"


def test_one_tool_cannot_hold_more_than_the_cap() -> None:
    debate = CONV_TYPES["debate"]
    assert debate.max_members + 1 > MAX_SEATS_PER_CLI, \
        "a moderated debate can no longer overflow one tool — pick another case"
    with _form("debate") as f:
        tool = f.tools()[0]
        f.page.check("input[name=mod_enable]")
        f.page.select_option("select[name=mod_cli]", tool)
        while f.rows().count() < debate.max_members:
            f.add_chair()
        for i in range(f.rows().count()):
            f.set_tool(i, tool)
        f.submit()
        err = f.page.locator("#orch-error")
        err.wait_for(state="visible")
        assert "Too many seats on one tool" in err.inner_text()
        assert f.posts == [], "an over-cap room reached POST /api/orchestrate"


def test_switching_format_clamps_the_chair_list() -> None:
    debate, podcast = CONV_TYPES["debate"], CONV_TYPES["podcast"]
    assert podcast.max_members < debate.max_members, "nothing left to clamp"
    with _form("debate") as f:
        while f.rows().count() < debate.max_members:
            f.add_chair()
        add = f.page.locator("#orch-add-seat")
        assert add.is_disabled() and add.inner_text() == "Maximum seats"
        f.pick_type("podcast")
        assert f.rows().count() == podcast.max_members
        assert add.is_disabled(), "podcast is full — the add button must stay off"
        # And back down to the floor: delete is refused at the minimum.
        while f.rows().count() > podcast.min_members:
            f.rows().last.locator(".seat-del").click()
        assert f.rows().last.locator(".seat-del").is_disabled()
        f.pick_type("debate")
        assert f.rows().count() == debate.min_members, "debate did not grow to its floor"


# ---------------------------------------------------------------------------
# What a launch posts
# ---------------------------------------------------------------------------

def test_submit_posts_derived_seat_ids_and_a_custom_card() -> None:
    card = "# Ada\n\nSpeaks only in proofs."
    with _form("debate") as f:
        tool = f.tools()[0]
        f.set_tool(0, tool)
        f.set_tool(1, tool)
        f.rows().nth(1).locator(".orch-persona-file").set_input_files(
            files=[{"name": "ada.md", "mimeType": "text/markdown",
                    "buffer": card.encode("utf-8")}])
        persona = f.rows().nth(1).locator(".seat-persona")
        f.page.wait_for_function(
            "el => el.value === '__custom__'", arg=persona.element_handle())
        f.submit()
        f.page.locator("#orch-error").wait_for(state="visible")
        assert len(f.posts) == 1, f"expected one POST, got {len(f.posts)}"
        sent = f.posts[0]
        second = f"{tool}-2"
        assert sent["conv_type"] == "debate"
        assert sent["participants"] == [tool, second]
        assert sent["personas"][second] == "__custom__"
        assert sent["persona_custom"] == {second: {"filename": "ada.md", "text": card}}
        assert sent["moderator"] is None


# ---------------------------------------------------------------------------
# Standalone runner (no pytest required)
# ---------------------------------------------------------------------------

def _main() -> int:
    if _SKIP:
        print(f"SKIP  test_orchestrate_browser: {_SKIP}")
        return 0
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
