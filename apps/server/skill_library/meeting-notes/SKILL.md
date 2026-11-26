---
name: meeting-notes
label: Meeting notes
description: "Turn a meeting transcript, recording or rough notes into clear minutes: summary, decisions, action items with owners and dates, open questions; also prepare agendas. Use for anything meeting-related."
license: MIT
source: simp
version: 1
---

# Meeting Notes

## Inputs

- Transcript / notes file in `/work` (txt, docx, vtt/srt, pdf): read it fully. Subtitle files: strip timestamps first.
- Audio/video recording: there is no speech-to-text model in the sandbox. Tell the user and ask for a transcript (most meeting tools export one). You can cut/convert audio with `ffmpeg` if needed (see `audio-video` skill).
- Calendar portal (if connected): get title, date, attendees from the event.

## Minutes template

```markdown
# <Meeting title> — <YYYY-MM-DD>
**Attendees:** ...   **Absent:** ...   **Facilitator / note-taker:** ...

## Summary
3–5 sentences: purpose, main outcomes.

## Decisions
- D1. <decision> (by whom, rationale in a few words)

## Action items
| # | Action | Owner | Due | Status |
|---|--------|-------|-----|--------|
| 1 | Send revised budget to finance | Lan | 2026-12-03 | Open |

## Discussion by topic
### <Topic 1>
- key points, options considered, data cited

## Open questions / parking lot
- ...

## Next meeting
date, agenda items carried over
```

## Rules

- Action items: start with a verb, one owner (a person, not "team"), a concrete due date. If the transcript has no owner or date, write "TBD" and list it under open questions; never invent.
- Decisions vs. discussion: only record something as a decision if it was agreed.
- Attribute statements only when it matters (commitments, objections); otherwise summarise neutrally.
- Keep the language of the meeting unless asked; keep names and numbers exactly as said.
- Length: summary readable in 1 minute; details below.

## Agenda (before a meeting)

Goal of the meeting (one line), items with owner + time box + desired outcome (decide / inform / discuss), pre-reads with links, and who must attend.

## Follow-ups

Offer: a follow-up email draft (Gmail portal, draft only), tasks in Linear/Notion/Atlassian if connected (confirm before creating), or a .docx via the `docx` skill.
