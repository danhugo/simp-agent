---
name: pptx
label: PowerPoint
description: "Create or edit PowerPoint decks (.pptx): slides, presentations, decks of any length, in any language."
version: 10
---

# Slides

You write a **deck folder** (content + layout names); `office_build` turns it into a designed .pptx and checks it.
Never write pptxgenjs/python-pptx code. Look at the result once (Fast path step 5), never loop on the look.

## Fast path (aim: 4–6 turns, no more)

1. **Content.** If the user gave the material, use it. Otherwise research only what the content needs (the web
   tools say how). No photos unless the user asks for them or the design brief calls for them.
2. **Write the whole deck in ONE message**: `write` design.xml and every slide file as parallel calls
   (`/work/<name>.deck/design.xml`, `/work/<name>.deck/01-cover.xml`, `02-....xml` …). Over 12 slides: two messages
   of about 10 files each.
3. `office_build(source="/work/<name>.deck")` → `/work/<name>.pptx`.
4. If it lists problems, fix them all in ONE message (`edit` the named files), build once more, then answer.
   "Text shrank … cut its words" means the slide says too much: shorten it (or split it in two), never ignore it.
5. **Look once**: one `office_run` with `office.open(path).screenshot(grid=True)`. Fix what the look names (overlaps,
   text over a busy picture, empty areas) in ONE message, build once more. No second look. If the screenshot fails or
   comes back blank, skip the look: the build check already passed. Never debug the tools (no test builds in /tmp).
6. Answer in 2–3 lines: the file path, slide count, theme. No slide-by-slide recap.

**First version first.** The user wants to see a result before asking for changes. Deliver the first complete deck as
soon as it builds clean (plus the one look). Do not polish further on your own: in the answer, offer 2–3 concrete
improvements they can ask for. A designed deck (below) should take about 15–25 tool calls, a plain one 4–8.

**Done rule:** `office_build` already validates and checks the file. After a clean build and the one look (step 5),
answer. Never unpack the file or run other checks.


## design.xml

One line: `<design theme="navy"/>`. Themes: `navy` (corporate, finance), `ocean` (tech, health), `forest` (nature,
education, ESG), `terracotta` (food, culture, lifestyle), `mono` (minimal, design), `violet` (startup, marketing),
`night` (dark tech, data), `crimson` (dark dramatic: film, games, anime, history). Pick by topic; the user's wish wins.
Optional overrides: `<design theme="ocean"><color name="accent" value="#E4572E"/></design>` (names: bg, surface, ink,
muted, primary, accent, on) and fonts: `<font name="heading" family="Arial"/>` (names: display = cover/section
titles, heading = slide titles, body, caption). All style lives here: a font or color change for the whole deck is one
line in design.xml, then build again.

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
- **Truth**: real numbers from research or the user; never invent statistics. Say "approx." when unsure. Facts only
  the user can know (their team, prices, results, dates, targets, contacts) that they did not give: write a clearly
  marked placeholder in their language, e.g. `[Tên CEO]`, `[X tỷ VND]`, `[ngày áp dụng]`, never a made-up value, and
  list in your answer what they need to fill in.
- Write in the user's language (Vietnamese text is fine in every theme).

## Designed decks: illustrations, shapes, photos

When the user asks for a designed or illustrated look (a template feel, a playful lesson, a brand style), build the
slides in **free layout** (below) and dress them; the layouts above are for plain business decks.

**Write the design brief first** (in your head or a short note, never as a question to the user; when the user wants
to see or edit the brief before building, use the `slide-design-brief` skill), concrete enough that
two designers would build the same deck from it. Fill each line from what the user said; where they gave nothing,
choose from the topic and audience:
- **Mood**: 3 words (e.g. playful · bold · flat).
- **Palette**: background, dark, 1–2 accents, text colour, as hex. One family, high contrast for text.
- **Type**: heading style (uppercase? weight, size about 44–60px) and body size (≥ 20px); one font family is enough.
- **Motif**: 5–8 subjects from the topic, drawn the same way every time (two-tone flat art in the palette via
  `office.art(..., tint=(light, dark))`, or line icons), plus one shape language: waves, blobs, circles or angles.
- **Decoration rules**: where motifs sit (a band along the top or bottom, blobs bleeding off two corners), how many per
  slide (2–4), and that text never sits on them.
- **Images**: none, or one treatment kept everywhere (black-and-white photos cropped to circles or half-slide panels).
- **Slide plan**: for each slide, one line: what it says and its composition (cover scene, 3 cards, big numbers, chart
  with a side note, timeline, closing scene).
When the user brings a reference (a picture, a .pptx, a brand), take the brief from it: look at it once
(`read` an image, or `office_run` with `screenshot(grid=True)` for a deck) and write down its palette, type, motifs and
decoration rules before building.

