"""Office files through officecli (a fast Rust CLI, run in the agent's env/sandbox).

Three tools, one job each:
- office_build(source): build a .pptx from a deck folder (design.xml + one XML file per slide, a small declarative
  syntax on a 1280x720 px canvas) or a .docx from a Markdown file; then check it (schema, text overflow, off-slide
  boxes) and report problems by file and element id. The source is the truth: edit it and build again.
- office_read(path, view): outline / text / issues of any .pptx/.docx/.xlsx (also files the user brought).
- office_run(code): code mode. Runs a Python script with `office` (office_rt.py: officecli as an API, edits batched)
  in one call, then checks every file it changed and looks at the screenshots it took.
A build remembers the output's hash, so a file changed elsewhere (e.g. in PowerPoint) is not overwritten silently."""

from __future__ import annotations

import html
import json
import os
import re
import shlex
import uuid
import xml.etree.ElementTree as ET

from ..agent import AgentTool
from ..coding.tools import look
from .office_layouts import LAYOUTS, THEMES, Layouts, theme_design

W, H, PT = 1280, 720, 0.75  # canvas px; 1 px = 0.75 pt (960 x 540 pt = 16:9)
CM_PX = 1 / 0.026458333  # px per cm
OUT_MAX = 12_000
READABLE = 18  # px on the 1280x720 canvas (13.5 pt): smaller body text is not readable when presented
RUNTIME = open(os.path.join(os.path.dirname(__file__), "office_rt.py"), encoding="utf-8").read()  # copied into the env
# runs the agent's main.py with `office` imported; its traceback keeps main.py's own line numbers
BOOT = ("import os, runpy, office\n"
        "runpy.run_path(os.environ['OFFICE_SCRIPT'], init_globals={'office': office}, run_name='__main__')\n")
RUN_DOC = """Run a Python script that reads or edits .pptx/.docx/.xlsx files through `office` (officecli as an API), all
in one call. Use it to change a file in place (one the user brought, or one with no deck/.md source), to inspect a file
in depth, or to make files that office_build can't. Write the whole job as one script: loops, conditions, reading then
editing. Edits are queued and sent as one atomic batch (all apply or none) before the next read and at the end; every
file is closed at the end, then each changed file is checked (schema + issues) and screenshots are looked at for you.
Errors name the script line. print() what you want to see; output over 12k chars is cut.

d = office.open(path) | office.create(path, force=False)      # .pptx .docx .xlsx
Read (Python data): d.get(path='/') -> Node; d.query(selector) -> [Node]  (Node: .path .type .text .props .children,
  .set(**p) .remove()); d.view(mode, start=, end=, max_lines=, range=, cols=) -> str, mode: outline | text | annotated
  (text with element paths) | stats | issues | forms | html; d.issues(type=); d.validate(); d.raw(part); d.dump(path)
Edit (queued): d.add(parent, type, before=, after=, index=, **props) -> .path of the new element; d.set(path, **props);
  d.remove(path); d.move(path, to=, before=, after=, index=); d.swap(p1, p2); d.replay(batch_items); d.flush()
Low level: d.raw_set(part, xpath, action, xml); d.add_part(parent, type); d.import_csv('/Sheet1', csv, header=True);
  d.refresh(); office.merge(template, out, data_dict)
Look: d.screenshot(page=1 | grid=True | range='/slide[1]/shape[@id=3]' or 'Sheet1!A1:D9') ; d.export('x.pdf'|'.html'|'.svg')
Docs: office.help('pptx') lists elements; office.help('pptx', 'shape') gives its props; office.search('shadow', 'pptx')
Any other command: office.cli('view', 'a.pptx', 'stats')
Paths: /slide[2]/shape[@id=5], /slide[1]/table[1]/tr[2]/tc[1], /body/p[3], /Sheet1/B4. Selectors: 'shape',
'slide[2] > shape', 'shape:contains("Q3")'. Props are officecli props, values as Python (True, 12, '2cm', 'FF0000');
a dotted prop takes __: font__latin='Arial'. Look up props with office.help before guessing.
Common: pptx d.add('/', 'slide', title=...) (a new .pptx has NO slides), then 'shape', 'textbox', 'table' (rows=, cols=),
'row' (c1=, c2=), 'picture', 'chart'; docx d.add('/body', 'paragraph', text=, style=); xlsx d.set('/Sheet1/A1',
value=…) or formula='SUM(A1:A9)'.
Each call is a new process: nothing (d, variables) carries over, so open the file again. Screenshots are looked at
for you and their answer is in the result; the PNGs are temporary (pass out='/work/x.png' to keep one)."""


