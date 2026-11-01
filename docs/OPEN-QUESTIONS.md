# Open questions

Decisions the scheduled roadmap runs can't make on their own. Fill in an
`- Answer:` line and the next run applies it, then moves the entry to
**Answered**. Entries are never deleted.

## Open

### `debate.ps1 -Format collaborate`: a task library, or a required `-Topic`? And cast personas or not?
- Asked: 2026-10-29 by agent-chat-roadmap
- Context: Roadmap row "Collaboration modes", sub-item (d), the last open part of the highest open item an unattended run can build. The podcast half shipped 2026-10-22 because `Podcast-Topics.md` gives each line a seat count. A collaboration's input is a task, not a proposition, and it usually runs without personas, so `debate.ps1`'s random topic + random cast pipeline doesn't fit as-is. Options: (1) `-Format collaborate` requires `-Topic` (the task) and `-Agents`, casts no personas unless `-Persona` is passed, and defaults the preset to `collaborate`'s default; (2) add a `docs/chat-topics/Collaborate-Tasks.md` library in the topic-file shape (`- Seats: N`, optional `- Preset:`) so it can pick at random like the other two formats. Recommendation: (1). It's smaller, a random task is rarely what an operator wants, and (2) can be added later without changing the flag.
- Answer:

## Answered

### Add Playwright as a test dependency so `/orchestrate`'s JS actually runs in a test?
- Asked: 2026-10-08 by agent-chat-roadmap
- Context: Roadmap row "The /orchestrate form has ~600 lines of browser JS and zero coverage", option (b). Option (a) shipped 2026-09-17 (`tests/test_orchestrate_form.py`, string invariants), so the script and the markup provably refer to the same page, but nothing executes the script: derived seat ids, the per-tool cap, format clamping and the custom-card flow are still untested. A headless Playwright smoke would cover that class, at the cost of the repo's "tests need nothing beyond the venv" rule (a pinned `playwright` plus a ~150 MB browser download in CI). Options: (1) add it as a CI-only dev dependency in a separate requirements file, so `requirements.txt` and the standalone runner stay untouched; (2) add it to `requirements.txt`; (3) don't, and keep re-checking the page by hand. Recommendation: (1), with the suite skipping cleanly when Playwright isn't installed.
- Answer: (1) Add Playwright as a CI-only dev dependency in a separate requirements file; `requirements.txt` and the standalone runner stay untouched, and the suite skips cleanly when Playwright isn't installed. (Mike, 2026-10-12)
- Applied: 2026-10-13 by agent-chat-upstream — recorded as the decision on the Roadmap row; building it is the roadmap routine's job (the upstream check does not build features).
- Built: 2026-10-29 by agent-chat-roadmap — `requirements-dev.txt` + `tests/test_orchestrate_browser.py`.

### One-command podcast launcher: a `-Format` flag on `debate.ps1`, or a separate `start-podcast` script and skill?
- Asked: 2026-10-08 by agent-chat-roadmap
- Context: Roadmap row "Podcast follow-ups", sub-item (1); the row says to decide this before building. `docs/chat-topics/Podcast-Topics.md` now exists in `debate.ps1`'s topic shape (`- Guests: N` for `- Debaters: N`), so either route can reuse the parser. A `-Format podcast` flag reuses the cast/seed/spawn pipeline and the existing `start-debate` skill, but `debate.ps1` gains a host-casting branch (from `Debate-Hosts`) and its name stops describing it. A separate launcher keeps each script single-purpose but duplicates the pipeline unless it's factored into `scripts/lib/`. Recommendation: `-Format` on `debate.ps1`, with `-TopicsGlob` defaulting by format.
- Answer: `-Format podcast` on `debate.ps1`, with `-TopicsGlob` defaulting by format; reuse the existing pipeline and the `start-debate` skill. (Mike, 2026-10-12)
- Applied: 2026-10-13 by agent-chat-upstream — recorded as the decision on the Roadmap row; building it is the roadmap routine's job (the upstream check does not build features).
