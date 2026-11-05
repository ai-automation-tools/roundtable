# 40 Collaboration Topics: Tasks, Not Arguments (2026 Edition)

A debate needs a claim to fight over and a podcast needs a question to open up.
A collaboration needs neither. It needs a **task**: something the room can
finish, with a facilitator who posts the finished artifact on its closing turn
(`signal='result'`). So every line here is an instruction, phrased as
"Design…", "Plan…", "Decide…", never as a yes/no question. A good task names
its constraints, so the room can't skip the hard part.

Each task carries two lines:

- **`- Seats: N`**: total seats, **facilitator included**. The facilitator is
  one of the collaborators, not an observer, so `- Seats: 3` means three agents
  in all. A collaboration seats 2–5.
- **`- Preset: <name>`**: the sub-type it was written for. That decides the
  shape of the deliverable (a plan, a decision, a findings register…). The
  presets are defined in `src/presets.py`:

| Preset | The room produces |
|:---|:---|
| `brainstorm` | A wide spread of ideas, then a short list (runs in continuous mode) |
| `plan` | A numbered plan: owners, dependencies, definition of done, risks |
| `decide` | The decision, every losing option and why it lost |
| `solve` | Root cause, the evidence for it, then the fix |
| `design` | Components, interfaces, data flow, failure modes, rejected alternatives |
| `validate` | A go / no-go / not-yet call on an idea, with its assumptions |
| `audit` | A ranked findings register (blind-first: nobody sees the others until they've posted) |
| `collaborate` | Open collaboration: whatever the task asks for, written out in full |

`code-review` is left out on purpose: its input is a real diff, not a line from
a list.

Format: a numbered `N. Task` line, then `- Seats: N` and `- Preset: <name>`.
This is the same shape as [`Debate-Topics.md`](Debate-Topics.md) and
[`Podcast-Topics.md`](Podcast-Topics.md), with one extra line.
`scripts\debate.ps1 -Format collaborate` picks an unused task from this file at
random when you don't pass `-Topic`, seats the task's `Seats` count, seeds with
its `Preset` (unless `-Preset` overrides it) and appends
` ✅ <!--used DATE conv#ID-->` to the line once seeded. Delete the marker to put
a task back in the pool. For a hand-seeded run, copy a task into `--topic` (with
`--type collaborate --preset <name>`) or into the `/orchestrate` form.

## Brainstorm

1. Brainstorm 30 game ideas a solo developer could build and ship in one weekend with AI tools, then pick the three most likely to find an audience.
   - Seats: 3
   - Preset: brainstorm

2. Brainstorm ways a small public library could get teenagers through the door, then shortlist five that cost under $500.
   - Seats: 3
   - Preset: brainstorm

3. Brainstorm names and one-line pitches for a tool that lets AI agents hold structured conversations with each other.
   - Seats: 2
   - Preset: brainstorm

4. Brainstorm a season of ten podcast episodes about how ordinary people use AI at work, with a hook for each.
   - Seats: 3
   - Preset: brainstorm

5. Brainstorm ways to make a city neighborhood measurably cooler during summer heatwaves without new construction.
   - Seats: 4
   - Preset: brainstorm

## Plan

6. Plan the launch of an indie game built mostly with AI tools: the four weeks before release and the two weeks after.
   - Seats: 3
   - Preset: plan

7. Plan a one-day workshop that teaches non-programmers to build and publish a small web app with an AI assistant.
   - Seats: 3
   - Preset: plan

8. Plan a migration of a ten-year-old monolith to a modular architecture without stopping feature work.
   - Seats: 3
   - Preset: plan

9. Plan a 90-day learning path for a career changer who wants a first job in software.
   - Seats: 2
   - Preset: plan

10. Plan a community game jam for 200 people where every entry must be built with AI tools and judged fairly.
    - Seats: 3
    - Preset: plan

## Decide

11. Decide which engine a two-person studio should use for a 2D game it plans to ship on PC, mobile and the web.
    - Seats: 3
    - Preset: decide

12. Decide between building, buying or open-sourcing an internal analytics dashboard for a 50-person company.
    - Seats: 3
    - Preset: decide

13. Decide how a free-to-play game should make money without pay-to-win mechanics or loot boxes.
    - Seats: 3
    - Preset: decide

14. Decide whether a small SaaS should move from a monthly subscription to usage-based pricing.
    - Seats: 2
    - Preset: decide

15. Decide which three features a note-taking app should cut to make room for an AI assistant.
    - Seats: 3
    - Preset: decide

## Solve

16. Solve why a multiplayer game's matchmaking queue times doubled after a patch that didn't touch matchmaking.
    - Seats: 3
    - Preset: solve

17. Solve why an online store's checkout conversion dropped 20% in a week with no deploys.
    - Seats: 3
    - Preset: solve

18. Solve why a team's two-week sprints consistently finish only half their planned work.
    - Seats: 2
    - Preset: solve

19. Solve why players quit a mobile puzzle game between level 8 and level 12.
    - Seats: 3
    - Preset: solve

20. Solve why a nightly data pipeline succeeds but produces reports that are wrong about once a week.
    - Seats: 2
    - Preset: solve

## Design

21. Design a system that lets anyone describe a game in plain language and play a working prototype within ten minutes.
    - Seats: 3
    - Preset: design

22. Design a moderation pipeline for a platform that receives 10,000 AI-generated games a day.
    - Seats: 4
    - Preset: design

23. Design a save-and-sync system for a game that runs offline on phones and syncs to the cloud.
    - Seats: 3
    - Preset: design

24. Design a notification system that tells a user something important without becoming noise.
    - Seats: 2
    - Preset: design

25. Design a fair, cheat-resistant ranked ladder for a 1v1 competitive game with a small player base.
    - Seats: 3
    - Preset: design

## Validate

26. Validate a marketplace where hobbyists sell games they generated with AI, with a revenue share for the tool makers.
    - Seats: 3
    - Preset: validate

27. Validate a subscription service that sends parents a new AI-generated educational game for their child each week.
    - Seats: 3
    - Preset: validate

28. Validate a tool that turns a team's meeting transcripts into a weekly decision log.
    - Seats: 2
    - Preset: validate

29. Validate a co-working space designed for people who work alongside AI agents all day.
    - Seats: 3
    - Preset: validate

30. Validate a service that ports abandoned indie games to modern platforms using AI tools.
    - Seats: 3
    - Preset: validate

## Audit

31. Audit the first ten minutes of a typical free-to-play mobile game for dark patterns, and rank them by harm.
    - Seats: 3
    - Preset: audit

32. Audit a typical SaaS onboarding flow for the steps where new users give up.
    - Seats: 3
    - Preset: audit

33. Audit the accessibility of a standard 3D action game for players with limited mobility or low vision.
    - Seats: 3
    - Preset: audit

34. Audit the risks of letting AI agents commit directly to a production codebase.
    - Seats: 4
    - Preset: audit

35. Audit a personal-finance app's data practices from the point of view of a privacy regulator.
    - Seats: 2
    - Preset: audit

## Open Collaboration

36. Write a one-page manifesto for a game studio that ships only games made with AI tools, including what it refuses to do.
    - Seats: 3
    - Preset: collaborate

37. Write the rules of a brand-new card game that two people can learn in five minutes.
    - Seats: 2
    - Preset: collaborate

38. Write a style guide for an AI agent that writes release notes for a consumer app.
    - Seats: 3
    - Preset: collaborate

39. Write a short story told by three narrators who each remember the same night differently.
    - Seats: 3
    - Preset: collaborate

40. Write a charter for an online community of AI-assisted game makers: what it's for, who it's for, and how disputes get settled.
    - Seats: 4
    - Preset: collaborate
