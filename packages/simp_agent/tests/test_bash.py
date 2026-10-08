from __future__ import annotations

import asyncio
import os
import time

from simp_agent.agent import AgentTool, ToolContext, run_tool
from simp_agent.agent.env import LocalEnv
from simp_agent.ai import ToolCall
from simp_agent.coding import make_tools


def ctx(tmp_path, cancel=None):
    async def upd(text):
        pass

    return ToolContext(cancel or asyncio.Event(), LocalEnv(), str(tmp_path), upd)


async def call(tmp_path, cancel=None, max_timeout=None, **args):
    return await run_tool(make_tools(max_timeout), ToolCall("c", "bash", args), ctx(tmp_path, cancel))


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_schema_has_descriptions():
    for t in make_tools():
        for name, p in t.parameters["properties"].items():
            assert p.get("description"), (t.name, name)
    assert "seconds" in make_tools()[3].parameters["properties"]["timeout"]["description"]


async def test_no_timeout_runs_until_done(tmp_path):
    r = await call(tmp_path, command="sleep 0.3; echo done")
    assert not r.is_error and "done" in r.content and "[exit code: 0]" in r.content


async def test_invalid_timeout_is_error(tmp_path):
    for bad in (0, -1, float("inf")):
        r = await call(tmp_path, command="echo x", timeout=bad)
        assert r.is_error and "timeout" in r.content


async def test_max_option_clamps(tmp_path):
    t = time.monotonic()
    r = await call(tmp_path, max_timeout=0.5, command="echo hi; sleep 30", timeout=120000)
    assert time.monotonic() - t < 5
    assert "hi" in r.content and "timed out after 0.5 seconds" in r.content


async def test_abort_kills_tree_and_keeps_output(tmp_path):
    cancel = asyncio.Event()
    pidfile = tmp_path / "pid"
    # child shell + grandchild sleep; the grandchild writes its pid
    cmd = f"echo line1; echo line2; sh -c 'sleep 60 & echo $! > {pidfile}; wait'"
    task = asyncio.ensure_future(call(tmp_path, cancel, command=cmd))
    while not pidfile.exists() or not pidfile.read_text().strip():
        await asyncio.sleep(0.05)
    await asyncio.sleep(1.1)
    cancel.set()
    r = await asyncio.wait_for(task, 5)
    assert "line1" in r.content and "line2" in r.content
    assert "interrupted by the user after 1s" in r.content
    await asyncio.sleep(0.1)
    assert not alive(int(pidfile.read_text()))


async def test_any_tool_abort_says_interrupted(tmp_path):
    cancel = asyncio.Event()
    cancel.set()

    async def boom(args, c):
        raise RuntimeError("x")

    r = await run_tool([AgentTool("t", "", {"type": "object"}, boom)], ToolCall("c", "t", {}), ctx(tmp_path, cancel))
    assert r.is_error and r.content == "Interrupted by the user"
