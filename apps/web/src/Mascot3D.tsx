import { useEffect, useRef } from "react";

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
type Pal = Record<"hi" | "base" | "mid" | "low" | "out" | "eye" | "blush" | "sweat" | "hot", [number, number, number] | null>;

function readPal(): Pal {
  const s = getComputedStyle(document.documentElement);
  const rgb = (k: string): [number, number, number] | null => {
    const v = s.getPropertyValue(`--m3-${k}`).trim();
    if (!v.startsWith("#")) return null;
    const n = parseInt(v.slice(1), 16);
    return [n >> 16, (n >> 8) & 255, n & 255];
  };
  return { hi: rgb("hi"), base: rgb("base"), mid: rgb("mid"), low: rgb("low"), out: rgb("out"), eye: rgb("eye"), blush: rgb("blush"), sweat: rgb("sweat"), hot: rgb("hot") };
}

function eyeDist(lon: number, lat: number, lonC: number, blink: number) {
  let best = 99;
  for (let i = 0; i <= 12; i++) {
    const u = i / 12, alon = lonC + (u - 0.5) * 20, alat = -1 + Math.sin(u * Math.PI) * 8 * (1 - blink);
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
function render(ctx: CanvasRenderingContext2D, N: number, pal: Pal, yaw: number, pitch: number, blink: number, focus = 0, overload = 0) {
  const img = ctx.createImageData(N, N), R = N / 2 - 0.6, c = N / 2, eyeW = (1.4 * 24) / N + 1.6;
  for (let py = 0; py < N; py++) for (let px = 0; px < N; px++) {
    const u = (px + 0.5 - c) / R, v = -(py + 0.5 - c) / R, d2 = u * u + v * v;
    if (d2 > 1) continue;
    const z = Math.sqrt(1 - d2);
    let col: [number, number, number] | null;
    if (pal.out && d2 > (1 - 1.4 / R) ** 2) col = pal.out;
    else {
      const lit = Math.max(0, u * LIGHT[0] + v * LIGHT[1] + z * LIGHT[2]);
      col = lit > 0.93 ? pal.hi : lit > 0.62 ? pal.base : lit > 0.32 ? pal.mid : pal.low;
      const y1 = v * Math.cos(pitch) + z * Math.sin(pitch), z1 = -v * Math.sin(pitch) + z * Math.cos(pitch);
      const x2 = u * Math.cos(yaw) - z1 * Math.sin(yaw), z2 = u * Math.sin(yaw) + z1 * Math.cos(yaw);
      if (z2 > 0) {
        const lon = deg(Math.atan2(x2, z2)), lat = deg(Math.asin(Math.max(-1, Math.min(1, y1))));
        const squint = Math.max(blink, focus * 0.8);  // focused: the ^ ^ flattens into narrowed eyes
        const eye = overload > 0.5
          ? Math.min(chevronDist(lon, lat, -18, 1), chevronDist(lon, lat, 18, -1))
          : Math.min(eyeDist(lon, lat, -18, squint), eyeDist(lon, lat, 18, squint));
        const cheek = 1 + overload * 0.5;  // cheeks grow and turn red when overloaded
        if (eye < eyeW) col = pal.eye;
        else if (focus > 0.5 && pal.sweat && (((lon - 40) / 5) ** 2 + ((lat - 24) / (lat > 24 ? 4 : 7)) ** 2 < 1)) col = pal.sweat;  // drop on the brow
        else if (((lon - 33) / (9 * cheek)) ** 2 + ((lat + 15) / (4.5 * cheek)) ** 2 < 1 || ((lon + 33) / (9 * cheek)) ** 2 + ((lat + 15) / (4.5 * cheek)) ** 2 < 1)
          col = overload > 0.5 && pal.hot ? pal.hot : pal.blush;
      }
    }
    if (!col) continue;
    const i = (py * N + px) * 4;
    img.data[i] = col[0]; img.data[i + 1] = col[1]; img.data[i + 2] = col[2]; img.data[i + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
}

export function Mascot3D({ size = 120, pixels = 48, working = false, className }: {
  size?: number; pixels?: number; working?: boolean; className?: string;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const steam = useRef<HTMLSpanElement>(null);
  const workingRef = useRef(working);
  workingRef.current = working;
  useEffect(() => {
    const cv = canvas.current, ctx = cv?.getContext("2d");
    if (!cv || !ctx) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let pal = readPal(), blink = 0, raf = 0, timer = 0, since = 0, focus = 0, overload = 0;
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
      const t = workingRef.current ? { yaw: 0, pitch: rad(20) } : target, k = reduce ? 1 : 0.12;
      cur.yaw += (t.yaw - cur.yaw) * k; cur.pitch += (t.pitch - cur.pitch) * k;
      const shake = focused && !reduce ? rad(Math.sin(now / 45) * 2.2) : 0;  // straining: a tiny fast tremble
      render(ctx, pixels, pal, cur.yaw + shake, cur.pitch, blink, focus, overload);
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
      cancelAnimationFrame(raf); clearTimeout(timer); themeObs.disconnect();
      removeEventListener("pointermove", onMove); document.removeEventListener("pointerleave", onLeave);
    };
  }, [pixels]);
  return (
    <span className={`mascot3d ${working ? "working" : ""} ${className ?? ""}`} style={{ width: size }} aria-hidden="true">
      <span ref={steam} className="mascot3d-steam"><i /><i /></span>
      <canvas ref={canvas} width={pixels} height={pixels} style={{ width: size, height: size }} />
      <span className="mascot3d-shadow" />
    </span>
  );
}
