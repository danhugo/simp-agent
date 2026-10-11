import importlib.util
import json
from pathlib import Path

from simp_agent.ai import AssistantMessage, TextContent, ToolCall
from simp_agent.testing import FakeProvider

spec = importlib.util.spec_from_file_location("evals_run", Path(__file__).parent / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


async def test_read_answer_passes_with_fake_provider(tmp_path):
    fake = FakeProvider(
        AssistantMessage([ToolCall("c1", "read", {"path": "config.ini"})], stop_reason="tool_use",
                         usage={"input": 100, "output": 10}),
        AssistantMessage([TextContent("The port is 8473.")], usage={"input": 200, "output": 20}))
    profile = {"model": "fake", "price_in": 1.0, "price_out": 2.0}
    rows = await run.run_all("p", profile, {}, ["read_answer"], stream_fn=fake, out_dir=tmp_path)
    assert rows[0]["name"] == "read_answer" and rows[0]["passed"]
    assert rows[0]["turns"] == 2 and rows[0]["input"] == 300 and rows[0]["output"] == 30
    assert abs(rows[0]["cost"] - (300 * 1 + 30 * 2) / 1e6) < 1e-12
    data = json.loads(next(tmp_path.glob("*-p.json")).read_text())
    assert data["profile"] == "p" and data["model"] == "fake"
    assert set(data["tasks"][0]) >= {"name", "passed", "turns", "input", "output", "cost", "seconds"}
    assert data["total"]["passed"] == 1


def test_tasks_load():
    assert {t["name"] for t in run.load_tasks(None)} == {"fizzbuzz", "fix_bug", "refactor_rename", "read_answer"}