class SourceError(Exception):
    pass


def _num(el, attr, default=None, where=""):
    v = el.get(attr)
    if v is None:
        if default is None:
            raise SourceError(f"{where}: missing {attr}")
        return default
    try:
        return float(v)
    except ValueError:
        raise SourceError(f"{where}: {attr}={v!r} is not a number") from None


def _pt(px: float) -> str:
    return f"{round(px * PT, 2):g}pt"


class Design:
    def __init__(self, text: str):
        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            raise SourceError(f"design.xml: {e}") from None
        if root.tag != "design":
            raise SourceError("design.xml: the root element must be <design>")
        if root.get("theme"):  # a built-in theme; <color>/<font> children override its entries
            if root.get("theme") not in THEMES:
                raise SourceError(f"design.xml: unknown theme {root.get('theme')!r} (have: {', '.join(THEMES)})")
            own, root = list(root), ET.fromstring(theme_design(root.get("theme")))
            for c in own:  # an override changes only the attributes it gives (a font keeps its size)
                old = next((o for o in root if (o.tag, o.get("name")) == (c.tag, c.get("name"))), None)
                if old is None:
                    root.append(c)
                else:
                    old.attrib.update(c.attrib)
        self.colors = {c.get("name"): c.get("value") for c in root.iter("color")}
        self.fonts = {f.get("name"): (f.get("family"), float(f.get("size") or 18)) for f in root.iter("font")}

    def color(self, v: str | None, where: str) -> str | None:
        if v is None or v == "none":
            return v
        if v.startswith("#"):
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?", v):
                raise SourceError(f"{where}: bad color {v!r} (use #RRGGBB, #RRGGBBAA or a design.xml name)")
            return v.upper()
        if v not in self.colors:
            raise SourceError(f"{where}: unknown color {v!r} (design.xml has: {', '.join(self.colors) or 'none'})")
        return self.colors[v].upper()

    def font(self, v: str | None, where: str) -> tuple[str | None, float]:
        if v is None:
            return self.fonts.get("body", (None, 18))
        if v in self.fonts:
            return self.fonts[v]
        if re.fullmatch(r"[a-z][a-z0-9-]*", v):
            raise SourceError(f"{where}: unknown font {v!r} (design.xml has: {', '.join(self.fonts) or 'none'})")
        return v, 18  # a literal family


GEOMETRY = {"rect": "rect", "ellipse": "ellipse", "triangle": "triangle", "diamond": "diamond", "arrow": "rightArrow",
            "chevron": "chevron", "star": "star5", "hexagon": "hexagon", "pentagon": "pentagon", "parallelogram": "parallelogram"}
CHARTS = {"bar": "bar", "column": "column", "line": "line", "area": "area", "pie": "pie", "donut": "doughnut", "scatter": "scatter"}
INLINE = {"strong": {"bold": "true"}, "em": {"italic": "true"}, "u": {"underline": "true"}, "span": {}}


