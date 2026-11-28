// The components every deck can import from "deck". The deck's own components are plain React on top of these.
import { createElement as h } from "react";

const url = (src) => (src && src.startsWith("/") ? "file://" + src : src);

/** One 1280×720 slide. bg: its background colour (also the PowerPoint slide background). notes: speaker notes. */
export const Slide = ({ bg, notes, className = "", style, children }) =>
  h("section", { "data-slide": "", "data-notes": notes || undefined, className: "slide " + className,
                 style: { background: bg, ...style } }, children);

/** A picture: .svg/.png/.jpg path (office.art makes SVG artwork). Sized by CSS; keep the aspect ratio. */
export const Art = ({ src, className, style, alt = "" }) =>
  h("img", { src: url(src), "data-src": src, className, style, alt });

/** A real PowerPoint chart (editable data). type: column, bar, line, area, pie, doughnut, scatter.
 * series: [{ name, values: [..] }], categories: [..], colors: ["#hex", ..], legend: none|bottom|right|top,
 * labels: data labels on the chart, e.g. "percent", "category,percent", "value" (default none). */
export const Chart = ({ type, categories = [], series = [], colors = [], legend, labels, fontSize = 16,
                        textColor = "#595959", className, style, children, ...rest }) =>
  h("div", { className, style: { position: "relative", ...style },
             "data-chart": JSON.stringify({ type, categories, series, colors, legend, labels, fontSize, textColor,
                                            unknown: Object.keys(rest) }) },
    h(Preview, { type, categories, series, colors, textColor, labels }));

const PALETTE = ["#3182F6", "#F59E0B", "#10B981", "#EF4444", "#8B5CF6", "#64748B"];
/** A rough picture of the chart for the HTML preview only (the .pptx gets a real chart). */
function Preview({ type, categories, series, colors, textColor, labels }) {
  const col = (i) => colors[i] || PALETTE[i % PALETTE.length];
  const all = series.flatMap((s) => s.values.map(Number)), max = Math.max(1, ...all);
  const W = 1000, H = 600, n = Math.max(1, categories.length || (series[0]?.values.length ?? 1));
  const kids = [];
  if (type === "pie" || type === "doughnut" || type === "donut") {
    const vals = (series[0]?.values || []).map(Number), sum = vals.reduce((a, b) => a + b, 0) || 1;
    let a0 = -Math.PI / 2;
    vals.forEach((v, i) => {
      const a1 = a0 + (v / sum) * 2 * Math.PI, r = 260, cx = 500, cy = 300, big = a1 - a0 > Math.PI ? 1 : 0;
      kids.push(h("path", { key: i, fill: col(i), d: `M${cx},${cy} L${cx + r * Math.cos(a0)},${cy + r * Math.sin(a0)} A${r},${r} 0 ${big} 1 ${cx + r * Math.cos(a1)},${cy + r * Math.sin(a1)} Z` }));
      if (labels && labels !== "none") {
        const m = (a0 + a1) / 2, lr = type === "pie" ? r * 0.62 : r * 0.75;
        const parts = [/categor/.test(labels) && categories[i], /percent/.test(labels) && `${Math.round((v / sum) * 100)}%`,
                       /value/.test(labels) && v].filter((x) => x !== false && x !== undefined);
        kids.push(h("text", { key: "l" + i, x: cx + lr * Math.cos(m), y: cy + lr * Math.sin(m), textAnchor: "middle",
                              dominantBaseline: "middle", fontSize: 26, fill: "#fff", fontWeight: 700 }, parts.join(" ")));
      }
      a0 = a1;
    });
    if (type !== "pie") kids.push(h("circle", { key: "hole", cx: 500, cy: 300, r: 130, fill: "#fff" }));
  } else {
    const gw = W / n;
    series.forEach((s, si) => {
      if (type === "line" || type === "area") {
        const pts = s.values.map((v, i) => `${gw * (i + 0.5)},${H - 40 - (v / max) * (H - 80)}`).join(" ");
        kids.push(h("polyline", { key: si, points: pts, fill: "none", stroke: col(si), strokeWidth: 8 }));
      } else {
        const bw = (gw * 0.7) / series.length;
        s.values.forEach((v, i) => {
          const bh = (v / max) * (H - 80);
          kids.push(h("rect", { key: `${si}-${i}`, x: gw * i + gw * 0.15 + bw * si, y: H - 40 - bh, width: bw, height: bh, fill: col(si) }));
        });
      }
    });
    categories.forEach((c, i) => kids.push(h("text", { key: "c" + i, x: gw * (i + 0.5), y: H - 8, textAnchor: "middle",
                                                        fontSize: 28, fill: textColor }, c)));
  }
  return h("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: /pie|donut|doughnut/.test(type) ? "xMidYMid meet" : "none", "data-preview": "",
                    style: { position: "absolute", inset: 0, width: "100%", height: "100%" } }, kids);
}
