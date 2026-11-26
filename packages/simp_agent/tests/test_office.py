"""Deck source -> officecli batch ops (no officecli needed), plus problem mapping back to file #element."""
import os
import re
import shutil

import pytest

from simp_agent.plugins.office import explain, parse_deck
from simp_agent.plugins.office_layouts import LAYOUTS, THEMES

DESIGN = '<design theme="navy"/>'
ALL = {
    "cover": '<slide layout="cover" title="T" subtitle="S" meta="M"/>',
    "section": '<slide layout="section" number="02" title="Part" lead="Why"/>',
    "bullets": '<slide layout="bullets" title="T"><li><strong>A</strong> one</li><li>two</li><note><li>n</li></note></slide>',
    "two-col": '<slide layout="two-col" title="T"><col title="A"><li>a</li></col><col title="B"><li>b</li></col></slide>',
    "cards": '<slide layout="cards" title="T"><card title="A" value="1">x</card><card title="B">y</card></slide>',
    "kpis": '<slide layout="kpis" title="T"><kpi value="9" label="L" note="n"/><kpi value="8" label="M"/></slide>',
    "chart": '<slide layout="chart" title="T" type="column" categories="a,b"><series name="S" values="1,2"/><li>i</li></slide>',
    "table": '<slide layout="table" title="T"><tr><td>H</td><td>V</td></tr><tr><td>a, b</td><td>1</td></tr><note>src</note></slide>',
    "steps": '<slide layout="steps" title="T"><step title="1">a</step><step title="2">b</step><step title="3">c</step></slide>',
    "quote": '<slide layout="quote" quote="Q" by="B"/>',
    "image": '<slide layout="image" title="T" src="/work/a.png"><li>x</li></slide>',
    "closing": '<slide layout="closing" title="Thanks"/>',
}


def test_every_layout_builds_in_every_theme():
    assert set(ALL) == set(LAYOUTS)
    for theme in THEMES:
        deck = parse_deck(f'<design theme="{theme}"/>', [(f"{i:02d}.xml", x) for i, x in enumerate(ALL.values(), 1)])
        assert deck.errors == [], (theme, deck.errors)
        assert sum(o["type"] == "slide" for o in deck.ops if o["command"] == "add") == len(ALL)


def test_runs_keep_inline_style_and_resolve_theme_colors():
    deck = parse_deck(DESIGN, [("01.xml", ALL["bullets"])])
    runs = [o["props"] for o in deck.ops if o.get("type") == "run"]
    a = next(r for r in runs if r["text"] == "A")
    assert a["bold"] == "true" and a["color"] == "#1B2333"


@pytest.mark.parametrize("src,msg", [
    ('<slide><text x="1200" y="10" width="200" height="40">x</text></slide>', "leaves the 1280x720 canvas"),
    ('<slide><shape type="rect" x="0" y="0" width="10" height="10" fill="brandy"/></slide>', "unknown color 'brandy'"),
    ('<slide layout="nope" title="T"/>', "unknown layout 'nope'"),
    ('<slide layout="cards" title="T"><card title="A">x</card></slide>', "2 to 4"),
    ('<slide><chart type="pie" x="0" y="0" width="9" height="9" categories="a,b"><series values="1"/></chart></slide>', "1 values for 2"),
    ('<slide><text x="0" y="0" width="9" height="9"><b>x</b></text></slide>', "<b> is not allowed"),
    ('<slide><oops/>', "01.xml:"),
])
def test_source_errors_name_file_and_element(src, msg):
    errors = parse_deck(DESIGN, [("01.xml", src)]).errors
    assert any(msg in e for e in errors), errors


def test_issue_lines_map_to_file_and_element():
    deck = parse_deck(DESIGN, [("01.xml", ALL["cover"]), ("02.xml", ALL["bullets"])])
    sid = next(k for k, v in deck.ids.items() if v.startswith("02.xml") and k[0] == 2)[1]
    out = explain(f"  [O1] /slide[2]/shape[@id={sid}]: text overflow: 5 lines. suggest.height=2.65cm", deck.ids)
    assert out[0].startswith("02.xml #") and "needs height ≈ 100px" in out[0]