class Deck:
    """XML sources -> officecli batch ops. ids maps (slide number, shape id) -> 'file #element' for problem reports."""

    def __init__(self, design: Design):
        self.d, self.ops, self.ids, self.errors, self.warnings, self.total = design, list(), dict(), list(), list(), 0

    def slide(self, n: int, fname: str, text: str) -> None:
        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            self.errors.append(f"{fname}: {e}")
            return
        unescape(root)
        if root.tag != "slide":
            self.errors.append(f"{fname}: the root element must be <slide>")
            return
        if root.get("layout"):
            try:
                gen = Layouts(self.d.colors).build(root, n, self.total)
            except (ValueError, SourceError) as e:
                self.errors.append(f"{fname}: {e}")
                return
            root = ET.Element("slide")
            root.extend(gen)
            self._readable(fname, gen)
        bg = root.find("background")
        try:
            props = {"background": self.d.color(bg.get("color"), f"{fname} <background>")} if bg is not None else {}
        except SourceError as e:
            self.errors.append(str(e))
            props = {}
        self.ops.append({"command": "add", "parent": "/", "type": "slide", "props": props})
        for k, el in enumerate(e for e in root if e.tag != "background"):
            sid = n * 1000 + k + 1
            name = el.get("id") or f"{el.tag}{k + 1}"
            where = f"{fname} <{el.tag} id={name}>"
            self.ids[(n, sid)] = f"{fname} #{name}"
            try:
                getattr(self, "_" + el.tag, self._unknown)(n, sid, name, el, where)
            except SourceError as e:
                self.errors.append(str(e))

    def _readable(self, fname: str, gen: list) -> None:
        """A layout shrinks text to fit its box; below READABLE px it is too small to read from a seat."""
        for el in gen:
            if el.tag not in ("text", "table") or el.get("font") == "caption":
                continue
            size = float(el.get("size") or READABLE)
            if size < READABLE:
                cut = round(100 * (1 - (size / READABLE) ** 2))
                self.warnings.append(f"{fname} #{el.get('id') or el.tag}: text shrank to {size:g}px to fit (readable: "
                                     f"{READABLE:g}px+). Cut its words by about {max(cut, 10)}% or split the slide")

    def _unknown(self, n, sid, name, el, where):
        raise SourceError(f"{where}: unknown element (use text, shape, image, chart, table)")

    def _box(self, el, where, line=False) -> dict:
        x, y = _num(el, "x", 0, where), _num(el, "y", 0, where)
        w, h = _num(el, "width", where=where), _num(el, "height", where=where)
        if not line and (x < 0 or y < 0 or x + w > W + 0.5 or y + h > H + 0.5):
            raise SourceError(f"{where}: box {x:g},{y:g} {w:g}x{h:g} leaves the {W}x{H} canvas")
        p = {"x": _pt(x), "y": _pt(y), "width": _pt(w), "height": _pt(h)}
        if el.get("rotation"):
            p["rotation"] = el.get("rotation")
        return p

    def _text(self, n, sid, name, el, where):
        family, size = self.d.font(el.get("font"), where)
        size = _num(el, "size", size, where)
        base = {"size": _pt(size), "color": self.d.color(el.get("color"), where) or "#000000"}
        if family:
            base["font"] = family
        if el.get("bold") == "true":
            base["bold"] = "true"
        props = {"id": str(sid), "name": name, **self._box(el, where), "fill": self.d.color(el.get("fill"), where) or "none",
                 "line": "none", "margin": _pt(_num(el, "padding", 0, where)),
                 "valign": {"middle": "middle", "bottom": "bottom"}.get(el.get("anchor"), "top"),
                 "autoFit": "normal" if el.get("autofit") == "shrink" else "none"}
        if el.get("line-height"):
            props["lineSpacing"] = f"{_num(el, 'line-height', where=where):g}x"
        self.ops.append({"command": "add", "parent": f"/slide[{n}]", "type": "shape", "props": props})
        shape = f"/slide[{n}]/shape[@id={sid}]"
        paras = self._paragraphs(el, base, el.get("align"), where)
        if not paras:
            raise SourceError(f"{where}: no text")
        if el.get("space-after"):
            for pprops, _ in paras:
                pprops["spaceAfter"] = _pt(_num(el, "space-after", where=where))
        for i, (pprops, runs) in enumerate(paras):
            self.ops.append({"command": "add", "parent": shape, "type": "paragraph", "props": pprops})
            for r in runs:  # +2: a new shape starts with one empty paragraph (removed below)
                self.ops.append({"command": "add", "parent": f"{shape}/paragraph[{i + 2}]", "type": "run", "props": r})
        self.ops.append({"command": "remove", "path": f"{shape}/paragraph[1]"})

    def _paragraphs(self, el, base, align, where) -> list:
        blocks = [c for c in el if c.tag in ("p", "ul", "ol")]
        if not blocks:
            return [({"align": align or "left"}, self._runs(el, base, where))]
        out = list()
        for b in blocks:
            if b.tag == "p":
                out.append(({"align": b.get("align") or align or "left"}, self._runs(b, base, where)))
            else:
                self._list(b, base, align, where, 0, out)
        return [(p, r) for p, r in out if r]

    def _list(self, lst, base, align, where, level, out):
        for li in lst.findall("li"):
            nested = [c for c in li if c.tag in ("ul", "ol")]
            for c in nested:
                li.remove(c)
            props = {"align": align or "left", "list": "numbered" if lst.tag == "ol" else (lst.get("bullet") or "bullet"),
                     "marginLeft": f"{round(base_pt(base) * (1.2 + 1.2 * level), 1):g}pt",
                     "indent": f"-{round(base_pt(base) * 1.2, 1):g}pt"}
            if level:
                props["level"] = str(level)
            out.append((props, self._runs(li, base, where)))
            for c in nested:
                self._list(c, base, align, where, level + 1, out)

    def _runs(self, el, base, where) -> list:
        runs = list()

        def walk(node, style):
            if node.text:
                runs.append({**style, "text": node.text})
            for c in node:
                if c.tag not in INLINE:
                    raise SourceError(f"{where}: <{c.tag}> is not allowed inside text (use strong, em, u, span)")
                s = {**style, **INLINE[c.tag]}
                if c.get("color"):
                    s["color"] = self.d.color(c.get("color"), where)
                if c.get("size"):
                    s["size"] = _pt(_num(c, "size", where=where))
                if c.get("font"):
                    s["font"] = self.d.font(c.get("font"), where)[0]
                walk(c, s)
                if c.tail:
                    runs.append({**style, "text": c.tail})

        walk(el, base)
        runs = [r for r in runs if r["text"].strip() or len(runs) > 1]
        if runs:  # layout whitespace of the XML is not text
            runs[0]["text"] = runs[0]["text"].lstrip()
            runs[-1]["text"] = runs[-1]["text"].rstrip()
        return [r for r in runs if r["text"]]

    def _shape(self, n, sid, name, el, where):
        kind = el.get("type") or "rect"
        stroke = self.d.color(el.get("stroke"), where)
        sw = _num(el, "stroke-width", 1, where)
        if kind == "line":
            props = {"id": str(sid), "name": name, **self._box(el, where, line=True),
                     "color": stroke or "#000000", "lineWidth": _pt(sw)}
            if el.get("arrow-end") == "arrow":
                props["tailEnd"] = "triangle"
            self.ops.append({"command": "add", "parent": f"/slide[{n}]", "type": "connector", "props": props})
            return
        if kind not in GEOMETRY:
            raise SourceError(f"{where}: unknown shape type {kind!r} (have line, {', '.join(GEOMETRY)})")
        fill = self.d.color(el.get("fill"), where)
        if fill is None:
            raise SourceError(f"{where}: fill is required (a color, or none)")
        props = {"id": str(sid), "name": name, **self._box(el, where), "geometry": GEOMETRY[kind], "fill": fill,
                 "line": f"{stroke}:{round(sw * PT, 2):g}" if stroke else "none"}
        if kind == "rect" and el.get("corner-radius"):
            r = _num(el, "corner-radius", where=where)
            short = min(_num(el, "width", where=where), _num(el, "height", where=where)) or 1
            props["geometry"], props["adj"] = "roundRect", f"adj:val {int(min(50000, r / short * 100000))}"
        if el.get("opacity"):
            props["opacity"] = el.get("opacity")
        self.ops.append({"command": "add", "parent": f"/slide[{n}]", "type": "shape", "props": props})

    def _image(self, n, sid, name, el, where):
        src = el.get("src") or ""
        if not src.startswith(("/", "http://", "https://")):
            raise SourceError(f"{where}: src must be an absolute path or an http(s) URL")
        self.ops.append({"command": "add", "parent": f"/slide[{n}]", "type": "picture",
                         "props": {"id": str(sid), "name": name, **self._box(el, where), "src": src}})

    def _chart(self, n, sid, name, el, where):
        kind = el.get("type") or ""
        if kind not in CHARTS:
            raise SourceError(f"{where}: chart type must be one of {', '.join(CHARTS)}")
        cats = [c.strip() for c in (el.get("categories") or "").split(",") if c.strip()]
        series = el.findall("series")
        if not series:
            raise SourceError(f"{where}: needs at least one <series values=...>")
        data = list()
        for i, s in enumerate(series):
            vals = [v.strip() for v in (s.get("values") or "").split(",") if v.strip()]
            if cats and len(vals) != len(cats):
                raise SourceError(f"{where}: series {i + 1} has {len(vals)} values for {len(cats)} categories")
            try:
                [float(v) for v in vals]
            except ValueError:
                raise SourceError(f"{where}: series values must be plain numbers") from None
            data.append(f"{(s.get('name') or f'Series {i + 1}').replace(':', ' ').replace(';', ' ')}:{','.join(vals)}")
        colors = [self.d.color(c.strip(), where) for c in (el.get("color") or "").split(",") if c.strip()]
        props = {"id": str(sid), "name": name, **self._box(el, where), "chartType": CHARTS[kind], "data": ";".join(data),
                 "legend": el.get("legend") or ("right" if kind in ("pie", "donut") else "none")}
        if cats:
            props["categories"] = ",".join(cats)
        if colors:
            props["colors"] = ",".join(c.lstrip("#")[:6] for c in colors)
        family, size = self.d.font(el.get("font"), where)
        size = _num(el, "size", size, where)
        tc = (self.d.color(el.get("text-color"), where) or "#595959").lstrip("#")[:6]
        spec = f"{round(size * PT, 1):g}:{tc}" + (f":{family}" if family else "")
        props.update({"axisfont": spec, "legendFont": spec, "gridlines": el.get("gridlines") or "E6E6E6:0.5"})
        if el.get("data-labels") == "true":
            props["dataLabels"] = "percent" if kind in ("pie", "donut") else "value"
            props["labelfont"] = spec
        self.ops.append({"command": "add", "parent": f"/slide[{n}]", "type": "chart", "props": props})

    def _table(self, n, sid, name, el, where):
        rows = [[(td.text or "").strip() for td in tr.findall("td")] for tr in el.findall("tr")]
        if not rows or not rows[0]:
            raise SourceError(f"{where}: needs <tr><td>…</td></tr> rows")
        cols = len(rows[0])
        if any(len(r) != cols for r in rows):
            raise SourceError(f"{where}: every row needs {cols} cells")
        q = lambda s: '"' + s.replace('"', '""') + '"' if any(c in s for c in ',;"') else s  # noqa: E731
        family, size = self.d.font(el.get("font"), where)
        size = _num(el, "size", size, where)
        props = {"id": str(sid), "name": name, **self._box(el, where), "data": ";".join(",".join(q(c) for c in r) for r in rows),
                 "style": "none"}
        if el.get("header-fill"):
            props["headerFill"] = self.d.color(el.get("header-fill"), where)
        if el.get("fill"):
            props["bodyFill"] = self.d.color(el.get("fill"), where)
        if el.get("columns"):
            ws = [float(w) for w in el.get("columns").split(",")]
            total = sum(ws) or 1
            props["colWidths"] = ",".join(_pt(_num(el, "width", where=where) * w / total) for w in ws)
        self.ops.append({"command": "add", "parent": f"/slide[{n}]", "type": "table", "props": props})
        pad = _pt(_num(el, "padding", 8, where))
        cell = {"size": _pt(size), "color": self.d.color(el.get("color"), where) or "#000000", "valign": "middle",
                "padding.left": pad, "padding.right": pad}
        if family:
            cell["font"] = family
        head = {**cell, "bold": "true", **({"color": self.d.color(el.get("header-color"), where)} if el.get("header-color") else {})}
        for r in range(len(rows)):
            for c in range(cols):
                self.ops.append({"command": "set", "path": f"/slide[{n}]/table[@id={sid}]/tr[{r + 1}]/tc[{c + 1}]",
                                 "props": head if r == 0 else cell})


