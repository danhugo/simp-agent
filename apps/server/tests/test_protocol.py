import asyncio
import json
import shutil
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from simp_server import protocol as p
from simp_server.fake import Hub, create_app
from simp_server.gen_protocol import OUT, generate


def test_round_trip_every_event_and_command():
    evs = [p.UserMessage(seq=1, text="hi"), p.AssistantMessage(seq=2, msg_id="m1", text="x",
           tool_calls=[p.ToolCall(id="c", name="bash", arguments={"command": "ls"})]),
           p.ToolResult(seq=3, call_id="c", tool="bash", content="ok"),
           p.ApprovalRequest(seq=4, call_id="c", tool="bash", args={}), p.ApprovalResolved(seq=5, call_id="c", decision="aborted"),
           p.RunState(seq=6, state="idle"), p.Compaction(seq=7, summary="s", tokens_before=9, tokens_after=1),
           p.Notice(seq=8, text="n"), p.TextDelta(msg_id="m", offset=0, delta="a"),
           p.ThinkingDelta(msg_id="m", offset=0, delta="a"), p.ToolOutput(call_id="c", offset=0, delta="a"),
           p.Snapshot(last_seq=8, run_state="running", in_flight=p.InFlight(msg_id="m", text="ab"))]
    for e in evs:
        assert p.server_event.validate_json(e.model_dump_json()) == e
    for c in [p.Prompt(text="a"), p.Steer(text="a"), p.FollowUp(text="a"), p.Abort(), p.Approve(call_id="c", decision="always")]:
        assert p.command.validate_json(c.model_dump_json()) == c
    with pytest.raises(ValueError):
        p.command.validate_python({"type": "approve", "call_id": "c", "decision": "maybe"})


def test_hello_and_state_machine():
    assert isinstance(p.check_hello(p.Hello(protocol_version=1)), p.Hello)
    assert isinstance(p.check_hello(p.Hello(protocol_version=2)), p.HelloError)
    p.check_transition("waiting_approval", "aborting")
    with pytest.raises(ValueError):
        p.check_transition("idle", "waiting_approval")


@pytest.mark.skipif(not shutil.which("npx"), reason="needs node")
def test_no_ts_drift():
    assert OUT.read_text() == generate(), "run: uv run python -m simp_server.gen_protocol"


async def wait_for(cond, timeout=5):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end
        await asyncio.sleep(0.001)


async def test_full_replay_with_approval_validates():
    h = Hub("s", delay=0)
    first, q = h.subscribe(0)
    assert first[-1]["type"] == "snapshot"
    h.command(p.Prompt(text="list files"))
    await wait_for(lambda: h.pending)
    h.command(p.Approve(call_id="call_1", decision="allow"))
    await wait_for(lambda: h.state == "idle" and h.task.done())
    seen = [q.get_nowait() for _ in range(q.qsize())]
    for e in seen:
        p.server_event.validate_python(e)
    states = [e["state"] for e in seen if e["type"] == "run_state"]
    assert states == ["running", "waiting_approval", "running", "idle"]
    assert [e["seq"] for e in h.log] == list(range(1, len(h.log) + 1))
    assert h.log[-2]["type"] == "assistant_message" and h.log[-2]["text"].startswith("There are")


async def test_reconnect_mid_delta_gets_full_in_flight_text():
    h = Hub("s", delay=0.002)
    h.command(p.Prompt(text="go"))
    await wait_for(lambda: len(h.inflight.text) >= 8)  # in the middle of the first text stream
    first, q = h.subscribe(after=1)  # client had seen only user_message
    snap = first[-1]
    assert [e["seq"] for e in first[:-1]] == list(range(2, snap["last_seq"] + 1))
    text = snap["in_flight"]["text"]
    assert snap["in_flight"]["thinking"].startswith("The user wants") and 0 < len(text)
    await wait_for(lambda: h.pending)
    for e in [q.get_nowait() for _ in range(q.qsize())]:
        if e["type"] == "text_delta":
            assert e["offset"] == len(text)
            text += e["delta"]
    assert text == "Let me look at the directory."


async def test_abort_settles_pending_approval():
    h = Hub("s", delay=0)
    h.command(p.Prompt(text="go"))
    h.command(p.FollowUp(text="later"))  # busy -> queued
    await wait_for(lambda: h.pending)
    h.command(p.Abort())
    await wait_for(lambda: h.task.done())
    tail = [(e["type"], e.get("decision") or e.get("state")) for e in h.log[-4:]]
    assert tail == [("run_state", "aborting"), ("approval_resolved", "aborted"), ("run_state", "idle"), ("notice", None)]
    assert h.state == "idle" and not h.queued and h.pending is None


def test_http_api_and_sse_resume():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    server = uvicorn.Server(uvicorn.Config(create_app(delay=0), port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(500):
            try:
                httpx.get(base + "/api/sessions")
                break
            except httpx.ConnectError:
                time.sleep(0.01)
        assert httpx.post(base + "/api/hello", json={"protocol_version": 9}).status_code == 400
        sid = httpx.post(base + "/api/sessions").json()["id"]
        assert httpx.post(f"{base}/api/sessions/{sid}/commands", json={"type": "nope"}).status_code == 422
        httpx.post(f"{base}/api/sessions/{sid}/commands", json={"type": "prompt", "text": "hi"})
        with httpx.stream("GET", f"{base}/api/sessions/{sid}/events", headers={"Last-Event-ID": "1"}) as r:
            frames = []
            for line in r.iter_lines():
                if line.startswith("data: "):
                    frames.append(json.loads(line[6:]))
                    if frames[-1]["type"] == "snapshot":
                        break
        assert frames[0]["seq"] == 2 and frames[-1]["type"] == "snapshot"
    finally:
        server.should_exit = True
