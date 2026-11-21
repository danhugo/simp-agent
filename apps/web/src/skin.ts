/**
 * Persona outfits: LLM-written JavaScript (the body of `wear(p, H)`), a signed-distance function in head space
 * (head = unit sphere, +y up, +x right of the picture, +z out of the face). Mascot3D ray-marches it into the same
 * pixel grid, 4-tone palette and outline as the head. The code is the model's, run in this page: the user accepted
 * that risk; we only hide the obvious globals and check the result's shape before using it.
 */
export type Part = [number, string] | null;
export type Box = { lo: number[]; hi: number[] };
/** An outfit; `boxes` (head space) hold all of it, one per slot, so the renderer marches only where a ray is inside one. */
export type Wear = ((p: number[]) => Part) & { boxes?: Box[]; grid?: number[] };
type V = number[];

const len = (x: number, y: number, z: number) => Math.hypot(x, y, z);
const sub = (p: V, c: V) => [p[0] - c[0], p[1] - c[1], p[2] - c[2]];

export const H = {
  sphere: (p: V, c: V, r: number) => len(...(sub(p, c) as [number, number, number])) - r,
  box: (p: V, c: V, h: V) => {
    const q = sub(p, c).map((v, i) => Math.abs(v) - h[i]);
    return len(Math.max(q[0], 0), Math.max(q[1], 0), Math.max(q[2], 0)) + Math.min(Math.max(q[0], q[1], q[2]), 0);
  },
  rbox: (p: V, c: V, h: V, r: number) => H.box(p, c, h.map((v) => Math.max(v - r, 0))) - r,
  cyl: (p: V, c: V, r: number, hh: number) => {
    const q = sub(p, c), dx = Math.hypot(q[0], q[2]) - r, dy = Math.abs(q[1]) - hh;
    return Math.min(Math.max(dx, dy), 0) + Math.hypot(Math.max(dx, 0), Math.max(dy, 0));
  },
  cone: (p: V, c: V, r: number, h: number) => {
    const q = sub(p, c), y = q[1], rr = Math.hypot(q[0], q[2]);
    // a cone as the intersection of its slanted side and the base plane (good enough for sphere tracing)
    const side = (rr * h - (h - y) * r) / Math.hypot(h, r);
    return Math.max(side, -y, y - h);
  },
  torus: (p: V, c: V, R: number, r: number) => {
    const q = sub(p, c);
    return Math.hypot(Math.hypot(q[0], q[2]) - R, q[1]) - r;
  },
  /** a tapered lock of hair (or spike, horn): from root a (thickness r) to the pointed tip b, bent toward m if given */
  lock: (p: V, a: V, b: V, r: number, m?: V) => {
    const mid = m ?? a.map((v, k) => (v + b[k]) / 2), at = (t: number) => a.map((v, k) => (1 - t) ** 2 * v + 2 * (1 - t) * t * mid[k] + t * t * b[k]);
    let best = 9, prev = at(0);
    for (let i = 1; i <= 8; i++) {
      const cur = at(i / 8), d = sub(cur, prev), q = sub(p, prev), L = d[0] ** 2 + d[1] ** 2 + d[2] ** 2 || 1;
      const h = Math.max(0, Math.min(1, (q[0] * d[0] + q[1] * d[1] + q[2] * d[2]) / L));
      best = Math.min(best, len(q[0] - d[0] * h, q[1] - d[1] * h, q[2] - d[2] * h) - r * (1 - (i - 1 + h) / 8));
      prev = cur;
    }
    return best;
  },
  shell: (d: number, t: number) => Math.abs(d) - t,
  tilt: (p: V, c: V, ax: "x" | "y" | "z", deg: number) => {
    const a = (-deg * Math.PI) / 180, s = Math.sin(a), k = Math.cos(a), q = sub(p, c);
    const [i, j] = ax === "x" ? [1, 2] : ax === "y" ? [2, 0] : [0, 1];
    const r = [...q];
    r[i] = q[i] * k - q[j] * s; r[j] = q[i] * s + q[j] * k;
    return [r[0] + c[0], r[1] + c[1], r[2] + c[2]];
  },
  union: (...parts: Part[]): Part => {
    let best: Part = null;
    for (const x of parts) if (x && (!best || x[0] < best[0])) best = x;
    return best;
  },
  cut: (a: Part, d: number): Part => (a ? [Math.max(a[0], -d), a[1]] : null),
  /** keep only the piece of part a above / below height y0 */
  above: (a: Part, p: V, y0: number): Part => (a ? [Math.max(a[0], y0 - p[1]), a[1]] : null),
  below: (a: Part, p: V, y0: number): Part => (a ? [Math.max(a[0], p[1] - y0), a[1]] : null),
  smooth: (a: Part, b: Part, k: number): Part => {
    if (!a || !b) return a ?? b;
    const h = Math.max(0, Math.min(1, 0.5 + (0.5 * (b[0] - a[0])) / k));
    return [b[0] * (1 - h) + a[0] * h - k * h * (1 - h), h > 0.5 ? a[1] : b[1]];
  },
  head: (p: V) => len(p[0], p[1], p[2]) - 1,
};

