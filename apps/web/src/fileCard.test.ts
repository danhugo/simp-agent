import { describe, expect, it } from "vitest";
import { toolLabel, writtenFile } from "./Chat";

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
it("toolLabel: short plain line, no raw args", () => {
  const c = call;
  expect(toolLabel(c("read", { path: "src/app.py" }), true)).toBe("Read src/app.py");
  expect(toolLabel(c("edit", { path: "a.py", edits: [] }), true)).toBe("Edited a.py");
  expect(toolLabel(c("bash", { command: "npm test\necho hi" }), true)).toBe("Ran `npm test`");
  expect(toolLabel(c("bash", { command: "ls" }), false)).toBe("Running `ls`");
  expect(toolLabel(c("web_search", { query: "vite" }), true)).toBe("Searched the web: vite");
  expect(toolLabel(c("web_fetch", { url: "https://docs.python.org/3/" }), true)).toBe("Opened docs.python.org");
  expect(toolLabel(c("make_plan", { x: 1 }), true)).toBe("Make plan");
});
