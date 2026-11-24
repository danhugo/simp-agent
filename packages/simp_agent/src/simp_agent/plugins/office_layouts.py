"""Slide layouts: content slots in, positioned elements out (1280x720 px), so the model writes content, not coordinates.

<slide layout="cards" title="..."><card title="..." value="42%">text</card>...</slide> becomes a background, a title,
an accent bar, cards and a page number, in the deck theme, with text sizes shrunk until the estimate fits the box.
A slide without `layout` keeps its own elements (free layout)."""

from __future__ import annotations

import copy
import math
import xml.etree.ElementTree as ET

# name: bg, surface, ink (text), muted, primary, accent, on (text on primary), heading font, body font
THEMES = {
    "navy": ("#FFFFFF", "#F1F4F9", "#1B2333", "#5B6578", "#1F3A68", "#E8A33D", "#FFFFFF", "Georgia", "Calibri"),
    "ocean": ("#F7FAFC", "#E3EEF4", "#102A43", "#486581", "#0B6E99", "#F26B38", "#FFFFFF", "Arial", "Arial"),
    "forest": ("#F8F6F0", "#ECE7DA", "#23302A", "#5E6B63", "#2F5D50", "#C8873A", "#FFFFFF", "Georgia", "Calibri"),
    "terracotta": ("#F6EFE2", "#EADFCB", "#271D17", "#6A564A", "#5D331C", "#C66846", "#FFFFFF", "Georgia", "Calibri"),
    "mono": ("#FFFFFF", "#F2F2F2", "#111111", "#555555", "#111111", "#E63946", "#FFFFFF", "Arial", "Arial"),
    "night": ("#0F172A", "#1E293B", "#F1F5F9", "#94A3B8", "#38BDF8", "#F59E0B", "#0F172A", "Arial", "Arial"),
    "crimson": ("#16110F", "#2A221E", "#F5EFE6", "#B8A99A", "#B3261E", "#E9B44C", "#FFFFFF", "Georgia", "Arial"),
    "violet": ("#FBFAFF", "#EEEAFB", "#1E1B3A", "#5F5B7A", "#5B3FD1", "#FF7A59", "#FFFFFF", "Trebuchet MS", "Calibri"),
}
KEYS = ("bg", "surface", "ink", "muted", "primary", "accent", "on")

M, CW, TOP, BOTTOM = 64, 1152, 156, 656  # margin, content width, content top/bottom


def theme_design(name: str) -> str:
    t = THEMES[name]
    colors = "".join(f'<color name="{k}" value="{v}"/>' for k, v in zip(KEYS, t[:7]))
    return (f"<design>{colors}<font name=\"display\" family=\"{t[7]}\" size=\"60\"/>"
            f"<font name=\"heading\" family=\"{t[7]}\" size=\"40\"/><font name=\"body\" family=\"{t[8]}\" size=\"24\"/>"
            f"<font name=\"caption\" family=\"{t[8]}\" size=\"16\"/></design>")


def plain(el) -> list[str]:
    """Paragraph texts of an element (li/p children, or its own text)."""
    items = [c for c in el.iter() if c.tag in ("li", "p")]
    return ["".join(c.itertext()).strip() for c in items] if items else ["".join(el.itertext()).strip()]


def est(texts: list[str], w: float, s: float, lh: float = 1.25, gap: float = 0.4, em: float = 0.55) -> float:
    per = max(1, int(w / (em * s)))
    lines = sum(max(1, math.ceil(len(t) / per)) for t in texts if t) or 1
    return lines * s * lh + max(0, len(texts) - 1) * s * gap


def fit(texts: list[str], w: float, h: float, size: float, low: float, lh: float = 1.25, gap: float = 0.4,
        em: float = 0.55) -> float:
    """Largest size from `size` down to `low` whose estimated wrapped height fits w x h (0.52 em per character)."""
    s = size
    while s > low:
        per = max(1, int(w / (em * s)))
        lines = sum(max(1, math.ceil(len(t) / per)) for t in texts if t) or 1
        if lines * s * lh + max(0, len(texts) - 1) * s * gap <= h:
            return s
        s -= 1
    return low


