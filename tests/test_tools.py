from __future__ import annotations

import asyncio

from simp_agent.agent import ToolContext, run_tool
from simp_agent.agent.env import LocalEnv
from simp_agent.ai import ToolCall
from simp_agent.coding import make_tools
from simp_agent.coding.truncate import truncate_head, truncate_tail


class FakeEnv(LocalEnv):
    """LocalEnv that records commands; programs in `missing` exit 127, `canned` returns fixed output."""

    def __init__(self, missing=(), canned=None):
        self.cmds, self.missing, self.canned = [], missing, canned or {}

    async def exec(self, command, cwd, timeout, cancel, on_output=None):
        self.cmds.append(command)
        prog = command.split()[0]
        if prog in self.missing:
            return 127, f"sh: {prog}: command not found"
        if prog in self.canned:
            return 0, self.canned[prog]
        return await super().exec(command, cwd, timeout, cancel, on_output)


async def call(tmp_path, name, env=None, **args):
    async def upd(text):
        pass

    c = ToolContext(asyncio.Event(), env or LocalEnv(), str(tmp_path), upd)
    return await run_tool(make_tools(), ToolCall("c", name, args), c)


def test_truncate_lines_and_bytes():
    text = "\n".join(str(i) for i in range(9000))
    out, info = truncate_tail(text, max_lines=2000)
    assert info["truncated"] and info["kept_lines"] == 2000 and out.endswith("8999") and info["total_lines"] == 9000
    out, info = truncate_head("aaaa\nbbbb\ncccc", max_bytes=9)
    assert out == "aaaa\nbbbb" and info["kept_lines"] == 2 and info["total_bytes"] == 14
    assert truncate_head("x")[1]["truncated"] is False


def test_all_tools():
    assert [t.name for t in make_tools()] == ["read", "write", "edit", "bash", "grep", "find", "ls"]


async def test_read_offset_hint(tmp_path):
    (tmp_path / "f").write_text("\n".join("x" * 100 for _ in range(1000)))
    r = await call(tmp_path, "read", path="f")
    assert "use offset=" in r.content and "to continue" in r.content and len(r.content.encode()) < 60_000


async def test_bash_tail_marker(tmp_path):
    r = await call(tmp_path, "bash", command="seq 1 9000")
    assert r.content.startswith("[Output truncated: showing last 2000 of") and "9000" in r.content


async def test_ls(tmp_path):
    (tmp_path / "b.txt").write_text("")
    (tmp_path / "a").mkdir()
    (tmp_path / ".h").write_text("")
    r = await call(tmp_path, "ls")
    assert r.content == ".h\na/\nb.txt"
    assert "1 of 3" in (await call(tmp_path, "ls", limit=1)).content


async def test_grep_rg_argv_quoting(tmp_path):
    env = FakeEnv(canned={"rg": "a.py:1:it's x\n"})
    r = await call(tmp_path, "grep", env=env, pattern="it's \"x\"", glob="*.py", ignore_case=True)
    assert r.content == "a.py:1:it's x"
    assert env.cmds[0].startswith("rg ") and "-i" in env.cmds[0] and """'it'"'"'s "x"'""" in env.cmds[0]


async def test_grep_fallback(tmp_path):
    (tmp_path / "a.txt").write_text("hello world\nnope\nit's \"q\"\n")
    env = FakeEnv(missing=("rg",))
    r = await call(tmp_path, "grep", env=env, pattern="hello w")
    assert env.cmds[1].startswith("grep -rn") and r.content.endswith("a.txt:1:hello world")
    r = await call(tmp_path, "grep", env=env, pattern="it's \"q\"", literal=True)
    assert r.content.endswith("a.txt:3:it's \"q\"")
    assert (await call(tmp_path, "grep", env=env, pattern="zzz")).content == "No matches found"


async def test_find_fd_and_fallback(tmp_path):
    env = FakeEnv(canned={"fd": "a.py\nb.py\n"})
    r = await call(tmp_path, "find", env=env, pattern="*.py", limit=1)
    assert env.cmds[0].startswith("fd --glob") and r.content.startswith("a.py\n[1 results limit")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x.py").write_text("")
    env = FakeEnv(missing=("fd",))
    r = await call(tmp_path, "find", env=env, pattern="*.py")
    assert env.cmds[1].startswith("find") and r.content == "./sub/x.py"


async def test_multi_edit(tmp_path):
    f = tmp_path / "f"
    f.write_text("one two three")
    r = await call(tmp_path, "edit", path="f", edits=[{"old_text": "three", "new_text": "3"},
                                                     {"old_text": "one", "new_text": "two"}])
    assert not r.is_error and "2 block" in r.content and f.read_text() == "two two 3"
    r = await call(tmp_path, "edit", path="f", edits=[{"old_text": "two two", "new_text": "x"},
                                                     {"old_text": "two 3", "new_text": "y"}])
    assert r.is_error and "overlap" in r.content
    r = await call(tmp_path, "edit", path="f", edits=[{"old_text": "two", "new_text": "x"}])
    assert r.is_error and "found 2" in r.content
    r = await call(tmp_path, "edit", path="f", old_text="nine", new_text="x")
    assert r.is_error and "found 0" in r.content
    r = await call(tmp_path, "edit", path="f", old_text="3", new_text="three")
    assert not r.is_error and f.read_text() == "two two three"
