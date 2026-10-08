"""System prompt + print-mode CLI: `simp-agent "task"`."""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys

from .agent import Agent
from .ai import Model
from .tools import TOOLS


def system_prompt(tools: list, cwd: str) -> str:
    tool_list = "\n".join(f"- {t.name}: {t.description}" for t in tools)
    return (
        "You are an expert coding assistant. You help the user by reading files, running commands, "
        "editing code, and writing new files.\n\n"
        f"Available tools:\n{tool_list}\n\n"
        "Be concise. Use read before edit. Paths are relative to the working directory.\n\n"
        f"Current date: {datetime.date.today()}\nCurrent working directory: {cwd}"
    )


def _print_event(e: dict) -> None:
    if e["type"] == "message_end" and e["message"].role == "assistant" and e["message"].text():
        print(e["message"].text(), flush=True)
    elif e["type"] == "tool_execution_start":
        print(f"> {e['call'].name} {json.dumps(e['call'].arguments)[:120]}", flush=True)
    elif e["type"] == "tool_execution_end" and e["result"].is_error:
        print(f"  ! {e['result'].content[:200]}", flush=True)


async def run(task: str, model: Model) -> int:
    agent = Agent(system_prompt(TOOLS, os.getcwd()), model, TOOLS)
    agent.subscribe(_print_event)
    last = (await agent.prompt(task))[-1]
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
    p.add_argument("task", nargs="+")
    a = p.parse_args()
    if a.api == "openai-completions":
        if not a.model or not a.context_window:
            p.error("--model and --context-window are required for openai-completions")
        model = Model(id=a.model, provider="openai", api=a.api, base_url=a.base_url, context_window=a.context_window)
    else:
        model = Model(**{k: v for k, v in [("id", a.model), ("context_window", a.context_window)] if v})
    sys.exit(asyncio.run(run(" ".join(a.task), model)))
