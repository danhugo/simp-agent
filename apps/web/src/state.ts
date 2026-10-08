import type {
  ApprovalResolved, AssistantMessage, InFlight, Notice, PendingApproval, Protocol, RunState, ToolResult,
} from "./protocol.gen";

export type ServerEvent = Protocol["event"];

export type Item =
  | { kind: "user"; seq: number; text: string }
  | { kind: "assistant"; seq: number; msg: AssistantMessage }
  | { kind: "notice"; seq: number; level: Notice["level"]; text: string };

export interface ChatState {
  lastSeq: number;
  runState: RunState["state"];
  items: Item[];
  inFlight: InFlight;
  toolOutputs: Record<string, string>; // live output per call_id
  results: Record<string, ToolResult>;
  decisions: Record<string, ApprovalResolved["decision"]>;
  pending: PendingApproval | null;
}

const emptyInFlight = (): InFlight => ({ msg_id: null, thinking: "", text: "", tool_outputs: {} });

export const initialState = (): ChatState => ({
  lastSeq: 0, runState: "idle", items: [], inFlight: emptyInFlight(),
  toolOutputs: {}, results: {}, decisions: {}, pending: null,
});

/** Append `delta` only when it starts exactly at the end of `cur`; anything else is a dup or a gap. */
export function appendAt(cur: string, offset: number, delta: string): string {
  return offset === cur.length ? cur + delta : cur;
}

export function reduce(s: ChatState, ev: ServerEvent): ChatState {
  if ("seq" in ev) {
    if (ev.seq <= s.lastSeq) return s; // durable event already applied
    s = { ...s, lastSeq: ev.seq };
  }
  switch (ev.type) {
    case "user_message":
      return { ...s, items: [...s.items, { kind: "user", seq: ev.seq, text: ev.text }] };
    case "assistant_message":
      return { ...s, items: [...s.items, { kind: "assistant", seq: ev.seq, msg: ev }], inFlight: emptyInFlight() };
    case "tool_result":
      return { ...s, results: { ...s.results, [ev.call_id]: ev } };
    case "approval_request":
      return { ...s, pending: { call_id: ev.call_id, tool: ev.tool, args: ev.args } };
    case "approval_resolved":
      return {
        ...s, decisions: { ...s.decisions, [ev.call_id]: ev.decision },
        pending: s.pending?.call_id === ev.call_id ? null : s.pending,
      };
    case "run_state":
      return { ...s, runState: ev.state };
    case "notice":
      return { ...s, items: [...s.items, { kind: "notice", seq: ev.seq, level: ev.level, text: ev.text }] };
    case "compaction":
      return { ...s, items: [...s.items, { kind: "notice", seq: ev.seq, level: "info",
        text: `Context compacted (${ev.tokens_before} → ${ev.tokens_after} tokens)` }] };
    case "text_delta":
    case "thinking_delta": {
      let f = s.inFlight;
      if (f.msg_id !== ev.msg_id) {
        if (ev.offset !== 0) return s; // a new message must start at 0
        f = { ...emptyInFlight(), msg_id: ev.msg_id };
      }
      const key = ev.type === "text_delta" ? "text" : "thinking";
      return { ...s, inFlight: { ...f, [key]: appendAt(f[key], ev.offset, ev.delta) } };
    }
    case "tool_output": {
      const cur = s.toolOutputs[ev.call_id] ?? "";
      return { ...s, toolOutputs: { ...s.toolOutputs, [ev.call_id]: appendAt(cur, ev.offset, ev.delta) } };
    }
    case "snapshot":
      // The snapshot is the truth for everything live: replace the in-flight bubble and live tool output.
      return {
        ...s, lastSeq: Math.max(s.lastSeq, ev.last_seq), runState: ev.run_state, pending: ev.pending_approval,
        inFlight: ev.in_flight, toolOutputs: { ...s.toolOutputs, ...ev.in_flight.tool_outputs },
      };
  }
}