const HIDDEN = ["window", "document", "globalThis", "self", "fetch", "XMLHttpRequest", "WebSocket", "localStorage",
  "sessionStorage", "indexedDB", "navigator", "location", "importScripts", "Function"];

export type Slot = "hat" | "bottom";
/** Face paint: a color (or "skin" to clear the blush there, or null) at a point of the face, in degrees. */
export type Paint = (lon: number, lat: number) => string | null;

/** What a slot's code actually draws, measured by sampling: what the model gets back to "see" its work. */
export interface Report { bbox: [number[], number[]]; colors: string[]; touchesHead: boolean; volume: number }

/** Compile and check one slot's code. Throws a message the model can act on (with the measured report). */
export function compileSkin(code: string, slot?: Slot): Wear {
  let fn: (...a: unknown[]) => unknown;
  try {
    fn = new Function("p", "H", ...HIDDEN, `"use strict";\n${code}`) as typeof fn;
  } catch (e) {
    throw new Error(`syntax error: ${(e as Error).message}`);
  }
  const wear: Wear = (p) => fn(p, H) as Part;
  // shape and speed check on random points in the allowed box, measuring what is drawn
  let rnd = 12345;
  const r = () => ((rnd = (rnd * 16807) % 2147483647) / 2147483647);
  const t0 = performance.now();
  const lo = [9, 9, 9], hi = [-9, -9, -9], colors = new Set<string>();
  let inside = 0, touches = false, misplaced = 0;
  const N = 4000;
  for (let i = 0; i < N; i++) {
    const p = [r() * 3.6 - 1.8, r() * 3.8 - 1.9, r() * 3.6 - 1.8];
    let out: unknown;
    try { out = wear(p); } catch (e) { throw new Error(`threw at p=${JSON.stringify(p.map((v) => +v.toFixed(2)))}: ${(e as Error).message}`); }
    if (out === null || out === undefined) continue;
    if (!Array.isArray(out) || typeof out[0] !== "number" || !Number.isFinite(out[0]) || typeof out[1] !== "string" || !/^#[0-9a-f]{6}$/i.test(out[1]))
      throw new Error(`must return null or [finiteNumber, "#rrggbb"], got ${JSON.stringify(out)?.slice(0, 120)}`);
    if (out[0] >= 0) continue;
    inside++; colors.add(out[1].toLowerCase());
    p.forEach((v, k) => { lo[k] = Math.min(lo[k], v); hi[k] = Math.max(hi[k], v); });
    if (Math.hypot(p[0], p[1], p[2]) < 1.2) touches = true;
    if ((slot === "hat" && (p[1] < -1.5 || (p[1] < 0.3 && p[2] > 0.3 && Math.abs(p[0]) < 0.75))) || (slot === "bottom" && p[1] > -0.15)) misplaced++;
  }
  const ms = performance.now() - t0;
  if (ms > 160) throw new Error(`too slow: ${N} calls took ${ms.toFixed(0)} ms (budget 160 ms); simplify the code`);
  if (!inside) throw new Error("it is empty: no sampled point was inside any part (distance < 0). Parts are probably too thin (< 0.05) or outside the allowed box");
  const f = (v: number) => +v.toFixed(2);
  const report: Report = { bbox: [lo.map(f), hi.map(f)], colors: [...colors].slice(0, 8), touchesHead: touches, volume: f((inside / N) * 3.6 * 3.8 * 3.6) };
  const seen = `Measured: it fills x ${report.bbox[0][0]}..${report.bbox[1][0]}, y ${report.bbox[0][1]}..${report.bbox[1][1]}, z ${report.bbox[0][2]}..${report.bbox[1][2]}; colors ${report.colors.join(" ")}; volume ${report.volume}; ${touches ? "touches" : "does NOT touch"} the head.`;
  // the face must stay visible: nothing may cover the eyes (just in front of the sphere)
  for (const x of [-0.31, 0.31]) {
    const out = wear([x, 0.02, 1.0]);
    if (out && out[0] < 0) throw new Error(`it covers the eyes: point [${x}, 0.02, 1.0] is inside the ${out[1]} part; keep the face (front, y between -0.45 and 0.5) clear. ${seen}`);
  }
  // the whole face (eyes, brows, cheeks), just in front of the sphere: a stray lock or a high collar hides it
  for (let lat = -20; lat <= 12; lat += 4) for (let lon = -32; lon <= 32; lon += 4) {
    const a = (lon * Math.PI) / 180, b = (lat * Math.PI) / 180, q = [1.04 * Math.cos(b) * Math.sin(a), 1.04 * Math.sin(b), 1.04 * Math.cos(b) * Math.cos(a)];
    const out = wear(q);
    if (out && out[0] < 0) throw new Error(`it covers the face: point [${q.map((v) => v.toFixed(2)).join(", ")}] in front of the face is inside the ${out[1]} part. The face (front, |x| < 0.7, y from -0.4 to 0.3) must stay fully clear: bangs end above y = 0.35, side hair hangs at |x| > 0.8, a bottom starts below y = -0.5. ${seen}`);
  }
  if (slot && !touches) throw new Error(`it floats: no part touches the head (sphere of radius 1). ${seen}`);
  if (slot && misplaced / inside > 0.08) throw new Error(slot === "hat"
    ? `${Math.round((misplaced / inside) * 100)}% of the hat/hair is over the face (front, |x| < 0.75, below y = 0.3) or below y = -1.5; bangs end above y = 0.35, long hair falls down the sides (|x| > 0.8) and the back. ${seen}`
    : `${Math.round((misplaced / inside) * 100)}% of the bottom is above y = -0.15, over the face; it stays below y = -0.3 (use H.below). ${seen}`);
  // sampled extent, padded by a few sample spacings so thin edges between samples stay inside
  const blo = lo.map((v) => v - 0.2), bhi = hi.map((v) => v + 0.2);
  // random samples can miss thin parts at the edges (a brim, a feather), and whatever sticks out of the box is
  // never drawn: push each face out while the outfit still crosses it
  const G = 24, LIM = [[-2, 2], [-2, 2.1], [-2, 2]];
  for (let k = 0; k < 3; k++) for (const side of [0, 1]) {
    for (let step = 0; step < 20; step++) {
      const b = side ? bhi : blo, i = (k + 1) % 3, j = (k + 2) % 3;
      if (side ? b[k] >= LIM[k][1] : b[k] <= LIM[k][0]) break;
      let crosses = false;
      for (let a = 0; a <= G && !crosses; a++) for (let c = 0; c <= G && !crosses; c++) {
        const p = [0, 0, 0];
        p[k] = b[k]; p[i] = blo[i] + ((bhi[i] - blo[i]) * a) / G; p[j] = blo[j] + ((bhi[j] - blo[j]) * c) / G;
        const out = wear(p);
        crosses = !!out && out[0] < 0.05;
      }
      if (!crosses) break;
      b[k] = side ? Math.min(LIM[k][1], b[k] + 0.15) : Math.max(LIM[k][0], b[k] - 0.15);
    }
  }
  wear.boxes = [{ lo: blo, hi: bhi }];
  if (report.volume < 0.02) throw new Error(`it is too small to see at 48 pixels (volume ${report.volume}); make the parts chunkier. ${seen}`);
  return wear;
}

/** One slot's code as a standalone object: checked, then baked into its own grid. Throws like compileSkin. */
export const item = (code: string, slot: Slot): Wear => bake(compileSkin(code, slot));

/** Assemble: all objects merged into ONE grid (one unified 3D object), built once. Cheap on baked items. */
export const combine = (ws: (Wear | null)[]): Wear | null => {
  const list = ws.filter((w): w is Wear => !!w);
  if (!list.length) return null;
  const w: Wear = (p) => H.union(...list.map((x) => x(p)));
  if (!list.every((x) => x.boxes)) return w;
  w.boxes = list.flatMap((x) => x.boxes!);
  return bake(w);
};

const CELL = 0.05;  // grid spacing in head units; a screen pixel is ~0.036 at the outfit view

/**
 * Sample an outfit once on a grid over its boxes; the result answers with trilinear distance and the nearest
 * sample's color. The model's code can be slow (it is called ~30k times a frame otherwise): this makes the cost
 * one-off (~100k calls when the outfit changes) and each frame cheap.
 */
export function bake(w: Wear): Wear {
  const boxes = w.boxes!;
  const lo = [0, 1, 2].map((k) => Math.max(-2, Math.min(...boxes.map((b) => b.lo[k]))));
  const hi = [0, 1, 2].map((k) => Math.min(2.1, Math.max(...boxes.map((b) => b.hi[k]))));
  const n = lo.map((v, k) => Math.max(2, Math.ceil((hi[k] - v) / CELL) + 1));
  const [nx, ny, nz] = n, dist = new Float32Array(nx * ny * nz), col = new Uint8Array(nx * ny * nz), colors: string[] = [];
  const colorIdx = new Map<string, number>();
  for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) for (let k = 0; k < nz; k++) {
    const out = w([lo[0] + i * CELL, lo[1] + j * CELL, lo[2] + k * CELL]), at = (i * ny + j) * nz + k;
    dist[at] = out ? out[0] : 1;
    if (out) {
      let c = colorIdx.get(out[1]);
      if (c === undefined) { c = colors.length; colors.push(out[1]); colorIdx.set(out[1], c); }
      col[at] = Math.min(c, 255);
    }
  }
  const baked: Wear = (p) => {
    const fx = (p[0] - lo[0]) / CELL, fy = (p[1] - lo[1]) / CELL, fz = (p[2] - lo[2]) / CELL;
    if (fx < 0 || fy < 0 || fz < 0 || fx > nx - 1 || fy > ny - 1 || fz > nz - 1) return null;
    const i = Math.min(nx - 2, fx | 0), j = Math.min(ny - 2, fy | 0), k = Math.min(nz - 2, fz | 0);
    const x = fx - i, y = fy - j, z = fz - k, a = (i * ny + j) * nz + k, sy = nz, sx = ny * nz;
    const c00 = dist[a] * (1 - z) + dist[a + 1] * z, c01 = dist[a + sy] * (1 - z) + dist[a + sy + 1] * z;
    const c10 = dist[a + sx] * (1 - z) + dist[a + sx + 1] * z, c11 = dist[a + sx + sy] * (1 - z) + dist[a + sx + sy + 1] * z;
    const d = (c00 * (1 - y) + c01 * y) * (1 - x) + (c10 * (1 - y) + c11 * y) * x;
    const near = a + (x > 0.5 ? sx : 0) + (y > 0.5 ? sy : 0) + (z > 0.5 ? 1 : 0);
    return [d, colors[col[near]] ?? colors[0] ?? "#888888"];
  };
  baked.boxes = boxes;
  baked.grid = n;
  return baked;
}

