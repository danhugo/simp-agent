import { describe, expect, it } from "vitest";
import { parseCards } from "./Chat";

describe("parseCards", () => {
  it("keeps http(s) cards and drops bad images", () => {
    const c = parseCards(JSON.stringify({ cards: [
      { url: "https://a.com", title: "A", snippet: "s", image: "https://i/a.png" },
      { url: "javascript:alert(1)", title: "x" },
      { url: "http://b.com", title: "B", image: "data:x" },
    ] }));
    expect(c).toEqual([
      { url: "https://a.com", title: "A", snippet: "s", image: "https://i/a.png" },
      { url: "http://b.com", title: "B", snippet: "", image: "" },
    ]);
  });
  it("returns [] for non-JSON (e.g. an error string)", () => {
    expect(parseCards("show_cards error: nope")).toEqual([]);
  });
});
