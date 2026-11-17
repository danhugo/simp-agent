import { useEffect, useRef } from "react";
import { getSkin, onSkin, type Wear } from "./skin";

/**
 * Simp's head as a real 3D sphere rendered into a small pixel grid (default 48x48) and scaled up crisply.
 * Each pixel is lit (light from the upper left, fixed) and snapped to a 4-tone palette; the smiling eyes and blush
 * are painted on the sphere surface, so when the head turns toward the pointer they slide over the curve.
 * Colors come from the --m3-* CSS variables (light/dark). Blinks now and then; respects prefers-reduced-motion.
 */
const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;
const LIGHT = (() => { const v = [-0.55, 0.62, 0.56]; const n = Math.hypot(...v); return v.map((x) => x / n); })();
const FOCUS_AFTER_MS = 2 * 60 * 1000;     // 2 min of continuous work: focused (squint, sweat, tremble)
const OVERLOAD_AFTER_MS = 5 * 60 * 1000;  // 5 min: overloaded (> < eyes, red cheeks, steam)
/** Short-lived or state-driven faces beyond idle/working (see public/mascot-states.html). */
export type Mood = "idle" | "done" | "asking" | "error" | "stopped";
export type Face = { roll?: number; h?: number; eyes?: "arc" | "round" | "flat"; sweat?: boolean; blush?: boolean; yaw?: number; pitch?: number };
const FACES: Record<Mood, Face> = {
  idle: {},
  done: { h: 11 },                                            // big happy ^ ^ (plus one hop, in CSS)
  asking: { eyes: "round", pitch: -14, sweat: true },         // round eyes looking up at you, sweat drop
  error: { h: -6, pitch: 24, blush: false },                  // sad eyes, looking down
  stopped: { eyes: "flat", yaw: -22, pitch: 6 },              // flat eyes, turned aside
};
type Pal = Record<"hi" | "base" | "mid" | "low" | "out" | "eye" | "blush" | "sweat" | "hot", [number, number, number] | null>;

export function readPal(): Pal {
  const s = getComputedStyle(document.documentElement);
  const rgb = (k: string): [number, number, number] | null => {
    const v = s.getPropertyValue(`--m3-${k}`).trim();
    if (!v.startsWith("#")) return null;
    const n = parseInt(v.slice(1), 16);
    return [n >> 16, (n >> 8) & 255, n & 255];
  };
  return { hi: rgb("hi"), base: rgb("base"), mid: rgb("mid"), low: rgb("low"), out: rgb("out"), eye: rgb("eye"), blush: rgb("blush"), sweat: rgb("sweat"), hot: rgb("hot") };
}

function eyeDist(lon: number, lat: number, lonC: number, blink: number, h = 8) {
  let best = 99;
  for (let i = 0; i <= 12; i++) {
    const u = i / 12, alon = lonC + (u - 0.5) * 20, alat = -1 + Math.sin(u * Math.PI) * h * (1 - blink);
    best = Math.min(best, Math.hypot((lon - alon) * Math.cos(rad(lat)), lat - alat));
  }
  return best;
}

// distance from (lon, lat) to a "> <" eye: two strokes meeting at the inner tip (dir +1 for ">", -1 for "<")
function chevronDist(lon: number, lat: number, lonC: number, dir: number) {
  const seg = (ax: number, ay: number, bx: number, by: number) => {
    const px = lon - ax, py = lat - ay, vx = bx - ax, vy = by - ay;
    const t = Math.max(0, Math.min(1, (px * vx + py * vy) / (vx * vx + vy * vy)));
    return Math.hypot(px - t * vx, py - t * vy);
  };
  const tipX = lonC + dir * 6, backX = lonC - dir * 6;
  return Math.min(seg(backX, 6, tipX, 0), seg(tipX, 0, backX, -6));
}

/** focus 0..1: squinting eyes and a sweat drop; overload 0..1: "> <" eyes and red cheeks */
const SKIN_VIEW = 2;  // with an outfit the camera backs off so a hat or skirt fits: view = +-2 head radii
const hexCache = new Map<string, [number, number, number]>();
const hex = (h: string) => {
  let c = hexCache.get(h);
  if (!c) { const n = parseInt(h.slice(1), 16); c = [n >> 16, (n >> 8) & 255, n & 255]; hexCache.set(h, c); }
  return c;
};
// the head's 4 tones, applied to an outfit color: highlight, base, mid, low
const tone = (c: [number, number, number], lit: number): [number, number, number] => {
  const k = lit > 0.93 ? 1.28 : lit > 0.62 ? 1 : lit > 0.32 ? 0.76 : 0.55;
  return k > 1 ? c.map((x) => Math.round(x + (255 - x) * (k - 1))) as [number, number, number]
    : c.map((x) => Math.round(x * k)) as [number, number, number];
};

