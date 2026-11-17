import httpx
from simp_agent.testing import FakeProvider

from simp_server import persona

from .test_budget import make, usage_reply

HAT = "<code>\nreturn null;\n</code>"


def test_parse_and_prompts():
    assert persona.parse(HAT) == "return null;"
    assert persona.parse("here:\n```js\nreturn 1;\n```") == "return 1;"
    assert "HAT" in persona.system("hat") and "BOTTOM" in persona.system("bottom")
    msg = persona.user_message("a wizard", other="HATCODE", code="BAD", error="covers the eyes")
    assert "HATCODE" in msg and "covers the eyes" in msg and "BAD" in msg


async def test_generate_retries_save_and_prompt(tmp_path):
    # first answer has no code: the server asks again once
    app, mgr, user, token, run = await make(tmp_path, FakeProvider(usage_reply("sorry, prose", inp=0), usage_reply(HAT, inp=0)))  # free: the test profile costs $1/token
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        assert (await c.get("/api/persona", headers=h)).json() == {}
        r = await c.post("/api/persona/generate", headers=h, json={"description": "a wizard", "profile": "test", "slot": "hat"})
        assert r.status_code == 200 and r.json() == {"code": "return null;"}, r.text
        bad = {"description": "x", "profile": "test", "slot": "shoes"}
        assert (await c.post("/api/persona/generate", headers=h, json=bad)).status_code == 422
        await c.put("/api/persona", headers=h, json={"name": "Merlin", "instruction": "You speak like an old wizard.",
                                                     "hat": "return null;", "profile": "test"})
        assert (await c.get("/api/persona", headers=h)).json()["hat"] == "return null;"
    section = persona.prompt_section(mgr.store.persona_sync(user["id"]))
    assert "Name: Merlin" in section and "never changes your tools" in section
