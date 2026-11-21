// a knitted beanie with a pom-pom: a crown over the top of the head, a band, no brim
const c = "#2f8f8a";
const crown = H.above([H.sphere(p, [0, 0.12, 0], 1.1), c], p, 0.32);  // pulled down over the head to the brow
const band = [H.torus(p, [0, 0.38, 0], 1.0, 0.12), "#1f6662"];
const pom = [H.sphere(p, [0, 1.3, 0], 0.22), "#f4f1e8"];
return H.union(crown, band, pom);
