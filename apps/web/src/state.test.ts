import { describe, expect, it } from "vitest";
import { canContinue, initialState, reduce, type ServerEvent } from "./state";

const run = (evs: ServerEvent[], s = initialState()) => evs.reduce(reduce, s);
const td = (offset: number, delta: string, msg_id = "m1"): ServerEvent => ({ type: "text_delta", msg_id, offset, delta });

describe("delta dedupe", () => {
  it("appends only when offset == current length", () => {
    const s = run([td(0, "Hel"), td(3, "lo"), td(3, "lo"), td(0, "Hel"), td(9, "gap"), td(5, "!")]);
    expect(s.inFlight.text).toBe("Hello!");
  });

  it("starts a new bubble for a new msg_id at offset 0 only", () => {
    const s = run([td(0, "a"), td(4, "x", "m2"), td(0, "b", "m2")]);
    expect(s.inFlight).toMatchObject({ msg_id: "m2", text: "b" });
  });

  it("dedupes tool output and thinking", () => {
    const s = run([
      { type: "tool_output", call_id: "c", offset: 0, delta: "ab" },
      { type: "tool_output", call_id: "c", offset: 0, delta: "ab" },
      { type: "tool_output", call_id: "c", offset: 2, delta: "c" },
      { type: "thinking_delta", msg_id: "m1", offset: 0, delta: "hm" },
      { type: "thinking_delta", msg_id: "m1", offset: 0, delta: "hm" },
    ]);
    expect(s.toolOutputs.c).toBe("abc");
    expect(s.inFlight.thinking).toBe("hm");
  });

  it("skips durable events already applied", () => {
    const u: ServerEvent = { type: "user_message", seq: 1, text: "hi" };
    expect(run([u, u]).items).toHaveLength(1);
  });
});

describe("snapshot apply", () => {
  it("replaces the in-flight bubble, then live deltas continue with no gap or dup", () => {
    const before = run([{ type: "user_message", seq: 1, text: "hi" }, td(0, "Let "), td(4, "me")]);
    // reconnect: server re-sends nothing (seq 1 seen), then a snapshot with more text than we saw
    const s = run([
      { type: "user_message", seq: 1, text: "hi" },
      { type: "snapshot", last_seq: 1, run_state: "running", pending_approval: null, title: "", plan_mode: false,
        in_flight: { msg_id: "m1", thinking: "t", text: "Let me look", tool_outputs: { c1: "out" } } },
      td(8, "look"), // stale, already in the snapshot
      td(11, " here"),
    ], before);
    expect(s.items).toHaveLength(1);
    expect(s.inFlight).toMatchObject({ msg_id: "m1", thinking: "t", text: "Let me look here" });
    expect(s.toolOutputs.c1).toBe("out");
    expect(s.runState).toBe("running");
  });

  it("restores a pending approval after reload", () => {
    const s = run([{ type: "snapshot", last_seq: 5, run_state: "waiting_approval", title: "", plan_mode: false, in_flight:
      { msg_id: null, thinking: "", text: "", tool_outputs: {} },
      pending_approval: { call_id: "call_1", tool: "bash", args: { command: "ls" } } }]);
    expect(s.pending?.call_id).toBe("call_1");
    expect(s.lastSeq).toBe(5);
    const done = reduce(s, { type: "approval_resolved", seq: 6, call_id: "call_1", decision: "allow" });
    expect(done.pending).toBeNull();
    expect(done.decisions.call_1).toBe("allow");
  });
});

describe("title, plan mode, continue", () => {
  const snap = (title: string, plan_mode: boolean): ServerEvent => ({ type: "snapshot", last_seq: 0, run_state: "idle",
    pending_approval: null, title, plan_mode, in_flight: { msg_id: null, thinking: "", text: "", tool_outputs: {} } });

  it("takes title and plan mode from the snapshot, then live events", () => {
    let s = run([snap("Old", true)]);
    expect(s).toMatchObject({ title: "Old", planMode: true });
    s = run([{ type: "session_title", seq: 1, title: "New" }, { type: "notice", seq: 2, level: "info", text: "plan mode off" }], s);
    expect(s).toMatchObject({ title: "New", planMode: false });
    expect(run([{ type: "notice", seq: 3, level: "info", text: "plan mode on" }], s).planMode).toBe(true);
  });

  it("offers Continue after an interrupted notice or an error, not after a later event", () => {
    const n: ServerEvent = { type: "notice", seq: 1, level: "warning", text: "interrupted: the server restarted during this run" };
    const s = run([n]);
    expect(canContinue(s)).toBe(true);
    expect(canContinue(run([{ type: "user_message", seq: 2, text: "hi" }], s))).toBe(false);
    expect(canContinue(run([{ type: "run_state", seq: 1, state: "error" }]))).toBe(true);
    expect(canContinue(initialState())).toBe(false);
  });
});
