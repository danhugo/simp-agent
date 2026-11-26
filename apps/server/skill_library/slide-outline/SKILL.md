---
name: slide-outline
label: Slide outline & storytelling
description: "Plan a presentation before building it: audience, key message, storyline, slide-by-slide outline with titles, content and visuals, speaker notes. Use before making a deck or when the user wants a talk structure."
license: MIT
source: simp
version: 1
---

# Slide Outline & Storytelling

Plan the story first, then build the deck with the `pptx` skill (`office_build`).

## 1. Frame (ask at most one question if these are unclear)

- Audience and what they already know; setting (live talk, read-alone deck, pitch, class).
- **The one message** the audience must remember (one sentence).
- What they should do or decide afterwards.
- Length: minutes or slide count (rule of thumb: 1 slide per 1–2 minutes of talk).

## 2. Storyline

Pick a structure:
- **SCR** (situation, complication, resolution): business updates and proposals.
- **Pyramid:** answer first, then 3 supporting arguments, each with evidence.
- **Problem → solution → proof → ask:** pitches.
- **Before / after / how:** change and training.
- **Teach:** why it matters → concept → example → practice → recap (lessons).

## 3. Outline format

Write `/work/<deck>-outline.md`:

```markdown
# <Deck title> — <audience>, <minutes> min
Key message: ...

1. **Title slide** — title, subtitle, presenter, date
2. **<Action title: a full sentence stating the takeaway>**
   - Content: 3 bullets max / one chart / one image idea
   - Visual: bar chart of X by Y, highlight Z
   - Notes: what to say (2–4 sentences)
...
N. **Next steps / the ask**
Appendix: backup data
```

Rules:
- **Action titles:** each title is the slide's conclusion ("Churn fell 3 pts after onboarding redesign"), not a topic ("Churn"). Reading only titles should tell the whole story.
- One idea per slide; ≤ 3 bullets of ≤ 12 words; numbers over adjectives.
- Every chart has one takeaway highlighted.
- Visuals: say concretely what to show (chart type and data, diagram, photo). There is no image generator; use charts, icons/shapes, the user's images or Canva (if connected).
- Open with why it matters to this audience; close with the message and the ask.

## 4. Review

Read the titles in order: is the logic complete? Remove slides that don't support the key message (move to appendix). Then confirm with the user and build.
