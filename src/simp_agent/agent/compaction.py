"""Context compaction: summarize old messages when the history gets near the context window. Generic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from . import ai
from .ai import AssistantMessage, Context, UserMessage

SUMMARIZATION_PROMPT = """The messages above are a conversation to summarize. Create a structured context checkpoint summary that another LLM will use to continue the work.

Use this EXACT format:

## Goal
[What is the user trying to accomplish?]

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

UPDATE_SUMMARIZATION_PROMPT = """The messages above are NEW conversation messages to incorporate into the existing summary provided in <previous-summary> tags.

Update the existing structured summary with new information. RULES:
- PRESERVE all existing information from the previous summary
- ADD new progress, decisions, and context from the new messages
- UPDATE the Progress section: move items from "In Progress" to "Done" when completed
- UPDATE "Next Steps" based on what was accomplished
- PRESERVE exact file paths, function names, and error messages
- If something is no longer relevant, you may remove it

Use the same format: ## Goal, ## Constraints & Preferences, ## Progress (### Done / ### In Progress / ### Blocked),
## Key Decisions, ## Next Steps, ## Critical Context. Keep each section concise."""


SUMMARY_PREFIX = "The conversation history before this point was compacted into the following summary:\n\n<summary>\n"


@dataclass
class CompactionSettings:
    enabled: bool = True
    reserve_tokens: int = 16384
    keep_recent_tokens: int = 20000


@dataclass
class CompactionEntry:
    """Marker appended to history. History stays append-only; build_view() turns it into the LLM view."""

    summary: str
    first_kept_index: int
    role: Literal["compaction"] = "compaction"


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
        n = sum(len(c.text) if isinstance(c, ai.TextContent) else len(c.name) + len(str(c.arguments)) for c in m.content)
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


async def summarize(stream_fn, model, old: list, previous: str | None) -> str:
    prompt = SUMMARIZATION_PROMPT
    if previous:
        prompt = f"<previous-summary>\n{previous}\n</previous-summary>\n\n{UPDATE_SUMMARIZATION_PROMPT}"
    msgs = ai.transform_messages(old) + [UserMessage(prompt)]
    ctx = Context("You summarize conversations for another assistant to continue the work.", msgs, [])
    msg = None
    async for ev in stream_fn(model, ctx):
        if ev["type"] in ("done", "error"):
            msg = ev["message"]
    if msg is None or msg.stop_reason in ("error", "length", "aborted"):
        raise RuntimeError(f"summary failed: {msg.error if msg else 'no response'}")
    return msg.text()


async def compact(messages: list, model, stream_fn, settings: CompactionSettings) -> tuple[str, int]:
    """Pure: summarize full history up to a cut. Returns (summary, first_kept_index). Raises if nothing to do or on failure."""
    k = _last_entry(messages)
    start, previous = (messages[k].first_kept_index, messages[k].summary) if k is not None else (0, None)
    cut = find_cut(messages, start, settings.keep_recent_tokens)
    if cut is None:
        raise RuntimeError("nothing to compact")
    old = [m for m in messages[start:cut] if not isinstance(m, CompactionEntry)]
    return await summarize(stream_fn, model, old, previous), cut
