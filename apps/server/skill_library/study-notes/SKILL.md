---
name: study-notes
label: Study notes & flashcards
description: "Turn lectures, textbooks, slides or PDFs into study notes, summaries, flashcards (Anki-importable CSV), practice quizzes and study plans; explain concepts step by step. Use for learning and exam prep."
license: MIT
source: simp
version: 1
---

# Study Notes & Flashcards

## 1. Gather material

Read the user's files (`markitdown` for docx/pptx, `pdftotext -layout` for PDFs, `ocr-scans` skill for photos of notes). Ask the level (high school, university, professional exam) and the exam date/format if relevant. Use only the material plus well-established knowledge; flag anything you add from outside the material.

## 2. Notes

Structure per topic:
```markdown
## <Topic>
**Big idea:** one sentence.
**Key terms:** term — short definition (original-language term in brackets if translating)
**How it works:** 3–6 bullets or numbered steps; formulas in LaTeX-ish plain text with units
**Example:** one worked example
**Common mistakes:** 1–3
**Links to:** related topics
```
Prefer the Cornell layout (cues / notes / summary) if the user asks for printable notes. Keep it shorter than the source: notes are for revision, not a rewrite.

## 3. Flashcards

- One fact or idea per card; question side is specific ("What does the mitochondrial ETC produce?" not "Mitochondria?").
- Mix types: definition, why/how, compare A vs B, cloze (`{{c1::...}}`), apply-to-example.
- 15–40 cards per chapter; tag by chapter.
- Export Anki-importable CSV (UTF-8, no header): `front,back,tags`, with `csv` module quoting:
  ```python
  import csv; w = csv.writer(open("/work/study/cards.csv","w",newline="",encoding="utf-8")); w.writerows(cards)
  ```
  Tell the user: Anki → Import → select file → map fields.

## 4. Quizzes

Multiple-choice (4 options, plausible distractors), short-answer and one or two application problems per topic. Put the answer key with brief explanations **after** all questions (or in a separate file) so the user can self-test. Offer interactive mode: ask one question at a time in chat and give feedback.

## 5. Explaining a concept

Start from what the learner knows, use an analogy, then the precise definition, then a worked example, then check understanding with one question. For maths/code, go step by step and verify calculations with Python.

## 6. Study plan

Work backwards from the exam date: topics weighted by difficulty and exam weight, spaced repetition (review after 1, 3, 7, 14 days), practice tests in the last week, buffer days. Table by date; optionally create Calendar events if the portal is connected (confirm first).

Deliver Markdown in chat for short material; for longer, write files in `/work/study/` (notes .md or .docx via the `docx` skill, cards .csv, quiz .md).
