"""Tiny eval harness: run each task in evals/tasks/*.toml with AgentSession + LocalEnv in a temp dir, then its check.

uv run python evals/run.py --profile sol [--home ~/.simp-server] [--tasks a,b]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

from simp_agent import ai
from simp_agent.agent.env import LocalEnv
from simp_agent.session import AgentSession
from simp_agent.session.profile import build_model

HERE = Path(__file__).parent
MAX_TURNS, TIMEOUT_S, CHECK_TIMEOUT_S = 25, 300, 120


def load_tasks(names: list[str] | None) -> list[dict]:
    tasks = {f.stem: {"name": f.stem, **tomllib.loads(f.read_text())} for f in sorted((HERE / "tasks").glob("*.toml"))}
    if names is None:
        return list(tasks.values())
    if missing := [n for n in names if n not in tasks]:
        raise SystemExit(f"unknown tasks: {', '.join(missing)} (have: {', '.join(tasks)})")
    return [tasks[n] for n in names]


async def run_task(task: dict, profile: dict, keys: dict, stream_fn) -> dict:
    model = build_model(profile)
    key = keys.get(model.api_key_env or ("OPENAI_API_KEY" if model.api.startswith("openai") else "ANTHROPIC_API_KEY"))
    with tempfile.TemporaryDirectory(prefix=f"simp-eval-{task['name']}-") as d:
        root = Path(d).resolve()
        for rel, text in task.get("setup", {}).items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        s = AgentSession(model, env=LocalEnv(str(root)), cwd=str(root), stream_fn=stream_fn,
                         get_api_key=lambda provider: key, max_retries=1)
        r = {"name": task["name"], "turns": 0, "input": 0, "output": 0, "error": None}

        def on_event(e):
            m = e.get("message")
            if e["type"] == "message_end" and getattr(m, "role", None) == "assistant":
                r["turns"] += 1
                r["input"] += m.usage.get("input", 0)
                r["output"] += m.usage.get("output", 0)
                r["answer"] = m.text()
                if m.error:
                    r["error"] = m.error
                if r["turns"] >= MAX_TURNS:
                    r["error"] = f"hit {MAX_TURNS} turns"
                    s.abort()

        s.subscribe(on_event)
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(s.prompt(task["prompt"]), TIMEOUT_S)
        except TimeoutError:
            s.abort()
            r["error"] = f"timeout after {TIMEOUT_S}s"
        r["seconds"] = round(time.monotonic() - t0, 1)
        (root / "_answer.txt").write_text(r.pop("answer", ""))
        try:
            chk = subprocess.run(task["check"], shell=True, cwd=root, capture_output=True, text=True,
                                 timeout=CHECK_TIMEOUT_S, env={**os.environ, "PYTHON": sys.executable})
            r["passed"], r["check_output"] = chk.returncode == 0, (chk.stdout + chk.stderr)[-2000:]
        except subprocess.TimeoutExpired:
            r["passed"], r["check_output"] = False, "check timed out"
    r["cost"] = (r["input"] * profile.get("price_in", 0) + r["output"] * profile.get("price_out", 0)) / 1e6
    return r


def line(name, ok, turns, inp, out, cost, secs) -> str:
    return f"{name:<16}{ok:<6}{turns:>4} turns  {inp:>8}/{out:<8} ${cost:.4f}  {secs:.1f}s"


async def run_all(profile_name: str, profile: dict, keys: dict, names: list[str] | None, stream_fn=ai.stream,
                  out_dir: Path = HERE / "results") -> list[dict]:
    if "price_in" not in profile or "price_out" not in profile:
        print(f"warning: profile {profile_name} has no price_in/price_out: cost shows $0", file=sys.stderr)
    rows = list()
    for t in load_tasks(names):
        r = await run_task(t, profile, keys, stream_fn)
        rows.append(r)
        print(line(r["name"], "PASS" if r["passed"] else "FAIL", r["turns"], r["input"], r["output"], r["cost"],
                   r["seconds"]) + (f"  ({r['error']})" if r["error"] else ""), flush=True)
    total = {k: sum(r[k] for r in rows) for k in ("turns", "input", "output", "cost", "seconds")}
    total["passed"] = sum(r["passed"] for r in rows)
    print(line("total", f"{total['passed']}/{len(rows)}", total["turns"], total["input"], total["output"],
               total["cost"], total["seconds"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{profile_name}.json"
    f.write_text(json.dumps({"profile": profile_name, "model": profile.get("model"), "tasks": rows, "total": total},
                            indent=2))
    print(f"wrote {f}")
    return rows


def main() -> None:
    from simp_server.server import load_settings, take_keys

    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--home", default=os.environ.get("SIMP_SERVER_HOME", "~/.simp-server"))
    ap.add_argument("--tasks")
    a = ap.parse_args()
    settings = load_settings(Path(a.home).expanduser())
    if a.profile not in settings["profiles"]:
        raise SystemExit(f"no profile {a.profile!r} in {a.home}/settings.toml")
    keys = take_keys(settings)
    asyncio.run(run_all(a.profile, settings["profiles"][a.profile], keys, a.tasks.split(",") if a.tasks else None))


if __name__ == "__main__":
    main()
