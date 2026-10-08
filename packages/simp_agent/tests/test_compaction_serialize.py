from simp_agent.ai import AssistantMessage, Model, TextContent, ToolCall, ToolResultMessage, UserMessage, from_dict, to_dict
from simp_agent.agent.compaction import CompactionEntry, CompactionSettings, compact

SUM = AssistantMessage([TextContent("SUM")])


def capture():
    seen = []

    async def stream(model, ctx):
        seen.append((model, ctx))
        yield {"type": "done", "message": SUM}

    return stream, seen


def turn(path, tool="write"):
    return [UserMessage(f"make {path}" + "x" * 8000),
            AssistantMessage([ToolCall("c", tool, {"path": path, "content": "C" * 19000})], stop_reason="tool_use"),
            ToolResultMessage("c", tool, "R" * 19000),
            AssistantMessage([TextContent("done")])]


SETTINGS = CompactionSettings(keep_recent_tokens=100)


async def test_request_is_one_serialized_user_message():
    stream, seen = capture()
    msgs = turn("a.html") + turn("b.html", "read") + [UserMessage("last" + "x" * 1000)]
    entry = await compact(msgs, Model(max_tokens=100000), stream, SETTINGS)
    model, ctx = seen[0]
    assert "Do NOT continue the conversation" in ctx.system_prompt
    assert len(ctx.messages) == 1 and ctx.messages[0].content.startswith("<conversation>\n[User]: make a.html")
    text = ctx.messages[0].content
    assert "C" * 501 not in text and "R" * 2001 not in text and "more characters truncated]" in text
    assert "## User Requests (chronological)" in text
    assert model.max_tokens == int(0.8 * SETTINGS.reserve_tokens)
    assert entry.modified_files == ["a.html"] and entry.read_files == ["b.html"]
    assert entry.summary.endswith("<read-files>\nb.html\n</read-files>\n\n<modified-files>\na.html\n</modified-files>")


async def test_repeated_compaction_keeps_file_lists():
    stream, seen = capture()
    msgs = turn("a.html") + [UserMessage("next")]
    msgs.append(await compact(msgs, Model(), stream, SETTINGS))
    msgs += turn("b.html") + [UserMessage("again" + "x" * 1000)]
    entry = await compact(msgs, Model(), stream, SETTINGS)
    assert entry.modified_files == ["a.html", "b.html"]
    assert "<previous-summary>" in seen[1][1].messages[0].content
    assert "KEEP every item" in seen[1][1].messages[0].content and "may remove" not in seen[1][1].messages[0].content


def test_entry_roundtrip_and_old_format():
    e = CompactionEntry("s", 3, ["r"], ["m"])
    assert from_dict(to_dict(e)) == e
    assert from_dict({"role": "compaction", "summary": "s", "first_kept_index": 3}).read_files == []
