// form 2 ROUND BODY, a striped suit with a belt: a round belly blended into the head; the pattern is a color chosen by where p is
const body = H.smooth([H.head(p) - 0.03, ""], [H.sphere([p[0], (p[1] + 1.0) * 1.15, p[2]], [0, 0, 0], 1.02) / 1.15, ""], 0.35)[0];
const stripe = (p[1] * 5) - Math.floor(p[1] * 5) < 0.35;  // horizontal stripes
const belt = Math.abs(p[1] + 0.95) < 0.07;
return H.below([body, belt ? "#3a2a1a" : stripe ? "#e8c84a" : "#4f9a4a"], p, -0.5);
