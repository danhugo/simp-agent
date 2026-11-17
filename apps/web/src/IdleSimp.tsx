import { useEffect, useRef, useState } from "react";
import { type Face, readPal, render, SKIN_VIEW } from "./Mascot3D";
import { getSkin } from "./skin";

/**
 * When the chat sits idle, Simp hops down from the end of the conversation onto the top edge of the message box
 * and plays there. Each trip it picks one game at random (Stroll, Peek or Nap) and keeps at it until it goes home.
 * Sending a message sends it hopping back home; typing, mouse moves and scrolling leave it playing. Off with prefers-reduced-motion.
 * The idle delay is 60s; e2e tests shorten it with localStorage "simp.idleMs".
 */
const SIZE = 36, N = 48, R = SIZE / 2;
const rad = (d: number) => (d * Math.PI) / 180;
const ease = (p: number) => (p < 0.5 ? 2 * p * p : 1 - (-2 * p + 2) ** 2 / 2);
const idleMs = () => { try { return Number(localStorage.getItem("simp.idleMs")) || 60_000; } catch { return 60_000; } };
const HOP_MS = 750;
type Spot = { x: number; y: number };
type Jump = { t0: number; from: Spot; to: Spot; dir: 1 | -1; done?: () => void };
type Pose = { x: number; y: number; sx?: number; sy?: number; yaw?: number; pitch?: number; face?: Face };

/** A real jump (the "Real jump" on public/mascot-hop.html): crouch, gravity arc, squash on landing. k is 0..1. */
function jumpPose(k: number, { from, to, dir }: Jump): Pose {
  if (k < 0.18) {  // crouch
    const c = Math.sin((k / 0.18) * Math.PI / 2);
    return { x: from.x, y: from.y, sx: 1 + 0.22 * c, sy: 1 - 0.25 * c, yaw: dir * 25 * c, pitch: dir < 0 ? -10 : 10 };
  }
  if (k < 0.82) {  // flight: a parabola from -> apex -> to (screen y grows downward)
    const q = (k - 0.18) / 0.64, a = from.y, b = to.y, h = Math.min(a, b) - (dir > 0 ? 50 : 60);
    const A = 2 * a + 2 * b - 4 * h, B = -3 * a - b + 4 * h, vy = B + 2 * A * q, st = Math.min(0.15, Math.abs(vy) / 2000);
    return { x: from.x + (to.x - from.x) * q, y: a + B * q + A * q * q, sx: 1 - st, sy: 1 + st, yaw: dir * 30, pitch: vy > 0 ? 18 : -14,
      face: { roll: dir * Math.sin(q * Math.PI) * 0.35 } };
  }
  const q = (k - 0.82) / 0.18, s = Math.sin(q * Math.PI) * (1 - q * 0.4);  // land: squash and a smile
  return { x: to.x, y: to.y, sx: 1 + 0.28 * s, sy: 1 - 0.3 * s, yaw: dir * 30 * (1 - q), face: q < 0.6 ? { h: 11 } : {} };
}