def unescape(root: ET.Element) -> None:
    """Models often escape twice (&amp;amp; shows as "&amp;" on the slide): decode leftover entities once."""
    for el in root.iter():
        if el.text and "&" in el.text:
            el.text = html.unescape(el.text)
        if el.tail and "&" in el.tail:
            el.tail = html.unescape(el.tail)
        for k, v in el.attrib.items():
            if "&" in v:
                el.attrib[k] = html.unescape(v)


def parse_deck(design_text: str, slides: list[tuple[str, str]]) -> Deck:
    try:
        deck = Deck(Design(design_text))
    except SourceError as e:
        deck = Deck.__new__(Deck)
        deck.ops, deck.ids, deck.errors, deck.warnings = list(), dict(), [str(e)], list()
        return deck
    deck.ops.append({"command": "set", "path": "/", "props": {"slideWidth": _pt(W), "slideHeight": _pt(H)}})
    deck.total = len(slides)
    for n, (fname, text) in enumerate(slides, 1):
        deck.slide(n, fname, text)
    return deck


# officecli also reports house-style opinions; they are not defects of a generated file
NOT_PROBLEMS = re.compile(r"first-line indent|widow|orphan|Empty paragraph", re.I)
ISSUE = re.compile(r"\[\w+\]\s+/slide\[(\d+)\]/\w+\[@id=(\d+)\][^:]*:\s*(.*)")


