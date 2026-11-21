// form 3 BELL, a skirt: slightly rounded sides, a flat hem at y = -1.65, a narrower round base under it. Always this size
const c = "#7a4fd0", cut = -1.65;
const flare = [Math.max(0.5 * H.cone(p, [0, cut, 0], 1.3, 2.9)
  + 0.5 * (Math.hypot(p[0] / 1.3, (p[1] - cut) / 1.45, p[2] / 1.3) - 1) * 1.3, p[1] + 0.5, cut - p[1]), c];
const base = [Math.max(H.sphere([p[0], (p[1] - cut) * 1.6, p[2]], [0, 0, 0], 0.85) / 1.6, p[1] - cut - 0.05), c];
const skirt = H.below(H.union(flare, base), p, -0.5);
const waist = [H.torus(p, [0, -0.52, 0], 0.88, 0.09), "#4b2e8f"];
return H.union(skirt, waist);
