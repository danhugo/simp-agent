// a hood: a thick shell over the head, open for the face, falling to the cheeks, a soft point at the back
// a hood: a thick shell over the whole head, open for the face; it falls down the back and sides to the cheeks
const c = "#6a4a8a";
let hood = H.shell(H.sphere(p, [0, 0.05, -0.05], 1.12), 0.07);
hood = Math.max(hood, -0.6 - p[1]);
hood = Math.max(hood, -Math.max(p[1] - 0.45, -p[2] - 0.05, Math.abs(p[0]) - 0.8));  // the face opening
const peak = [H.lock(p, [0, 1.05, -0.2], [0, 1.25, -0.75], 0.25, [0, 1.3, -0.4]), c];  // a soft point at the back
const rim = [Math.max(H.torus(H.tilt(p, [0, 0, 0.55], "x", 90), [0, 0, 0.55], 0.95, 0.07), -0.6 - p[1]), "#8f6fb0"];
return H.union([hood, c], peak, rim);
