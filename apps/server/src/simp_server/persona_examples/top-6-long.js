// long straight hair with bangs: a scalp cap, a curtain down the sides and back, open in front for the face
const c = "#6b3d2a";
const scalp = H.above([H.sphere(p, [0, 0.05, -0.05], 1.08), c], p, 0.25);
// long hair: a soft bell around the head, flaring a little toward the ends, open in front for the face
const y = Math.max(-1.3, Math.min(0.3, p[1]));
let d = Math.abs(Math.hypot(p[0], p[2] + 0.12) - (1.0 + 0.2 * Math.max(0, -y) ** 1.5)) - 0.12;
d = Math.max(d, p[1] - 0.4, -1.35 - p[1]);
d = Math.max(d, -H.rbox(p, [0, -0.55, 1.1], [0.82, 1.0, 0.9], 0.45));
const ends = [-2.2, -1.5, -0.8, 0, 0.8, 1.5, 2.2].map((a) => { const s = Math.sin(a + Math.PI), k = Math.cos(a + Math.PI); return [H.lock(p, [1.15 * s, -1.15, 1.15 * k - 0.12], [1.25 * s, -1.6, 1.25 * k - 0.12], 0.18), c]; });
const bangs = [-0.5, -0.17, 0.17, 0.5].map((x) => [H.lock(p, [x * 0.5, 1.0, 0.3], [x * 1.1, 0.42, 1.0], 0.22, [x * 0.8, 0.95, 0.85]), c]);
return H.union(scalp, [d, c], ...ends, ...bangs);
