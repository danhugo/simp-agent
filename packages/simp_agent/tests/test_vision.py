"""Pictures: the model sees them during the run only; history keeps text; `read` of an image attaches it."""
from __future__ import annotations

import base64

from simp_agent.agent import LoopConfig, agent_loop
from simp_agent.agent.env import LocalEnv
from simp_agent.ai import AssistantMessage, Model, TextContent, ToolCall, UserMessage
from simp_agent.ai.providers.openai_completions import to_openai
from simp_agent.coding.tools import make_tools
from simp_agent.testing import FakeProvider

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
DONE = AssistantMessage([TextContent("a cat")])


def read_call(path):
    return AssistantMessage([ToolCall("r1", "read", {"path": path})], stop_reason="tool_use")


async def run(tmp_path, replies, vision=True, images=()):
    (tmp_path / "cat.png").write_bytes(PNG)
    fake = FakeProvider(*replies)
    history = []
    cfg = LoopConfig(Model(vision=vision), make_tools(), stream_fn=fake, env=LocalEnv(), cwd=str(tmp_path), images=list(images))
    await agent_loop("sys", history, [UserMessage("what is this? [Attached files in the workspace: cat.png]")], cfg)
    return fake, history


async def test_attached_picture_rides_the_first_call_only_and_not_history(tmp_path):
    url = "data:image/png;base64," + base64.b64encode(PNG).decode()
    fake, history = await run(tmp_path, [read_call("notes.txt"), DONE], images=[("cat.png", url)])
    assert fake.messages[0][-1].images == [url] and "cat.png" in fake.messages[0][-1].content
    assert not any(getattr(m, "images", None) for m in fake.messages[1])  # sent once, then dropped
    assert not any(getattr(m, "images", None) for m in history)  # history: text only


async def test_read_of_an_image_attaches_it_for_the_next_call(tmp_path):
    fake, history = await run(tmp_path, [read_call("cat.png"), DONE])
    assert not any(getattr(m, "images", None) for m in fake.messages[0])
    assert fake.messages[1][-1].images[0].startswith("data:image/png;base64,")
    result = next(m for m in history if m.role == "tool_result")
    assert "attached below" in result.content and "base64" not in result.content  # no image bytes as text


async def test_read_again_after_a_rebuild_shows_the_new_picture(tmp_path):
    def rebuild(_):  # the file changes between the two reads
        (tmp_path / "cat.png").write_bytes(PNG + b"v2")
        return read_call("cat.png")
    fake = FakeProvider(read_call("cat.png"), rebuild, DONE)
    (tmp_path / "cat.png").write_bytes(PNG)
    cfg = LoopConfig(Model(vision=True), make_tools(), stream_fn=fake, env=LocalEnv(), cwd=str(tmp_path))
    await agent_loop("sys", [], [UserMessage("look")], cfg)
    first, second = fake.messages[1][-1].images[0], fake.messages[2][-1].images[0]
    assert first != second and len(fake.messages[2][-1].images) == 1


async def test_model_without_vision_gets_a_note(tmp_path):
    fake, history = await run(tmp_path, [read_call("cat.png"), DONE], vision=False)
    assert "cannot view images" in next(m for m in history if m.role == "tool_result").content
    assert not any(getattr(m, "images", None) for sent in fake.messages for m in sent)


def test_openai_request_puts_the_picture_after_tool_results():
    msgs = to_openai("sys", [UserMessage("look", images=["data:image/png;base64,AAAA"])])
    assert msgs[-1]["content"][1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
