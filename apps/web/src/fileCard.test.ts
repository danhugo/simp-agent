import { describe, expect, it } from "vitest";
import { writtenFile } from "./Chat";

const call = (name: string, args: Record<string, unknown>) => ({ id: "c1", name, arguments: args });
const ok = { is_error: false }, err = { is_error: true };

describe("writtenFile: which tool calls get a file card", () => {
  it("write and edit with a path, after a successful result", () => {
    expect(writtenFile(call("write", { path: "src/a.py", content: "x" }), ok)).toBe("src/a.py");
    expect(writtenFile(call("edit", { path: "b.md", edits: [] }), ok)).toBe("b.md");
  });
  it("not before the result, not on error", () => {
    expect(writtenFile(call("write", { path: "a" }))).toBeUndefined();
    expect(writtenFile(call("write", { path: "a" }), err)).toBeUndefined();
  });
  it("not for other tools or a missing path", () => {
    expect(writtenFile(call("read", { path: "a" }), ok)).toBeUndefined();
    expect(writtenFile(call("bash", { command: "echo > a" }), ok)).toBeUndefined();
    expect(writtenFile(call("write", {}), ok)).toBeUndefined();
  });
});