export function IdleSimp({ enabled }: { enabled: boolean }) {
  const [on, setOn] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const cv = useRef<HTMLCanvasElement>(null);
  const zz = useRef<HTMLSpanElement>(null);
  const leaving = useRef(false);

  // come out when no message has been sent for a while; hop home when one is sent (enabled turns false)
  useEffect(() => {
    if (!enabled || matchMedia("(prefers-reduced-motion: reduce)").matches) {
      if (box.current?.classList.contains("on")) goHome(); else setOn(false);
      return;
    }
    const timer = window.setTimeout(() => setOn(true), idleMs());
    return () => clearTimeout(timer);
  }, [enabled]);

  // where the conversation's Simp sits, in our box's coordinates (x from the left, y = bottom offset, + is down)
  const homeSpot = () => {
    const home = document.querySelector(".run-status canvas, .idle-mascot canvas")?.getBoundingClientRect(), b = box.current?.getBoundingClientRect();
    return home && b ? { x: home.left - b.left, y: home.bottom - b.bottom } : null;
  };
  const pos = useRef({ x: 0, y: 0 });
  const jump = useRef<Jump | null>(null);
  const goHome = () => {
    if (leaving.current) return;
    leaving.current = true;
    const done = () => { leaving.current = false; jump.current = null; setOn(false); };
    const to = homeSpot();
    if (!to) return done();
    jump.current = { t0: performance.now(), from: { ...pos.current }, to, dir: -1, done };
  };

  // play loop while out
  useEffect(() => {
    if (!on) return;
    const c = cv.current, ctx = c?.getContext("2d"), b = box.current;
    if (!c || !ctx || !b) return;
    const pal = readPal(), start = performance.now();
    // the persona's outfit: render SKIN_VIEW times more pixels on a canvas that grows around the head,
    // so the head keeps its size and its feet stay where the games put them
    const wear = getSkin(), n = wear ? N * SKIN_VIEW : N;
    c.width = c.height = n;
    if (wear) {
      const big = SIZE * SKIN_VIEW, m = (SIZE - big) / 2;
      Object.assign(c.style, { width: `${big}px`, height: `${big}px`, marginLeft: `${m}px`, marginBottom: `${m}px`,
        transformOrigin: `50% ${50 + 50 / SKIN_VIEW}%` });  // squash around the head's bottom, not the canvas's
    }
    let napFrom: number | null = null, raf = 0, blink = 0, napStart = start, cyStart = start;
    // each trip down picks one game and keeps playing it until Simp goes home
    const game = (["stroll", "peek", "nap"] as const)[Math.floor(Math.random() * 3)];
    const cur = { yaw: 0, pitch: 0 };
    const x0 = 24;
    pos.current = { x: x0, y: 0 };
    const from = homeSpot();
    if (from) jump.current = { t0: start, from, to: { x: x0, y: 0 }, dir: 1, done: () => { cyStart = napStart = performance.now(); } };
    const blinkTimer = window.setInterval(() => {
      const s = performance.now();
      const st = (n: number) => { const p = (n - s) / 170; blink = p < 1 ? Math.sin(p * Math.PI) : 0; if (p < 1) requestAnimationFrame(st); };
      requestAnimationFrame(st);
    }, 3800);
    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      const j = jump.current;
      if (j) {  // hopping down or home
        const k = Math.min(1, (now - j.t0) / HOP_MS), ps = jumpPose(k, j);
        cur.yaw += (rad(ps.yaw ?? 0) - cur.yaw) * 0.25; cur.pitch += (rad(ps.pitch ?? 0) - cur.pitch) * 0.25;
        render(ctx, n, pal, cur.yaw, cur.pitch, blink, 0, 0, ps.face, wear);
        c.style.transform = `translate(${ps.x}px, ${ps.y}px) scale(${ps.sx ?? 1}, ${ps.sy ?? 1})`;
        if (zz.current) zz.current.textContent = "";
        if (k >= 1) { jump.current = null; j.done?.(); }
        return;
      }
      const W = b.clientWidth - SIZE - 8, t = (now - cyStart) / 1000;
      let x = pos.current.x, y = 0, yaw = 0, pitch = 0, hide = 0, face: Face = {}, zzz = "";
      if (game === "nap") {
        // nap: roll to the right end (whole turns, so the face ends upright), then sleep
        const napT = (now - napStart) / 1000;
        if (napFrom === null) napFrom = x;
        const x1 = napFrom, p = Math.min(1, napT / 3);
        x = x1 + ease(p) * (W - x1);
        const turns = Math.max(1, Math.round((W - x1) / (2 * Math.PI * R)));
        face = p < 1 ? { roll: ease(p) * turns * 2 * Math.PI } : { eyes: "flat" };
        yaw = p < 1 ? 35 : 0; pitch = p < 1 ? 0 : 14; y = p < 1 ? 0 : 2 + Math.sin(napT * 1.5) * 1.5;
        if (p >= 1) zzz = "z".repeat(1 + (Math.floor(napT * 1.2) % 3));
      } else if (game === "stroll") {
        // stroll (as in the preview page): walk right with little hops, stop and look around, walk back
        const p = (t % 12) / 12;
        const go = p < 0.35 ? ease(p / 0.35) : p < 0.5 ? 1 : p < 0.85 ? 1 - ease((p - 0.5) / 0.35) : 0;
        x = x0 + go * Math.max(40, W - 120);
        const moving = p < 0.35 || (p > 0.5 && p < 0.85);
        yaw = moving ? (p < 0.35 ? 30 : -30) : Math.sin(t * 2.2) * 35;
        y = moving ? -Math.abs(Math.sin(t * 9)) * 3 : 0;
      } else {
        // peek: sink behind the box, pop up somewhere else, look at you, hide again
        const p = (t % 4) / 4, k = Math.floor(t / 4);
        x = 24 + ((k * 0.618 + 0.2) % 1) * (W - 48);
        hide = p < 0.15 ? 1 - p / 0.15 : p < 0.6 ? 0 : p < 0.75 ? (p - 0.6) / 0.15 : 1;
        face = { eyes: "round" }; pitch = -10; yaw = Math.sin(t * 3) * 12;
      }
      pos.current = { x, y };
      cur.yaw += (rad(yaw) - cur.yaw) * 0.15; cur.pitch += (rad(pitch) - cur.pitch) * 0.15;
      render(ctx, n, pal, cur.yaw, cur.pitch, face.eyes === "flat" ? 0 : blink, 0, 0, face, wear);
      c.style.transform = `translate(${x}px, ${y + hide * SIZE}px)`;
      if (zz.current) { zz.current.textContent = zzz; zz.current.style.transform = `translate(${x + SIZE - 4}px, ${-((t * 8) % 14)}px)`; }
    };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); clearInterval(blinkTimer); };
  }, [on]);

  return (
    <div ref={box} className={`idle-simp ${on ? "on" : ""}`} aria-hidden="true">
      {on && <canvas ref={cv} width={N} height={N} />}
      {on && <span ref={zz} className="idle-zz" />}
    </div>
  );
}
