"""Helpers for well-formed, good-looking workbooks with openpyxl. Import from a .xlsx.py source:

    import os, sys; sys.path.insert(0, "/opt/simp/skills/xlsx/scripts")
    from xlsx_kit import Book
    b = Book()                                    # theme: navy (default), ocean, forest, mono
    ws = b.sheet("Sales")
    b.table(ws, ["Month", "Revenue", "Cost", "Profit"], rows, formats=[None, "money", "money", "money"],
            formulas={"Profit": "=B{r}-C{r}"}, total=True)
    b.chart(ws, "column", title="Revenue vs cost", cats="A", series=["B", "C"], at="F2")
    b.save()                                      # to os.environ["OUT"] (office_build sets it)
"""

from __future__ import annotations

import os

from openpyxl import Workbook
from openpyxl.chart import AreaChart, BarChart, DoughnutChart, LineChart, PieChart, Reference, ScatterChart, Series
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

THEMES = {"navy": ("1F3A68", "E8EEF7", "E8A33D"), "ocean": ("0B6E99", "E3EEF4", "F26B38"),
          "forest": ("2F5D50", "ECE7DA", "C8873A"), "mono": ("222222", "F2F2F2", "E63946")}
FORMATS = {"money": '#,##0;(#,##0);"-"', "money2": '#,##0.00;(#,##0.00);"-"', "int": '#,##0;(#,##0);"-"',
           "pct": '0.0%;(0.0%);"-"', "num": '#,##0.0;(#,##0.0);"-"', "date": "yyyy-mm-dd", "x": '0.0"x"',
           "usd": '"$"#,##0;("$"#,##0);"-"', "vnd": '#,##0" ₫";(#,##0" ₫");"-"'}
PALETTE = ["1F3A68", "E8A33D", "0B6E99", "C8873A", "5B3FD1", "2F5D50", "B3261E", "6A564A"]