@pytest.mark.skipif(not shutil.which("officecli"), reason="officecli not installed")
async def test_build_with_officecli(tmp_path):
    import asyncio

    from simp_agent.agent.env import LocalEnv
    from simp_agent.plugins.office import Office

    d = tmp_path / "x.deck"
    d.mkdir()
    (d / "design.xml").write_text(DESIGN)
    for i, x in enumerate(ALL.values(), 1):
        (d / f"{i:02d}.xml").write_text(x.replace("/work/a.png", str(tmp_path / "none.png")) if "image" not in x else ALL["cover"])

    class Api:
        tools = {}

        def register_tool(self, t):
            self.tools[t.name] = t

    class Ctx:
        env, cwd, cancel, state = LocalEnv(), str(tmp_path), asyncio.Event(), {}

    api = Api()
    Office().setup(api, {})
    out = await api.tools["office_build"].execute({"source": "x.deck"}, Ctx())
    assert out.startswith(f"Built {tmp_path}/x.pptx (12 slides)"), out
    again = await api.tools["office_build"].execute({"source": "x.deck"}, Ctx())  # own output: rebuilt freely
    assert again.startswith("Built"), again
    (tmp_path / "x.pptx").write_bytes((tmp_path / "x.pptx").read_bytes() + b"\0")  # changed elsewhere
    assert "was not built from this source" in await api.tools["office_build"].execute({"source": "x.deck"}, Ctx())


def test_double_escaped_entities_render_as_characters():
    src = '<slide layout="bullets" title="A &amp;amp; B"><li>x &amp;gt; 4 &amp;amp; y</li></slide>'
    texts = [o.get("props", {}).get("text") for o in parse_deck(DESIGN, [("01.xml", src)]).ops]
    assert "A & B" in texts and any(t and "x > 4 & y" in t for t in texts), texts


def test_design_override_keeps_the_theme_font_size():
    from simp_agent.plugins.office import Design
    d = Design('<design theme="navy"><font name="heading" family="Arial"/></design>')
    assert d.fonts["heading"] == ("Arial", 40.0)


def test_bullets_keep_the_size_fit_chose():
    """text() must not shrink again with a bigger paragraph gap than fit() assumed."""
    import xml.etree.ElementTree as ET
    from simp_agent.plugins.office_layouts import Layouts
    li = "".join(f"<li><strong>Point {i}:</strong> {'a fairly long sentence with some detail ' * 3}</li>" for i in range(4))
    items = next(e for e in Layouts({}).build(ET.fromstring(f'<slide layout="bullets" title="T">{li}</slide>'), 2, 9)
                 if e.get("id") == "items")
    assert float(items.get("size")) >= 24


def test_too_much_text_is_reported():
    long = "".join(f"<li>{'word ' * 150}</li>" for _ in range(6))
    deck = parse_deck(DESIGN, [("01.xml", f'<slide layout="bullets" title="T">{long}</slide>')])
    assert deck.errors == [] and any("01.xml #items: text shrank" in w for w in deck.warnings), deck.warnings


@pytest.mark.skipif(not shutil.which("officecli"), reason="officecli not installed")
async def test_xlsx_build_stores_formula_values(tmp_path):
    """officecli calculates the formulas and writes their values, so viewers that don't calculate show numbers."""
    import asyncio
    import sys
    import zipfile

    from simp_agent.agent.env import LocalEnv
    from simp_agent.plugins.office import Office

    pytest.importorskip("openpyxl")
    (tmp_path / "m.xlsx.py").write_text(
        "import os, openpyxl\nwb = openpyxl.Workbook(); ws = wb.active; ws.title = 'Báo cáo'\n"
        "ws['A1'] = 5; ws['A2'] = 7; ws['A3'] = '=SUM(A1:A2)*2'; ws['A4'] = '=A1/0'\nwb.save(os.environ['OUT'])\n")

    class Api:
        tools = {}

        def register_tool(self, t):
            self.tools[t.name] = t

    class Ctx:
        env, cwd, cancel, state = LocalEnv(), str(tmp_path), asyncio.Event(), {}

    api = Api()
    Office().setup(api, {})
    old = os.environ["PATH"]
    os.environ["PATH"] = os.path.dirname(sys.executable) + os.pathsep + old  # `python` with openpyxl
    try:
        out = await api.tools["office_build"].execute({"source": "m.xlsx.py"}, Ctx())
    finally:
        os.environ["PATH"] = old
    assert out.startswith(f"Built {tmp_path}/m.xlsx") and "#DIV/0!" in out, out
    sheet = zipfile.ZipFile(tmp_path / "m.xlsx").read("xl/worksheets/sheet1.xml").decode()
    assert re.search(r"<(x:)?v>24</(x:)?v>", sheet) and "XFD" not in sheet


def test_svg_fallback_size_is_not_a_problem():
    line = '  [F3] /slide[1]/picture[@id=1011]: Picture "image11" is stretched: source 1x1px (1.00:1) in a 3x1cm box'
    assert explain(line, {}) == []
