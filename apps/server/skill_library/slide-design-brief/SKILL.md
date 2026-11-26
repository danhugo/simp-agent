---
name: slide-design-brief
label: Slide design brief
description: "Write a designer's description of how a deck should look: mood, palette with hex codes, fonts, illustration and photo style, decorations, slide-by-slide composition. From a vague idea (\"make it look like a Canva template\"), a topic, a brand, or a reference picture or deck. The user reads and edits it, then it builds the deck. Use when the user wants to describe, plan or copy a slide style, or asks for a design prompt."
license: MIT
source: simp
version: 1
---

# Slide design brief

Turn what the user has (a topic, a few words of style, a brand, a reference) into a **design description** concrete
enough that two designers would build the same deck from it. The user reads it, changes what they like, then says
"make it": build it with the `pptx` skill (designed decks, free layout).

## 1. Gather (no questions unless nothing is given)

- **From words**: topic, audience, the style words they used ("cute", "luxury", "Canva", "minimal").
- **From a reference picture**: `read` it once and ask the look helper for palette (hex), fonts, motifs, layout habits.
- **From a reference deck** (.pptx): one `office_run`: `print(office.open(p).view("outline"))` and
  `office.open(p).screenshot(grid=True)`; describe what the look helper sees. Describe it; never copy its text or images.
- **From a brand**: their colours, logo colours, tone; else infer from the business type.

Fill every gap yourself from the topic and audience: a brief with "TBD" is not a brief.

## 2. Write the brief (in the user's language), in this order

1. **One-paragraph description**: the whole look in 4–6 sentences, written like a prompt to a designer. This is the
   part users copy and reuse. Example:
   > A bold flat-illustration lesson deck. Royal-blue background (#4352BE) on every slide, navy (#1E2A8A) and mint
   > (#9EEFBC) as the only accents. Big uppercase sans-serif headings in mint. Flat two-tone illustrations of factories,
   > fish, coral and a globe; wavy mint bands along the top or bottom edge and navy blobs bleeding off two corners.
   > Black-and-white photos cropped into circles for contrast. Generous space, never more than 3 ideas per slide.
2. **Palette**: 4–5 swatches with role and hex: background, dark, accent 1, accent 2, text. Check text contrast.
3. **Type**: heading (family, case, weight, size about 44–64 px) and body (family, ≥ 20 px). Prefer fonts every viewer
   has: Arial, Calibri, Georgia, Segoe UI, Verdana.
4. **Motifs**: 5–8 subjects from the topic, one drawing style (two-tone flat in the palette, line icons, or photos) and
   one shape language (waves, blobs, circles, angles, paper tape...).
5. **Decoration rules**: where decorations sit, how many per slide (2–4), what bleeds off the edges, that text never
   sits on them.
6. **Images**: none, or one treatment kept on every slide.
7. **Slide plan**: one line per slide: what it says + its composition (e.g. "3 · Three causes — 3 cards with an icon
   each, wave band at the bottom").

Keep it to about one screen. Put it in the chat; also save it to `/work/<name>-brief.md` when it is long or the user
will reuse it.

## 3. After

End with one line: "Reply 'make it' or tell me what to change." On "make it": build with the `pptx` skill, following
the brief exactly (palette, motifs, decoration rules, slide plan). On changes: edit the brief, show only what changed.

## Design rules every brief follows

From Duarte, Presentation Zen (Garr Reynolds), Microsoft's PowerPoint guidance and university accessibility guides
(Manchester, Oxford, Berkeley). Sizes are px on the 1280×720 canvas (1 pt = 1.33 px).

- **Glance test** (Duarte): each slide's point is clear in 3 seconds. One idea per slide; the title states it.
- **Signal over noise** (Reynolds): every element serves the point; decoration frames the content, never competes.
  Contrast, repetition, alignment, proximity: one margin (about 64 px) and one grid on every slide.
- **Type**: body ≥ 32 px for a talk (24 pt), never under 24 px (18 pt); headings ≥ 44 px. At most 2 families
  (one for headings, one for body). Sans-serif for body text. No all-caps or italics for body text; caps only for short
  headings and labels.
- **Colour**: 3–4 colours in all. 60-30-10: about 60% the dominant colour (usually the background), 30% a secondary,
  10% the accent for what matters. Text contrast WCAG AA: 4.5:1 for body, 3:1 for big headings (check it: compute the
  contrast ratio of each text/background pair in Python before you commit to the palette). Never carry meaning by
  colour alone: label chart series and states.
- **Backgrounds**: subtle and the same on every slide (Microsoft); the theme never pulls focus from the message.
- **Whitespace**: leave about a third of each slide empty; group related things close, unrelated things apart.
- **Fit the audience**: playful for kids and cafés, restrained for finance and medicine; specific beats pretty
  (hex codes, sizes, counts, positions; "modern and clean" says nothing).
