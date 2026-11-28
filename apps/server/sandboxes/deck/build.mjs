// deck.jsx -> (React, then Chromium lays it out) -> officecli batch ops (JSON) + the rendered HTML.
// Usage: node deck-build.mjs <deck.jsx> <ops.json> <deck.html>
// The deck module: `export default function Deck() { return <>…<Slide>…</Slide>…</> }`, optional `export const css`.
import { writeFileSync, mkdtempSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";
// esbuild, puppeteer-core and react live in the sandbox's node modules (NODE_PATH), which ESM imports do not search
const NODE = (process.env.NODE_PATH || "/opt/simp/node/node_modules").split(":")[0];
const need = createRequire(join(NODE, "_"));
const { build } = need("esbuild");
const puppeteer = need("puppeteer-core");

const HERE = dirname(fileURLToPath(import.meta.url));
const [src, opsOut, htmlOut] = process.argv.slice(2);
const W = 1280, H = 720, PT = 0.75;  // canvas px; 1 px = 0.75 pt (960 x 540 pt = 16:9)
const BASE = `*{box-sizing:border-box;margin:0;padding:0}body{background:#888}
.slide{width:${W}px;height:${H}px;position:relative;overflow:hidden;background:#fff;font-family:Arial,sans-serif;
font-size:24px;line-height:1.25;color:#111}`;

// 1. JSX -> one HTML page (React on the server side of the build, in this process)
const tmp = mkdtempSync(join(tmpdir(), "deck-"));
const entry = `import Deck, * as M from ${JSON.stringify(resolve(src))};
import { renderToStaticMarkup } from "react-dom/server"; import { createElement } from "react";
module.exports.html = "<!doctype html><html><head><meta charset=utf-8><style>" + ${JSON.stringify(BASE)} + (M.css || "")
  + "</style></head><body>" + renderToStaticMarkup(createElement(Deck)) + "</body></html>";`;
const bundle = join(tmp, "deck.cjs");
try {
  await build({ stdin: { contents: entry, resolveDir: dirname(resolve(src)), loader: "jsx" }, bundle: true,
                platform: "node", format: "cjs", outfile: bundle, jsx: "automatic", logLevel: "silent",
                alias: { deck: join(HERE, "runtime.jsx") }, nodePaths: [NODE],
                loader: { ".jsx": "jsx", ".js": "jsx" } });
} catch (e) {
  console.error((e.errors || []).map((x) => `${x.location ? `${x.location.file}:${x.location.line}: ` : ""}${x.text}`).join("\n") || e.message);
  process.exit(2);
}
const { html } = createRequire(import.meta.url)(bundle);
writeFileSync(htmlOut, html);

// 2. Chromium lays it out; read every box, text run, picture and chart with its real position
const browser = await puppeteer.launch({ executablePath: process.env.CHROME || "/usr/local/bin/chromium",
                                         args: ["--no-sandbox", "--disable-dev-shm-usage", "--allow-file-access-from-files"] });
const page = await browser.newPage();
await page.setViewport({ width: W, height: H });
await page.goto(pathToFileURL(resolve(htmlOut)).href, { waitUntil: "load" });
await page.evaluate(() => document.fonts.ready);
const slides = await page.evaluate(() => {
  const color = (c) => {
    const m = /rgba?\(([^)]+)\)/.exec(c || "");
    if (!m) return null;
    const [r, g, b, a = "1"] = m[1].split(/[ ,/]+/).filter(Boolean);
    if (+a === 0) return null;
    return { hex: [r, g, b].map((x) => (+x).toString(16).padStart(2, "0")).join("").toUpperCase(), a: +a };
  };
  const inline = (el) => getComputedStyle(el).display.startsWith("inline") && !["IMG", "svg"].includes(el.tagName);
  const out = [];
  for (const slide of document.querySelectorAll("[data-slide]")) {
    const S = slide.getBoundingClientRect(), items = [], warn = [];
    const box = (el) => { const r = el.getBoundingClientRect(); return { x: r.left - S.left, y: r.top - S.top, w: r.width, h: r.height }; };
    const runsOf = (el) => {  // text + its inline children, each piece with its own style
      const runs = [];
      const walk = (node) => {
        for (const c of node.childNodes) {
          if (c.nodeType === 3) {
            const t = c.textContent.replace(/\s+/g, " ");
            if (!t.trim() && !runs.length) continue;
            const cs = getComputedStyle(c.parentElement);
            runs.push({ text: t, size: parseFloat(cs.fontSize), color: color(cs.color)?.hex || "000000",
                        bold: +cs.fontWeight >= 600, italic: cs.fontStyle === "italic",
                        underline: cs.textDecorationLine.includes("underline"),
                        font: cs.fontFamily.split(",")[0].replace(/["']/g, "").trim(),
                        upper: cs.textTransform === "uppercase", spacing: parseFloat(cs.letterSpacing) || 0 });
          } else if (c.nodeType === 1 && c.tagName === "BR") runs.push({ br: true });
          else if (c.nodeType === 1 && inline(c)) walk(c);
        }
      };
      walk(el);
      while (runs.length && !runs[runs.length - 1].br && !runs[runs.length - 1].text.trim()) runs.pop();
      if (runs.length && runs[runs.length - 1].text) runs[runs.length - 1].text = runs[runs.length - 1].text.trimEnd();
      if (runs.length && runs[0].text) runs[0].text = runs[0].text.trimStart();
      return runs;
    };
    const visit = (el) => {
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden" || +cs.opacity === 0) return;
      const b = box(el), id = el.getAttribute("data-src-id") || "";
      if (el !== slide) {
        if (el.dataset.chart) { items.push({ kind: "chart", ...b, spec: JSON.parse(el.dataset.chart), id }); return; }
        if (el.tagName === "IMG") { items.push({ kind: "picture", ...b, src: el.dataset.src || el.getAttribute("src"), id }); return; }
        if (el.tagName.toLowerCase() === "svg") { items.push({ kind: "svg", ...b, svg: el.outerHTML, id }); return; }
        const fill = color(cs.backgroundColor), bw = parseFloat(cs.borderTopWidth) || 0;
        if (cs.backgroundImage !== "none") warn.push(`${el.tagName.toLowerCase()}.${el.className}: background-image is not carried over (use a solid colour, or an <Art> picture)`);
        if (cs.boxShadow !== "none") warn.push(`${el.tagName.toLowerCase()}.${el.className}: box-shadow is not carried over`);
        if (fill || bw) items.push({ kind: "box", ...b, fill, border: bw ? { w: bw, c: color(cs.borderTopColor) } : null,
                                     radius: parseFloat(cs.borderTopLeftRadius) || 0, opacity: +cs.opacity, id });
      }
      const hasText = [...el.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim());
      if (el !== slide && hasText && !inline(el)) {
        const pl = parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth), pt = parseFloat(cs.paddingTop) + parseFloat(cs.borderTopWidth);
        const pr = parseFloat(cs.paddingRight) + parseFloat(cs.borderRightWidth), pb = parseFloat(cs.paddingBottom) + parseFloat(cs.borderBottomWidth);
        const lh = cs.lineHeight === "normal" ? 1.2 : parseFloat(cs.lineHeight) / parseFloat(cs.fontSize);
        const bullet = el.tagName === "LI" && cs.listStyleType !== "none" ? (el.parentElement.tagName === "OL" ? "numbered" : "bullet") : null;
        items.push({ kind: "text", x: b.x + pl, y: b.y + pt, w: b.w - pl - pr, h: b.h - pt - pb, runs: runsOf(el), align: cs.textAlign,
                     valign: cs.display.includes("flex") ? ({ center: "middle", "flex-end": "bottom" }[cs.alignItems] || "top") : "top",
                     lh, bullet, id });
      }
      for (const c of el.children) if (!(hasText && inline(c))) visit(c);
    };
    visit(slide);
    out.push({ bg: color(getComputedStyle(slide).backgroundColor)?.hex, notes: slide.dataset.notes || "", items, warn });
  }
  return out;
});
await browser.close();

// 3. officecli batch ops (the same props office_build's XML path uses)
const pt = (px) => `${Math.round(px * PT * 100) / 100}pt`;
const ops = [{ command: "set", path: "/", props: { slideWidth: pt(W), slideHeight: pt(H) } }];
const warnings = [], errors = [];
slides.forEach((s, i) => {
  const n = i + 1, at = `/slide[${n}]`;
  ops.push({ command: "add", parent: "/", type: "slide", props: s.bg ? { background: "#" + s.bg } : {} });
  let k = 0;
  for (const w of s.warn) warnings.push(`slide ${n}: ${w}`);
  for (const it of s.items) {
    const sid = String(n * 1000 + ++k), geo = { x: pt(it.x), y: pt(it.y), width: pt(it.w), height: pt(it.h) };
    if (it.x < -1 || it.y < -1 || it.x + it.w > W + 1 || it.y + it.h > H + 1) {
      if (it.kind === "text") warnings.push(`slide ${n}: text "${(it.runs[0]?.text || "").slice(0, 30)}" runs off the slide`);
    }
    if (it.kind === "box") {
      const props = { id: sid, name: `box${k}`, ...geo, fill: it.fill ? "#" + it.fill.hex : "none",
                      line: it.border ? `#${it.border.c?.hex || "000000"}:${Math.round(it.border.w * PT * 100) / 100}pt` : "none",
                      geometry: "rect" };
      if (it.radius) props.geometry = "roundRect", props.adj = `adj:val ${Math.round(Math.min(50000, it.radius / Math.min(it.w, it.h) * 100000))}`;
      const a = (it.fill ? it.fill.a : 1) * it.opacity;
      if (a < 1) props.opacity = String(Math.round(a * 100) / 100);
      ops.push({ command: "add", parent: at, type: "shape", props });
    } else if (it.kind === "picture") {
      if (!it.src || (it.src.startsWith("/") && !existsSync(it.src))) {
        errors.push(`slide ${n}: picture not found: ${it.src || "(no src)"} (save it first, e.g. office.art(..., out=...))`);
        continue;
      }
      ops.push({ command: "add", parent: at, type: "picture", props: { id: sid, name: `picture${k}`, ...geo, src: it.src } });
    } else if (it.kind === "svg") {
      const f = join(tmp, `inline-${n}-${k}.svg`);
      writeFileSync(f, it.svg.includes("xmlns") ? it.svg : it.svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"'));
      ops.push({ command: "add", parent: at, type: "picture", props: { id: sid, name: `drawing${k}`, ...geo, src: f } });
    } else if (it.kind === "chart") {
      const c = it.spec, types = { donut: "doughnut" };
      const props = { id: sid, name: `chart${k}`, ...geo, chartType: types[c.type] || c.type,
                      data: (c.series || []).map((x, j) => `${String(x.name || `Series ${j + 1}`).replace(/[:;]/g, " ")}:${x.values.join(",")}`).join(";"),
                      legend: c.legend || (["pie", "doughnut", "donut"].includes(c.type) ? "right" : "none") };
      if (c.categories) props.categories = c.categories.join(",");
      if (c.colors) props.colors = c.colors.map((x) => x.replace("#", "")).join(",");
      const spec = `${Math.round(c.fontSize * PT * 10) / 10}:${(c.textColor || "#595959").replace("#", "")}`;
      Object.assign(props, { axisfont: spec, legendFont: spec });
      ops.push({ command: "add", parent: at, type: "chart", props });
    } else if (it.kind === "text" && it.runs.length) {
      const small = Math.min(...it.runs.filter((r) => !r.br).map((r) => r.size));
      if (small < 18) warnings.push(`slide ${n}: text "${(it.runs.find((r) => r.text)?.text || "").slice(0, 40)}" is ${small}px: `
                                    + "too small to read when presented (18px+, body 24px+)");
      const shape = `${at}/shape[@id=${sid}]`;
      // a little extra width: PowerPoint's text metrics differ slightly from Chromium's; never wrap earlier
      ops.push({ command: "add", parent: at, type: "shape", props: { id: sid, name: `text${k}`, x: geo.x, y: geo.y,
        width: pt(it.w * 1.03 + 2), height: geo.height, fill: "none", line: "none", margin: "0pt",
        valign: it.valign, autoFit: "none", lineSpacing: `${Math.round(it.lh * 100) / 100}x` } });
      const paras = [[]];
      for (const r of it.runs) r.br ? paras.push([]) : paras[paras.length - 1].push(r);
      const align = { start: "left", end: "right", justify: "justify" }[it.align] || it.align;
      paras.forEach((runs, p) => {
        const pp = { align: ["left", "right", "center", "justify"].includes(align) ? align : "left" };
        if (it.bullet) pp.list = it.bullet;
        ops.push({ command: "add", parent: shape, type: "paragraph", props: pp });
        for (const r of runs.length ? runs : [{ text: " ", size: 12, color: "000000" }]) {
          const rp = { text: r.upper ? r.text.toUpperCase() : r.text, size: pt(r.size), color: "#" + r.color };
          if (r.bold) rp.bold = "true";
          if (r.italic) rp.italic = "true";
          if (r.underline) rp.underline = "true";
          if (r.font) rp.font = r.font;
          if (r.spacing) rp.spacing = String(Math.round(r.spacing * PT * 100) / 100);  // points, a bare number
          ops.push({ command: "add", parent: `${shape}/paragraph[${p + 2}]`, type: "run", props: rp });
        }
      });
      ops.push({ command: "remove", path: `${shape}/paragraph[1]` });
    }
  }
  if (s.notes) ops.push({ command: "add", parent: at, type: "notes", props: { text: s.notes } });
});
// the whole slide: content that ends below the slide (the slide clips it) is the usual cause of "runs off the slide"
slides.forEach((s, i) => {
  const bottom = Math.max(0, ...s.items.filter((x) => x.kind === "text").map((x) => x.y + x.h));
  if (bottom > H + 1) warnings.push(`slide ${i + 1}: its content is ${Math.round(bottom - H)}px taller than the slide `
    + `(ends at ${Math.round(bottom)}px of ${H}): cut text, shrink sizes or gaps, or split the slide`);
});
writeFileSync(opsOut, JSON.stringify(ops));
console.log(JSON.stringify({ slides: slides.length, ops: ops.length, warnings, errors }));
if (errors.length) process.exit(3);
