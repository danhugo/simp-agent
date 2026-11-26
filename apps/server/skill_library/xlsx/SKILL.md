---
name: xlsx
label: Excel
description: "Create, read and edit spreadsheets (.xlsx, .csv): workbooks with formulas, formatting, charts, dashboards, data cleanup."
license: Complete terms in LICENSE.txt
version: 6
---

# Spreadsheets

**Create** = write ONE Python source `/work/<name>.xlsx.py`, then `office_build(source="/work/<name>.xlsx.py")`.
It runs the script, stores calculated values (officecli), and checks every formula and column: problems come back
as `Sheet!Cell: what is wrong`. Fix the script, build again. Aim: 3–5 turns for a 10-sheet workbook.


**Research budget:** at most TWO messages of research in total: one of parallel `web_search` calls (2–4 queries), then optionally one of parallel `web_fetch(url, prompt=...)` calls. Never fetch search-engine pages (google, bing, duckduckgo…), never retry failed fetches, never curl. Then write with what you have: mark uncertain figures "≈" or "approx." and name the source you did get.

**Done rule:** `office_build` already validates, recalculates and checks the file. When it says "No problems found", answer the user right away. Never unpack, render, re-open or re-check the built file yourself, and never run other checks after a clean build.

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
brought: one `office_run` script, e.g. `d = office.open(p)`, then `for r in range(2, 20): d.set(f"/Sheet1/D{r}",
formula=f"B{r}*C{r}")`, `print(d.view("text", range="Sheet1!A1:D20"))`; or load it with openpyxl in a `.xlsx.py`
that saves to OUT for a big restructure.
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

openpyxl writes formulas as strings with **no cached values**: until something calculates them, every formula cell
reads back as `None` to `pandas`, `load_workbook(data_only=True)` and most previewers. `office_build` and `office_run`
store the values for you (officecli calculates when it writes). For a file you saved with openpyxl yourself, one
`office_run` with any edit stores them, and `view issues` lists every formula error (`#DIV/0!`, `#REF!`…) and every
formula it cannot evaluate:

```python
d = office.open("/work/model.xlsx"); d.set("/sheet[1]/XFD1", value="x"); d.remove("/sheet[1]/XFD1")
print(d.view("issues"))
```

**A clean file proves your formulas *evaluate*, not that they are *right*.** An off-by-one range or a reference to
the wrong row yields an error-free file with wrong numbers. Write 2–3 formulas first and check they pull the values
you expect (`print(d.view("text", range="Sheet1!A1:F10"))`), before building out a grid.

A formula listed as "not evaluated" (a function officecli lacks, or a link to another workbook) keeps no value until
Excel opens the file: leave it, and tell the user.

## Choosing formulas that survive verification

- **Prefer widely supported functions**: `SUMIFS`, `INDEX`, `MATCH`, `XLOOKUP`, `IFERROR`, `SUMPRODUCT`, `TEXTJOIN`.
- **Post-2007 functions need an `_xlfn.` prefix** when written with openpyxl (it writes the formula verbatim; Excel
  stores those names prefixed and hides it): `_xlfn.XLOOKUP`, `_xlfn.TEXTJOIN`, `_xlfn.IFS`, `_xlfn.MAXIFS`… Written
  bare, Excel shows `#NAME?`.
- **Avoid spilling functions** (`SORT`, `FILTER`, `UNIQUE`, `SEQUENCE`): an openpyxl-written file has no spill
  metadata, so only the top-left cell fills. Sort, filter and de-duplicate in Python before writing the cells.

## openpyxl gotchas

- **Reading a model takes two loads.** `data_only=True` yields cached values with the formulas gone; the default yields formula strings with no values. One pass cannot give you both.
- **`data_only=True` is destructive if you save.** That workbook has no formulas left, so saving replaces every one with a literal — permanently.
- **`data_only=True` on a file openpyxl just wrote returns `None` everywhere** — store the values first (above). (A formula whose result is `""` also reads back as `None`.)
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

`openpyxl`, `pandas`, `markitdown` (pip, preinstalled) · officecli (through `office_build`, `office_read`, `office_run`)
