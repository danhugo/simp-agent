/* Generated from apps/server/src/simp_server/protocol.py. Do not edit; run gen_protocol. */

/**
 * Root used only for schema generation: pulls every wire type into one document.
 */
export interface Protocol {
  hello: Hello;
  hello_error: HelloError;
  event:
    | UserMessage
    | AssistantMessage
    | ToolResult
    | ApprovalRequest
    | ApprovalResolved
    | RunState
    | Compaction
    | Notice
    | TextDelta
    | ThinkingDelta
    | ToolOutput
    | Snapshot;
  command: Prompt | Steer | FollowUp | Abort | Approve;
  session: SessionInfo;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "Hello".
 */
export interface Hello {
  type: "hello";
  protocol_version: number;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "HelloError".
 */
export interface HelloError {
  type: "hello_error";
  error: string;
  supported: number[];
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "UserMessage".
 */
export interface UserMessage {
  type: "user_message";
  seq: number;
  text: string;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "AssistantMessage".
 */
export interface AssistantMessage {
  type: "assistant_message";
  seq: number;
  msg_id: string;
  thinking: string;
  text: string;
  tool_calls: ToolCall[];
  usage: Usage;
  stop_reason: string;
  error: string | null;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "ToolCall".
 */
export interface ToolCall {
  id: string;
  name: string;
  arguments: {
    [k: string]: unknown;
  };
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "Usage".
 */
export interface Usage {
  input: number;
  output: number;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "ToolResult".
 */
export interface ToolResult {
  type: "tool_result";
  seq: number;
  call_id: string;
  tool: string;
  content: string;
  is_error: boolean;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "ApprovalRequest".
 */
export interface ApprovalRequest {
  type: "approval_request";
  seq: number;
  call_id: string;
  tool: string;
  args: {
    [k: string]: unknown;
  };
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "ApprovalResolved".
 */
export interface ApprovalResolved {
  type: "approval_resolved";
  seq: number;
  call_id: string;
  decision: "allow" | "deny" | "always" | "aborted";
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "RunState".
 */
export interface RunState {
  type: "run_state";
  seq: number;
  state: "idle" | "running" | "waiting_approval" | "aborting" | "error";
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "Compaction".
 */
export interface Compaction {
  type: "compaction";
  seq: number;
  summary: string;
  tokens_before: number;
  tokens_after: number;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "Notice".
 */
export interface Notice {
  type: "notice";
  seq: number;
  level: "info" | "warning" | "error";
  text: string;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "TextDelta".
 */
export interface TextDelta {
  type: "text_delta";
  msg_id: string;
  offset: number;
  delta: string;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "ThinkingDelta".
 */
export interface ThinkingDelta {
  type: "thinking_delta";
  msg_id: string;
  offset: number;
  delta: string;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "ToolOutput".
 */
export interface ToolOutput {
  type: "tool_output";
  call_id: string;
  offset: number;
  delta: string;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "Snapshot".
 */
export interface Snapshot {
  type: "snapshot";
  last_seq: number;
  run_state: "idle" | "running" | "waiting_approval" | "aborting" | "error";
  in_flight: InFlight;
  pending_approval: PendingApproval | null;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "InFlight".
 */
export interface InFlight {
  msg_id: string | null;
  thinking: string;
  text: string;
  tool_outputs: {
    [k: string]: string;
  };
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "PendingApproval".
 */
export interface PendingApproval {
  call_id: string;
  tool: string;
  args: {
    [k: string]: unknown;
  };
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "Prompt".
 */
export interface Prompt {
  type: "prompt";
  text: string;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "Steer".
 */
export interface Steer {
  type: "steer";
  text: string;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "FollowUp".
 */
export interface FollowUp {
  type: "follow_up";
  text: string;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "Abort".
 */
export interface Abort {
  type: "abort";
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "Approve".
 */
export interface Approve {
  type: "approve";
  call_id: string;
  decision: "allow" | "deny" | "always";
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "SessionInfo".
 */
export interface SessionInfo {
  id: string;
  run_state: "idle" | "running" | "waiting_approval" | "aborting" | "error";
}
