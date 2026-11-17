import { describe, expect, it } from "vitest";
import { compileSkin } from "./skin";

const BEANIE = `
const cap = H.above([H.sphere(p, [0, 0.1, 0], 1.08), "#d94141"], p, 0.55);
const band = [H.torus(p, [0, 0.6, 0], 0.85, 0.1), "#b02e2e"];
const pom = [H.sphere(p, [0, 1.25, 0], 0.18), "#ffffff"];
const shorts = H.below([H.shell(H.head(p), 0.06), "#3463c9"], p, -0.3);
return H.union(cap, band, pom, shorts);`;

describe("compileSkin", () => {
  it("accepts the prompt's example and places it", () => {
    const w = compileSkin(BEANIE);
    expect(w([0, 1.25, 0])?.[1]).toBe("#ffffff");          // pom on top
    expect(w([0, 0.7, 0])![0]).toBeLessThan(0);             // inside the cap
    expect(w([0, -0.9, 0.42])?.[1]).toBe("#3463c9");        // shorts on the lower half
  });
  it("gives the model actionable errors", () => {
    expect(() => compileSkin("return [")).toThrow(/syntax/);
    expect(() => compileSkin("return [1, 'red']")).toThrow(/#rrggbb/);
    expect(() => compileSkin("return null")).toThrow(/empty/);
    expect(() => compileSkin("return window.x")).toThrow(/threw/);
    expect(() => compileSkin("return [H.head(p) - 0.1, '#ff0000']")).toThrow(/covers the eyes/);
  });
});
