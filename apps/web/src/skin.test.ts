import { describe, expect, it } from "vitest";
import { compilePaint, compileSkin } from "./skin";

const BEANIE = `
const cap = H.above([H.sphere(p, [0, 0.1, 0], 1.08), "#d94141"], p, 0.55);
const band = [H.torus(p, [0, 0.6, 0], 0.85, 0.1), "#b02e2e"];
const pom = [H.sphere(p, [0, 1.25, 0], 0.18), "#ffffff"];
const shorts = H.below([H.shell(H.head(p), 0.06), "#3463c9"], p, -0.5);
return H.union(cap, band, pom, shorts);`;

describe("compileSkin", () => {
  it("accepts the prompt's example and places it", () => {
    const w = compileSkin(BEANIE);  // hat + shorts: no slot, so no placement check
    expect(w([0, 1.25, 0])?.[1]).toBe("#ffffff");          // pom on top
    expect(w([0, 0.7, 0])![0]).toBeLessThan(0);             // inside the cap
    expect(w([0, -0.9, 0.42])?.[1]).toBe("#3463c9");        // shorts on the lower half
  });
  it("boxes hold thin edge parts that random samples miss (else they are cut off when drawn)", () => {
    const w = compileSkin(`return H.union(H.above([H.sphere(p,[0,0.1,0],1.08),"#d02020"],p,0.55), [H.box(p,[-1.1,1.2,0],[0.4,0.03,0.03]),"#111111"]);`, "hat");
    expect(w([-1.48, 1.2, 0])![0]).toBeLessThan(0);   // the feather's far tip is part of the hat...
    expect(w.boxes![0].lo[0]).toBeLessThan(-1.5);      // ...and inside its box
  });
  it("gives the model actionable errors", () => {
    expect(() => compileSkin("return [")).toThrow(/syntax/);
    expect(() => compileSkin("return [1, 'red']")).toThrow(/#rrggbb/);
    expect(() => compileSkin("return null")).toThrow(/empty/);
    expect(() => compileSkin("return window.x")).toThrow(/threw/);
    expect(() => compileSkin("return [H.head(p) - 0.1, '#ff0000']")).toThrow(/covers the eyes/);
    expect(() => compileSkin("return [H.sphere(p, [0, 1.6, 0], 0.3), '#ff0000']", "hat")).toThrow(/floats.*Measured/);
    expect(() => compileSkin("return H.below([H.shell(H.head(p), 0.06), '#3463c9'], p, -0.3)", "hat")).toThrow(/over the face|covers the face/);
    expect(() => compileSkin("return H.below([H.shell(H.head(p), 0.06), '#3463c9'], p, -0.5)", "bottom")).not.toThrow();
  });
  it("face paint: baked lookup, actionable errors", () => {
    const p = compilePaint(`return Math.abs(Math.abs(lon) - 18) < 4 && lat > 6 && lat < 22 ? "#9b7fb0" : Math.abs(lat + 15) < 6 ? "skin" : null;`);
    expect(p(18, 14)).toBe("#9b7fb0");   // a stroke above the right eye
    expect(p(33, -15)).toBe("skin");     // blush cleared
    expect(p(0, 40)).toBeNull();
    expect(() => compilePaint("return 'red'")).toThrow(/#rrggbb/);
    expect(() => compilePaint("return null")).toThrow(/nothing/);
    expect(() => compilePaint("return [")).toThrow(/syntax/);
    const brow = compilePaint(`return D.curve(Math.abs(lon), lat, [7, 23], [18, 32], [30, 24], 3, 3, 7.5) ? "#3b2a20" : D.dot(lon, lat, [0, -30], 4) ? "#ff0000" : null;`);
    expect(brow(-18, 27.5)).toBe("#3b2a20");  // the arch's middle, mirrored to the left brow
    expect(brow(18, 20)).toBeNull();          // under the arch
    expect(brow(0, -30)).toBe("#ff0000");
  });
});

describe("hair", () => {
  it("side locks may fall past the ears, the face stays clear", () => {
    const side = `return H.union(H.above([H.sphere(p,[0,0.06,-0.06],1.06),"#5a1d16"],p,0.3), [H.lock(p,[0.75,0.45,0.2],[1.15,-0.35,0.3],0.24),"#5a1d16"], [H.lock(p,[-0.75,0.45,0.2],[-1.15,-0.35,0.3],0.24),"#5a1d16"]);`;
    expect(() => compileSkin(side, "hat")).not.toThrow();
    expect(() => compileSkin(`return [H.sphere(p,[0,0.1,0.9],0.4),"#5a1d16"]`, "hat")).toThrow(/over the face|covers the eyes/);
  });
});