/** focus 0..1: squinting eyes and a sweat drop; overload 0..1: "> <" eyes and red cheeks; skin: a persona outfit */
export function render(ctx: CanvasRenderingContext2D, N: number, pal: Pal, yaw: number, pitch: number, blink: number, focus = 0, overload = 0, face: Face = {}, skin: Wear | null = null) {
  const img = ctx.createImageData(N, N), S = skin ? SKIN_VIEW : 1, R = (N / 2 - 0.6) / S, c = N / 2, eyeW = (1.4 * 24) / (N / S) + 1.6;  // by the head's own pixel size, so eyes look the same with an outfit
  const rl = face.roll ?? 0, cr = Math.cos(rl), sr = Math.sin(rl), cp = Math.cos(pitch), sp = Math.sin(pitch), cy = Math.cos(yaw), sy = Math.sin(yaw);
  // view space (u right, v up, z toward the viewer) -> head space, the same turn the painted face gets
  const toHead = (u: number, v: number, z: number) => {
    const ru = u * cr - v * sr, rv = u * sr + v * cr, y1 = rv * cp + z * sp, z1 = -rv * sp + z * cp;
    return [ru * cy - z1 * sy, y1, ru * sy + z1 * cy];
  };
  const dist = (u: number, v: number, z: number) => skin!(toHead(u, v, z))?.[0] ?? 1;
  // the outfit's boxes (head space): a ray is marched only over the stretches where it is inside one
  const boxes = skin?.boxes ?? [{ lo: [-2, -2, -2], hi: [2, 2, 2] }];
  const B = toHead(0, 0, 1);  // the view ray's direction in head space (same for every pixel)
  // per frame: the outfit only changes with the pose, so a blink-only frame reuses the last outfit pass
  const key = skin ? `${N}|${yaw}|${pitch}|${rl}` : "";
  const cached = skin && outfitCache.wear === skin && outfitCache.key === key ? outfitCache : null;
  const hits = cached ? cached.hits : skin ? new Float32Array(N * N * 4).fill(-1) : null;  // z, r, g, b per pixel
  const mask = skin ? new Uint8Array(N * N) : null;  // 1 = head, 2 = outfit (for the outfit's outline)
  for (let py = 0; py < N; py++) for (let px = 0; px < N; px++) {
    const u = (px + 0.5 - c) / R, v = -(py + 0.5 - c) / R, d2 = u * u + v * v;
    const zHead = d2 <= 1 ? Math.sqrt(1 - d2) : -Infinity;
    if (skin && hits) {
      const o = (py * N + px) * 4;
      if (!cached) {
        // ray p(z) = A + z*B in head space; march each box's stretch, nearest first, until a hit
        const A = toHead(u, v, 0), spans: [number, number][] = [];
        for (const bx of boxes) {
          let zIn = SKIN_VIEW + 0.3, zOut = zHead;
          for (let k = 0; k < 3 && zIn > zOut; k++) {
            if (Math.abs(B[k]) < 1e-9) { if (A[k] < bx.lo[k] || A[k] > bx.hi[k]) zIn = -Infinity; continue; }
            const t1 = (bx.lo[k] - A[k]) / B[k], t2 = (bx.hi[k] - A[k]) / B[k];
            zIn = Math.min(zIn, Math.max(t1, t2)); zOut = Math.max(zOut, Math.min(t1, t2));
          }
          if (zIn > zOut) spans.push([zIn, zOut]);
        }
        spans.sort((x, y) => y[0] - x[0]);
        let z = -Infinity, part = null as ReturnType<Wear>;
        for (const [zIn, zOut] of spans) {
          if (zIn <= z) continue;
          z = zIn;
          for (let i = 0; i < 32 && z > zOut; i++) {
            part = skin(toHead(u, v, z));
            const d = part?.[0] ?? 1;
            if (d < 0.02) break;
            part = null;
            z -= Math.max(d, 0.02);  // baked distances are smooth: full steps are safe
          }
          if (part) break;
        }
        {
          if (part && z > zHead) {
            // normal from 4 samples (tetrahedron), lit like the head
            const e = 0.025, k1 = dist(u + e, v - e, z - e), k2 = dist(u - e, v - e, z + e), k3 = dist(u - e, v + e, z - e), k4 = dist(u + e, v + e, z + e);
            const nx = k1 - k2 - k3 + k4, ny = -k1 - k2 + k3 + k4, nz = -k1 + k2 - k3 + k4;
            const nl = Math.hypot(nx, ny, nz) || 1, lit = Math.max(0, (nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2]) / nl);
            const col = tone(hex(part[1]), lit);
            hits[o] = z; hits[o + 1] = col[0]; hits[o + 2] = col[1]; hits[o + 3] = col[2];
          }
        }
      }
      if (hits[o] !== -1 && hits[o] > zHead) {
        const i = (py * N + px) * 4;
        img.data[i] = hits[o + 1]; img.data[i + 1] = hits[o + 2]; img.data[i + 2] = hits[o + 3]; img.data[i + 3] = 255;
        mask![py * N + px] = 2;
        continue;
      }
    }
    if (d2 > 1) continue;
    if (mask) mask[py * N + px] = 1;
    const z = zHead;
    let col: [number, number, number] | null;
    if (pal.out && d2 > (1 - 1.4 / R) ** 2) col = pal.out;
    else {
      const lit = Math.max(0, u * LIGHT[0] + v * LIGHT[1] + z * LIGHT[2]);
      col = lit > 0.93 ? pal.hi : lit > 0.62 ? pal.base : lit > 0.32 ? pal.mid : pal.low;
      // roll turns the painted face around the view axis (light stays put); positive = clockwise, i.e. rolling right
      const [x2, y1, z2] = toHead(u, v, z);
      if (z2 > 0) {
        const lon = deg(Math.atan2(x2, z2)), lat = deg(Math.asin(Math.max(-1, Math.min(1, y1))));
        const squint = Math.max(blink, focus * 0.8);  // focused: the ^ ^ flattens into narrowed eyes
        const eye = overload > 0.5
          ? Math.min(chevronDist(lon, lat, -18, 1), chevronDist(lon, lat, 18, -1))
          : face.eyes === "round" ? Math.min(...[-18, 18].map((c) => Math.abs(Math.hypot((lon - c) * Math.cos(rad(lat)), lat - 1) - 5 * (1 - blink))))
          : face.eyes === "flat" ? Math.min(...[-18, 18].map((c) => Math.hypot(lon - Math.max(c - 9, Math.min(c + 9, lon)), lat)))
          : Math.min(eyeDist(lon, lat, -18, squint, face.h), eyeDist(lon, lat, 18, squint, face.h));
        const cheek = 1 + overload * 0.5;  // cheeks grow and turn red when overloaded
        if (eye < eyeW) col = pal.eye;
        else if ((focus > 0.5 || face.sweat) && pal.sweat && (((lon - 40) / 5) ** 2 + ((lat - 24) / (lat > 24 ? 4 : 7)) ** 2 < 1)) col = pal.sweat;  // drop on the brow
        else if (face.blush === false) { /* no blush */ }
        else if (((lon - 33) / (9 * cheek)) ** 2 + ((lat + 15) / (4.5 * cheek)) ** 2 < 1 || ((lon + 33) / (9 * cheek)) ** 2 + ((lat + 15) / (4.5 * cheek)) ** 2 < 1)
          col = overload > 0.5 && pal.hot ? pal.hot : pal.blush;
      }
    }
    if (!col) continue;
    const i = (py * N + px) * 4;
    img.data[i] = col[0]; img.data[i + 1] = col[1]; img.data[i + 2] = col[2]; img.data[i + 3] = 255;
  }
  // outfit outline: an outfit pixel next to anything that is not outfit gets the outline color, like the head's rim
  if (mask && pal.out) for (let py = 0; py < N; py++) for (let px = 0; px < N; px++) {
    if (mask[py * N + px] !== 2) continue;
    const edge = [[1, 0], [-1, 0], [0, 1], [0, -1]].some(([dx, dy]) => {
      const x = px + dx, y = py + dy;
      return x < 0 || y < 0 || x >= N || y >= N || mask[y * N + x] === 0;
    });
    if (edge) { const i = (py * N + px) * 4; img.data[i] = pal.out[0]; img.data[i + 1] = pal.out[1]; img.data[i + 2] = pal.out[2]; }
  }
  if (skin && hits && !cached) { outfitCache.wear = skin; outfitCache.key = key; outfitCache.hits = hits; }
  ctx.putImageData(img, 0, 0);
}
const outfitCache: { wear: Wear | null; key: string; hits: Float32Array } = { wear: null, key: "", hits: new Float32Array(0) };