def explain(issues: str, ids: dict) -> list[str]:
    """officecli `view issues` lines -> 'file #element: problem' (sizes in px, like the source)."""
    out = list()
    for line in issues.splitlines():
        if NOT_PROBLEMS.search(line):
            continue
        m = ISSUE.search(line)
        if not m:
            if re.match(r"\s*\[\w+\]", line):
                out.append(line.strip())
            continue
        msg = re.sub(r"suggest\.height=([\d.]+)cm", lambda g: f"needs height ≈ {float(g.group(1)) * CM_PX:.0f}px", m.group(3))
        where = ids.get((int(m.group(1)), int(m.group(2)))) or f"/slide[{m.group(1)}]/shape[@id={m.group(2)}]"
        out.append(f"{where}: {msg}")
    return out


def base_pt(style: dict) -> float:
    return float(style["size"].rstrip("pt"))


def _tidy(out: str, run: str) -> str:
    """Traceback lines of the runtime and runpy are noise: keep main.py's frames and the error."""
    keep, skip = list(), False
    for line in out.splitlines():
        if line.startswith('  File "'):
            skip = f"{run}/main.py" not in line
            if not skip:
                line = line.replace(f"{run}/", "")
        elif not line.startswith("    "):
            skip = False
        if not skip:
            keep.append(line)
    return "\n".join(keep)


