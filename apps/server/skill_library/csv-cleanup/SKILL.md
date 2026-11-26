---
name: csv-cleanup
label: CSV & data cleanup
description: "Clean messy tabular data: fix encodings, headers, dates, numbers, duplicates, whitespace, split/merge columns, join files, and export a tidy CSV/Excel. Use when the user's data is messy or needs reshaping."
license: MIT
source: simp
version: 1
---

# CSV & Data Cleanup

Never overwrite the original. Write `<name>_clean.csv` (or .xlsx) and a short change log.

## 1. Diagnose

```bash
file data.csv; head -5 data.csv; wc -l data.csv
```
```python
import pandas as pd
df = pd.read_csv("data.csv", sep=None, engine="python", encoding="utf-8-sig", dtype=str)  # sniff delimiter, keep raw text
print(df.shape, list(df.columns)); print(df.head(15).to_string())
for c in df.columns: print(c, df[c].nunique(), df[c].isna().sum(), df[c].dropna().head(5).tolist())
```
Look for: header not on row 1, merged/multi-row headers, totals rows, mixed date formats, numbers stored as text (`1.234,5`, `$1,200`, `(300)`), stray spaces, inconsistent categories ("HN", "Ha Noi", "Hà Nội"), duplicates, mojibake (`Ã©` → re-read as utf-8 or fix with `.encode("latin-1").decode("utf-8")`).

## 2. Clean (pandas recipes)

- Columns: `df.columns = df.columns.str.strip().str.lower().str.replace(r"\W+", "_", regex=True)`
- Whitespace: `df = df.apply(lambda s: s.str.strip() if s.dtype == object else s)`
- Numbers: strip currency/thousand separators, `(x)` → `-x`, then `pd.to_numeric(errors="coerce")`. Decide the decimal separator from the data (Vietnamese/European files often use `.` for thousands and `,` for decimals).
- Dates: `pd.to_datetime(s, errors="coerce", dayfirst=True)` when the data is day-first (check values > 12 in first position). Count NaT created.
- Categories: build an explicit mapping dict; show it to the user; fuzzy candidates via `difflib.get_close_matches`.
- Duplicates: `df.duplicated(subset=keys, keep="first")`; report how many and on which keys.
- Missing: leave as blank unless the user wants a fill rule; never invent values.
- Reshape: `melt` (wide → long), `pivot_table` (long → wide), `str.split(expand=True)`, `explode`.
- Join: `pd.merge(a, b, on=key, how="left", validate="m:1", indicator=True)`; report unmatched rows.

## 3. Validate and report

- Row counts before/after, per step.
- Rows that failed parsing → save to `<name>_issues.csv` with a reason column.
- Print `df.dtypes` and a 10-row sample of the result.

Export: `df.to_csv(out, index=False, encoding="utf-8-sig")` (the BOM makes Excel open UTF-8 correctly). For a formatted Excel output use the `xlsx` skill.

Tell the user: what changed (bullet list with counts), where the clean file and issues file are, and any decisions they should confirm.
