// form 2 ROUND BODY, a person in overalls over a striped shirt: a round belly blended into the head, layers and a pattern by where p is
const body = H.smooth([H.head(p) - 0.03, ""], [H.sphere([p[0], (p[1] + 1.0) * 1.15, p[2]], [0, 0, 0], 1.02) / 1.15, ""], 0.35)[0];
const stripe = (p[1] * 5) - Math.floor(p[1] * 5) < 0.4;  // the shirt: horizontal stripes
const bib = p[2] > 0.2 && Math.abs(p[0]) < 0.42 && p[1] < -0.62;  // the overalls' bib on the front
const pants = p[1] < -1.05;  // and their lower part all around
const strap = Math.abs(Math.abs(p[0]) - 0.32) < 0.07 && p[1] > -0.75;
const buttons = [-0.26, 0.26].map((x) => [H.sphere(p, [x, -0.66, 0.92], 0.07), "#e8c84a"]);
const col = bib || pants || strap ? "#3b6fb6" : stripe ? "#f1ead6" : "#c8463a";
return H.union(H.below([body, col], p, -0.5), ...buttons);
