import asyncio

from simp_agent.ai import Model
from simp_agent.plugins import FileMemoryStore, Memory, build_plugins
from simp_agent.session import AgentSession


def run_tool(s, name, **args):
    tool = next(t for t in s.agent.tools if t.name == name)
    return asyncio.run(tool.execute(args, None))


def started(plugin, **cfg):
    s = AgentSession(Model(), [], system_prompt="s", plugins=[plugin], plugin_config={"memory": cfg})
    asyncio.run(s.start())
    return s


def test_file_store_round_trip(tmp_path):
    st = FileMemoryStore(tmp_path)
    a = st.save("User likes Python", "global")
    st.save("Run tests with uv", "agent")
    again = FileMemoryStore(tmp_path)  # fresh instance reads the files
    assert [i["content"] for i in again.search("python")] == ["User likes Python"]
    assert again.search("uv", scope="global") == []
    assert len(again.search("uv", scope="agent")) == 1
    assert again.delete(a) and not again.delete(a)
    assert again.search("python") == []


def test_load_respects_char_limit(tmp_path):
    st = FileMemoryStore(tmp_path, max_chars=30)
    st.save("old " * 5, "agent")
    st.save("new fact", "global")
    assert st.load() == "- [global] new fact"


def test_plugin_tools_and_prompt(tmp_path):
    (p,) = build_plugins(["memory"])
    s = started(p, dir=str(tmp_path))
    assert "saved" in run_tool(s, "memory_save", content="User name is Hung", scope="global")
    prompt = asyncio.run(s._build_prompt())
    assert "NEVER save secrets" in prompt and '"global"' in prompt and "- [global] User name is Hung" in prompt
    found = run_tool(s, "memory_search", query="hung", scope="global")
    item_id = __import__("json").loads(found)[0]["id"]
    assert run_tool(s, "memory_delete", id=item_id) == "deleted"
    assert "User name is Hung" not in asyncio.run(s._build_prompt())


class FakeStore:
    def __init__(self): self.saved = []
    def load(self): return "CORE"
    def search(self, query, scope=None, limit=10): return [{"id": "1", "scope": "agent", "content": query, "created": 0}]
    def save(self, content, scope): self.saved.append((content, scope)); return "x"
    def delete(self, id): return True


def test_works_with_fake_store():
    store = FakeStore()
    s = started(Memory(store))
    run_tool(s, "memory_save", content="lesson", scope="agent")
    assert store.saved == [("lesson", "agent")]
    assert "CORE" in asyncio.run(s._build_prompt())