class Book:
    def __init__(self, theme: str = "navy", font: str = "Arial"):
        self.wb = Workbook()
        self._first = True
        self.primary, self.band, self.accent = THEMES[theme]
        self.font = font
        thin = Side(style="thin", color="D9D9D9")
        self.border = Border(bottom=thin)

    def sheet(self, title: str, tab: str | None = None, index: int | None = None):
        """A new sheet (the first call reuses the default one). index=0 puts it first (e.g. a dashboard made last)."""
        if self._first:
            ws = self.wb.active
            self._first = False
        else:
            ws = self.wb.create_sheet(index=index)
        if index is not None and ws.parent.index(ws) != index:
            ws.parent.move_sheet(ws, offset=index - ws.parent.index(ws))
        ws.title = title[:31]
        ws.sheet_view.showGridLines = False
        if tab:
            ws.sheet_properties.tabColor = tab
        return ws

    def title(self, ws, text: str, sub: str | None = None):
        """Sheet heading in A1 (and a subtitle in A2); tables then start at row 4."""
        ws["A1"] = text
        ws["A1"].font = Font(name=self.font, size=16, bold=True, color=self.primary)
        if sub:
            ws["A2"] = sub
            ws["A2"].font = Font(name=self.font, size=10, italic=True, color="666666")
        ws.row_dimensions[1].height = 24

    def table(self, ws, headers: list, rows: list, start: str = "A1", formats: list | None = None,
              formulas: dict | None = None, total: bool | list = False, widths: dict | None = None, freeze: bool = True):
        """Header + rows from `start`. formulas: {header: "=B{r}*C{r}"} fills that column per row ({r} = row number).
        total: True sums every numeric-format column, or a list of headers to sum. Returns (first_row, last_row)."""
        col0 = ws[start].column
        r0 = ws[start].row
        hdr_fill = PatternFill("solid", fgColor=self.primary)
        for j, h in enumerate(headers):
            c = ws.cell(r0, col0 + j, h)
            c.font = Font(name=self.font, bold=True, color="FFFFFF")
            c.fill, c.alignment = hdr_fill, Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[r0].height = 30
        formats = formats or [None] * len(headers)
        formulas = formulas or {}
        band = PatternFill("solid", fgColor=self.band)
        for i, row in enumerate(rows):
            r = r0 + 1 + i
            for j, h in enumerate(headers):
                v = formulas[h].format(r=r) if h in formulas else (row[j] if j < len(row) else None)
                c = ws.cell(r, col0 + j, v)
                c.font, c.border = Font(name=self.font), self.border
                if formats[j]:
                    c.number_format = FORMATS.get(formats[j], formats[j])
                if i % 2:
                    c.fill = band
        last = r0 + len(rows)
        if total:
            t = last + 1
            ws.cell(t, col0, "Total").font = Font(name=self.font, bold=True)
            want = headers if total is True else total
            for j, h in enumerate(headers):
                if j and h in want and (formats[j] in ("money", "money2", "int", "num", "usd", "vnd")):
                    L = get_column_letter(col0 + j)
                    c = ws.cell(t, col0 + j, f"=SUM({L}{r0 + 1}:{L}{last})")
                    c.number_format = FORMATS.get(formats[j], formats[j])
                    c.font = Font(name=self.font, bold=True)
                ws.cell(t, col0 + j).border = Border(top=Side(style="medium", color=self.primary))
        for j, h in enumerate(headers):
            L = get_column_letter(col0 + j)
            longest = max([len(str(h))] + [len(f"{r[j]:,.2f}" if isinstance(r[j], float) else str(r[j]))
                                           for r in rows if j < len(r) and r[j] is not None])
            nums = [abs(r[j]) for r in rows if j < len(r) and isinstance(r[j], (int, float))]
            if nums or formats[j] or h in formulas:  # numbers and their total: wide enough for the SUM, never "####"
                big = sum(nums) * 1.5 if nums else 1e9
                longest = max(longest, len(f"{big:,.0f}") + (3 if formats[j] in ("vnd", "usd") else 1))
                floor = 14
            else:
                floor = 10
            ws.column_dimensions[L].width = (widths or {}).get(h) or min(48, max(floor, longest + 3))
        if freeze:
            ws.freeze_panes = ws.cell(r0 + 1, col0)
        return r0, last

    def chart(self, ws, kind: str, title: str, cats: str, series: list, at: str, header_row: int = 1,
              last_row: int | None = None, y_title: str | None = None, x_title: str | None = None,
              width: float = 18, height: float = 9, stacked: bool = False, data_ws=None):
        """kind: column, bar, line, area, pie, donut, scatter. cats/series are column letters of a table whose header
        is on header_row (series names come from it); data may live on data_ws (default: ws)."""
        src = data_ws or ws
        last = last_row or src.max_row
        kinds = {"column": BarChart, "bar": BarChart, "line": LineChart, "area": AreaChart, "pie": PieChart,
                 "donut": DoughnutChart, "scatter": ScatterChart}
        ch = kinds[kind]()
        if kind in ("column", "bar"):
            ch.type = "col" if kind == "column" else "bar"
            if stacked:
                ch.grouping, ch.overlap = "stacked", 100
        ch.title, ch.width, ch.height, ch.style = title, width, height, 10
        ch.roundedCorners = False
        col = lambda L: src[L + "1"].column  # noqa: E731
        cat_ref = Reference(src, min_col=col(cats), min_row=header_row + 1, max_row=last)
        for k, L in enumerate(series):
            ref = Reference(src, min_col=col(L), min_row=header_row, max_row=last)
            if kind == "scatter":
                s = Series(Reference(src, min_col=col(L), min_row=header_row + 1, max_row=last), cat_ref,
                           title_from_data=False, title=str(src.cell(header_row, col(L)).value))
                ch.series.append(s)
            else:
                ch.add_data(ref, titles_from_data=True)
        if kind != "scatter":
            ch.set_categories(cat_ref)
        for k, s in enumerate(ch.series):
            color = PALETTE[k % len(PALETTE)]
            if kind in ("line", "scatter"):
                s.graphicalProperties.line.solidFill = color
                s.graphicalProperties.line.width = 28000
                s.smooth = False
            elif kind not in ("pie", "donut"):
                s.graphicalProperties.solidFill = color
                s.graphicalProperties.line.solidFill = color
        if kind in ("pie", "donut"):
            from openpyxl.chart.series import DataPoint
            s = ch.series[0]
            for i in range(last - header_row):
                pt = DataPoint(idx=i)
                pt.graphicalProperties.solidFill = PALETTE[i % len(PALETTE)]
                s.dPt.append(pt)
        else:
            ch.x_axis.delete = False
            ch.y_axis.delete = False
            if y_title:
                ch.y_axis.title = y_title
            if x_title:
                ch.x_axis.title = x_title
            ch.y_axis.majorGridlines = ch.y_axis.majorGridlines  # keep default light gridlines
        if ch.legend is not None:
            ch.legend.position = "b"
            ch.legend.overlay = False
            if len(series) == 1 and kind not in ("pie", "donut"):
                ch.legend = None
        ws.add_chart(ch, at)
        return ch

    def note(self, ws, cell: str, text: str):
        ws[cell] = text
        ws[cell].font = Font(name=self.font, size=9, italic=True, color="666666")

    def save(self, path: str | None = None):
        self.wb.save(path or os.environ["OUT"])
