import { describe, expect, it } from "vitest";
import { hasRaw, kindOf, tooBig } from "./fileKind";

describe("kindOf: file type -> viewer", () => {
  it.each([
    ["src/app.py", "code"], ["a.ts", "code"], ["Makefile", "code"], ["notes.txt", "code"], ["x.yaml", "code"],
    ["README.md", "markdown"], ["pic.PNG", "image"], ["logo.svg", "image"], ["data.csv", "sheet"], ["b.xlsx", "office"],
    ["doc.docx", "office"], ["site/index.html", "html"], ["paper.pdf", "pdf"], ["deck.pptx", "office"], ["a.zip", "info"],
  ])("%s -> %s", (name, kind) => expect(kindOf(name)).toBe(kind));
  it("Rendered/Raw only for markdown and html", () => {
    expect(hasRaw("markdown") && hasRaw("html")).toBe(true);
    expect(hasRaw("code") || hasRaw("image")).toBe(false);
  });
});

describe("tooBig: size caps", () => {
  const MB = 1024 * 1024;
  it("text over 2 MB", () => {
    expect(tooBig("code", 2 * MB)).toBe(false);
    expect(tooBig("code", 2 * MB + 1)).toBe(true);
    expect(tooBig("markdown", 3 * MB)).toBe(true);
  });
  it("others over 20 MB", () => {
    expect(tooBig("image", 3 * MB)).toBe(false);
    expect(tooBig("pdf", 20 * MB + 1)).toBe(true);
  });
});
