/**
 * Persona outfits: LLM-written JavaScript (the body of `wear(p, H)`), a signed-distance function in head space
 * (head = unit sphere, +y up, +x right of the picture, +z out of the face). Mascot3D ray-marches it into the same
 * pixel grid, 4-tone palette and outline as the head. The code is the model's, run in this page: the user accepted
 * that risk; we only hide the obvious globals and check the result's shape before using it.
 */
export type Part = [number, string] | null;
export type Wear = (p: number[]) => Part;
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

/** Compile and check the model's code. Throws a message the model can act on. */
export function compileSkin(code: string): Wear {
  let fn: (...a: unknown[]) => unknown;
  try {
    fn = new Function("p", "H", ...HIDDEN, `"use strict";\n${code}`) as typeof fn;
  } catch (e) {
    throw new Error(`syntax error: ${(e as Error).message}`);
  }
  const wear: Wear = (p) => fn(p, H) as Part;
  // shape and speed check on random points in the allowed box
  let rnd = 12345;
  const r = () => ((rnd = (rnd * 16807) % 2147483647) / 2147483647);
  const t0 = performance.now();
  let inside = 0;
  for (let i = 0; i < 3000; i++) {
    const p = [r() * 3.2 - 1.6, r() * 3.5 - 1.6, r() * 3.2 - 1.6];
    let out: unknown;
    try { out = wear(p); } catch (e) { throw new Error(`threw at p=${JSON.stringify(p.map((v) => +v.toFixed(2)))}: ${(e as Error).message}`); }
    if (out === null || out === undefined) continue;
    if (!Array.isArray(out) || typeof out[0] !== "number" || !Number.isFinite(out[0]) || typeof out[1] !== "string" || !/^#[0-9a-f]{6}$/i.test(out[1]))
      throw new Error(`must return null or [finiteNumber, "#rrggbb"], got ${JSON.stringify(out)?.slice(0, 120)}`);
    if (out[0] < 0) inside++;
  }
  const ms = performance.now() - t0;
  if (ms > 120) throw new Error(`too slow: 3000 calls took ${ms.toFixed(0)} ms (budget 120 ms); simplify the code`);
  if (!inside) throw new Error("the outfit is empty: no sampled point was inside any part (distance < 0)");
  // the face must stay visible: nothing may cover the eyes (just in front of the sphere)
  for (const x of [-0.31, 0.31]) {
    const out = wear([x, 0.02, 1.0]);
    if (out && out[0] < 0) throw new Error(`the outfit covers the eyes: point [${x}, 0.02, 1.0] is inside the ${out[1]} part; keep the face (y between -0.45 and 0.5 on the front, z > 0.6) clear`);
  }
  return wear;
}

// the saved persona's outfit, shown by every Mascot3D unless one is passed explicitly
let current: Wear | null = null;
const subs = new Set<() => void>();
export const getSkin = () => current;
export function setSkin(w: Wear | null) { current = w; subs.forEach((f) => f()); }
export function onSkin(f: () => void) { subs.add(f); return () => { subs.delete(f); }; }
