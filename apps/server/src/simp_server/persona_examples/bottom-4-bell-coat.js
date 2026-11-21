// form 3 BELL in two layers: an open coat with a dot pattern over a dark robe (the coat is cut open in front so the robe shows)
const cut = -1.65, robe = "#2f2a3a", coatC = "#3a8f86";
const bell = (s) => Math.max(0.5 * H.cone(p, [0, cut, 0], 1.3 * s, 2.9)
  + 0.5 * (Math.hypot(p[0] / (1.3 * s), (p[1] - cut) / 1.45, p[2] / (1.3 * s)) - 1) * 1.3, p[1] + 0.5, cut - p[1]);
const base = [Math.max(H.sphere([p[0], (p[1] - cut) * 1.6, p[2]], [0, 0, 0], 0.85) / 1.6, p[1] - cut - 0.05), robe];
const inner = H.below([bell(0.92), robe], p, -0.5);
const w = 0.16 + (-0.5 - p[1]) * 0.3;  // the front opening widens toward the hem
let coat = H.below([H.shell(bell(1.04), 0.05), coatC], p, -0.5);
coat = H.cut(coat, Math.max(Math.abs(p[0]) - w, -p[2]));
// pattern: dots on a grid wrapped around the coat (angle x height)
const a = Math.atan2(p[0], p[2]) * 1.6, u = a - Math.floor(a), v = p[1] * 3 - Math.floor(p[1] * 3);
const dot = Math.hypot(u - 0.5, (v - 0.5) * 0.8) < 0.18;
return H.union(inner, base, coat && [coat[0], dot ? "#f1ead6" : coatC]);
