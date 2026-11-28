---
name: xlsx
label: Excel
description: "Create, read and edit spreadsheets (.xlsx, .csv): workbooks with formulas, formatting, charts, dashboards, data cleanup."
license: Complete terms in LICENSE.txt
version: 8
---

# Spreadsheets

**Create or edit** = ONE `office_run` script (officecli through `office`). It writes cells, formulas, formats, tables
and charts, calculates every formula and stores its value, then checks the file: formula errors (`#DIV/0!`,
`#REF!`…) and formulas it cannot evaluate come back in the result. Fix the script, run again. Aim: 2–4 turns.

**Research:** only what the content needs (the web tools say how); the user's own material comes first.

**Done rule:** after a clean run, look once (`print(d.view("text", range="Sales!A1:F12"))` or the screenshot the
script took) and answer. Never unpack the file or re-check it another way.

```python
d = office.create("/work/sales.xlsx")                    # office.open(path) to edit one the user brought
d.set("/Sheet1", name="Sales")
S = "/Sales"
d.set(f"{S}/A1", value="Sales 2025", font__bold=True, font__size=16)
for i, h in enumerate(["Month", "Revenue", "Cost", "Profit", "Margin"]):
    d.set(f"{S}/{'ABCDE'[i]}3", value=h, font__bold=True, fill="1F3A68", font__color="FFFFFF")
for r, (m, rev, cost) in enumerate(rows, start=4):         # rows: from the user or your research
    d.set(f"{S}/A{r}", value=m)
    d.set(f"{S}/B{r}", value=rev, numberformat="$#,##0")
    d.set(f"{S}/C{r}", value=cost, numberformat="$#,##0")
    d.set(f"{S}/D{r}", formula=f"B{r}-C{r}", numberformat="$#,##0")
    d.set(f"{S}/E{r}", formula=f"IFERROR(D{r}/B{r},0)", numberformat="0.0%")
last = 3 + len(rows)
d.set(f"{S}/A{last + 1}", value="Total", font__bold=True)
for c in "BCD":
    d.set(f"{S}/{c}{last + 1}", formula=f"SUM({c}4:{c}{last})", numberformat="$#,##0", font__bold=True)
d.add(S, "table", ref=f"A3:E{last}", style="TableStyleMedium2", name="SalesTable")
d.add(S, "chart", chartType="column", title="Revenue vs cost", dataRange=f"Sales!A3:C{last}", anchor="G3:N18")
for c, w in zip("ABCDE", (14, 12, 12, 12, 10)):
    d.set(f"{S}/col[{c}]", width=w)
d.set(S, freeze="A4")
print(d.view("text", range=f"Sales!A1:E{last + 1}"))
d.screenshot(sheet="Sales")                               # each sheet you want to see: one screenshot each
```

- Cells: `value=`, `formula=` (no leading `=`), `numberformat=`, `font__bold/italic/size/color/name`, `fill=`,
  `alignment__horizontal=`, `alignment__wrapText=True`, `border__all="thin"`, `merge="A1:E1"`.
- Sheets: `d.add("/", "sheet", name="North")`, rename with `d.set("/Sheet1", name=...)`, `freeze=`, `tabColor=`.
- Tables (`table`), charts (`chart`: column, bar, line, area, pie, doughnut, scatter, combo…), conditional formatting
  (`conditionalformatting`), data validation (`validation`), named ranges (`namedrange`), pivot tables (`pivottable`),
  sparklines (`sparkline`): `print(office.help("xlsx", "chart"))` lists every property; look it up before guessing.
- Lots of data: read it with `pandas`, then write the cells in a loop; edits are batched, so thousands are fine.
  Import a CSV in one call: `d.import_csv("/Sales", "/work/data.csv", header=True)`.
- Formulas: any Excel function works, `XLOOKUP`, `FILTER`, `TEXTJOIN`… included (officecli writes the prefixes and
  spill metadata Excel needs and calculates them).

**Read** a workbook: `office_read(path, view="text")` (cells with values) or `view="outline"`; a region:
`d.view("text", range="Sheet1!A1:F20")`. **Edit** one the user brought: `office.open`, then change only what was asked;
keep its fonts, colours and input cells.

## A workbook worth handing over

- **A Summary/Dashboard sheet first** for 3+ sheets: key totals pulled by formulas from the detail sheets
  (`'North'!B14`), one or two charts.
- **Every number is a formula or a labeled input.** Totals, growth, margins, shares: formulas, never Python results.
- **Real data** from the user or research; if you must assume, put assumptions in labeled input cells (blue text).
- **Follow the user's spec literally**: exact tab names, headers and formulas they named.
- **Editing an existing file: match its conventions** (fonts, colors, input cells) and leave its formulas alone.
- One table per sheet starting at A1 (or A3 under a title), header row styled, frozen panes, number formats on every
  numeric column, column widths that fit, a chart where a trend or comparison matters. Sheet names short, no special
  characters.

**A clean run proves your formulas *evaluate*, not that they are *right*.** An off-by-one range or a reference to the
wrong row yields an error-free file with wrong numbers. Print the region you built and check that the numbers make
sense before you answer. A formula listed as "not evaluated" (a link to another workbook, a rare function) keeps no
value until Excel opens the file: leave it, and tell the user.

## Financial models

Unless the user says otherwise, or the existing file already does something else.

**Color:** blue text (`0000FF`) for hardcoded inputs and scenario levers · black for formulas · green (`008000`) for
links to another sheet · red (`FF0000`) for links to another file · yellow fill (`FFFF00`) for key assumptions and
cells the user should fill in.

**Numbers:** currency `$#,##0`, with the unit named in the header (`Revenue ($mm)`) · zeros render as `-`, including
in percentages (`$#,##0;($#,##0);-`) · negatives in parentheses · percentages `0.0%`, **stored as fractions** (`0.15`
renders `15.0%`; storing `15` renders `1500.0%`) · valuation multiples `0.0x` · years as text (`"2024"`, never
`2,024`).

**Structure:** every assumption in its own labeled cell, referenced by the formulas that use it (`B5*(1+$B$6)`, never
`B5*1.05`) · formulas consistent across every projection period, since a lone edited cell mid-row is the commonest
silent error · guard denominators that can be zero.

## Dependencies

officecli (through `office_run`, `office_read`) · `pandas` for reading data (preinstalled)
