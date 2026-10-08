"""Context compaction: summarize old messages when the history gets near the context window. Generic."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass

from .. import ai
from ..ai import AssistantMessage, CompactionEntry, Context, ToolResultMessage, UserMessage

SYSTEM_PROMPT = """You are a context summarization assistant. Your task is to read a conversation between a user and an AI assistant, then produce a structured summary following the exact format specified.

Do NOT continue the conversation. Do NOT respond to any questions in the conversation. ONLY output the structured summary."""

SUMMARIZATION_PROMPT = """The messages in <conversation> are a conversation to summarize. Create a structured context checkpoint summary that another LLM will use to continue the work.

Use this EXACT format:

## User Requests (chronological)
1. [EVERY request the user made, in order, done or not. Never drop one.]

## Goal
[All open goals of the user, not only the latest one]

## Constraints & Preferences
- [Constraints, preferences, or requirements from the user, or "(none)"]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Data, examples, or references needed to continue, or "(none)"]

Keep each section concise. Preserve exact file paths, function names, and error messages."""

UPDATE_SUMMARIZATION_PROMPT = """The messages in <conversation> are NEW conversation messages to incorporate into the existing summary provided in <previous-summary> tags.

Update the existing structured summary with new information. RULES:
- PRESERVE all existing information from the previous summary
- KEEP every item of "## User Requests (chronological)" and APPEND the new user requests at the end
- ADD new progress, decisions, and context from the new messages
- UPDATE the Progress section: move items from "In Progress" to "Done" when completed
- UPDATE "Next Steps" based on what was accomplished
- PRESERVE exact file paths, function names, and error messages

Use the same format: ## User Requests (chronological), ## Goal, ## Constraints & Preferences, ## Progress (### Done / ### In Progress / ### Blocked),
## Key Decisions, ## Next Steps, ## Critical Context. Keep each section concise."""


SUMMARY_PREFIX = "The conversation history before this point was compacted into the following summary:\n\n<summary>\n"


@dataclass
class CompactionSettings:
    enabled: bool = True
    reserve_tokens: int = 16384
    keep_recent_tokens: int = 20000


def _last_entry(messages: list) -> int | None:
    return next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], CompactionEntry)), None)


def build_view(messages: list) -> list:
    """[summary user message] + messages from first_kept_index on (markers dropped). No marker -> history as is."""
    k = _last_entry(messages)
    if k is None:
        return messages
    e = messages[k]
    kept = [m for m in messages[e.first_kept_index :] if not isinstance(m, CompactionEntry)]
    return [UserMessage(f"{SUMMARY_PREFIX}{e.summary}\n</summary>")] + kept


def estimate(m) -> int:
    if isinstance(m, AssistantMessage):
        n = sum(len(c.text) if isinstance(c, ai.TextContent) else len(c.thinking) if isinstance(c, ai.ThinkingContent)
                else len(c.name) + len(str(c.arguments)) for c in m.content)
    elif isinstance(m, CompactionEntry):
        n = len(m.summary)
    else:
        n = len(m.content)
    return n // 4


def estimate_tokens(messages: list) -> int:
    """Tokens of the LLM view of full history: last valid assistant usage after the last CompactionEntry + chars/4 after it.
    No such usage -> chars/4 of the view. Error, aborted and all-zero usage are ignored."""
    k = _last_entry(messages)
    for i in range(len(messages) - 1, -1 if k is None else k, -1):
        m = messages[i]
        if isinstance(m, AssistantMessage) and m.stop_reason not in ("error", "aborted") and any(m.usage.values()):
            return m.usage["input"] + m.usage["output"] + sum(estimate(x) for x in messages[i + 1 :])
    return sum(estimate(x) for x in build_view(messages))


def should_compact(tokens: int, model, settings: CompactionSettings) -> bool:
    return settings.enabled and tokens > model.context_window - settings.reserve_tokens


