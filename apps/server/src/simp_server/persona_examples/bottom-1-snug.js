// form 1 SNUG, a small round thing (a ladybug shell): a thin shell hugging the lower ball, a pattern by where p is
const shell = H.below([H.shell(H.head(p), 0.06), "#d8342c"], p, -0.5);
const spot = [[-0.45, -0.75, 0.62], [0.45, -0.75, 0.62], [0, -1.0, 0.3], [-0.75, -0.7, -0.1], [0.75, -0.7, -0.1]]
  .some((c) => Math.hypot(p[0] - c[0], p[1] - c[1], p[2] - c[2]) < 0.2);
const seam = Math.abs(p[0]) < 0.04 && p[2] < 0;  // the line between the wing cases, at the back
return shell && [shell[0], spot || seam ? "#1d1a1a" : "#d8342c"];
