// form 1 SNUG, overalls: a fitted shell on the lower ball plus chunky pieces on the front
const base = H.below([H.shell(H.head(p), 0.06), "#3b6fb6"], p, -0.5);
const bib = H.below([H.rbox(p, [0, -0.7, 0.8], [0.36, 0.22, 0.12], 0.05), "#5b8fd6"], p, -0.5);
const buttons = H.union([H.sphere(p, [-0.26, -0.56, 0.9], 0.09), "#f2c230"], [H.sphere(p, [0.26, -0.56, 0.9], 0.09), "#f2c230"]);
return H.union(base, bib, buttons);
