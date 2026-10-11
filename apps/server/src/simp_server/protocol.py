"""Wire protocol v1 between simp-server and the web UI. Source of truth: JSON Schema + TS are generated from here.

DURABLE events carry a monotonic per-session `seq` (= SSE id). LIVE events have no seq and are lost on reconnect;
the snapshot that follows a (re)connect carries everything still in flight.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PROTOCOL_VERSION = 1
SUPPORTED_VERSIONS = {1}

RunStateName = Literal["idle", "running", "waiting_approval", "aborting", "error"]
Decision = Literal["allow", "deny", "always"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


# ---- handshake
class Hello(_M):
    type: Literal["hello"] = "hello"
    protocol_version: int


class HelloError(_M):
    type: Literal["hello_error"] = "hello_error"
    error: str
    supported: list[int]


def check_hello(h: Hello) -> Hello | HelloError:
    if h.protocol_version not in SUPPORTED_VERSIONS:
        return HelloError(error=f"unsupported protocol_version {h.protocol_version}", supported=sorted(SUPPORTED_VERSIONS))
    return Hello(protocol_version=PROTOCOL_VERSION)


# ---- content
class ToolCall(_M):
    id: str
    name: str
    arguments: dict[str, Any]


class Usage(_M):
    input: int = 0
    output: int = 0


# ---- durable server events
class UserMessage(_M):
    type: Literal["user_message"] = "user_message"
    seq: int
    text: str


class AssistantMessage(_M):
    type: Literal["assistant_message"] = "assistant_message"
    seq: int
    msg_id: str
    thinking: str = ""
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    stop_reason: str = "stop"
    error: str | None = None


class ToolResult(_M):
    type: Literal["tool_result"] = "tool_result"
    seq: int
    call_id: str
    tool: str
    content: str
    is_error: bool = False


class ApprovalRequest(_M):
    type: Literal["approval_request"] = "approval_request"
    seq: int
    call_id: str
    tool: str
    args: dict[str, Any]


class ApprovalResolved(_M):
    type: Literal["approval_resolved"] = "approval_resolved"
    seq: int
    call_id: str
    decision: Literal["allow", "deny", "always", "aborted"]


class RunState(_M):
    type: Literal["run_state"] = "run_state"
    seq: int
    state: RunStateName


class Compaction(_M):
    type: Literal["compaction"] = "compaction"
    seq: int
    summary: str
    tokens_before: int
    tokens_after: int


class Notice(_M):
    type: Literal["notice"] = "notice"
    seq: int
    level: Literal["info", "warning", "error"] = "info"
    text: str


class SessionTitle(_M):
    type: Literal["session_title"] = "session_title"
    seq: int
    title: str


# ---- live server events (no seq)
class TextDelta(_M):
    type: Literal["text_delta"] = "text_delta"
    msg_id: str
    offset: int
    delta: str


class ThinkingDelta(_M):
    type: Literal["thinking_delta"] = "thinking_delta"
    msg_id: str
    offset: int
    delta: str


class ToolOutput(_M):
    type: Literal["tool_output"] = "tool_output"
    call_id: str
    offset: int
    delta: str


class InFlight(_M):
    msg_id: str | None = None
    thinking: str = ""
    text: str = ""
    tool_outputs: dict[str, str] = Field(default_factory=dict)


class PendingApproval(_M):
    call_id: str
    tool: str
    args: dict[str, Any]


class Snapshot(_M):
    type: Literal["snapshot"] = "snapshot"
    last_seq: int
    run_state: RunStateName
    in_flight: InFlight
    pending_approval: PendingApproval | None = None
    title: str = ""
    plan_mode: bool = False


DURABLE = (UserMessage, AssistantMessage, ToolResult, ApprovalRequest, ApprovalResolved, RunState, Compaction, Notice, SessionTitle)
ServerEvent = Annotated[
    Union[UserMessage, AssistantMessage, ToolResult, ApprovalRequest, ApprovalResolved, RunState, Compaction, Notice,
          SessionTitle, TextDelta, ThinkingDelta, ToolOutput, Snapshot],
    Field(discriminator="type"),
]


# ---- client commands (POST /api/sessions/{id}/commands)
class Prompt(_M):
    type: Literal["prompt"] = "prompt"
    text: str


class Steer(_M):
    type: Literal["steer"] = "steer"
    text: str


class FollowUp(_M):
    type: Literal["follow_up"] = "follow_up"
    text: str


class Abort(_M):
    type: Literal["abort"] = "abort"


class Approve(_M):
    type: Literal["approve"] = "approve"
    call_id: str
    decision: Decision


class Compact(_M):
    type: Literal["compact"] = "compact"


class Continue(_M):
    type: Literal["continue"] = "continue"


class SetPlanMode(_M):
    type: Literal["set_plan_mode"] = "set_plan_mode"
    enabled: bool


Command = Annotated[Union[Prompt, Steer, FollowUp, Abort, Approve, Compact, Continue, SetPlanMode], Field(discriminator="type")]


class SessionInfo(_M):
    id: str
    title: str = ""
    run_state: RunStateName = "idle"
    plan_mode: bool = False


class Protocol(_M):
    """Root used only for schema generation: pulls every wire type into one document."""

    hello: Hello
    hello_error: HelloError
    event: ServerEvent
    command: Command
    session: SessionInfo


server_event = TypeAdapter(ServerEvent)
command = TypeAdapter(Command)


# ---- run state machine (owned by the server)
TRANSITIONS: dict[str, set[str]] = {
    "idle": {"running"},
    "running": {"waiting_approval", "aborting", "idle", "error"},
    "waiting_approval": {"running", "aborting"},
    "aborting": {"idle", "error"},
    "error": {"running", "idle"},
}


def check_transition(old: str, new: str) -> None:
    if new not in TRANSITIONS[old]:
        raise ValueError(f"bad run_state transition {old} -> {new}")


def _untitle(x):
    """Drop per-field titles so TS gets plain inline types, not `type Seq1 = number` aliases."""
    if isinstance(x, dict):
        return {k: _untitle(v) for k, v in x.items() if not (k == "title" and isinstance(v, str) and "properties" not in x)}
    return [_untitle(v) for v in x] if isinstance(x, list) else x


def json_schema() -> str:
    return json.dumps(_untitle(Protocol.model_json_schema(mode="serialization")), indent=2) + "\n"
