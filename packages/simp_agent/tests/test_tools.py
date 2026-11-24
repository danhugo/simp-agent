from __future__ import annotations

import asyncio

from simp_agent.testing import FakeEnv
from simp_agent.agent import ToolContext, run_tool
from simp_agent.agent.env import LocalEnv
from simp_agent.ai import ToolCall
from simp_agent.coding import make_tools
from simp_agent.coding.truncate import truncate_head, truncate_tail


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
    assert r.is_error and "matches 2 places" in r.content
    r = await call(tmp_path, "edit", path="f", old_text="nine", new_text="x")
    assert r.is_error and "not found" in r.content
    r = await call(tmp_path, "edit", path="f", old_text="3", new_text="three")
    assert not r.is_error and f.read_text() == "two two three"


async def test_edit_fails_when_file_changed_since_read(tmp_path):
    async def upd(text):
        pass

    c = ToolContext(asyncio.Event(), LocalEnv(), str(tmp_path), upd)
    run = lambda name, **a: run_tool(make_tools(), ToolCall("c", name, a), c)  # noqa: E731
    f = tmp_path / "f.txt"
    f.write_text("one\ntwo\n")
    assert not (await run("edit", path="f.txt", old_text="one", new_text="ONE")).is_error  # no prior read: allowed
    assert not (await run("read", path="f.txt")).is_error
    assert not (await run("edit", path="f.txt", old_text="two", new_text="TWO")).is_error  # own edit keeps the hash
    f.write_text("ONE\nTWO\nthree\n")  # changed by someone else (another session, a command)
    r = await run("edit", path="f.txt", old_text="three", new_text="3")
    assert r.is_error and "read it again" in r.content and f.read_text() == "ONE\nTWO\nthree\n"
    await run("read", path="f.txt")
    assert not (await run("edit", path="f.txt", old_text="three", new_text="3")).is_error


async def _ctx_call(tmp_path, ctx, name, **args):
    return await run_tool(make_tools(), ToolCall("c", name, args), ctx)


def _ctx(tmp_path):
    async def upd(text):
        pass
    return ToolContext(asyncio.Event(), LocalEnv(), str(tmp_path), upd)


async def test_read_same_lines_unchanged_gives_note_then_blocks(tmp_path):
    (tmp_path / "f").write_text("a\nb\n")
    c = _ctx(tmp_path)
    assert "1\ta" in (await _ctx_call(tmp_path, c, "read", path="f")).content
    r2 = await _ctx_call(tmp_path, c, "read", path="f")
    assert "has not changed" in r2.content and "1\ta" not in r2.content and "loop" not in r2.content
    r3 = await _ctx_call(tmp_path, c, "read", path="f")
    assert "loop" in r3.content
    r4 = await _ctx_call(tmp_path, c, "read", path="f")
    assert r4.is_error and "BLOCKED" in r4.content


async def test_read_full_again_after_change_or_other_range(tmp_path):
    (tmp_path / "f").write_text("a\nb\n")
    c = _ctx(tmp_path)
    await _ctx_call(tmp_path, c, "read", path="f")
    assert "2\tb" in (await _ctx_call(tmp_path, c, "read", path="f", offset=2)).content
    (tmp_path / "f").write_text("a\nc\n")
    assert "2\tc" in (await _ctx_call(tmp_path, c, "read", path="f")).content
    c.state.pop("reads")  # what compaction does
    assert "1\ta" in (await _ctx_call(tmp_path, c, "read", path="f")).content


async def test_edit_errors_steer_and_nudge_after_three(tmp_path):
    (tmp_path / "f").write_text("x\ny\nx\n")
    c = _ctx(tmp_path)
    r = await _ctx_call(tmp_path, c, "edit", path="f", old_text="x", new_text="z")
    assert r.is_error and "lines 1, 3" in r.content and "unique" in r.content
    r = await _ctx_call(tmp_path, c, "edit", path="f", old_text="nope", new_text="z")
    assert r.is_error and "not found" in r.content and "failed edit" not in r.content
    r = await _ctx_call(tmp_path, c, "edit", path="f", old_text="nope", new_text="z")
    assert "failed edit #3" in r.content
    assert not (await _ctx_call(tmp_path, c, "edit", path="f", old_text="y", new_text="z")).is_error
    r = await _ctx_call(tmp_path, c, "edit", path="f", old_text="nope", new_text="z")
    assert "failed edit" not in r.content  # success reset the count
