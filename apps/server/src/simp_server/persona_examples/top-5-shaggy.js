// short shaggy hair that FALLS DOWN, every lock different, two-tone tips (the color picked by height)
// shaggy layered hair that FALLS DOWN. Every lock differs (length, tilt, thickness, bend) and some cross: real hair
// is never evenly spaced or parallel. r(i) is a fixed "random" in 0..1, so the hair looks the same every frame.
const top = "#8a5a9e", tip = "#d07fae";
const r = (i) => { const v = Math.sin(i * 12.9898) * 43758.5453; return v - Math.floor(v); };
const cap = H.cut(H.above([H.sphere(p, [0, 0.08, -0.04], 1.1), top], p, -0.1), Math.max(p[1] - 0.45, -p[2] - 0.2, Math.abs(p[0]) - 0.78));
const locks = [];
for (let i = 0; i < 11; i++) {  // sides and back (angles away from the face), hanging down
  const a = (i < 6 ? 1 : -1) * (1.0 + (i % 6) * 0.42 + r(i) * 0.25), s = Math.sin(a), k = Math.cos(a);
  const len = 0.35 + r(i + 20) * 0.55, tilt = (r(i + 40) - 0.5) * 0.5;  // how far down, and a sideways lean
  locks.push(H.lock(p, [0.95 * s, 0.55 + r(i + 60) * 0.25, 0.95 * k],
    [1.1 * s + tilt * k, 0.2 - len, 1.1 * k - tilt * s], 0.18 + r(i + 80) * 0.12, [1.2 * s, 0.3, 1.2 * k]));
}
for (let i = 0; i < 6; i++) {  // bangs: uneven lengths, leaning left or right, stopping above the eyes
  const x = -0.6 + i * 0.24 + (r(i + 100) - 0.5) * 0.12, lean = (r(i + 120) - 0.5) * 0.35;
  locks.push(H.lock(p, [x * 0.7, 0.98, 0.42], [x + lean, 0.42 + r(i + 140) * 0.18, 1.0], 0.17 + r(i + 160) * 0.1, [x * 0.9 + lean * 0.4, 0.9, 0.86]));
}
const col = p[1] < 0.35 ? tip : top;  // two-tone: the tips are orange
const hair = H.union(cap, [Math.min(...locks), col]);
return hair && [hair[0], col];
