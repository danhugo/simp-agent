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


class Helper:
    def __init__(self, reply="## cat.png\na cat"):
        self.calls, self.reply = [], reply

    async def __call__(self, system, text, images):
        self.calls.append((text, images))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


async def read_with(tmp_path, args, helper):
    (tmp_path / "cat.png").write_bytes(PNG)
    (tmp_path / "dog.png").write_bytes(PNG + b"dog")
    fake = FakeProvider(AssistantMessage([ToolCall("r1", "read", args)], stop_reason="tool_use"), DONE)
    history = []
    cfg = LoopConfig(Model(vision=True), make_tools(), stream_fn=fake, env=LocalEnv(), cwd=str(tmp_path),
                     tool_state={"look": helper} if helper else {})
    await agent_loop("sys", history, [UserMessage("look")], cfg)
    assert not any(getattr(m, "images", None) for sent in fake.messages for m in sent)  # never in the chat
    return next(m for m in history if m.role == "tool_result").content


async def test_read_images_one_helper_call_with_prompt(tmp_path):
    h = Helper("## cat.png\nA\n## dog.png\nB")
    out = await read_with(tmp_path, {"paths": ["cat.png", "dog.png"], "prompt": "colors?"}, h)
    assert out == "## cat.png\nA\n## dog.png\nB" and len(h.calls) == 1
    text, images = h.calls[0]
    assert "1) cat.png, 2) dog.png" in text and "Question: colors?" in text and len(images) == 2


async def test_read_image_default_question_and_fresh_file(tmp_path):
    h = Helper()
    await read_with(tmp_path, {"path": "cat.png"}, h)
    assert "Describe each picture" in h.calls[0][0]


async def test_read_image_errors_are_one_line(tmp_path):
    out = await read_with(tmp_path, {"paths": ["cat.png", "gone.png"]}, Helper(RuntimeError("refused")))
    assert out.startswith("Skipped gone.png:") and out.endswith("Could not view cat.png: refused")
    assert "no model here can view images" in await read_with(tmp_path, {"path": "cat.png"}, None)


async def test_paths_take_images_only(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    assert "images only" in await read_with(tmp_path, {"paths": ["cat.png", "a.txt"]}, Helper())


def test_openai_request_puts_the_picture_after_tool_results():
    msgs = to_openai("sys", [UserMessage("look", images=["data:image/png;base64,AAAA"])])
    assert msgs[-1]["content"][1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
