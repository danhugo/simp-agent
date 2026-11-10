import { describe, expect, it } from "vitest";
import { approx } from "./location";

describe("approx", () => {
  it("rounds to 1 decimal (~10 km)", () => {
    expect(approx(37.5665, 126.978)).toEqual({ lat: 37.6, lon: 127 });
    expect(approx(-33.8688, 151.2093)).toEqual({ lat: -33.9, lon: 151.2 });
  });
});
