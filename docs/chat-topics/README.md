<h1 align="center">🎙️ Chat Topics</h1>

<p align="center">
  <em>Curated libraries to seed a run with, one per conversation type: 120 debate propositions,<br>
  50 podcast interview subjects and 40 collaboration tasks, plus the original GPT- and Grok-authored lists kept for reference.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Debate_topics-120-10b981?style=for-the-badge&labelColor=09090b" alt="120 debate topics">
  <img src="https://img.shields.io/badge/Podcast_topics-50-8B5CF6?style=for-the-badge&labelColor=09090b" alt="50 podcast topics">
  <img src="https://img.shields.io/badge/Collaboration_tasks-40-f59e0b?style=for-the-badge&labelColor=09090b" alt="40 collaboration tasks">
  <img src="https://img.shields.io/badge/Legacy_lists-2-71717a?style=for-the-badge&labelColor=09090b" alt="2 legacy lists">
</p>

---

## 📚 What's here

Each conversation type needs a differently shaped prompt, so each gets its own
library. Using a debate proposition for a podcast leaves the guest nothing to do
but agree or disagree. Using an interview question for a collaboration gives the
room nothing to finish.

| Document | Type | Shape | Picked by |
|:---|:---|:---|:---|
| [**Debate-Topics.md**](Debate-Topics.md) | ⚔️ Debate | **A yes/no proposition** (*Should…? Is…? Will…?*) with `- Debaters: N` (2–5). 120 topics across AI, gaming, science, pop culture, technology and everyday ethics. | `scripts\debate.ps1` (the default), at random from the unused ones |
| [**Podcast-Topics.md**](Podcast-Topics.md) | 🎙️ Podcast | **An open question** (*What…? How…? Why…?*) with `- Guests: N` (1–4; the host is extra). 50 subjects. | `scripts\debate.ps1 -Format podcast`, at random from the unused ones |
| [**Collaboration-Topics.md**](Collaboration-Topics.md) | 🧩 Collaboration | **A task with constraints** (*Design… Plan… Decide…*) with `- Seats: N` (2–5; the facilitator counts) and the `- Preset:` it was written for. 40 tasks across brainstorm, plan, decide, solve, design, validate, audit and open collaboration. | `scripts\debate.ps1 -Format collaborate`, at random from the unused ones (seats and preset come from the task) |
| [**legacy/**](legacy/README.md) | — | The two original topic lists (GPT- and Grok-authored, April 2026) that seeded the debate library. Kept for reference, not maintained. | — |

All three share one line format, `N. Title` followed by an indented `- Key: N`
line, so one parser reads them all. `tests/test_topic_libraries.py` and
`tests/test_podcast_topics.py` keep each file in shape.

## 🎬 Using a topic

**Debate.** Pick a line from [`Debate-Topics.md`](Debate-Topics.md), or leave
`-Topic` off and let the launcher choose:

```powershell
# Auto-debate: random cast, your topic
.\scripts\debate.ps1 -Topic "Should prompts be copyrightable?"

# Manual seed
.\scripts\start.ps1 --topic "..." --participants claude-code,codex --max-turns 6
```

**Podcast.** Take a line from [`Podcast-Topics.md`](Podcast-Topics.md), or let
`-Format podcast` pick one along with its guest count:

```powershell
.\scripts\debate.ps1 -Format podcast

.\scripts\start.ps1 --type podcast --host claude-code --participants claude-code,codex `
  --topic "What does a working day actually look like for someone at the top of their field?" --max-turns 10
```

**Collaboration.** Let `-Format collaborate` pick a task. It takes the seat
count and preset from the task, makes the first seat the facilitator, and casts
no personas unless you pass `-Personalities` or `-Group`. Or copy a task from
[`Collaboration-Topics.md`](Collaboration-Topics.md) and pass its preset
yourself, since the preset sets the shape of the deliverable:

```powershell
.\scripts\debate.ps1 -Format collaborate
.\scripts\debate.ps1 -Format collaborate -Topic "Plan our Q1 launch" -Preset plan -Agents 3

.\scripts\start.ps1 --type collaborate --preset decide --participants claude-code,codex,opencode `
  --topic "Decide which engine a two-person studio should use for a 2D game it plans to ship on PC, mobile and the web."
```

The [`Personas-And-Topics`](../../prompts/Manage-Debates/Personas-And-Topics/personas-and-topics.md)
prompt library has a paste-ready prompt for finding topics that haven't run yet.

> [!NOTE]
> The ✅ check-offs are written by `debate.ps1` when it picks a topic at
> random, and by hand otherwise. The authoritative record of what actually ran is
> the `conversations` table. Browse it at
> [`/conversations`](http://127.0.0.1:8765/conversations) or via
> `inspect_conversations.py list`.

## 🔗 Related

| Doc | Why |
|:---|:---|
| [`../guides/debate.md`](../guides/debate.md) | Running a debate: the seats a debate topic is written for. |
| [`../guides/podcast.md`](../guides/podcast.md) | Running a podcast: the host and guest seats a podcast topic is written for. |
| [`../guides/collaborate.md`](../guides/collaborate.md) | Running a collaboration: the facilitator, the presets and the `signal='result'` deliverable. |
| [`../guides/auto-debate.md`](../guides/auto-debate.md) | The `-Topic` flag and everything else `debate.ps1` accepts. |
| [`../../prompts/Auto-Debate/README.md`](../../prompts/Auto-Debate/README.md) | Paste-ready prompts that launch a debate on a chosen topic. |
| [`../app/personas.md`](../app/personas.md) | Who argues about them — the persona registry. |

---

<p align="center">
  <sub>← <a href="../README.md">Documentation home</a> · <a href="../../README.md">Roundtable</a> · <a href="legacy/README.md">Legacy lists →</a></sub>
</p>
