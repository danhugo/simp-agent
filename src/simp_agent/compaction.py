"""Context compaction: summarize old messages when the history gets near the context window. Generic."""

from __future__ import annotations

from dataclasses import dataclass

from . import ai
from .ai import AssistantMessage, Context, ToolResultMessage, UserMessage

SUMMARY_TAG = "<summary>"

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


@dataclass
class CompactionSettings:
    enabled: bool = True
    reserve_tokens: int = 16384
    keep_recent_tokens: int = 20000


def estimate(m) -> int:
    if isinstance(m, AssistantMessage):
        n = sum(len(c.text) if isinstance(c, ai.TextContent) else len(c.name) + len(str(c.arguments)) for c in m.content)
    else:
        n = len(m.content)
    return n // 4


def count_tokens(messages: list) -> int:
    """Last good assistant usage + chars/4 for messages after it; chars/4 for all if no usage."""
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if isinstance(m, AssistantMessage) and m.stop_reason not in ("error", "aborted") and any(m.usage.values()):
            return m.usage["input"] + m.usage["output"] + sum(estimate(x) for x in messages[i + 1 :])
    return sum(estimate(x) for x in messages)


def is_summary(m) -> bool:
    return isinstance(m, UserMessage) and m.content.startswith(SUMMARY_TAG)


def find_cut(messages: list, keep_tokens: int) -> int | None:
    """Index of the first kept message. Always a real user message, so a tool_use/tool_result pair is never split."""
    start = 1 if messages and is_summary(messages[0]) else 0
    total, i = 0, len(messages)
    while i > start and total < keep_tokens:
        i -= 1
        total += estimate(messages[i])
    users = [j for j in range(start + 1, len(messages)) if isinstance(messages[j], UserMessage)]
    before = [j for j in users if j <= i]
    if before:
        return before[-1]
    return users[0] if users else None  # ponytail: no user message to cut at -> nothing to compact


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
        raise RuntimeError(f"summary failed: {msg.error if msg else 'no response'} ({msg and msg.stop_reason})")
    return msg.text()


async def compact(messages: list, model, stream_fn, settings: CompactionSettings, emit, force: bool = False) -> list | None:
    """Return the new history ([summary] + kept), or None when nothing was done."""
    before = count_tokens(messages)
    if not settings.enabled or (not force and before <= model.context_window - settings.reserve_tokens):
        return None
    cut = find_cut(messages, settings.keep_recent_tokens)
    if cut is None:
        return None
    await emit({"type": "compaction_start", "tokens_before": before})
    previous = messages[0].content[len(SUMMARY_TAG) : -len("</summary>")] if is_summary(messages[0]) else None
    old = messages[1 if previous is not None else 0 : cut]
    try:
        text = await summarize(stream_fn, model, old, previous)
    except Exception as e:
        await emit({"type": "compaction_end", "error": str(e), "tokens_before": before, "tokens_after": before})
        return None
    new = [UserMessage(f"{SUMMARY_TAG}{text}</summary>")] + messages[cut:]
    after = sum(estimate(m) for m in new)
    await emit({"type": "compaction_end", "error": None, "tokens_before": before, "tokens_after": after})
    return new