def find_cut(messages: list, start: int, keep_tokens: int) -> int | None:
    """First kept index in (start, len). Only a user or assistant message: never a tool_result, so pairs stay together.
    ponytail: no split-turn cut (pi isSplitTurn); one huge turn cannot be compacted."""
    total, i = 0, len(messages)
    while i > start and total < keep_tokens:
        i -= 1
        total += estimate(messages[i])
    ok = [j for j in range(start + 1, len(messages)) if isinstance(messages[j], (UserMessage, AssistantMessage))]
    before = [j for j in ok if j <= i]
    return before[-1] if before else (ok[0] if ok else None)


TOOL_RESULT_MAX = 2000
ARG_MAX = 500


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else f"{text[:n]}\n\n[... {len(text) - n} more characters truncated]"


def serialize_conversation(messages: list) -> str:
    """Messages -> one text, so the summarizer reads it instead of continuing the chat (pi serializeConversation)."""
    parts = []
    for m in ai.transform_messages(messages):
        if isinstance(m, UserMessage) and m.content:
            parts.append(f"[User]: {m.content}")
        elif isinstance(m, AssistantMessage):  # thinking skipped: big, the text + tool calls carry the result
            if text := m.text():
                parts.append(f"[Assistant]: {text}")
            calls = [f"{c.name}({', '.join(f'{k}={_cut(json.dumps(v), ARG_MAX)}' for k, v in c.arguments.items())})"
                     for c in m.content if isinstance(c, ai.ToolCall)]
            if calls:
                parts.append(f"[Assistant tool calls]: {'; '.join(calls)}")
        elif isinstance(m, ToolResultMessage) and m.content:
            parts.append(f"[Tool result]: {_cut(m.content, TOOL_RESULT_MAX)}")
    return "\n\n".join(parts)


def file_lists(messages: list, prev: CompactionEntry | None) -> tuple[list, list]:
    """(read_only, modified) paths from read/write/edit calls, merged with the previous entry's lists."""
    read, mod = set(prev.read_files if prev else []), set(prev.modified_files if prev else [])
    for m in messages:
        if isinstance(m, AssistantMessage):
            for c in m.content:
                if isinstance(c, ai.ToolCall) and isinstance(p := c.arguments.get("path"), str):
                    {"read": read, "write": mod, "edit": mod}.get(c.name, set()).add(p)
    return sorted(read - mod), sorted(mod)


def format_files(read: list, mod: list) -> str:
    s = [f"<{t}>\n" + "\n".join(fs) + f"\n</{t}>" for t, fs in (("read-files", read), ("modified-files", mod)) if fs]
    return "\n\n" + "\n\n".join(s) if s else ""


async def summarize(stream_fn, model, old: list, previous: str | None, reserve_tokens: int = 16384) -> str:
    text = f"<conversation>\n{serialize_conversation(old)}\n</conversation>\n\n"
    if previous:
        text += f"<previous-summary>\n{previous}\n</previous-summary>\n\n{UPDATE_SUMMARIZATION_PROMPT}"
    else:
        text += SUMMARIZATION_PROMPT
    model = dataclasses.replace(model, max_tokens=min(int(0.8 * reserve_tokens), model.max_tokens))
    msg = None
    async for ev in stream_fn(model, Context(SYSTEM_PROMPT, [UserMessage(text)], [])):
        if ev["type"] in ("done", "error"):
            msg = ev["message"]
    if msg is None or msg.stop_reason in ("error", "length", "aborted"):
        raise RuntimeError(f"summary failed: {msg.error if msg else 'no response'}")
    return msg.text()


async def compact(messages: list, model, stream_fn, settings: CompactionSettings) -> CompactionEntry:
    """Pure: summarize full history up to a cut into a new CompactionEntry. Raises if nothing to do or on failure."""
    k = _last_entry(messages)
    prev = messages[k] if k is not None else None
    start, previous = (prev.first_kept_index, prev.summary) if prev else (0, None)
    cut = find_cut(messages, start, settings.keep_recent_tokens)
    if cut is None:
        raise RuntimeError("nothing to compact")
    old = [m for m in messages[start:cut] if not isinstance(m, CompactionEntry)]
    read, mod = file_lists(old, prev)
    summary = await summarize(stream_fn, model, old, previous, settings.reserve_tokens)
    return CompactionEntry(summary + format_files(read, mod), cut, read, mod)
