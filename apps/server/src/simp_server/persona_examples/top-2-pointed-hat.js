// a tall pointed hat with a wide brim: worn, the crown wraps the head, the brim is wider than the head
const c = "#3f6f4a";
const crown = H.above([H.sphere(p, [0, 0.05, 0], 1.08), c], p, 0.5);
const brim = [H.cyl(p, [0, 0.55, 0], 1.45, 0.05), c];
const cone = [H.cone(H.tilt(p, [0, 0.6, 0], "z", -12), [0, 0.6, 0], 0.85, 1.5), c];
const band = [H.torus(p, [0, 0.66, 0], 0.88, 0.09), "#d8c06a"];
return H.union(crown, brim, cone, band);