export function Mascot3D({ size = 120, pixels = 48, working = false, mood = "idle", className, skin, onSkinError }: {
  size?: number; pixels?: number; working?: boolean; mood?: Mood; className?: string;
  /** an outfit to wear; undefined = the saved persona's, null = none */
  skin?: Wear | null; onSkinError?: (msg: string) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const steam = useRef<HTMLSpanElement>(null);
  const workingRef = useRef(working);
  workingRef.current = working;
  const moodRef = useRef(mood);
  moodRef.current = mood;
  const skinRef = useRef(skin);
  skinRef.current = skin;
  const errRef = useRef(onSkinError);
  errRef.current = onSkinError;
  useEffect(() => {
    const cv = canvas.current, ctx = cv?.getContext("2d");
    if (!cv || !ctx) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let pal = readPal(), blink = 0, raf = 0, timer = 0, since = 0, focus = 0, overload = 0;
    let lastKey = "", lastWear: Wear | null = null, broken: Wear | null = null;
    const offSkin = onSkin(() => { lastKey = ""; });
    const target = { yaw: 0, pitch: 0 }, cur = { yaw: 0, pitch: 0 };
    const onMove = (e: PointerEvent) => {
      const b = cv.getBoundingClientRect();
      const dx = (e.clientX - (b.left + b.width / 2)) / (innerWidth / 2), dy = (e.clientY - (b.top + b.height / 2)) / (innerHeight / 2);
      target.yaw = rad(Math.max(-1, Math.min(1, dx)) * 40);
      target.pitch = rad(Math.max(-1, Math.min(1, dy)) * 28);
    };
    const onLeave = () => { target.yaw = 0; target.pitch = 0; };
    const themeObs = new MutationObserver(() => { pal = readPal(); });  // theme toggles set data-theme on <html>
    themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const frame = () => {
      const now = performance.now();
      if (workingRef.current) { if (!since) since = now; } else since = 0;
      const focused = since > 0 && now - since > FOCUS_AFTER_MS;  // working this long: switch to the focused face
      focus += ((focused ? 1 : 0) - focus) * 0.08;
      const over = since > 0 && now - since > OVERLOAD_AFTER_MS;
      overload += ((over ? 1 : 0) - overload) * 0.08;
      steam.current?.classList.toggle("on", over);
      const face = workingRef.current ? {} : FACES[moodRef.current];
      const posed = face.yaw !== undefined || face.pitch !== undefined;  // a mood with its own pose stops following the pointer
      const t = workingRef.current ? { yaw: 0, pitch: rad(20) } : posed ? { yaw: rad(face.yaw ?? 0), pitch: rad(face.pitch ?? 0) } : target, k = reduce ? 1 : 0.12;
      const sway = moodRef.current === "asking" && !workingRef.current && !reduce ? rad(Math.sin(now / 500) * 10) : 0;
      cur.yaw += (t.yaw - cur.yaw) * k; cur.pitch += (t.pitch - cur.pitch) * k;
      const shake = focused && !reduce ? rad(Math.sin(now / 45) * 2.2) : 0;  // straining: a tiny fast tremble
      let wear = skinRef.current === undefined ? getSkin() : skinRef.current;
      if (wear && wear === broken) wear = null;
      const args = [cur.yaw + shake + sway, cur.pitch, face.eyes === "flat" ? 0 : blink, focus, overload] as const;
      const key = `${args.map((x) => x.toFixed(4))}|${JSON.stringify(face)}|${pal.base}`;
      if (key !== lastKey || wear !== lastWear) {  // an outfit is costly to march: skip frames where nothing moved
        lastKey = key; lastWear = wear;
        // with an outfit the camera backs off SKIN_VIEW times: render that many more pixels, so the head keeps its density
        const n = wear ? Math.round(pixels * SKIN_VIEW) : pixels;
        if (cv.width !== n) { cv.width = n; cv.height = n; }
        try { render(ctx, n, pal, ...args, face, wear); }
        catch (e) { broken = wear; lastKey = ""; errRef.current?.(`threw while drawing: ${(e as Error).message}`); }
      }
      raf = requestAnimationFrame(frame);
    };
    const doBlink = () => {
      const s = performance.now();
      const step = (now: number) => { const p = (now - s) / 170; blink = p < 1 ? Math.sin(p * Math.PI) : 0; if (p < 1) requestAnimationFrame(step); };
      requestAnimationFrame(step);
    };
    const loop = () => { timer = window.setTimeout(() => { if (!reduce) doBlink(); loop(); }, 2800 + Math.random() * 3000); };
    if (!reduce) { addEventListener("pointermove", onMove); document.addEventListener("pointerleave", onLeave); }
    loop();
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf); clearTimeout(timer); themeObs.disconnect(); offSkin();
      removeEventListener("pointermove", onMove); document.removeEventListener("pointerleave", onLeave);
    };
  }, [pixels]);
  return (
    <span className={`mascot3d ${working ? "working" : `mood-${mood}`} ${className ?? ""}`} style={{ width: size, ["--s" as string]: `${size}px` }} aria-hidden="true">
      <span ref={steam} className="mascot3d-steam"><i /><i /></span>
      <canvas ref={canvas} width={pixels} height={pixels} style={{ width: size, height: size }} />
      <span className="mascot3d-shadow" />
    </span>
  );
}
