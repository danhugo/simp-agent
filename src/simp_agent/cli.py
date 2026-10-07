"""System prompt + print-mode CLI: `simp-agent "task"`."""

from __future__ import annotations

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


async def run(task: str) -> int:
    agent = Agent(system_prompt(TOOLS, os.getcwd()), Model(), TOOLS)
    agent.subscribe(_print_event)
    last = (await agent.prompt(task))[-1]
    if last.stop_reason in ("error", "aborted"):
        print(f"Error: {last.error}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('usage: simp-agent "task"')
    sys.exit(asyncio.run(run(" ".join(sys.argv[1:]))))