def _clip(s: str) -> str:
    return s if len(s) <= OUT_MAX else s[:OUT_MAX] + f"\n[… {len(s) - OUT_MAX} more chars]"


class Office:
    """The office_* tools. Needs `officecli` on the env's PATH (the sandbox template installs it)."""

    name = "office"

    def __init__(self, docx_reference: str | None = None, xlsx_recalc: str | None = None):
        """docx_reference: pandoc --reference-doc (the house style). xlsx_recalc: a recalc.py that stores computed
        values (LibreOffice) so viewers that don't calculate still show numbers."""
        self.docx_reference, self.xlsx_recalc = docx_reference, xlsx_recalc

    def setup(self, api, config: dict) -> None:
        s = {"type": "string"}
        api.register_tool(AgentTool(
            "office_build", "Build an office file from its source, then check it: a deck folder (design.xml + one .xml per "
            "slide, in file-name order) → .pptx; a .md file → .docx; a .xlsx.py openpyxl script (saves to "
            "os.environ['OUT']) → .xlsx with values calculated. Returns the output path and every problem (file #element "
            "or Sheet!cell: what is wrong). Fix the source and build again; never edit the built file by hand.",
            {"type": "object", "properties": {
                "source": {**s, "description": "deck folder (/work/q3.deck → /work/q3.pptx), .md (→ .docx) or .xlsx.py (→ .xlsx)"},
                "overwrite": {"type": "boolean", "description": "replace an output that was changed outside the source"}},
             "required": ["source"]}, self._build))
        api.register_tool(AgentTool(
            "office_read", "Look inside a .pptx/.docx/.xlsx (any, also one the user brought): outline (structure), text, "
            "annotated (text with element paths for office_run), issues (overflow, broken parts).",
            {"type": "object", "properties": {"path": s, "view": {"type": "string",
                                                                  "enum": ["outline", "text", "annotated", "issues"]}},
             "required": ["path"]}, self._read, parallel=True))
        api.register_tool(AgentTool("office_run", RUN_DOC, {"type": "object", "properties": {
            "code": {**s, "description": "Python script; `office` is already imported"},
            "look": {**s, "description": "question for the screenshots the script took (default: describe and find faults)"},
            "timeout": {"type": "integer", "description": "seconds, default 180"}},
            "required": ["code"]}, self._run))

    async def _sh(self, ctx, cmd: str, timeout: float = 180) -> tuple[int | None, str]:
        return await ctx.env.exec(cmd, ctx.cwd, timeout, ctx.cancel)

    async def _hash(self, ctx, path: str) -> str:
        code, out = await self._sh(ctx, f"sha256sum {shlex.quote(path)} 2>/dev/null | cut -c1-64", 30)
        return out.strip()

    async def _check(self, ctx, out: str) -> tuple[str, str]:
        q = shlex.quote(out)
        _, valid = await self._sh(ctx, f"officecli validate {q} 2>&1 | tail -20")
        _, issues = await self._sh(ctx, f"officecli view {q} issues 2>&1 | head -60")
        return valid.strip(), issues.strip()

    async def _build(self, args, ctx) -> str:
        src = os.path.join(ctx.cwd, args["source"]).rstrip("/")
        low = src.lower()
        kind = "docx" if low.endswith(".md") else "xlsx" if low.endswith(".xlsx.py") else "pptx"
        out = {"docx": src[:-3] + ".docx", "xlsx": src[:-3], "pptx": re.sub(r"\.deck$", "", src) + ".pptx"}[kind]
        stamp = os.path.join(os.path.dirname(src), f".{os.path.basename(src)}.built")
        old = await self._hash(ctx, out)
        if old and not args.get("overwrite"):
            try:
                known = (await ctx.env.read_file(stamp)).strip()
            except Exception:
                known = ""
            if old != known:
                return (f"{out} exists and was not built from this source (or was changed after the last build, e.g. in "
                        "PowerPoint/Word/Excel). Edit it in place with office_run, or build again with overwrite=true.")
        tmp = f"/tmp/office-{uuid.uuid4().hex[:8]}"
        made, ids, deck_warnings = f"{tmp}.{kind}", dict(), list()
        if kind == "docx":
            ref = f" --reference-doc={shlex.quote(self.docx_reference)}" if self.docx_reference else ""
            cmd = f"cd {shlex.quote(os.path.dirname(src))} && pandoc {shlex.quote(src)} -o {made}{ref} 2>&1"
        elif kind == "xlsx":
            cmd = f"cd {shlex.quote(os.path.dirname(src))} && OUT={made} python {shlex.quote(src)} 2>&1 | tail -30"
            cmd += f" && test -f {made} || {{ echo 'the script did not save to OUT'; exit 1; }}"
            if self.xlsx_recalc:
                d, f = os.path.split(self.xlsx_recalc)
                cmd += f"; cd {shlex.quote(d)} && python {shlex.quote(f)} {made} 60 >/dev/null 2>&1; true"
        else:
            entries = sorted(e["name"] for e in await ctx.env.list(src) if not e["is_dir"] and e["name"].endswith(".xml"))
            if "design.xml" not in entries:
                return f"{src} has no design.xml (colors and fonts); write it first."
            slides = [(f, await ctx.env.read_file(f"{src}/{f}")) for f in entries if f != "design.xml"]
            if not slides:
                return f"{src} has no slide files (e.g. 01-cover.xml)."
            deck = parse_deck(await ctx.env.read_file(f"{src}/design.xml"), slides)
            if deck.errors:
                return "Not built; fix the source:\n" + "\n".join(f"- {e}" for e in deck.errors)
            ids, deck_warnings = deck.ids, deck.warnings
            await ctx.env.write_file(f"{tmp}.json", json.dumps(deck.ops, ensure_ascii=False))
            cmd = (f"officecli create {made} >/dev/null && officecli batch {made} --input {tmp}.json "
                   f"| tail -5 && officecli close {made} >/dev/null")
        code, log = await self._sh(ctx, cmd)
        if code != 0:
            return f"Build failed (exit {code}):\n{_clip(log.strip())}"
        valid, issues = await self._check(ctx, made)
        # a resident officecli may still hold the old file in memory: close it so later reads see the new one
        await self._sh(ctx, f"officecli close {shlex.quote(out)} >/dev/null 2>&1; mv -f {made} {shlex.quote(out)}; "
                            f"officecli close {made} >/dev/null 2>&1; rm -f {tmp}.json", 30)
        await ctx.env.write_file(stamp, await self._hash(ctx, out))
        problems = explain(issues, ids) + (deck_warnings if kind == "pptx" else [])
        if "passed" not in valid.lower():
            problems.insert(0, f"schema: {valid}")
        what = f" ({len({n for n, _ in ids})} slides)" if kind == "pptx" else ""
        if kind == "docx":  # page count (LibreOffice layout; Word's may differ by a little)
            _, pages = await self._sh(ctx, f"cd /tmp && soffice --headless --convert-to pdf {shlex.quote(out)} >/dev/null 2>&1; "
                                           f"pdfinfo /tmp/{shlex.quote(os.path.basename(out)[:-5])}.pdf 2>/dev/null | "
                                           f"awk '/^Pages:/{{print $2}}'; rm -f /tmp/{shlex.quote(os.path.basename(out)[:-5])}.pdf", 120)
            _, words = await self._sh(ctx, f"pandoc -t plain {shlex.quote(src)} 2>/dev/null | wc -w", 60)
            if pages.strip().isdigit() and words.strip().isdigit():
                p, w = int(pages.strip()), int(words.strip())
                what = (f" (about {p} pages, {w} words, so about {w // max(p, 1)} words a page here; to change the length, "
                        "cut or add words once by that ratio)")
        if not problems:
            return f"Built {out}{what}. No problems found."
        return f"Built {out}{what}, with problems to fix in the source:\n" + "\n".join(f"- {p}" for p in problems)

    async def _read(self, args, ctx) -> str:
        path = shlex.quote(os.path.join(ctx.cwd, args["path"]))
        code, out = await self._sh(ctx, f"officecli view {path} {args.get('view') or 'outline'} 2>&1", 120)
        return _clip(out.strip() or f"(exit {code}, no output)")

    async def _run(self, args, ctx) -> str:
        run = f"/tmp/office-run-{uuid.uuid4().hex[:8]}"
        await ctx.env.write_file(f"{run}/office.py", RUNTIME)
        await ctx.env.write_file(f"{run}/main.py", args["code"])
        await ctx.env.write_file(f"{run}/boot.py", BOOT)
        q = shlex.quote(run)
        code, out = await self._sh(ctx, f"OFFICE_RUN_DIR={q} OFFICE_SCRIPT={q}/main.py PYTHONPATH={q} "
                                        f"python {q}/boot.py 2>&1",
                                   min(int(args.get("timeout") or 180), 600))
        try:
            state = json.loads(await ctx.env.read_file(f"{run}/state.json"))
        except Exception:
            state = {}
        parts = [_clip(_tidy(out.strip(), run)) or "(no output)"]
        if code not in (0, None):
            parts.append(f"(exit {code})")
        if state.get("warnings"):
            parts.append("officecli warnings:\n" + "\n".join(f"- {w}" for w in state["warnings"]))
        for path in state.get("changed", []):
            valid, issues = await self._check(ctx, path)
            problems = explain(issues, {})
            if "passed" not in valid.lower():
                problems.insert(0, f"schema: {valid}")
            rel = os.path.relpath(path, ctx.cwd) if path.startswith(ctx.cwd) else path
            parts.append(f"Check {rel}: " + ("no problems." if not problems else "\n" + "\n".join(f"- {p}" for p in problems)))
        if state.get("images"):
            parts.append(await look(state["images"], args.get("look"), ctx))
        await self._sh(ctx, f"rm -rf {q}", 30)
        return "\n\n".join(parts)
