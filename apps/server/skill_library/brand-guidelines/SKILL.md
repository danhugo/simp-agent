---
name: brand-guidelines
label: Brand guidelines
description: "Apply a company's brand (colours, fonts, logo, tone) consistently to documents, slides, spreadsheets, charts and web pages; or help write a brand style guide. Use when the user mentions brand, style guide, corporate look, or company template."
license: Apache-2.0 (see LICENSE.txt)
source: https://github.com/anthropics/skills/tree/main/skills/brand-guidelines
version: 1
---

# Brand Guidelines

## 1. Get the brand

In order of preference:
1. A brand file the user gave (PDF style guide, .pptx/.docx template, logo) in `/work`: extract colours (hex), fonts, logo and rules. For images, `magick logo.png -colors 6 -unique-colors txt:-` lists the main colours.
2. A brand saved earlier in memory.
3. The user's website: `web_fetch(url, prompt="list brand colours (hex), fonts and tone of voice")`.
4. Ask. If the user has none, propose one (below) and get approval.

Save the result as a brand card in memory (so later chats reuse it) and/or `/work/brand.md`:

```markdown
# <Company> brand
Colours: Primary #...  Secondary #...  Accent #...  Dark text #...  Light background #...
Fonts: Headings <font> (fallback Arial)  Body <font> (fallback Georgia)
Logo: /work/brand/logo.png (min width, clear space, light/dark versions)
Tone: 3 adjectives + 2 do / 2 don't examples
```

## 2. Apply it

- **Text colour:** dark text on light backgrounds; check contrast (≥ 4.5:1 for body text).
- **Headings** in the heading font, **body** in the body font. If the font is not installed (Office files on other PCs), name the font anyway and give a safe fallback (Arial / Georgia / Calibri).
- **Accents:** primary for key shapes/titles, secondary and accent for highlights and chart series, in a fixed order.
- **Charts:** series colours in brand order, grey for "other"/context, no rainbow defaults.
- **Slides/docs:** logo in a fixed spot (e.g. title slide + footer), same margins everywhere, brand colours for headers and table header rows.
- **Web:** put colours and fonts in CSS custom properties (`--brand-primary`, …) once.
- **Tone:** rewrite copy to match the brand adjectives.

For .docx/.pptx/.xlsx use the office skills and `office_build`; pass the brand values into the script as constants at the top.

## 3. Proposing a brand from scratch

Give 2–3 options, each: name, 5 hex colours with roles, a heading + body font pair (Google Fonts), and the mood in one sentence. Ground each in the company's industry and audience; avoid generic defaults (cream + terracotta, black + neon green).

## Writing a style guide

Sections: brand story (1 paragraph), logo usage, colour palette (hex/RGB/CMYK), typography scale, imagery, tone of voice with examples, templates. Deliver as a document via the docx skill or Markdown.
