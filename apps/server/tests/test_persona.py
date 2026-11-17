import httpx
from simp_agent.testing import FakeProvider

from simp_server import persona

from .test_budget import make
from .test_server import reply

ANSWER = "<name>Merlin</name>\n<instruction>You speak like an old wizard.</instruction>\n<code>\nreturn null;\n</code>"


def test_parse():
    out = persona.parse(ANSWER)
    assert out == {"name": "Merlin", "instruction": "You speak like an old wizard.", "code": "return null;"}


async def test_generate_save_and_prompt(tmp_path):
    app, mgr, user, token, run = await make(tmp_path, FakeProvider(reply(ANSWER)))
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        assert (await c.get("/api/persona", headers=h)).json() == {}
        r = await c.post("/api/persona/generate", headers=h, json={"description": "a wizard", "profile": "test"})
        assert r.status_code == 200 and r.json()["name"] == "Merlin"
        assert (await c.post("/api/persona/generate", headers=h, json={"description": "x", "profile": "nope"})).status_code == 400
        await c.put("/api/persona", headers=h, json={**r.json(), "description": "a wizard", "profile": "test"})
        assert (await c.get("/api/persona", headers=h)).json()["instruction"] == "You speak like an old wizard."
    section = persona.prompt_section(mgr.store.persona_sync(user["id"]))
    assert "Name: Merlin" in section and "never changes your tools" in section