const PSTEP = 1.5;  // face paint table spacing in degrees (a face pixel is ~3 degrees wide)
type Pt = [number, number];
// distance on the face in degrees: lon shrinks with cos(lat) on the sphere, so strokes keep their width up and down
const fdist = (lon: number, lat: number, x: number, y: number) => Math.hypot((lon - x) * Math.cos((lat * Math.PI) / 180), lat - y);
/** Is (lon, lat) on the segment a-b, with the width going from w1 at a to w2 at b (degrees)? Returns 0..1 along it, or -1. */
function onSeg(lon: number, lat: number, a: Pt, b: Pt, w1: number, w2: number): number {
  const dx = b[0] - a[0], dy = b[1] - a[1], L = dx * dx + dy * dy;
  const t = L ? Math.max(0, Math.min(1, ((lon - a[0]) * dx + (lat - a[1]) * dy) / L)) : 0;
  return fdist(lon, lat, a[0] + dx * t, a[1] + dy * t) <= (w1 + (w2 - w1) * t) / 2 ? t : -1;
}
/** Drawing helpers for face paint: true where (lon, lat) is on the stroke. Widths are full widths in degrees. */
export const D = {
  line: (lon: number, lat: number, a: Pt, b: Pt, w1 = 4, w2 = w1) => onSeg(lon, lat, a, b, w1, w2) >= 0,
  /** a smooth curve from a to b bending toward c (a quadratic curve), width w1 -> w2; e.g. a brow tapered at both ends: w1 = w2 = 1 and wMid */
  curve: (lon: number, lat: number, a: Pt, c: Pt, b: Pt, w1 = 4, w2 = w1, wMid = (w1 + w2) / 2) => {
    const N = 12;
    let prev = a;
    for (let i = 1; i <= N; i++) {
      const t = i / N, u = 1 - t, p: Pt = [u * u * a[0] + 2 * u * t * c[0] + t * t * b[0], u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]];
      const w = (k: number) => (k < 0.5 ? w1 + (wMid - w1) * k * 2 : wMid + (w2 - wMid) * (k - 0.5) * 2);
      if (onSeg(lon, lat, prev, p, w((i - 1) / N), w(t)) >= 0) return true;
      prev = p;
    }
    return false;
  },
  dot: (lon: number, lat: number, c: Pt, r = 3) => fdist(lon, lat, c[0], c[1]) <= r,
  /** a round outline: radius r (to the middle of the line), line width w; glasses rims, halos */
  ring: (lon: number, lat: number, c: Pt, r: number, w = 3) => Math.abs(fdist(lon, lat, c[0], c[1]) - r) <= w / 2,
};
/**
 * Compile and check face paint: the body of `paint(lon, lat, D)` (D: stroke helpers), lon/lat in degrees on the head sphere (lon 0 = the
 * middle of the face, + toward the picture's right; lat 0 = eye level, + up). Baked once into a table, so drawing is
 * a lookup. Throws a message the model can act on.
 */
