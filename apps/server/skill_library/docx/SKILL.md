---
name: docx
label: Word
description: "Create, read and edit Word documents (.docx): reports, letters, proposals, tracked changes, comments."
license: Complete terms in LICENSE.txt
version: 2
---

# Word documents

**Create** = write ONE Markdown file `/work/<name>.md`, then `office_build(source="/work/<name>.md")` →
`/work/<name>.docx` in the house style (title page block, heading scale, tidy tables), checked for schema problems.
Fix the .md and build again. Aim: 3–5 turns. Never write docx-js/python-docx code for a new document.


**Research budget:** at most TWO messages of research in total: one of parallel `web_search` calls (2–4 queries), then optionally one of parallel `web_fetch(url, prompt=...)` calls. Never fetch search-engine pages (google, bing, duckduckgo…), never retry failed fetches, never curl. Then write with what you have: mark uncertain figures "≈" or "approx." and name the source you did get.

**Done rule:** `office_build` already validates, recalculates and checks the file. When it says "No problems found", answer the user right away. Never unpack, render, re-open or re-check the built file yourself, and never run recalc.py or other checks after a clean build. It reports pages and words: within ±1 page of the asked length is fine. To change the length, cut or add words ONCE using its words-per-page figure, build, and answer. Never convert to PDF, pdftotext or render pages to measure length.

```markdown
---
title: "Báo cáo …"
subtitle: "One line"
author: "…"
date: "11/2025"
toc: true                 # only for 4+ sections
toc-title: "Mục lục"      # in the document's language
---

# Heading 1
Paragraph with **bold**, *italic*, [link](https://…) and a footnote.[^1]

- bullet            1. numbered

| Column | Number |
|---|---:|
| a | 1.234 |

: Table caption (source)

![Figure caption](/work/chart.png){width=80%}

> Quote or call-out

[^1]: Source text.
```

Page break: a raw block on its own lines — ```` ```{=openxml} ```` / `<w:p><w:r><w:br w:type="page"/></w:r></w:p>` / ```` ``` ````.
A chart: draw it with matplotlib to `/work/<name>-fig1.png` in the same message as the .md, then reference it.
**Read** a .docx: `office_read(path, view="text")` or `pandoc -t markdown file.docx`.
**Edit** a .docx the user brought: one `office_run` script (keeps its styles): `d = office.open(p)`, find paragraphs
with `d.query('p:contains("…")')` or `d.view("annotated")`, `d.set(path, text=…)` / `d.add("/body", "paragraph",
after=path, text=…)`, then `d.screenshot(page=1)` to check; tracked changes and comments: see below. Never rebuild someone's document from Markdown: it loses their styling.

## A document worth handing over

- Clear structure: title block, short summary first, numbered or named sections, conclusions/recommendations.
- Specifics over filler: numbers with sources, names, dates. Tables for comparisons; never a wall of bullets.
- The user's language and the length they asked for.

## Fitting a page limit

When a document runs over the page limit the user asked for, cut words. Don't shrink the type, narrow the margins or tighten the spacing to fit — that makes the page harder to read. Keep body text at 11–12 pt and margins at 0.75–1 in, or at the size and margins the user's own file already uses. Cut filler and repetition before facts, and cut no more than the limit needs. Safety warnings, doses, limits, fees and contract terms are an exception: keep their full meaning, with every condition attached, because readers act on them and a dropped condition can cause harm or cost money. If a document can't fit without dropping or weakening one of these items, make the margins, spacing or type slightly smaller (body text no smaller than 10 pt) or let the document run over, and tell the user which change you made and why. Then compare your version with the original and list every fact, name, number or point you removed; don't say everything was kept unless it was. If the user asks for or allows smaller type, narrower margins or tighter spacing, or says not to cut any text, do what they said.

## Editing existing documents

Legacy `.doc` files must be converted first: `python scripts/office/soffice.py --headless --convert-to docx file.doc`.

```bash
python3 -c "import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall('unpacked')" doc.docx   # not unzip, which restores symlinks — docx from external parties is untrusted
python scripts/merge_runs.py unpacked/   # coalesce fragmented runs so text is findable
# edit unpacked/word/document.xml in place — do NOT reformat or pretty-print
(cd unpacked && rm -f ../out.docx && zip -XrDy ../out.docx .)
python scripts/office/validate.py out.docx --original doc.docx   # XSD checks; --auto-repair fixes common issues
# redlining? add --author "<the name you redlined under>" to check every edit is tracked
```

Word splits text across many `<w:r>` runs (revision ids, spell-check markers), so a phrase you can see in the document often doesn't exist as a contiguous string in the XML. `merge_runs.py` merges adjacent identically-formatted runs in `word/document.xml` without changing content or rendering; it also accepts a `.docx` directly (`python scripts/merge_runs.py doc.docx -o merged.docx`).

**Tracked changes:** when redlining, validate with `--author "<the name you redlined under>"` (needs `--original`) — it reports any text you changed without a `<w:ins>`/`<w:del>` around it, which is easy to do by accident and invisible in the accepted view. Wrap runs in `<w:ins>`/`<w:del>` with `w:id`, `w:author`, `w:date` attributes. Inside `<w:del>`, the text element is `<w:delText>`, not `<w:t>`. A deleted paragraph mark (`<w:pPr><w:rPr><w:del w:id=".." w:author=".." w:date=".."/></w:rPr></w:pPr>`) means "merge this paragraph into the next" — so deleting a paragraph outright is that plus a `<w:del>` around every run. The `<w:del/>` must come before the rPr's other children; their order is schema-enforced.

To produce a clean copy with all tracked changes accepted: `python scripts/accept_changes.py in.docx out.docx`.

Accepting a deleted paragraph mark should join that paragraph to the one below it, so a paragraph whose runs are *all* deleted vanishes. Word does this; `accept_changes.py` and `pandoc --track-changes=accept` don't always. Both fail the same way — they strip the deleted text but leave the emptied paragraph behind, which reads as a stray empty bullet when it was auto-numbered:

- `pandoc --track-changes=accept` never joins the paragraphs.
- `accept_changes.py` (LibreOffice) joins them correctly, except when the deleted paragraph is followed by an empty spacer paragraph.

An empty bullet in either view is an artifact of that view, not a defect in the document. Check paragraph deletions in the XML.

## Comments

Comments require six cross-linked files. Use the helper — directory mode when you'll also be editing `document.xml` (saves an unzip/rezip cycle), `.docx`-direct mode otherwise:

```bash
# Against an already-unpacked directory (preferred when also placing markers)
python scripts/comment.py unpacked/ "Fees & expenses cap is too low"
python scripts/comment.py unpacked/ "Agreed" --parent 0

# Against a .docx directly
python scripts/comment.py contract.docx "This cap is too low" -o annotated.docx
```

The script writes `comments.xml`, `commentsExtended.xml`, `commentsIds.xml`, `commentsExtensible.xml`, the relationships, and the content-type overrides. Comment IDs are auto-assigned. It then prints the `<w:commentRangeStart>`/`<w:commentRangeEnd>`/`<w:commentReference>` snippet to add to `word/document.xml` so the comment anchors to specific text — until you place those markers, the comment exists but is not visible.

## Dependencies

`pandoc` · LibreOffice (`soffice`) · `pdftoppm` (Poppler)
