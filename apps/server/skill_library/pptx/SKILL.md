---
name: pptx
label: PowerPoint
description: "Create or edit PowerPoint decks (.pptx): slides, presentations, decks of any length, in any language."
---

# Slides

You write a **deck folder** (content + layout names); `office_build` turns it into a designed .pptx and checks it.
Never write pptxgenjs/python-pptx code, never render screenshots to review, never loop on the look.

## Fast path (aim: 4–6 turns, no more)

1. **Content.** If the user gave the material, use it. Otherwise: **Research budget:** at most TWO messages of research in total: one of parallel `web_search` calls (2–4 queries), then optionally one of parallel `web_fetch(url, prompt=...)` calls. Never fetch search-engine pages (google, bing, duckduckgo…), never retry failed fetches, never curl. Then write with what you have: mark uncertain figures "≈" or "approx." and name the source you did get. Never search for or download pictures
   unless the user asks for pictures.
2. **Write the whole deck in ONE message**: `write` design.xml and every slide file as parallel calls
   (`/work/<name>.deck/design.xml`, `/work/<name>.deck/01-cover.xml`, `02-....xml` …). Over 12 slides: two messages
   of about 10 files each.
3. `office_build(source="/work/<name>.deck")` → `/work/<name>.pptx`.
4. If it lists problems, fix them all in ONE message (`edit` the named files), build once more, then answer.
5. Answer in 2–3 lines: the file path, slide count, theme. No slide-by-slide recap.

**Done rule:** `office_build` already validates, recalculates and checks the file. When it says "No problems found", answer the user right away. Never unpack, render, re-open or re-check the built file yourself, and never run recalc.py or other checks after a clean build.


## design.xml

One line: `<design theme="navy"/>`. Themes: `navy` (corporate, finance), `ocean` (tech, health), `forest` (nature,
education, ESG), `terracotta` (food, culture, lifestyle), `mono` (minimal, design), `violet` (startup, marketing),
`night` (dark tech, data), `crimson` (dark dramatic: film, games, anime, history). Pick by topic; the user's wish wins.
Optional overrides: `<design theme="ocean"><color name="accent" value="#E4572E"/></design>` (names: bg, surface, ink,
muted, primary, accent, on).

## Slide files: pick a layout, write the content

Files are built in file-name order: name them `01-…`, `02-…`. Attribute values need `&amp;` for `&` and `&quot;` for `"`.
Inside text you may use `<strong>`, `<em>`, `<span color="accent">`.

```xml
<slide layout="cover" title="Deck title" subtitle="One line that says what the deck gives" meta="Author · Date"/>
<slide layout="section" number="02" title="Section title" lead="One sentence."/>
<slide layout="bullets" title="Title">
  <li><strong>Key term</strong> concrete fact, number or example</li>      <!-- 3–6 items, each ≤ 2 lines -->
  <note><li>side fact</li><li>source</li></note>                          <!-- optional right card -->
</slide>
<slide layout="two-col" title="Compare A and B">
  <col title="A"><li>…</li><li>…</li></col><col title="B"><li>…</li><li>…</li></col>
</slide>
<slide layout="cards" title="Title">                                       <!-- 2–4 cards; value optional -->
  <card title="Name" value="42%">One or two sentences.</card> …
</slide>
<slide layout="kpis" title="Title">                                        <!-- 2–4 big numbers -->
  <kpi value="$1.2B" label="What it measures" note="Context or source"/> …
</slide>
<slide layout="chart" title="Revenue by year (USD M)" type="column" categories="2022,2023,2024">
  <series name="Revenue" values="120,180,260"/>                            <!-- more series = grouped -->
  <li>Insight the chart proves</li><li>Second insight</li>                 <!-- optional side card -->
</slide>
<slide layout="table" title="Title" columns="2,1,3">                       <!-- first row = header; ≤ 8 rows -->
  <tr><td>Name</td><td>Value</td><td>Note</td></tr><tr><td>…</td><td>…</td><td>…</td></tr>
  <note>Source: …</note>
</slide>
<slide layout="steps" title="How it works">                                <!-- 3–6 steps: process, timeline -->
  <step title="Step name">One short sentence.</step> …
</slide>
<slide layout="quote" quote="A memorable line." by="Who said it"/>
<slide layout="image" title="Title" src="/work/photo.jpg"><li>…</li></slide>   <!-- only with a real image file -->
<slide layout="closing" title="Thank you" subtitle="Questions? / next step" meta="Contact"/>
```

Chart types: column, bar, line, area, pie, donut. Values are plain numbers (no %, $, commas); put units in the title.

## What makes a deck good (every deck)

- **Count**: exactly the number of slides the user asked for, cover and closing included (default 10).
- **Arc**: cover → 1 agenda or context slide → body → takeaway/recommendation → closing. 15+ slides: add `section` slides.
- **Variety**: never more than 2 `bullets` slides in a row. Numbers → `kpis` or `chart`; comparisons → `two-col` or
  `table`; processes/history → `steps`; 2–4 parallel ideas → `cards`.
- **Density**: every body slide carries specifics (names, numbers, dates, examples), not generic phrases. Titles are
  short claims ("Sales doubled in 2024"), not labels ("Sales"). ≤ 6 bullets, each ≤ 2 lines.
- **Truth**: real numbers from research or the user; never invent statistics. Say "approx." when unsure.
- Write in the user's language (Vietnamese text is fine in every theme).

## Free layout (rare)

A `<slide>` without `layout` holds positioned elements on a 1280×720 canvas (x, y, width, height in px):
`<background color="bg"/>`, `<text x y width height font="heading|body|caption|display" size color align
anchor="top|middle|bottom">…</text>`, `<shape type="rect|ellipse|line|arrow|…" fill stroke corner-radius/>`,
`<image src/>`, `<chart>`, `<table>`. Use it only for a slide no layout fits.

## Editing

- A deck you built: `edit` the slide file (or reorder by renaming files), `office_build` again.
- A .pptx the user brought (no deck folder): `office_read(path, view="annotated")` to see element paths, then
  `office_edit(path, ops=[{"command":"set","path":"/slide[2]/shape[@id=5]","props":{"text":"…"}}])`.
- If `office_build` says the .pptx changed outside its source (the user edited it), use `office_edit` on it instead
  of rebuilding, unless the user wants it rebuilt.