export function compilePaint(code: string): Paint {
  let fn: (...a: unknown[]) => unknown;
  try { fn = new Function("lon", "lat", "D", ...HIDDEN, `"use strict";\n${code}`) as typeof fn; }
  catch (e) { throw new Error(`syntax error: ${(e as Error).message}`); }
  const n = Math.round(180 / PSTEP) + 1, table: (string | null)[] = new Array(n * n), t0 = performance.now();
  const colors = new Set<string>();
  let painted = 0;
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    const lon = -90 + i * PSTEP, lat = -90 + j * PSTEP;
    let out: unknown;
    try { out = fn(lon, lat, D); } catch (e) { throw new Error(`threw at lon=${lon}, lat=${lat}: ${(e as Error).message}`); }
    if (out === null || out === undefined) { table[i * n + j] = null; continue; }
    if (typeof out !== "string" || !(out === "skin" || /^#[0-9a-f]{6}$/i.test(out)))
      throw new Error(`must return null, "skin" or "#rrggbb", got ${JSON.stringify(out)?.slice(0, 80)}`);
    table[i * n + j] = out.toLowerCase();
    if (out !== "skin") { painted++; colors.add(out.toLowerCase()); }
  }
  if (performance.now() - t0 > 300) throw new Error("too slow; simplify the code");
  if (painted < 6) throw new Error("it paints (almost) nothing: return a color where the marks are; strokes at least 4 degrees wide");
  const paint: Paint = (lon, lat) => {
    const i = Math.round((lon + 90) / PSTEP), j = Math.round((lat + 90) / PSTEP);
    return i < 0 || j < 0 || i >= n || j >= n ? null : table[i * n + j];
  };
  return paint;
}

// the saved persona's outfit and face paint, shown by every Mascot3D unless passed explicitly
let current: Wear | null = null, currentPaint: Paint | null = null;
const subs = new Set<() => void>();
export const getSkin = () => current;
export const getPaint = () => currentPaint;
export function setSkin(w: Wear | null, paint: Paint | null = currentPaint) { current = w; currentPaint = paint; subs.forEach((f) => f()); }
export function onSkin(f: () => void) { subs.add(f); return () => { subs.delete(f); }; }