- **Illustrations and icons**: `office.art_search("fish")` lists artwork names; `office.art("fish", out="/work/<name>.deck/assets/fish.svg",
  tint=("#9EEFBC", "#1E2A8A"))` saves one as SVG in the deck's colours (light parts, dark parts); no tint keeps its own
  colours. `kind="icon"` gives one-colour line icons (`color="#9EEFBC"`). Thousands exist: objects, animals, plants,
  buildings, vehicles, weather, food, people, symbols. Save them all in ONE `office_run`, then `<image src=...svg>`.
- **Waves, blobs, bands, custom drawings**: write an SVG file yourself (a `<path>` with curves) and place it with
  `<image>`. Images and shapes may run off the slide edge (negative x/y, or past 1280×720) as long as part of them is
  on the slide: that is how corner blobs and edge bands bleed. Text boxes must stay inside.
- **Photos**: only when the user wants them; `web_download` a free-licence photo, then crop/grayscale it with Pillow.
- Repeat a motif and the palette on every slide; 2–4 accent colours at most; big headings; plenty of space.
- Keep text clear of decorations: a heading box tall enough for two lines, and cards below the heading's box.
- Readable from the back of a room: body ≥ 24 px (32 px for a talk), headings ≥ 44 px, text contrast at least 4.5:1;
  one idea per slide and about a third of it empty (the `slide-design-brief` skill has the full rules and sources).
- Write the whole deck in ONE message of parallel `write` calls (design.xml, every slide, every SVG you draw), after
  ONE `office_run` that saves all the artwork. Then build.

## Free layout (complete reference: there is nothing else to look up)

A `<slide>` without `layout` holds positioned elements on a 1280×720 px canvas, drawn in file order (later on top).
Colours are `#RRGGBB` or a design.xml name (bg, surface, ink, muted, primary, accent, on). Every element takes
`x y width height` in px; text, charts and tables must stay inside the canvas, shapes and images may bleed off it.

- `<background color="#4352BE"/>`: the slide's background colour.
- `<text x y width height font="display|heading|body|caption" size="40" color="#FFFFFF" bold="true"
  align="left|center|right" anchor="top|middle|bottom" fill="#1E2A8A" padding="16" line-height="1.2"
  space-after="12" autofit="shrink">…</text>`: content is plain text, or paragraphs `<p>…</p>`, or lists
  `<ul><li>…</li></ul>` / `<ol>`. Inline: `<strong>`, `<em>`, `<u>`, `<span color="#9EEFBC" size="28" font="heading">`.
  `font` picks design.xml's family; size is px. Leave height for every line (about size × 1.3 per line).
- `<shape type="rect|ellipse|triangle|diamond|arrow|chevron|star|hexagon|pentagon|parallelogram" x y width height
  fill="#9EEFBC|none" stroke="#1E2A8A" stroke-width="2" corner-radius="24" opacity="0.6"/>`; a line:
  `<shape type="line" x y width height stroke="#9EEFBC" stroke-width="4" arrow-end="arrow"/>` (from x,y to x+width,y+height).
- `<image src="/work/…/x.svg|.png|.jpg" x y width height/>`: keep the picture's own aspect ratio (the build reports a
  stretched one). Crop photos to a circle or panel beforehand with Pillow; no opacity on images (bake it into the file).
- `<chart x y width height type="column|bar|line|area|pie|donut|scatter" categories="A,B,C" color="#9EEFBC"
  legend="none|bottom|right" font="body" size="18"><series name="…" values="1,2,3"/></chart>`.
- `<table x y width height columns="2,1,1" font="body" size="18" fill="#2A3180" header-fill="#9EEFBC">
  <tr><td>…</td></tr></table>`: first row is the header.

Fonts: the file names a family; PowerPoint uses it if the viewer has it (preview and screenshots use what the sandbox
has). Safe for every viewer: Arial, Calibri, Georgia, Segoe UI, Verdana. Vietnamese text works in all of them. Do not
list or test the sandbox's fonts.

## Editing

- A deck you built (it has a `.deck` folder): change the source, never the .pptx. Text: `edit` the slide file.
  Order: rename files. Fonts/colors for the whole deck: design.xml (above). Then `office_build` once. Never inspect or
  patch the built .pptx with bash, officecli or office_run.
- A .pptx the user brought (no deck folder): one `office_run` script does the whole job. Find what to change
  with `d.query(...)` or `d.view("annotated")`, change it, and end with `d.screenshot(grid=True)` to see the result:
  ```python
  d = office.open("/work/q3.pptx")
  for s in d.query('shape:contains("2025")'):
      d.set(s.path, text=s.text.replace("2025", "2026"))
  t = "/slide[4]/table[1]"
  for name, v in rows:                      # rows from the user's data
      d.add(t, "row", c1=name, c2=v)        # unsure of a prop? print(office.help("pptx", "row"))
  d.screenshot(grid=True)
  ```
- If `office_build` says the .pptx changed outside its source (the user edited it), edit it with `office_run`
  instead of rebuilding, unless the user wants it rebuilt.