def E(tag, **a):
    return ET.Element(tag, {k.replace("_", "-"): (f"{v:g}" if isinstance(v, float) else str(v)) for k, v in a.items()})


def text(x, y, w, h, body, font, size, color, **a):
    """A <text> whose content is the given string or a copy of an element's inline/list content. Last guard: the size
    shrinks (to 60% at most) until the estimate fits the box, so a layout never emits an overflowing box."""
    texts = [body] if isinstance(body, str) else plain(body)
    em = 0.62 if (a.get("bold") == "true" or font in ("display", "heading")) else 0.56
    lh = float(a.get("line_height") or 1.2)
    pad = 2 * float(a.get("space_after") or 0) / max(size, 1)
    floor = max(10.0, size * 0.6)
    while size > floor and est(texts, w, size, lh, 0.4 + pad, em) > h:
        size -= 1
    if "space_after" in a:
        a["space_after"] = round(size * 0.5)
    el = E("text", x=x, y=y, width=w, height=h, font=font, size=float(size), color=color, **a)
    if isinstance(body, str):
        el.text = body
    else:
        lis = [c for c in body if c.tag == "li"]
        if lis:
            ul = ET.SubElement(el, "ul")
            for li in lis:
                ul.append(copy.deepcopy(li))
        else:
            el.text = body.text
            for c in body:
                if c.tag not in ("li", "series", "tr", "note"):
                    el.append(copy.deepcopy(c))
    return el


