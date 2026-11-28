---
name: spreadsheet-formulas
label: Spreadsheet formulas
description: "Write and explain Excel / Google Sheets formulas: lookups (XLOOKUP, INDEX/MATCH), conditional sums, dates, text, dynamic arrays, pivot-style summaries, conditional formatting rules, fixing #N/A/#VALUE errors."
license: MIT
source: simp
version: 2
---

# Spreadsheet Formulas

Ask (or infer) the app: **Excel 365**, older Excel (no dynamic arrays / XLOOKUP before 2021), or **Google Sheets**. Ask the decimal/argument separator only if the user's locale uses `;` (Vietnamese/European Excel often does: then write `=IF(A2>0;"Yes";"No")`).

## Answer format

1. The formula, ready to paste, for the user's real cell references.
2. One line saying where to put it and whether to fill down.
3. A short breakdown of how it works.
4. Edge cases (blanks, errors) handled or noted.

If the user gave a file, test it on a copy with one `office_run`: `d = office.open(copy)`, `d.set("/Sheet1/F2",
formula="…")` (no leading `=`), then `print(d.view("text", range="Sheet1!A1:F10"))`: officecli calculates it and
reports errors. Or reproduce the logic with pandas to check the expected result.

## Core patterns

| Need | Excel 365 / Sheets | Older Excel |
|---|---|---|
| Lookup | `=XLOOKUP(A2,Prices[SKU],Prices[Price],"Not found")` | `=IFERROR(INDEX(C:C,MATCH(A2,A:A,0)),"Not found")` |
| Two-key lookup | `=XLOOKUP(1,(T[Region]=F2)*(T[Month]=G2),T[Sales])` | `INDEX/MATCH` with helper key column |
| Conditional sum | `=SUMIFS(Sales,Region,"North",Date,">="&DATE(2026,1,1))` | same |
| Count unique | `=COUNTA(UNIQUE(A2:A500))` | `=SUMPRODUCT(1/COUNTIF(A2:A500,A2:A500))` (no blanks) |
| Filter rows | `=FILTER(A2:D500,C2:C500>1000,"none")` | AutoFilter / helper column |
| Sort | `=SORT(A2:D500,4,-1)` | Data → Sort |
| Top N | `=TAKE(SORT(A2:B500,2,-1),5)` (365) | `LARGE` + `INDEX/MATCH` |
| Text join | `=TEXTJOIN(", ",TRUE,A2:A10)` | `CONCATENATE` / `&` |
| Split text | `=TEXTSPLIT(A2," ")` (365), `=SPLIT(A2," ")` (Sheets) | Text to Columns |
| Clean text | `=TRIM(CLEAN(A2))`, `=PROPER(A2)` | same |
| Workdays between | `=NETWORKDAYS(A2,B2,Holidays)` | same |
| Month end / add months | `=EOMONTH(A2,0)`, `=EDATE(A2,3)` | same |
| Age / tenure | `=DATEDIF(A2,TODAY(),"y")` | same |
| Running total | `=SUM($B$2:B2)` | same |
| Tiered rate | `=XLOOKUP(A2,Tiers[Min],Tiers[Rate],,-1)` | `=VLOOKUP(A2,Tiers,2,TRUE)` (sorted) |
| Reusable calc | `=LET(x,A2*B2,IF(x>100,x*0.9,x))` | repeat expression |

Sheets-only extras: `QUERY(A:D,"select A, sum(D) where B='North' group by A")`, `ARRAYFORMULA`, `IMPORTRANGE`.

## Good practice

- Use Tables / named ranges instead of `A:A` full columns on big sheets (speed).
- Absolute refs (`$A$1`) for constants; put assumptions in labelled input cells, not inside formulas.
- Prefer `IFERROR` only around the part that can fail, so real errors still show.
- Avoid volatile functions (`INDIRECT`, `OFFSET`, `TODAY` in many cells) on large models.

## Fixing errors

- `#N/A`: lookup value missing; check extra spaces (`TRIM`), numbers stored as text (`--A2` or `VALUE`), exact match flag.
- `#VALUE!`: text in math, wrong separator, date stored as text (`DATEVALUE`).
- `#REF!`: deleted rows/columns referenced. `#DIV/0!`: wrap with `IF(B2=0,"",A2/B2)`.
- `#SPILL!`: something blocks the output range of a dynamic array.
- Wrong totals: check hidden rows, text-numbers, mixed units.

## Conditional formatting

Give the rule as a formula relative to the top-left cell of the range, e.g. range `A2:F200`, rule `=$F2<TODAY()` to highlight overdue rows.

For building whole workbooks, dashboards or models, use the `xlsx` skill.
