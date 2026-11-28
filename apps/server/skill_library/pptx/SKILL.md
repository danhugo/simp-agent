---
name: pptx
label: PowerPoint
description: "Create or edit PowerPoint decks (.pptx): slides, presentations, decks of any length, in any language."
version: 14
---

# Slides

Every deck is a **React deck**: one `/work/<name>.jsx` file (components + CSS, reference below). `office_build` lays it
out in a browser and turns it into an editable .pptx plus a preview. Never write pptxgenjs/python-pptx code.

## Fast path (plain deck: 4–8 tool calls; designed deck: 15–25)

1. **Content.** If the user gave the material, use it. Otherwise research only what the content needs (the web
   tools say how). No photos unless the user asks for them or the design brief calls for them.
2. **Pick a look**: a theme below for a plain deck, or a design brief (Designed decks) when the user wants a
   designed, illustrated or branded look. Icons or artwork: save them all in ONE `office_run` first.
3. **Write the whole deck in ONE `write`**: `/work/<name>.jsx`, every slide.
4. `office_build(source="/work/<name>.jsx")` → `/work/<name>.pptx` + `/work/<name>.html`. If it lists problems, fix
   them all in ONE `edit`, build once more. "Content taller than the slide" means the slide says too much: shorten it
   or split it in two.
5. **Look once, for the design only**: one `office_run` with `office.open(path).screenshot(grid=True)`. Judge the
   look (balance, colour, empty areas, text over a busy picture), not text fit: the build measured every text box,
   and the small grid makes the helper see overflow and clipping that are not there. Fix real design faults in ONE
   edit, build once more. No second look. If the screenshot fails or comes back blank, skip the look.
6. Answer in 2–3 lines: the file path, slide count, look. No slide-by-slide recap.

**First version first.** The user wants to see a result before asking for changes. Deliver the first complete deck as
soon as it builds clean (plus the one look). Do not polish further on your own: in the answer, offer 2–3 concrete
improvements they can ask for.

**Done rule:** `office_build` already validates and checks the file. After a clean build and the one look, answer.
Never unpack the file or run other checks (no `office_read` to check it: it only reads). Never debug the tools (no
test builds in /tmp). Pictures from .svg files are fine; never redraw them as PNG.

## Themes (plain decks)

Pick by topic; the user's wish wins. Put the colours in the CSS (bg = slide background, ink = text, primary =
headings and charts, accent = highlights, surface = cards).

| theme | for | bg | surface | ink | primary | accent |
|---|---|---|---|---|---|---|
| navy | corporate, finance | #FFFFFF | #F1F4F9 | #1B2433 | #1F3A68 | #E0A526 |
| ocean | tech, health | #F7FAFC | #FFFFFF | #102A43 | #0B7FAB | #F25F5C |
| forest | nature, education, ESG | #F6F8F4 | #FFFFFF | #1E2B22 | #2F6B3F | #D98E04 |
| terracotta | food, culture, lifestyle | #FBF6F0 | #FFFFFF | #3A2A20 | #B5532F | #2E7D6B |
| mono | minimal, design | #FFFFFF | #F4F4F4 | #111111 | #111111 | #E4572E |
| violet | startup, marketing | #FAF8FF | #FFFFFF | #221B3A | #5B3FD1 | #FF8A3D |
| night | dark tech, data | #0F1724 | #1A2436 | #E8EDF5 | #5AB0FF | #FFB547 |
| crimson | dark dramatic: film, games, history | #16110F | #241A17 | #F2E8E4 | #D7263D | #F2B134 |

Fonts: Arial (safe everywhere) or Calibri / Georgia / Segoe UI / Verdana. Vietnamese text works in all of them.

## Plain deck: layouts as components

Write these once at the top of the .jsx and build every slide from them. Change the theme by changing the CSS only.

