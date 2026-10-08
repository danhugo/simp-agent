"""Rendering: components, replay == live, session list, print mode lines, and a real pty + pyte screen test."""

from __future__ import annotations

import fcntl
import io
import os
import pty
import select
import struct
import sys
import termios
import time

import pyte

from simp_agent import cli
from simp_agent.ai import AssistantMessage, CompactionEntry, TextContent, ThinkingContent, ToolCall, ToolResultMessage, UserMessage
from simp_agent.cli.components import COMPACTED, AssistantMsg, Chat, ToolCall as ToolComp

ANSWER = "line one alpha\nline two beta\nline three gamma"


def plain(lines):
    import re
    return "\n".join(re.sub(r"\x1b\[[0-9;]*m", "", ln) for ln in lines)


def test_components_render():
    m = AssistantMessage([ThinkingContent("hmm"), TextContent("# Title\n\n**bold** text")])
    out = AssistantMsg.from_message(m).render(80)
    assert "hmm" in plain(out) and "Title" in plain(out) and "**" not in plain(out)  # markdown rendered
    assert "\x1b[2" in out[0]  # thinking is dim
    assert "hmm" not in plain(AssistantMsg.from_message(m, show_thinking=False).render(80))
    t = ToolComp(ToolCall("c", "bash", {"command": "ls"}))
    t.result = ToolResultMessage("c", "bash", "boom", is_error=True)
    assert plain(t.render(80)) == "> bash: ls\n  ! boom" and "\x1b[31m" in t.render(80)[1]


MSGS = [UserMessage("hi"), AssistantMessage([TextContent("a *b*"), ToolCall("c", "read", {"path": "x"})], stop_reason="tool_use"),
        ToolResultMessage("c", "read", "data"), CompactionEntry("s", 0), AssistantMessage([TextContent("done")])]


def renders(feed):
    out = []
    chat = Chat(lambda c: out.append(c.render(80)))
    feed(chat)
    return out


def test_replay_equals_live():
    def live(chat):
        for e in [{"type": "message_end", "message": MSGS[0]}, {"type": "message_update", "event": {"type": "text_delta", "delta": "a"}},
                  {"type": "tool_execution_start", "call": MSGS[1].content[1]}] + [{"type": "message_end", "message": m} for m in MSGS[1:]]:
            chat.on_event(e)
        assert not chat.live

    replayed = renders(lambda c: c.replay(MSGS))
    assert renders(live) == replayed and COMPACTED in plain(replayed[3])


def test_list_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SESSIONS", tmp_path)
    d = cli.session_dir("/p")
    for i, name in enumerate(["old", "new"]):
        s = cli.JsonlStore(d / f"{name}.jsonl")
        s.append(UserMessage(f"{name} first\nsecond"))
        s.append(AssistantMessage([TextContent("x")]))
        os.utime(d / f"{name}.jsonl", (1000 + i, 1000 + i))
    got = cli.list_sessions("/p")
    assert [(s["id"], s["first"], s["count"]) for s in got] == [("new", "new first", 2), ("old", "old first", 2)]


def test_print_mode_full_lines_no_ansi():
    out = io.StringIO()
    p = cli.LinePrinter(out=out)
    for d in ["li", "ne 1\nline", " 2"]:
        p({"type": "message_update", "event": {"type": "text_delta", "delta": d}})
        assert "\x1b" not in out.getvalue()
    assert out.getvalue() == "line 1\n"
    p({"type": "message_end", "message": AssistantMessage([TextContent("")])})
    assert out.getvalue() == "line 1\nline 2\n"


# ---- pty + pyte ------------------------------------------------------------------------------------------------------

CHILD = """
import argparse, asyncio, sys
from simp_agent import cli
from simp_agent.ai import AssistantMessage, Model, TextContent
from simp_agent.cli.repl import Repl
cli.SESSIONS = cli.Path(sys.argv[1])
ANSWER = %r

async def stream(model, ctx, api_key=None):
    for ch in ANSWER:
        await asyncio.sleep(0.02)
        yield {"type": "text_delta", "delta": ch}
    yield {"type": "done", "message": AssistantMessage([TextContent(ANSWER)])}

a = argparse.Namespace(resume=None, cont=False, pick=False, yes=True, thinking=True, bash_max_timeout_s=None)
asyncio.run(Repl(Model(), a, stream_fn=stream).run())
""" % ANSWER


def test_pty_streaming_screen(tmp_path):
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"  # fresh interpreter: no pytest state in the child
        os.execv(sys.executable, [sys.executable, "-c", CHILD, str(tmp_path)])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 20, 70, 0, 0))
    scr = pyte.Screen(70, 20)
    st = pyte.ByteStream(scr)

    def pump(t):
        end = time.time() + t
        while time.time() < end:
            if select.select([fd], [], [], 0.05)[0]:
                try:
                    d = os.read(fd, 65536)
                except OSError:
                    return
                st.feed(d)
                if b"\x1b[6n" in d:
                    os.write(fd, b"\x1b[%d;%dR" % (scr.cursor.y + 1, scr.cursor.x + 1))

    try:
        pump(1.5)
        os.write(fd, b"hi\r")
        pump(0.5)  # ~25 of 46 chars streamed
        mid = "\n".join(scr.display)
        print(mid)
        assert "line one alpha" in mid and "line three gamma" not in mid
        pump(2.5)
        end = "\n".join(scr.display)
        print(end)
        for ln in ANSWER.splitlines():
            assert ln in end
    finally:
        os.write(fd, b"\x04")
        pump(0.5)
        os.waitpid(pid, 0)
