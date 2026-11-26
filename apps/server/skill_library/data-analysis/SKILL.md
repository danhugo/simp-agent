---
name: data-analysis
label: Data analysis & charts
description: "Analyze tabular data (CSV, Excel, JSON) with pandas and make clear charts with matplotlib: summaries, trends, comparisons, pivots, simple statistics. Use when the user asks questions about their data or wants charts."
license: MIT
source: simp
version: 1
---

# Data Analysis & Charts

## Workflow

1. **Look first.** Load with pandas and inspect before answering:
   ```python
   import pandas as pd
   df = pd.read_csv(p)            # or read_excel(p, sheet_name=None) to see all sheets
   print(df.shape); print(df.dtypes); print(df.head(10)); print(df.isna().sum())
   print(df.describe(include="all").T.head(30))
   ```
   Big file? Read `nrows=5000` first. Encoding errors: `encoding="utf-8-sig"` or `"latin-1"`. Excel with header offsets: `header=2`.
2. **Restate the question** in measurable terms (metric, grouping, period, filter). If ambiguous, state your assumption and continue.
3. **Clean only what the question needs** (dtypes, dates `pd.to_datetime(errors="coerce")`, numbers with commas/currency, duplicates). Report how many rows you dropped and why. For heavy cleanup see the `csv-cleanup` skill.
4. **Compute** with groupby / pivot_table / resample. Keep a script in `/work/analysis/` so the result is reproducible.
5. **Sanity-check:** totals match the source, no double counting after joins (`validate="m:1"`), units, time zones, outliers.
6. **Answer** with the numbers first, then 2–4 key insights, caveats, and the chart/file paths.

## Charts (matplotlib)

- Pick the form from the question: change over time → line; compare categories → horizontal bar (sorted); part of whole → stacked bar (pie only for ≤ 4 parts); distribution → histogram/box; relationship → scatter.
- Title says the takeaway ("Sales rose 18% in Q3"), axes labelled with units, thousands separators, no 3D, no rainbow: one highlight colour + greys.
- Remove top/right spines; start bar axes at zero; direct labels beat legends.
```python
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(10, 5.5), dpi=150)
s.sort_values().plot.barh(ax=ax, color="#3b6ea8")
ax.set_title("Revenue by region, 2025 (USD m)", loc="left", fontweight="bold")
ax.spines[["top", "right"]].set_visible(False)
for c in ax.containers: ax.bar_label(c, fmt="{:,.1f}", padding=3)
fig.tight_layout(); fig.savefig("/work/analysis/revenue_by_region.png")
```
- **View the PNG** you saved (`read_file`) and fix overlaps, cut labels or wrong scales before showing it.
- Vietnamese or other non-ASCII text: use a font with the glyphs (DejaVu Sans is the default and covers Vietnamese).

## Statistics (keep it honest)

- Report n, mean/median, spread; prefer median for skewed data.
- Correlation ≠ causation; say so when relevant.
- Simple tests via numpy/pandas (`df.corr()`, bootstrap CIs) are fine; scipy may not be installed, check with `python -c "import scipy"` before using it.

## Outputs

- Excel deliverable → `xlsx` skill (`office_build`). Slides → `pptx` skill. Report → `docx` skill.
- Otherwise: chart PNGs + a short Markdown summary, and the cleaned CSV if useful.