```jsx
import { Slide, Art, Chart } from "deck";

const T = { bg: "#FFFFFF", surface: "#F1F4F9", ink: "#1B2433", primary: "#1F3A68", accent: "#E0A526", muted: "#5B6676" };
export const css = `
.slide { background:${T.bg}; color:${T.ink}; font-family:Arial; padding:64px 72px; display:flex; flex-direction:column; gap:28px }
h1 { font-size:60px; font-weight:800; line-height:1.1; color:${T.primary} }
h2 { font-size:40px; font-weight:700; line-height:1.15; color:${T.primary} }
.lead { font-size:26px; line-height:1.4; color:${T.muted} }
ul { display:flex; flex-direction:column; gap:16px; font-size:24px; line-height:1.35 }
.row { display:flex; gap:28px; flex:1 }
.card { flex:1; background:${T.surface}; border-radius:16px; padding:28px; display:flex; flex-direction:column; gap:10px }
.card h3 { font-size:26px; font-weight:700 }
.card p { font-size:21px; line-height:1.4; color:${T.muted} }
.num { font-size:60px; font-weight:800; color:${T.accent} }
.bar { width:72px; height:6px; background:${T.accent} }
.cover { background:${T.primary}; color:#fff; justify-content:center }
.cover h1 { color:#fff; font-size:64px } .cover .lead { color:#DDE5F0 }
table { border-collapse:collapse; font-size:21px } th { background:${T.primary}; color:#fff; text-align:left }
th, td { padding:10px 16px; border-bottom:1px solid #D5DBE3 }
`;

const Cover = ({ title, sub, meta }) => (
  <Slide className="cover">
    <div className="bar"/>
    <h1>{title}</h1>
    <p className="lead">{sub}</p>
    <p className="lead">{meta}</p>
  </Slide>
);
const Bullets = ({ title, items, notes }) => (
  <Slide notes={notes}>
    <h2>{title}</h2>
    <ul>{items.map((t) => <li key={t}>{t}</li>)}</ul>
  </Slide>
);
const Cards = ({ title, cards }) => (
  <Slide>
    <h2>{title}</h2>
    <div className="row">
      {cards.map((c) => (
        <div className="card" key={c.t}>
          {c.v && <div className="num">{c.v}</div>}
          <h3>{c.t}</h3>
          <p>{c.body}</p>
        </div>
      ))}
    </div>
  </Slide>
);
const ChartSlide = ({ title, chart, points }) => (
  <Slide>
    <h2>{title}</h2>
    <div className="row">
      <Chart {...chart} colors={[T.primary, T.accent]} fontSize={18} style={{ flex: 2 }}/>
      <div className="card"><ul>{points.map((p) => <li key={p}>{p}</li>)}</ul></div>
    </div>
  </Slide>
);
const Table = ({ title, rows }) => (
  <Slide>
    <h2>{title}</h2>
    <table>
      <thead><tr>{rows[0].map((h) => <th key={h}>{h}</th>)}</tr></thead>
      <tbody>{rows.slice(1).map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
    </table>
  </Slide>
);

export default function Deck() {
  return <>
    <Cover title="Q3 review" sub="Revenue up, churn down: what worked" meta="Finance team · Oct 2026"/>
    <Bullets title="Sales doubled in 2024" items={["Concrete fact, number or example", "…"]}/>
    <Cards title="Three wins" cards={[{ v: "38%", t: "Faster tickets", body: "…" } /* 2–4 */]}/>
    <ChartSlide title="Revenue by year (USD M)" chart={{ type: "column", categories: ["2023", "2024"],
      series: [{ name: "Revenue", values: [120, 260] }], legend: "none" }} points={["Insight the chart proves"]}/>
    <Table title="Plans compared" rows={[["Plan", "Price", "Seats"], ["Team", "$20", "10"]]}/>
  </>;
}
```

Other layouts are a few lines each in the same way: two columns (`.row` with two `.card`), steps (`.row` of numbered
cards), quote (one big `<p>`), section (`Slide` with `cover` class and a number), closing (like the cover).

## What makes a deck good (every deck)

- **Count**: exactly the number of slides the user asked for, cover and closing included (default 10).
- **Arc**: cover → 1 agenda or context slide → body → takeaway/recommendation → closing. 15+ slides: add section slides.
- **Variety**: never more than 2 bullet slides in a row. Numbers → big numbers or a chart; comparisons → two columns or
  a table; processes/history → steps; 2–4 parallel ideas → cards.
- **Density**: every body slide carries specifics (names, numbers, dates, examples), not generic phrases. Titles are
  short claims ("Sales doubled in 2024"), not labels ("Sales"). ≤ 6 bullets, each ≤ 2 lines.
- **Truth**: real numbers from research or the user; never invent statistics. Say "approx." when unsure. Facts only
  the user can know (their team, prices, results, dates, targets, contacts) that they did not give: write a clearly
  marked placeholder in their language, e.g. `[Tên CEO]`, `[X tỷ VND]`, `[ngày áp dụng]`, never a made-up value, and
  list in your answer what they need to fill in.
- Write in the user's language (Vietnamese text is fine in every theme).

## Designed decks: illustrations, shapes, photos

When the user asks for a designed or illustrated look (a template feel, a playful lesson, a brand style, a pitch),
write your own components and CSS from a design brief instead of the plain layouts.

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

- **Illustrations and icons**: `office.art_search("fish")` lists artwork names; `office.art("fish", out="/work/<name>/assets/fish.svg",
  tint=("#9EEFBC", "#1E2A8A"))` saves one as SVG in the deck's colours (light parts, dark parts); no tint keeps its own
  colours. `kind="icon"` gives one-colour line icons (`color="#9EEFBC"`). Thousands exist: objects, animals, plants,
  buildings, vehicles, weather, food, people, symbols. Save them all in ONE `office_run`, then `<Art src=...svg/>`.
- **Waves, blobs, bands, custom drawings**: inline `<svg>` in the JSX (a component, e.g. `<Wave/>`), placed with CSS;
  decorations may run off the slide edge (it clips them), text stays inside.
- **Photos**: only when the user wants them; `web_download` a free-licence photo, then crop/grayscale it with Pillow.
- Repeat a motif and the palette on every slide; 2–4 accent colours at most; big headings; plenty of space.
- Keep text clear of decorations: a heading box tall enough for two lines, and cards below the heading's box.
- Readable from the back of a room: body ≥ 24 px (32 px for a talk), headings ≥ 44 px, text contrast at least 4.5:1;
  one idea per slide and about a third of it empty (the `slide-design-brief` skill has the full rules and sources).
- ONE `office_run` that saves all the artwork, then ONE `write` of the whole .jsx, then `office_build`.

## React deck (.jsx): complete reference, there is nothing else to look up (designed example)

A React module: CSS lays the slides out (flex, grid, gap, padding), a browser measures every text box, and the build
turns each box into a real PowerPoint shape, text box, picture or chart (all editable). Write components once and
reuse them; never compute coordinates.

```jsx
import { Slide, Art, Chart } from "deck";

export const css = `
.slide { background:#F2F4F6; color:#191F28; font-family:Arial; padding:64px; display:flex; flex-direction:column; gap:32px }
h1 { font-size:60px; font-weight:800; color:#3182F6 }
h2 { font-size:44px; font-weight:700 }
.lead { font-size:28px; color:#4E5968 }
.row { display:flex; gap:32px; flex:1 }
.card { flex:1; background:#fff; border-radius:24px; padding:32px; display:flex; flex-direction:column; gap:12px }
.card h3 { font-size:30px; font-weight:700 }
.card p { font-size:24px; line-height:1.4; color:#4E5968 }
.big { font-size:72px; font-weight:800; color:#3182F6 }
.wave { position:absolute; left:0; bottom:0; width:1280px; height:120px }
`;

const Wave = () => <svg className="wave" viewBox="0 0 1280 120"><path d="M0 60 C320 0 640 120 1280 40 V120 H0Z" fill="#3182F6" opacity=".15"/></svg>;
const Card = ({ icon, title, children }) => (
  <div className="card"><Art src={icon} style={{ width: 56, height: 56 }}/><h3>{title}</h3><p>{children}</p></div>
);

export default function Deck() {
  return <>
    <Slide notes="Speaker notes for this slide."><h1>Helpy Code</h1><p className="lead">One line that says why.</p><Wave/></Slide>
    <Slide>
      <h2>Three problems</h2>
      <div className="row">{problems.map((p) => <Card key={p.t} icon={p.icon} title={p.t}>{p.body}</Card>)}</div>
      <Wave/>
    </Slide>
    <Slide>
      <h2>Pilot results</h2>
      <div className="row">
        <div className="card"><div className="big">38%</div><h3>Faster tickets</h3></div>
        <Chart type="column" categories={["W1","W2","W3","W4"]} series={[{ name: "PRs", values: [42,51,60,68] }]}
               colors={["#3182F6"]} legend="none" fontSize={18} style={{ flex: 2, background: "#fff", borderRadius: 24 }}/>
      </div>
    </Slide>
  </>;
}
const problems = [{ t: "Security", icon: "/work/helpy/assets/lock.svg", body: "…" } /* … */];
```

- Every slide is a `<Slide>` (1280×720 px; `bg`, `notes`). Sizes are px. Text: `h1`–`h3`, `p`, `div`, `li`; inline
  `<b>`, `<i>`, `<span style={{color}}>` keep their style in PowerPoint. `<Art src>` places an .svg/.png/.jpg; inline
  `<svg>` becomes a picture; `<Chart>` becomes a real chart (`type`: column, bar, line, area, pie, doughnut, scatter;
  `labels="percent"`, `"category,percent"` or `"value"` writes data labels on it; a pie stays round in any box).
- Carried into PowerPoint: background colours, borders, border-radius, opacity, font family/size/weight/style/colour,
  text-align, line-height, letter-spacing, uppercase, pictures, charts, speaker notes. **Not carried** (the build says so):
  gradients and background images (use an `<Art>` picture), box-shadow, transforms, CSS animation.
- `office_build(source="/work/<name>.jsx")` → `/work/<name>.pptx` and `/work/<name>.html` (the preview). It reports
  JSX errors with their line, and text under 18 px. Fix the .jsx and build again.

Fonts: the file names a family; PowerPoint uses it if the viewer has it (preview and screenshots use what the sandbox
has). Safe for every viewer: Arial, Calibri, Georgia, Segoe UI, Verdana. Vietnamese text works in all of them. Do not
list or test the sandbox's fonts.

## Editing

- A deck you built (it has a `.jsx` source, or an older `.deck` folder): change the source, never the .pptx: `edit`
  the .jsx (or the slide/design.xml files of a .deck folder), then `office_build` once. Never inspect or patch the
  built .pptx with bash, officecli or office_run.
- A .pptx the user brought (no source): one `office_run` script does the whole job. Find what to change
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