class Layouts:
    def __init__(self, design_colors: dict):
        g = lambda k, d: k if k in design_colors else d  # noqa: E731 (theme names, or literal fallbacks)
        self.c = {k: g(k, "#000000") for k in KEYS}

    def build(self, el, page: int, total: int) -> list:
        name = el.get("layout")
        fn = getattr(self, "l_" + name.replace("-", "_"), None)
        if fn is None:
            raise ValueError(f"unknown layout {name!r} (have: {', '.join(LAYOUTS)})")
        return fn(el, page, total)

    # -- chrome ---------------------------------------------------------------------------------------------------
    def chrome(self, el, page, dark=False) -> list:
        c = self.c
        title = el.get("title") or ""
        size = fit([title], CW, 72, 40, 24, lh=1.1, em=0.6)
        out = [E("background", color=c["bg"]),
               E("text", id="title", x=M, y=40, width=CW, height=72, font="heading", size=float(size), color=c["ink"],
                 anchor="bottom", line_height="1.1"),
               E("shape", id="title-bar", type="rect", x=M, y=124, width=72, height=5, fill=c["accent"]),
               E("text", id="page", x=1136, y=676, width=80, height=24, font="caption", size=14.0, color=c["muted"],
                 align="right")]
        out[1].text, out[3].text = title, f"{page:02d}"
        return out

    def items_text(self, body, x, y, w, h, size=24.0, low=16.0, color=None, lh=1.3, center=False, id="items"):
        """A list or paragraph block, as large as fits; vertically centred when it fills well under the box."""
        texts = plain(body)
        s = fit(texts, w, h, size, low, lh=lh, gap=0.6)
        anchor = "middle" if center and est(texts, w, s, lh, 0.6) < 0.7 * h else "top"
        return text(x, y, w, h, body, "body", s, color or self.c["ink"], line_height=str(lh), space_after=round(s * 0.6),
                    anchor=anchor, id=id)

    # -- layouts --------------------------------------------------------------------------------------------------
    def l_cover(self, el, page, total, closing=False):
        c = self.c
        title, sub, meta = el.get("title") or "", el.get("subtitle") or "", el.get("meta") or ""
        ts = fit([title], 1040, 230, 60, 36, lh=1.1)
        out = [E("background", color=c["primary"]),
               E("shape", id="band", type="rect", x=0, y=0, width=24, height=720, fill=c["accent"]),
               E("shape", id="bar", type="rect", x=M + 16, y=196, width=96, height=6, fill=c["accent"]),
               text(M + 16, 220, 1040, 230, title, "display", ts, c["on"], anchor="bottom", line_height="1.1", id="cover-title")]
        if sub:
            out.append(text(M + 16, 470, 1000, 90, sub, "body", fit([sub], 1000, 90, 26, 18), c["on"], id="subtitle"))
        if meta:
            out.append(text(M + 16, 640, 1000, 32, meta, "caption", 16.0, c["on"]))
        return out

    def l_closing(self, el, page, total):
        return self.l_cover(el, page, total, closing=True)

    def l_section(self, el, page, total):
        c = self.c
        title, lead = el.get("title") or "", el.get("lead") or ""
        out = [E("background", color=c["primary"]),
               text(M, 150, 400, 140, el.get("number") or f"{page:02d}", "display", 96.0, c["accent"]),
               text(M, 300, 1100, 170, title, "display", fit([title], 1100, 170, 56, 36, lh=1.1), c["on"], id="section-title",
                    line_height="1.1")]
        if lead:
            out.append(text(M, 490, 1000, 100, lead, "body", fit([lead], 1000, 100, 24, 18), c["on"]))
        return out

    def l_quote(self, el, page, total):
        c = self.c
        q, by = el.get("quote") or "".join(el.itertext()).strip(), el.get("by") or ""
        out = [E("background", color=c["primary"]),
               text(M + 40, 60, 240, 220, "“", "display", 160.0, c["accent"]),
               text(M + 40, 230, 1060, 300, q, "display", fit([q], 1060, 300, 44, 26, lh=1.25), c["on"], line_height="1.25", id="quote")]
        if by:
            out.append(text(M + 40, 560, 1060, 40, f"— {by}", "body", 22.0, c["on"]))
        return out

    def l_bullets(self, el, page, total):
        c = self.c
        out = self.chrome(el, page)
        note = el.find("note")
        w = CW if note is None else 740
        out.append(self.items_text(el, M, TOP, w, BOTTOM - TOP, 30, 18, center=True))
        if note is not None:
            nt = plain(note)
            ns = fit(nt, 320, BOTTOM - TOP - 56, 22, 15, lh=1.35, gap=0.6)
            nh = min(BOTTOM - TOP, max(160, est(nt, 320, ns, 1.35, 0.6) + ns + 56))
            out += [E("shape", id="note-card", type="rect", x=840, y=TOP, width=376, height=nh, fill=c["surface"],
                      corner_radius=12),
                    self.items_text(note, 868, TOP + 28, 320, nh - 56, ns, ns, lh=1.35, id="note")]
        return out

    def l_two_col(self, el, page, total):
        c = self.c
        out = self.chrome(el, page)
        cols = el.findall("col")[:2]
        if len(cols) != 2:
            raise ValueError("layout two-col needs exactly 2 <col title=...> children")
        w = (CW - 32) / 2
        for i, col in enumerate(cols):
            x = M + i * (w + 32)
            out += [E("shape", id=f"col{i + 1}", type="rect", x=x, y=TOP, width=w, height=BOTTOM - TOP, fill=c["surface"],
                      corner_radius=12),
                    text(x + 32, TOP + 28, w - 64, 44, col.get("title") or "", "heading", 26.0, c["primary"], bold="true", id=f"col{i + 1}-title"),
                    self.items_text(col, x + 32, TOP + 84, w - 64, BOTTOM - TOP - 112, 26, 16, id=f"col{i + 1}-items")]
        return out

    def l_cards(self, el, page, total):
        c = self.c
        out = self.chrome(el, page)
        cards = el.findall("card")
        n = len(cards)
        if not 2 <= n <= 4:
            raise ValueError("layout cards needs 2 to 4 <card title=...> children")
        gap, pad = 24, 28
        w = (CW - gap * (n - 1)) / n
        has_value = any(cd.get("value") for cd in cards)
        head = None
        avail = BOTTOM - TOP - 20
        bodies = [plain(cd) for cd in cards]
        ts = min(fit([cd.get("title") or ""], w - 2 * pad, 96, 28, 16, lh=1.15, em=0.62) for cd in cards)
        th = max(est([cd.get("title") or ""], w - 2 * pad, ts, 1.15, em=0.62) for cd in cards) + 8
        head = (84 if has_value else 0) + th + 12  # value row + title rows
        bs = min(fit(b, w - 2 * pad, avail - head - 2 * pad, 26, 14, lh=1.35) for b in bodies)
        body_h = max(est(b, w - 2 * pad, bs, 1.35) for b in bodies) + bs
        ch = min(avail, max(240, head + body_h + 2 * pad))
        y0 = TOP + (avail - ch) / 2
        for i, cd in enumerate(cards):
            x = M + i * (w + gap)
            out.append(E("shape", id=f"card{i + 1}", type="rect", x=x, y=y0, width=w, height=ch, fill=c["surface"],
                         corner_radius=12))
            y = y0 + pad
            if has_value:
                v = cd.get("value") or ""
                out.append(text(x + pad, y, w - 2 * pad, 72, v, "display", fit([v], w - 2 * pad, 64, 52, 20, lh=1.1, em=0.62),
                                c["primary"], bold="true", line_height="1.1", id=f"card{i + 1}-value"))
                y += 84
            out += [text(x + pad, y, w - 2 * pad, th, cd.get("title") or "", "heading", ts, c["ink"], bold="true", line_height="1.15", id=f"card{i + 1}-title"),
                    text(x + pad, y + th + 12, w - 2 * pad, y0 + ch - pad - (y + th + 12), cd, "body", bs, c["ink"], line_height="1.35", id=f"card{i + 1}-text",
                         space_after=round(bs * 0.4))]
        return out

    def l_kpis(self, el, page, total):
        c = self.c
        out = self.chrome(el, page)
        ks = el.findall("kpi")
        n = len(ks)
        if not 2 <= n <= 4:
            raise ValueError("layout kpis needs 2 to 4 <kpi value=... label=.../> children")
        gap = 32
        w = (CW - gap * (n - 1)) / n
        vs = min(fit([k.get("value") or ""], w, 90, 72, 28, lh=1.1) for k in ks)
        for i, k in enumerate(ks):
            x = M + i * (w + gap)
            out += [E("shape", id=f"kpi{i + 1}-bar", type="rect", x=x, y=TOP + 40, width=w, height=4, fill=c["accent"]),
                    text(x, TOP + 64, w, 110, k.get("value") or "", "display", vs, c["primary"], bold="true", line_height="1.1", id=f"kpi{i + 1}-value"),
                    text(x, TOP + 190, w, 70, k.get("label") or "", "heading", fit([k.get("label") or ""], w, 70, 24, 14, em=0.62), c["ink"], bold="true", id=f"kpi{i + 1}-label")]
            if k.get("note") or (k.text or "").strip():
                note = k.get("note") or k.text.strip()
                out.append(text(x, TOP + 270, w, 200, note, "body", fit([note], w, 200, 20, 14), c["muted"], line_height="1.35", id=f"kpi{i + 1}-note"))
        return out

    def l_chart(self, el, page, total):
        c = self.c
        out = self.chrome(el, page)
        notes = el.findall("li")
        w = 736 if notes else CW
        ch = E("chart", id="chart", x=M, y=TOP, width=w, height=BOTTOM - TOP, font="caption", size=20.0,
               text_color=c["muted"], type=el.get("type") or "column", categories=el.get("categories") or "",
               color=el.get("color") or ",".join([c["primary"], c["accent"], c["muted"], c["ink"]]),
               legend=el.get("legend") or ("bottom" if len(el.findall("series")) > 1 or el.get("type") in ("pie", "donut") else "none"),
               data_labels=el.get("data-labels") or "true")
        for s in el.findall("series"):
            ch.append(copy.deepcopy(s))
        out.append(ch)
        if notes:
            out += [E("shape", id="insight-card", type="rect", x=832, y=TOP, width=384, height=BOTTOM - TOP,
                      fill=c["surface"], corner_radius=12),
                    text(860, TOP + 28, 328, 40, el.get("insight-title") or "Key points", "heading", 22.0, c["primary"], bold="true"),
                    self.items_text(el, 860, TOP + 84, 328, BOTTOM - TOP - 112, 24, 15, lh=1.35, id="insights")]
        return out

    def l_table(self, el, page, total):
        c = self.c
        out = self.chrome(el, page)
        rows = el.findall("tr")
        note = el.find("note")
        avail = BOTTOM - TOP - (56 if note is not None else 0)
        rh = min(64, max(40, avail / max(1, len(rows))))
        cells = ["".join(td.itertext()) for tr in rows for td in tr.findall("td")]
        ncol = max(1, len(rows[0].findall("td"))) if rows else 1
        size = fit([max(cells, key=len, default="")], CW / ncol - 24, rh - 8, 20, 13)
        tb = E("table", id="table", x=M, y=TOP, width=CW, height=rh * len(rows), font="body", size=float(size), color=c["ink"],
               header_fill=c["primary"], header_color=c["on"], fill=c["surface"], padding=12)
        if el.get("columns"):
            tb.set("columns", el.get("columns"))
        for tr in rows:
            tb.append(copy.deepcopy(tr))
        out.append(tb)
        if note is not None:
            out.append(text(M, BOTTOM - 40, CW, 40, note, "caption", 16.0, c["muted"]))
        return out

    def l_steps(self, el, page, total):
        c = self.c
        out = self.chrome(el, page)
        st = el.findall("step")
        n = len(st)
        if not 3 <= n <= 6:
            raise ValueError("layout steps needs 3 to 6 <step title=...> children")
        w = CW / n
        out.append(E("shape", id="track", type="line", x=M + w / 2, y=TOP + 52, width=CW - w, height=0, stroke=c["accent"],
                     stroke_width=3.0))
        ts = min(fit([s.get("title") or ""], w - 24, 92, 24, 14, lh=1.15, em=0.62) for s in st)
        th = max(est([s.get("title") or ""], w - 24, ts, 1.15, em=0.62) for s in st) + 8
        by = TOP + 104 + th + 12
        bs = min(fit(plain(s), w - 24, BOTTOM - by, 22, 13, lh=1.35) for s in st)
        for i, s in enumerate(st):
            x = M + i * w
            out += [E("shape", id=f"dot{i + 1}", type="ellipse", x=x + w / 2 - 28, y=TOP + 24, width=56, height=56, fill=c["primary"]),
                    text(x + w / 2 - 28, TOP + 24, 56, 56, str(i + 1), "heading", 24.0, c["on"], align="center", anchor="middle", bold="true"),
                    text(x + 12, TOP + 104, w - 24, th, s.get("title") or "", "heading", ts, c["ink"], align="center", bold="true", line_height="1.15", id=f"step{i + 1}-title"),
                    text(x + 12, by, w - 24, BOTTOM - by, s, "body", bs, c["muted"], align="center", line_height="1.35", id=f"step{i + 1}-text")]
        return out

    def l_image(self, el, page, total):
        c = self.c
        out = self.chrome(el, page)
        out.append(E("image", id="image", x=M, y=TOP, width=560, height=BOTTOM - TOP, src=el.get("src") or ""))
        out.append(self.items_text(el, 656, TOP, 560, BOTTOM - TOP, 24, 16))
        return out


LAYOUTS = sorted(n[2:].replace("_", "-") for n in dir(Layouts) if n.startswith("l_"))
