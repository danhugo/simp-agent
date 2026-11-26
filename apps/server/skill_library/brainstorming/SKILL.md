---
name: brainstorming
label: Brainstorming
description: "Turn a vague idea into a clear, agreed design before building anything: a feature, an app, a talk, an event, a business idea. Asks focused questions, lays out 2-3 approaches, writes a short design for approval."
license: MIT (see LICENSE.txt)
source: https://github.com/obra/superpowers/tree/main/skills/brainstorming
version: 1
---

# Brainstorming

You build what you believe the user wants, and that belief is usually thinner than it feels. Find out what they actually want, and why, before building.

## First: what do you know?

- **Everything that matters is in the request** ("make the title blue"): just do it and say what you did.
- **Something non-trivial is missing:** start the conversation below.

Before building, in order: (1) lay out approaches and let the user pick, (2) write a short design, (3) get approval, (4) plan (see the `writing-plans` skill) or just build if small.

## Look before you ask

If there is context (files in `/work`, a repo, a spec, connected Drive/Notion docs, earlier chat), read it first until you can explain how things work today and what the change touches. Never ask what the context already answers.

## First message

- **They already said what they want:** ~200 words. Echo the request in your own words (what, for whom, why). Add what you found that bears on it, including any constraint or cheaper path they may not know. Invite corrections. If they haven't said *why*, ask that (one open question). If one open choice would change the result most, ask about that one, sketching options with trade-offs and your pick.
- **They haven't:** one open question, in their terms, about the biggest unknown, and say what the answer changes. ("If it's mostly for people deciding whether to stop by, I'd lead with hours and today's menu; taking orders is a different site. What should a visitor do first?")
- If they didn't ask to brainstorm, end with a light offer: "Or if you'd rather I just dive in, say so."

## The conversation

- Ask only when the answer changes what gets built and nothing answers it already. Otherwise state your call and reason as a correctable proposal.
- **One question at a time**, plain language, their vocabulary, no process jargon.
- Until you know *why*, ask open questions without example answers. After that, offer concrete options with trade-offs and your pick. "What do you think?" → propose something concrete.
- **How it gets made** (platform, language, tools, medium): if they talk about outcomes, make these calls yourself and state each in one line.
- Ground to cover (not a script): what it is and what makes it special; why now and what success looks like; goals, non-goals, anti-goals; things they've seen and loved/hated; current state; details they care about.
- Make each question build on their last answer, Socratically ("Voting closes before the meeting and two members joined this month. Do newcomers get a vote?").
- **Do recon** when it helps: their files, the web (`web_search`, `web_fetch`). Say what you found.
- **Show, don't tell:** sketch layouts, flows or screens in text/ASCII; for visual choices you can render a quick mockup image (matplotlib/HTML file) for them to react to.
- **Spikes:** a quick throwaway build is often the cheapest way to learn. Offer one; no tests or plan needed; bring the lessons back.

## Play it back

As soon as one part is understood, describe it back (~200 words). Mark what they said as theirs and what you filled in as your proposal with a reason. Ask what's wrong or missing. Alternate playback and questions.

## Lay out the approaches

In a message of its own: 2–3 real alternatives (drop weak ones and ones that work against their goal), each concrete enough to picture, with trade-offs. Recommend one, say why, ask which to take. If only one makes sense, say so and why.

## The design

Size it to the work: a few lines for small things, a short doc (`/work/designs/<topic>.md`) for bigger ones: goal and why, users, what's in and out, the chosen approach, key decisions with reasons, open questions, how we'll know it works. Ask for approval. Then plan or build.

## Don't

- ask several questions in one message, or questions the context answers;
- present your own assumptions as things the user agreed to;
- start building before they picked an approach (unless they opted out).
