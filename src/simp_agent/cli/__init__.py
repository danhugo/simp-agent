"""CLI: `simp-agent` = REPL (needs the `cli` extra), `simp-agent "task"` / `-p "task"` = print mode."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import uuid
from pathlib import Path

from ..ai import Model, from_dict, to_dict
from ..coding import make_tools
from ..session import AgentSession

HOME = Path.home() / ".simp-agent"
SESSIONS = HOME / "sessions"
SETTINGS = HOME / "settings.json"
DEFAULTS = {"api": "anthropic-messages", "max_tokens": 8192}


class JsonlStore:
    """SessionStore on a JSONL file: one finished message (or CompactionEntry) per line."""

    def __init__(self, path: Path):
        self.path = path

    def append(self, entry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:  # close = flush, so every entry is on disk right away
            f.write(json.dumps(to_dict(entry)) + "\n")

    def load(self) -> list:
        if not self.path.exists():
            return []
        return [from_dict(json.loads(line)) for line in self.path.read_text().splitlines() if line.strip()]


def session_dir(cwd: str) -> Path:
    return SESSIONS / cwd.strip("/").replace("/", "-")


def latest_session(cwd: str) -> str | None:
    files = sorted(session_dir(cwd).glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1].stem if files else None


# ---- settings -------------------------------------------------------------------------------------------------------

def resolve_config(settings: dict, args: argparse.Namespace) -> dict:
    """Profile from settings.json, then CLI flags on top. Keys never come from the file (only api_key_env)."""
    profiles = settings.get("profiles", {})
    name = args.profile or settings.get("default_profile")
    if args.profile and args.profile not in profiles:
        raise ValueError(f"unknown profile {args.profile!r}; have {sorted(profiles)}")
    cfg = {**DEFAULTS, **profiles.get(name, {})} if name else dict(DEFAULTS)
    cfg.pop("api_key", None)
    cfg["compat"] = dict(cfg.get("compat", {}))
    for k in ("api", "model", "base_url", "context_window", "max_tokens"):
        if getattr(args, k) is not None:
            cfg[k] = getattr(args, k)
    if args.max_tokens_field:
        cfg["compat"]["max_tokens_field"] = args.max_tokens_field
    if args.reasoning_effort:
        cfg["compat"]["reasoning_effort"] = args.reasoning_effort
    if args.no_include_usage:
        cfg["compat"]["include_usage"] = False
    return cfg


def build_model(cfg: dict) -> Model:
    if cfg["api"] == "openai-completions":
        if not cfg.get("model") or not cfg.get("context_window"):
            raise ValueError("model and context_window are required for openai-completions")
        return Model(id=cfg["model"], provider="openai", api=cfg["api"], max_tokens=cfg["max_tokens"],
                     base_url=cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL"), context_window=cfg["context_window"],
                     api_key_env=cfg.get("api_key_env"), compat={"include_usage": True, **cfg["compat"]})
    kw = {"id": cfg.get("model"), "context_window": cfg.get("context_window"), "max_tokens": cfg["max_tokens"],
          "base_url": cfg.get("base_url"), "api_key_env": cfg.get("api_key_env")}
    return Model(**{k: v for k, v in kw.items() if v})


# ---- pure input logic (unit tested; the REPL only wires it to the terminal) ----------------------------------------

def route(line: str, running: bool) -> tuple[str, str]:
    """Input line -> (kind, text). kind: empty | command | prompt | steer | follow_up."""
    text = line.strip()
    if not text:
        return "empty", ""
    if text.startswith("/"):
        return "command", text
    if running:
        return ("follow_up", text[2:].strip()) if text.startswith(">>") else ("steer", text)
    return "prompt", text


def approval_answer(text: str) -> str:
    return {"y": "allow", "yes": "allow", "a": "always", "always": "always"}.get(text.strip().lower(), "deny")


def interrupt_action(running: bool, last_idle_ctrl_c: float | None, now: float) -> str:
    """Ctrl-C -> abort (while running) | exit (second one within 2s when idle) | warn."""
    if running:
        return "abort"
    return "exit" if last_idle_ctrl_c is not None and now - last_idle_ctrl_c < 2 else "warn"


def describe_call(call) -> str:
    if call.name == "bash":
        return f"bash: {call.arguments.get('command', '')}"
    if call.name in ("write", "edit", "read"):
        return f"{call.name}: {call.arguments.get('path', '')}"
    return f"{call.name} {json.dumps(call.arguments)}"


# ---- print mode -----------------------------------------------------------------------------------------------------

def _print_event(e: dict) -> None:
    t = e["type"]
    if t == "message_update" and e["event"]["type"] == "text_delta":
        print(e["event"]["delta"], end="", flush=True)
    elif t == "message_end" and e["message"].role == "assistant" and e["message"].text():
        print(flush=True)
    elif t == "tool_execution_start":
        print(f"> {describe_call(e['call'])[:200]}", flush=True)
    elif t == "tool_execution_end" and e["result"].is_error:
        print(f"  ! {e['result'].content[:200]}", flush=True)


async def run(task: str, model: Model, args: argparse.Namespace) -> int:
    cwd = os.getcwd()
    sid = args.resume or (latest_session(cwd) if args.cont else None) or uuid.uuid4().hex[:8]
    loop = asyncio.get_running_loop()
    session: AgentSession | None = None

    def ask(call) -> str:  # blocking input is fine here: nothing else runs while a tool waits
        print(f"? {describe_call(call)}", flush=True)
        loop.remove_signal_handler(signal.SIGINT)  # let Ctrl-C raise in input()
        try:
            return approval_answer(input("Allow? [y/N/a] "))
        except KeyboardInterrupt:
            session.abort()
            return "deny"
        except EOFError:
            return "deny"
        finally:
            loop.add_signal_handler(signal.SIGINT, session.abort)

    session = AgentSession(model, make_tools(args.bash_max_timeout_s), JsonlStore(session_dir(cwd) / f"{sid}.jsonl"),
                           approve=None if args.yes else ask)
    session.subscribe(_print_event)
    loop.add_signal_handler(signal.SIGINT, session.abort)
    print(f"[session {sid}]", file=sys.stderr)
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
    p.add_argument("--profile", help="profile name in ~/.simp-agent/settings.json")
    p.add_argument("--api", choices=["anthropic-messages", "openai-completions"])
    p.add_argument("--model", help="model id (required for openai-completions)")
    p.add_argument("--base-url")
    p.add_argument("--context-window", type=int)
    p.add_argument("--max-tokens", type=int)
    p.add_argument("--max-tokens-field", choices=["max_tokens", "max_completion_tokens"])
    p.add_argument("--reasoning-effort", help="e.g. none (some servers need it with tools)")
    p.add_argument("--no-include-usage", action="store_true")
    p.add_argument("-c", "--continue", dest="cont", action="store_true", help="latest session for this cwd")
    p.add_argument("--resume", metavar="ID", help="resume session ID (for this cwd)")
    p.add_argument("-y", "--yes", action="store_true", help="never ask before running tools")
    p.add_argument("-p", "--print", dest="print_task", metavar="TASK", help="one-shot print mode")
    p.add_argument("task", nargs="*")
    a = p.parse_args()
    try:
        settings = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
        model = build_model(resolve_config(settings, a))
        a.bash_max_timeout_s = settings.get("bash_max_timeout_s")  # optional cap; None = no limit (like pi)
    except ValueError as e:
        p.error(str(e))
    task = a.print_task or " ".join(a.task)
    if task:
        sys.exit(asyncio.run(run(task, model, a)))
    from .repl import repl  # needs the `cli` extra

    sys.exit(asyncio.run(repl(model, a)))
