---
name: xlsx
label: Excel
description: "Create, read and edit spreadsheets (.xlsx, .csv): workbooks with formulas, formatting, charts, dashboards, data cleanup."
license: Complete terms in LICENSE.txt
---

# Spreadsheets

**Create** = write ONE Python source `/work/<name>.xlsx.py`, then `office_build(source="/work/<name>.xlsx.py")`.
It runs the script, stores calculated values (LibreOffice), and checks every formula and column: problems come back
as `Sheet!Cell: what is wrong`. Fix the script, build again. Aim: 3–5 turns for a 10-sheet workbook.


**Research budget:** at most TWO messages of research in total: one of parallel `web_search` calls (2–4 queries), then optionally one of parallel `web_fetch(url, prompt=...)` calls. Never fetch search-engine pages (google, bing, duckduckgo…), never retry failed fetches, never curl. Then write with what you have: mark uncertain figures "≈" or "approx." and name the source you did get.

**Done rule:** `office_build` already validates, recalculates and checks the file. When it says "No problems found", answer the user right away. Never unpack, render, re-open or re-check the built file yourself, and never run recalc.py or other checks after a clean build.

```python
import os, sys; sys.path.insert(0, "/opt/simp/skills/xlsx/scripts")
from xlsx_kit import Book                       # styled tables + charts, every openpyxl chart gotcha handled
b = Book("navy")                                # navy | ocean | forest | mono
ws = b.sheet("Sales")                           # one call per sheet, in tab order
b.title(ws, "Sales 2025", "USD, monthly")       # optional heading in A1/A2 → start tables at "A4"
first, last = b.table(ws, ["Month", "Revenue", "Cost", "Profit", "Margin"], rows, start="A4",
                      formats=[None, "usd", "usd", "usd", "pct"],         # usd money money2 int num pct date x vnd
                      formulas={"Profit": "=B{r}-C{r}", "Margin": "=IFERROR(D{r}/B{r},0)"},   # {r} = row number
                      total=["Revenue", "Cost", "Profit"])               # SUM row under the table
b.chart(ws, "column", "Revenue vs cost", cats="A", series=["B", "C"], at="H4", header_row=first, last_row=last)
b.save()                                        # saves to os.environ["OUT"]; never pick your own path
```

Complete API (do not read the module): `Book(theme="navy", font="Arial")` · `sheet(title, tab=None, index=None)`
(`index=0` = first tab) · `title(ws, text, sub=None)` · `table(ws, headers, rows, start="A1", formats=None,
formulas=None, total=False, widths=None, freeze=True)` → (header_row, last_row) · `chart(ws, kind, title, cats,
series, at, header_row=1, last_row=None, y_title=None, x_title=None, width=18, height=9, stacked=False,
data_ws=None)` · `note(ws, cell, text)` · `save()`.

`b.wb` is the openpyxl Workbook for anything else (conditional formatting, data validation, merged headers).
Chart kinds: column, bar, line, area, pie, donut, scatter; `data_ws=` charts a table on another sheet.

**Read** a workbook: `office_read(path, view="text")` (cells with values) or `view="outline"`. **Edit** one the user
brought: `office_read(view="annotated")`, then `office_edit(path, ops=[{"command":"set","path":"/Sheet1/B5",
"props":{"value":"=SUM(B2:B4)"}}])`, or for larger edits load it with openpyxl in a `.xlsx.py` that saves to OUT.
For bulk data in or out use `pandas`.

## A workbook worth handing over

- **A Summary/Dashboard sheet first** for 3+ sheets: key totals pulled by formulas from the detail sheets
  (`='North'!B14`), one or two charts.
- **Every number is a formula or a labeled input.** Totals, growth, margins, shares: formulas, never Python results.
- **Real data** from the user or research; if you must assume, put assumptions in labeled input cells (blue text).
- **Follow the user's spec literally**: exact tab names, headers and formulas they named.
- **Editing an existing file: match its conventions** (fonts, colors, input cells) and leave its formulas alone.
- One table per sheet starting at A1 (or A4 under a title), header row styled, frozen panes, number formats on every
  numeric column, a chart where a trend or comparison matters. Sheet names short, no special characters.

## Recalculating by hand (editing an existing file)

openpyxl writes formulas as strings with **no cached values**. Until you recalculate, every
formula cell reads back as `None` to anything reading cached values — `pandas`,
`load_workbook(data_only=True)`, and most previewers.

```bash
python /opt/simp/skills/xlsx/scripts/recalc.py output.xlsx [timeout_seconds]   # default 30
```

LibreOffice computes the formulas **on a copy**, only their values go into your file, and you get JSON:
`status` (`success` | `errors_found`), `total_formulas`, `total_errors`, and an
`error_summary` naming up to 100 cells per error type (`locations_truncated` says how many it
withheld — trust `total_errors`, not the length of the list). Fix what it names and run it
again. **JSON with an `error` key instead of a `status` means nothing was recalculated**, and
only that case exits non-zero — `errors_found` exits 0, so never treat a clean exit as a clean
workbook.

**A green recalc proves your formulas *evaluate*, not that they are *right*.** An off-by-one
range or a reference to the wrong row yields a clean, error-free file with wrong numbers.
Write 2–3 formulas first and check they pull the values you expect, before building out a grid.

