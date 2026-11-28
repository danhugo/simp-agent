"""Dev tool, not shipped to users: rebuilds apps/server/sandboxes/reference.docx, the house style for pandoc .md -> .docx (reference.docx): readable body, clear heading scale, tidy tables."""
import subprocess
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
raw = subprocess.run(["pandoc", "--print-default-data-file", "reference.docx"], capture_output=True)
open("/out/reference.docx", "wb").write(raw.stdout)
d = Document("/out/reference.docx")
PRIMARY, INK, MUTED = RGBColor(0x1F, 0x3A, 0x68), RGBColor(0x1B, 0x23, 0x33), RGBColor(0x5B, 0x65, 0x78)
def font(st, name, size, bold=None, color=None, italic=None):
    f = st.font; f.name = name; f.size = Pt(size)
    rpr = st.element.get_or_add_rPr(); rf = rpr.find(qn("w:rFonts"))
    if rf is None: rf = OxmlElement("w:rFonts"); rpr.append(rf)
    for k in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"): rf.set(qn(k), name)
    for k in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
        if rf.get(qn(k)) is not None: del rf.attrib[qn(k)]
    if bold is not None: f.bold = bold
    if italic is not None: f.italic = italic
    if color is not None: f.color.rgb = color
def para(st, before, after, line=None, keep=False):
    p = st.paragraph_format; p.space_before = Pt(before); p.space_after = Pt(after)
    if line: p.line_spacing = line
    if keep: p.keep_with_next = True
class _S:
    def __init__(s, st): s.m = {x.name.lower(): x for x in st}
    def __getitem__(s, k): return s.m[k.lower()]
    def __iter__(s): return iter(s.m.values())
S = _S(d.styles)
for name in ("Normal", "Body Text", "First Paragraph", "Compact"):
    if name.lower() in [x.name.lower() for x in S]:
        font(S[name], "Calibri", 10.5, color=INK); para(S[name], 0, 4 if name != "Compact" else 1, 1.15)
font(S["Title"], "Calibri", 22, bold=True, color=PRIMARY); para(S["Title"], 0, 2)
for name in ("author", "date"):
    if name in [x.name.lower() for x in S]: font(S[name], "Calibri", 10, color=MUTED); para(S[name], 0, 0)
if "subtitle" in [x.name.lower() for x in S]: font(S["Subtitle"], "Calibri", 12, color=MUTED); para(S["Subtitle"], 0, 6)
for lvl, size, before in ((1, 15, 12), (2, 12.5, 10), (3, 11, 8), (4, 10.5, 6)):
    st = S[f"Heading {lvl}"]; font(st, "Calibri", size, bold=True, color=PRIMARY if lvl < 3 else INK, italic=False)
    para(st, before, 4, keep=True)
for name in ("Block Text",):
    if name.lower() in [x.name.lower() for x in S]: font(S[name], "Calibri", 11, italic=True, color=MUTED)
if "table caption" in [x.name.lower() for x in S]: font(S["Table Caption"], "Calibri", 9.5, italic=True, color=MUTED)
if "image caption" in [x.name.lower() for x in S]: font(S["Image Caption"], "Calibri", 9.5, italic=True, color=MUTED)
for sec in d.sections:
    sec.left_margin = sec.right_margin = Cm(2.0); sec.top_margin = sec.bottom_margin = Cm(2.0)
# pandoc tables use the "Table" style: thin horizontal rules, bold shaded header
if "table" in [x.name.lower() for x in S]:
    t = S["Table"].element
    tblPr = t.find(qn("w:tblPr")) or OxmlElement("w:tblPr")
    if t.find(qn("w:tblPr")) is None: t.append(tblPr)
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "bottom", "insideH"):
        e = OxmlElement(f"w:{edge}"); e.set(qn("w:val"), "single"); e.set(qn("w:sz"), "4"); e.set(qn("w:color"), "BFC7D5"); b.append(e)
    old = tblPr.find(qn("w:tblBorders"))
    if old is not None: tblPr.remove(old)
    tblPr.append(b)
    mar = OxmlElement("w:tblCellMar")
    for edge in ("top", "bottom"):
        e = OxmlElement(f"w:{edge}"); e.set(qn("w:w"), "60"); e.set(qn("w:type"), "dxa"); mar.append(e)
    old = tblPr.find(qn("w:tblCellMar"))
    if old is not None: tblPr.remove(old)
    tblPr.append(mar)
    order = ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize", "tblStyleColBandSize", "tblW", "jc",
             "tblCellSpacing", "tblInd", "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook"]
    kids = sorted(list(tblPr), key=lambda e: order.index(e.tag.split("}")[1]) if e.tag.split("}")[1] in order else 99)
    for k in list(tblPr): tblPr.remove(k)
    for k in kids: tblPr.append(k)
    hdr = OxmlElement("w:tblStylePr"); hdr.set(qn("w:type"), "firstRow")
    rpr = OxmlElement("w:rPr"); rpr.append(OxmlElement("w:b")); hdr.append(rpr)
    tcpr = OxmlElement("w:tcPr"); tb = OxmlElement("w:tcBorders"); e = OxmlElement("w:bottom")
    e.set(qn("w:val"), "single"); e.set(qn("w:sz"), "12"); e.set(qn("w:color"), "1F3A68"); tb.append(e); tcpr.append(tb); hdr.append(tcpr)
    t.append(hdr)
# pandoc's default reference points two styles at styles it does not ship: drop the dangling links
for st in d.styles.element.findall(qn("w:style")):
    sid = st.get(qn("w:styleId"))
    known = {x.get(qn("w:styleId")) for x in d.styles.element.findall(qn("w:style"))}
    for tag in ("w:basedOn", "w:next"):
        ref = st.find(qn(tag))
        if ref is not None and ref.get(qn("w:val")) not in known:
            st.remove(ref)
d.save("/out/reference.docx")
print("ok")
