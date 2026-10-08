"""Print-mode CLI: `simp-agent "task"`."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from ..ai import Model, from_dict, to_dict
from ..session import AgentSession


def _print_event(e: dict) -> None:
    if e["type"] == "message_end" and e["message"].role == "assistant" and e["message"].text():
        print(e["message"].text(), flush=True)
    elif e["type"] == "tool_execution_start":
        print(f"> {e['call'].name} {json.dumps(e['call'].arguments)[:120]}", flush=True)
    elif e["type"] == "tool_execution_end" and e["result"].is_error:
        print(f"  ! {e['result'].content[:200]}", flush=True)


SESSIONS = Path.home() / ".simp-agent" / "sessions"


class JsonlStore:
    """SessionStore on a JSONL file: one finished message (or CompactionEntry) per line."""

    def __init__(self, path: Path):
        self.path = path

    def append(self, entry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(to_dict(entry)) + "\n")

    def load(self) -> list:
        if not self.path.exists():
            return []
        return [from_dict(json.loads(line)) for line in self.path.read_text().splitlines() if line.strip()]


async def run(task: str, model: Model, session_id: str | None = None) -> int:
    path = SESSIONS / f"{session_id or uuid.uuid4().hex[:8]}.jsonl"
    session = AgentSession(model, store=JsonlStore(path))
    session.subscribe(_print_event)
    print(f"[session {path.stem}]", file=sys.stderr)
    try:
        new = await (session.prompt(task) if task else session.continue_())
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    last = (new or session.messages)[-1]
    if last.stop_reason in ("error", "aborted"):
        print(f"Error: {last.error}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="simp-agent")
    p.add_argument("--api", choices=["anthropic-messages", "openai-completions"], default="anthropic-messages")
    p.add_argument("--model", help="model id (required for openai-completions)")
    p.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL"))
    p.add_argument("--context-window", type=int)
    p.add_argument("--max-tokens", type=int, default=8192)
    p.add_argument("--max-tokens-field", choices=["max_tokens", "max_completion_tokens"])
    p.add_argument("--reasoning-effort", help="e.g. none (some servers need it with tools)")
    p.add_argument("--no-include-usage", action="store_true")
    p.add_argument("--resume", metavar="ID", help="load ~/.simp-agent/sessions/<ID>.jsonl; no task = continue")
    p.add_argument("task", nargs="*")
    a = p.parse_args()
    if not a.task and not a.resume:
        p.error("task is required (unless --resume)")
    if a.api == "openai-completions":
        if not a.model or not a.context_window:
            p.error("--model and --context-window are required for openai-completions")
        compat = {"include_usage": not a.no_include_usage}
        if a.max_tokens_field:
            compat["max_tokens_field"] = a.max_tokens_field
        if a.reasoning_effort:
            compat["reasoning_effort"] = a.reasoning_effort
        model = Model(id=a.model, provider="openai", api=a.api, base_url=a.base_url, context_window=a.context_window, max_tokens=a.max_tokens, compat=compat)
    else:
        model = Model(**{k: v for k, v in [("id", a.model), ("context_window", a.context_window), ("max_tokens", a.max_tokens)] if v})
    sys.exit(asyncio.run(run(" ".join(a.task), model, a.resume)))
