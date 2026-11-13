from __future__ import annotations

import asyncio
import os
import sys
import textwrap
from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")
from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp_types import ToolAnnotations  # noqa: E402

from simp_agent.ai import Model  # noqa: E402
from simp_agent.plugins import McpPlugin, build_plugins  # noqa: E402
from simp_agent.plugins.mcp import UNTRUSTED  # noqa: E402
from simp_agent.session import AgentSession  # noqa: E402


def fake_server():
    s = MCPServer("fake")

    @s.tool(annotations=ToolAnnotations(read_only_hint=True))
    def echo(text: str) -> str:
        """Echo the text."""
        return text

    @s.tool()
    def big() -> str:
        return "x" * 50000

    @s.tool()
    async def slow() -> str:
        await asyncio.sleep(10)
        return "late"

    @s.tool()
    def boom() -> str:
        raise ValueError("bad input")
    return s


async def started(plugin, config=None):
    s = AgentSession(Model(), [], system_prompt="s", plugins=[plugin], plugin_config={"mcp": config or {}})
    errors = list()
    s.subscribe(lambda ev: errors.append(ev) if ev["type"] == "plugin_error" else None)
    await s.start()
    return s, errors


def tool(s, name):
    return next(t for t in s.agent.tools if t.name == name)


def ctx():
    return SimpleNamespace(cancel=asyncio.Event())


async def test_tools_call_cap_timeout_errors():
    p = McpPlugin([{"name": "fk", "server": fake_server()}], timeout=0.5, max_chars=100)
    s, errors = await started(p)
    names = {t.name for t in s.agent.tools}
    assert {"fk__echo", "fk__big", "fk__slow", "fk__boom"} <= names and not errors
    echo = tool(s, "fk__echo")
    assert echo.description == "Echo the text." and echo.read_only_hint is True
    assert await echo.execute({"text": "hi"}, ctx()) == f"{UNTRUSTED}\nhi"
    assert "[truncated: 50000 chars]" in await tool(s, "fk__big").execute({}, ctx())
    assert await tool(s, "fk__slow").execute({}, ctx()) == "fk__slow error: timed out after 0.5s"
    assert (await tool(s, "fk__boom").execute({}, ctx())).startswith("fk__boom error:")
    c = ctx()
    c.cancel.set()
    assert await tool(s, "fk__slow").execute({}, c) == "fk__slow error: cancelled"
    await s.shutdown()
    assert not p.tasks


async def test_allow_exclude_and_failing_server_skipped():
    p = McpPlugin([{"name": "a", "server": fake_server(), "tools": ["echo", "big"], "exclude": ["big"]},
                   {"name": "bad", "command": ["/no/such/binary"]}], timeout=5)
    s, errors = await started(p)
    assert [t.name for t in s.agent.tools if "__" in t.name] == ["a__echo"]
    assert len(errors) == 1 and "'bad'" in errors[0]["error"]
    await s.shutdown()


SERVER = textwrap.dedent("""
    import os
    from mcp.server.mcpserver import MCPServer
    s = MCPServer("stdio")

    @s.tool()
    def token() -> str:
        return os.environ["TOK"] + " " + str(os.getpid())
    s.run()
""")


async def test_stdio_via_build_plugins_env_and_shutdown(tmp_path, monkeypatch):
    (tmp_path / "srv.py").write_text(SERVER)
    monkeypatch.setenv("MY_SECRET", "s3cret")
    cfg = {"servers": {"st": {"command": [sys.executable, str(tmp_path / "srv.py")], "env": {"TOK": "${MY_SECRET}"}}}}
    s, errors = await started(build_plugins(["mcp"])[0], cfg)
    out = await tool(s, "st__token").execute({}, ctx())
    assert not errors and out.startswith(f"{UNTRUSTED}\ns3cret ")
    pid = int(out.split()[-1])
    await s.shutdown()
    with pytest.raises(ProcessLookupError):  # server process is gone
        for _ in range(50):
            os.kill(pid, 0)
            await asyncio.sleep(0.05)
