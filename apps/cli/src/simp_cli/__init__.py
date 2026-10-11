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

from simp_agent.ai import Model, from_dict, to_dict
from simp_agent.coding import make_tools
from simp_agent.session import AgentSession, profile

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


def list_sessions(cwd: str) -> list[dict]:
    """Sessions for this cwd, newest first: id, mtime, first user line, message count."""
    out = list()
    for f in session_dir(cwd).glob("*.jsonl"):
        msgs = JsonlStore(f).load()
        first = next((m.content for m in msgs if m.role == "user"), "")
        out.append({"id": f.stem, "mtime": f.stat().st_mtime, "first": first.strip().split("\n")[0][:60],
                    "count": sum(m.role not in ("compaction", "custom") for m in msgs)})
    return sorted(out, key=lambda s: s["mtime"], reverse=True)


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
    if cfg["api"] in ("openai-completions", "openai-responses"):
        if not cfg.get("model") or not cfg.get("context_window"):
            raise ValueError(f"model and context_window are required for {cfg['api']}")
        cfg = {**cfg, "base_url": cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL")}
    return profile.build_model({k: v for k, v in cfg.items() if v not in (None, "")})


def env_api_key(model: Model):
    """The CLI's get_api_key: keys come from env (providers never read env). openai keeps "dummy" for keyless servers."""

    def get(provider: str) -> str | None:
        if model.api_key_env and os.environ.get(model.api_key_env):
            return os.environ[model.api_key_env]
        if model.api.startswith("openai"):
            return os.environ.get("OPENAI_API_KEY") or "dummy"
        return os.environ.get("ANTHROPIC_API_KEY")

    return get


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

class LinePrinter:
    """Print mode: buffer deltas, print full lines only (no per-token output, no ANSI unless a tty)."""

    def __init__(self, thinking: bool = True, out=None):
        self.thinking, self.out, self.buf, self.dim = thinking, out or sys.stdout, "", False

    def _line(self, line: str) -> None:
        dim = self.dim and self.out.isatty()
        print(f"\033[2m{line}\033[0m" if dim and line else line, file=self.out, flush=True)

    def _add(self, text: str, dim: bool) -> None:
        if dim != self.dim:
            self.flush()
        self.dim, self.buf = dim, self.buf + text
        *lines, self.buf = self.buf.split("\n")
        for line in lines:
            self._line(line)

    def flush(self) -> None:
        if self.buf:
            self._line(self.buf)
        self.buf = ""

    def __call__(self, e: dict) -> None:
        t = e["type"]
        if t == "message_update" and e["event"]["type"] == "text_delta":
            self._add(e["event"]["delta"], False)
        elif t == "message_update" and self.thinking and e["event"]["type"] == "thinking_delta":
            self._add(e["event"]["delta"], True)
        elif t == "message_end" and e["message"].role == "assistant":
            self.flush()
        elif t == "tool_execution_start":
            self.flush()
            print(f"> {describe_call(e['call'])[:200]}", file=self.out, flush=True)
        elif t == "tool_execution_end" and e["result"].is_error:
            print(f"  ! {e['result'].content[:200]}", file=self.out, flush=True)


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

    store = JsonlStore(session_dir(cwd) / f"{sid}.jsonl")
    session = AgentSession(model, make_tools(args.bash_max_timeout_s), store, messages=store.load(),
                           get_api_key=env_api_key(model), approve=None if args.yes else ask)
    session.subscribe(LinePrinter(args.thinking))
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
    p.add_argument("--api", choices=["anthropic-messages", "openai-completions", "openai-responses"])
    p.add_argument("--model", help="model id (required for openai-completions)")
    p.add_argument("--base-url")
    p.add_argument("--context-window", type=int)
    p.add_argument("--max-tokens", type=int)
    p.add_argument("--max-tokens-field", choices=["max_tokens", "max_completion_tokens"])
    p.add_argument("--reasoning-effort", help="e.g. none (some servers need it with tools)")
    p.add_argument("--no-include-usage", action="store_true")
    p.add_argument("--thinking", action=argparse.BooleanOptionalAction, default=True, help="show model thinking (dim)")
    p.add_argument("-c", "--continue", dest="cont", action="store_true", help="latest session for this cwd")
    p.add_argument("--resume", metavar="ID", help="resume session ID (for this cwd)")
    p.add_argument("-r", dest="pick", action="store_true", help="pick a session for this cwd")
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
