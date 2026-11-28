---
name: docx
label: Word
description: "Create, read and edit Word documents (.docx): reports, letters, proposals, tracked changes, comments."
license: Complete terms in LICENSE.txt
version: 8
---

# Word documents

**Create** = write ONE Markdown file `/work/<name>.md`, then `office_build(source="/work/<name>.md")` →
`/work/<name>.docx` in the house style (title page block, heading scale, tidy tables), checked for schema problems.
Fix the .md and build again. Aim: 3–5 turns. Never write docx-js/python-docx code for a new document.


**Research:** only what the content needs (the web tools say how); the user's own material comes first.

**Done rule:** `office_build` already validates, recalculates and checks the file. When it says "No problems found", answer the user right away. Never unpack, render, re-open or re-check the built file yourself, and never run other checks after a clean build. It reports pages and words: within ±1 page of the asked length is fine. To change the length, cut or add words ONCE using its words-per-page figure, build, and answer. Never convert to PDF, pdftotext or render pages to measure length.

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
**Edit** a .docx the user brought: one `office_run` script (below). Never rebuild someone's document from Markdown:
it loses their styling.

## A document worth handing over

- Clear structure: title block, short summary first, numbered or named sections, conclusions/recommendations.
- Specifics over filler: numbers with sources, names, dates. Tables for comparisons; never a wall of bullets.
- The user's language and the length they asked for.

## Fitting a page limit

When a document runs over the page limit the user asked for, cut words. Don't shrink the type, narrow the margins or tighten the spacing to fit — that makes the page harder to read. Keep body text at 11–12 pt and margins at 0.75–1 in, or at the size and margins the user's own file already uses. Cut filler and repetition before facts, and cut no more than the limit needs. Safety warnings, doses, limits, fees and contract terms are an exception: keep their full meaning, with every condition attached, because readers act on them and a dropped condition can cause harm or cost money. If a document can't fit without dropping or weakening one of these items, make the margins, spacing or type slightly smaller (body text no smaller than 10 pt) or let the document run over, and tell the user which change you made and why. Then compare your version with the original and list every fact, name, number or point you removed; don't say everything was kept unless it was. If the user asks for or allows smaller type, narrower margins or tighter spacing, or says not to cut any text, do what they said.

## Editing existing documents

One `office_run` script; officecli edits the document in place and keeps its styles, numbering and layout.

```python
d = office.open("/work/contract.docx")
print(d.view("annotated"))                                     # text with each paragraph's path
d.set("/body", find="30 days", replace="45 days")             # every match, across runs and formatting
p = d.query('p:contains("Fees")')[0].path
d.set(p, text="Fees are capped at 8% of revenue.")            # rewrite one paragraph
d.add("/body", "paragraph", after=p, text="Late payments carry 1% interest a month.")
d.add(p, "comment", text="Cap raised from 5% as agreed", author="Simp")
d.screenshot(page=1)
```

- **Tracked changes (redlining):** add `revision__author="<name>"` to a `find`/`replace` or a text change, and
  officecli records it as an insertion/deletion by that author. `print(d.query("revision"))` lists them (type,
  author, text); `d.set("/revision", revision__action="accept")` accepts all,
  `d.set("/revision[@author=Alice]", revision__action="reject")` rejects one author's. Work on a copy when the user
  wants to keep the original. Accepting a fully deleted paragraph may leave an empty one behind (an empty bullet when
  it was numbered); remove it with `d.remove(path)`.
- **Comments:** `d.add(paragraph_path, "comment", text=..., author=...)`; reply with `parentId=`; resolve with
  `d.set(comment_path, done=True)`; list with `d.query("comment")`.
- **Anything else** (headers and footers, footnotes, tables, pictures, styles, a table of contents, sections):
  `print(office.help("docx"))` lists the elements, `office.help("docx", "<element>")` their properties.

Legacy `.doc` (Word 97–2003) files cannot be read here: ask the user to save it as .docx in Word and upload that.

## Dependencies

`pandoc` (through `office_build`) · officecli (through `office_build`, `office_read`, `office_run`)