**`not_computed` lists formulas LibreOffice cannot evaluate, even on `success`**: a function it lacks
(`_xlfn.XLOOKUP`, `_xlfn.LET`…) or a link to another workbook (`='[1]Returns Analysis'!$B$2`). They
keep what they held: after an openpyxl save, nothing until Excel opens it. For their numbers sooner,
read the original with `data_only=True`; keep the formulas. A sound formula depending on a listed one,
directly or not, reports `#NAME?` too: leave it and tell the user. A cell that tests one
(`IFERROR(B1,0)`) gets LibreOffice's fallback, and a kept value may be stale: say so. After editing
sheet XML, delete each changed formula's `<v>`: a mistake that keeps its value is listed, not reported.

## Choosing formulas that survive verification

LibreOffice implements fewer functions than Excel, and a formula it cannot evaluate has no value
until Excel opens the file.

- **Prefer Excel-2007-era functions** — `SUMIFS`, `INDEX`, `MATCH`, `IFERROR`, `SUMPRODUCT` — which need no prefix.
- **Six post-2007 functions work, but only with an `_xlfn.` prefix**, because openpyxl writes your formula into the XML verbatim and Excel stores post-2007 names prefixed (its UI hides the prefix): `_xlfn.TEXTJOIN`, `_xlfn.CONCAT`, `_xlfn.IFS`, `_xlfn.SWITCH`, `_xlfn.MAXIFS`, `_xlfn.MINIFS`. Written bare, each yields `#NAME?`.
- **Never use `XLOOKUP`, `XMATCH`, `SORT`, `FILTER`, `UNIQUE`, or `SEQUENCE`.** The runtime's LibreOffice cannot evaluate them, and one that can fills only the top-left cell of their result, since an openpyxl-written file has no spill metadata. Use `INDEX`/`MATCH` for lookups, and sort, filter, and de-duplicate in Python before writing the cells.
- A missing `)` is reported as `unbalanced brackets`. Too few arguments (`=ROUND(A1)`) is not: LibreOffice returns a value, and Excel may offer to repair the file.

## openpyxl gotchas

- **Reading a model takes two loads.** `data_only=True` yields cached values with the formulas gone; the default yields formula strings with no values. One pass cannot give you both.
- **`data_only=True` is destructive if you save.** That workbook has no formulas left, so saving replaces every one with a literal — permanently.
- **`data_only=True` on a file openpyxl just wrote returns `None` everywhere** — run `recalc.py` first. (A formula whose result is `""` also reads back as `None`.)
- **Merged cells: write the top-left anchor only.** Every other cell in the range is a `MergedCell` whose `.value` is read-only.
- **`.xlsm` loses its macros unless you pass `keep_vba=True`** to `load_workbook`.
- **A sheet name containing a space must be quoted** in a cross-sheet reference: `='Assumptions Inputs'!$B$5`. Unquoted, it evaluates to `#VALUE!`.
- **Saving an upload drops its text boxes, shapes and slicers.** First search `xl/drawings/` for `<xdr:sp ` (with the space) and look for an `xl/slicers/` part; if found, tell the user or edit the sheet XML directly.
- **Nothing mends a malformed workbook**: an unclosed quote in a number format (`'0.00 "USD'`), a defined name starting with `=`, or duplicate or empty table headers are saved as written, and Excel may offer to repair the file.
- **Partly bold or italic cell text is flattened** unless `load_workbook(rich_text=True)`; such a `.value` is then a `CellRichText`, not a `str`.
- **Every new formula needs its own `number_format`** (date, %, currency): nothing infers it, so a date shows as `45337` and 30% as `0.3`.
- **On every new chart set `chart.roundedCorners = False`, `.overlay = False` on its legend and on each title you gave it (`chart.legend`, `chart.title`, `chart.x_axis.title`…), and, if it has axes (not pie or doughnut), `chart.x_axis.delete = False` and `chart.y_axis.delete = False`**, or Excel may draw the title or legend over the plot, round the frame, or draw no axes.
- **With a `DateAxis`, set `chart.y_axis.crossAx = 500`**, or Excel may offer to repair the file.

## Financial models

Unless the user says otherwise, or the existing file already does something else.

**Color:** blue text (`0,0,255`) for hardcoded inputs and scenario levers · black for formulas ·
green (`0,128,0`) for links to another sheet · red (`255,0,0`) for links to another file ·
yellow fill (`255,255,0`) for key assumptions and cells the user should fill in.

**Numbers:** currency `$#,##0`, with the unit named in the header (`Revenue ($mm)`) · zeros
render as `-`, including in percentages (`$#,##0;($#,##0);-`) · negatives in parentheses ·
percentages `0.0%`, **stored as fractions** (`0.15` renders `15.0%`; storing `15` renders
`1500.0%`) · valuation multiples `0.0x` · years as text (`"2024"`, never `2,024`).

**Structure:** every assumption in its own labeled cell, referenced by the formulas that use it
(`=B5*(1+$B$6)`, never `=B5*1.05`) · formulas consistent across every projection period, since a
lone edited cell mid-row is the commonest silent error · guard denominators that can be zero.

## Dependencies

`openpyxl`, `pandas`, `markitdown` (pip, preinstalled — install only if an import fails or the command is missing) · LibreOffice (`soffice`, auto-configured for sandboxed environments via `scripts/office/soffice.py`)
