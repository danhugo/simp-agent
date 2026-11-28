---
name: translation
label: Translation
description: "Translate text and whole documents (docx, pptx, xlsx, pdf, srt, md) between languages, e.g. Vietnamese and English, keeping formatting, terminology and tone; also localize and review translations."
license: MIT
source: simp
version: 2
---

# Translation

## Principles

- Translate meaning, not words; keep tone and register (formal letter vs. chat). Natural target-language phrasing over literal.
- Keep unchanged: names, product names, code, URLs, numbers (but convert formats when localizing: `1.234,5` ↔ `1,234.5`, dates `26/11/2026` ↔ `Nov 26, 2026`).
- Terminology: build a glossary first for long or technical texts (`/work/glossary.csv`: source, target, note) and use it consistently. Ask the user for their preferred terms if the domain is specialised (legal, medical).
- Vietnamese: correct diacritics (Unicode NFC), suitable pronouns for the audience (anh/chị/bạn/quý khách), avoid word-for-word English syntax.
- Don't add or drop content. Flag ambiguities and untranslatable puns in a short note at the end.

## Short text

Reply with the translation only (plus notes if needed). Offer alternatives for slogans/titles.

## Documents: keep the format

Work on a copy, never the original. Translate in chunks of related text so context is kept.

- **.docx / .pptx / .xlsx:** one `office_run` script on the copy. `d = office.open(copy)`; collect the text with
  `d.query("paragraph")` (docx: also table cells, headers, footers; pptx: `d.query("shape")` and table cells, plus notes;
  xlsx: `d.view("text")`, string cells only, never formulas), translate, then write each back with
  `d.set(path, text=...)` (a cell: `value=`). officecli keeps the styles. pptx: translated Vietnamese/German is often
  longer, so the run's check reports text overflow; shorten or set a slightly smaller `size` on that shape, then
  `d.screenshot(grid=True)`.
- **.srt / .vtt:** keep indexes and timestamps; ≤ 42 characters per line, ≤ 2 lines per cue.
- **.md / .html:** keep markup; translate text nodes only (BeautifulSoup for HTML).
- **.pdf:** extract text (`pdftotext -layout`), translate, and rebuild as .docx (via the `docx` skill) since PDFs can't be edited in place; tell the user layout is approximate.

After writing, re-open the output and spot-check: count of paragraphs/cells matches, no source-language leftovers (`rg` for common source words), formatting intact.

## Reviewing a translation

Compare side by side; report errors as a table: location, source, current, suggested, reason (accuracy / terminology / grammar / style). Prioritise meaning errors over style.
