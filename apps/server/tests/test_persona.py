import httpx
from simp_agent.testing import FakeProvider

from simp_server import persona

from .test_budget import make, usage_reply

HAT = "<code>\nreturn null;\n</code>"


def test_parse_and_prompts():
    assert persona.parse(HAT) == "return null;"
    assert persona.parse("here:\n```js\nreturn 1;\n```") == "return 1;"
    assert "TOP" in persona.system("hat") and "BOTTOM" in persona.system("bottom")
    assert "paint(lon, lat, D)" in persona.system("face")
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
    await mgr.store.close()


async def test_outfit_collection(tmp_path):
    app, mgr, user, token, run = await make(tmp_path, FakeProvider())
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        assert (await c.post("/api/outfits", headers=h, json={"name": "x"})).status_code == 400  # empty
        oid = (await c.post("/api/outfits", headers=h, json={"name": "Wizard", "hat": "return null;"})).json()["id"]
        assert [o["name"] for o in (await c.get("/api/outfits", headers=h)).json()] == ["Wizard"]
        fid = (await c.post("/api/outfits", headers=h, json={"kind": "face", "name": "Paint", "face": "return null;", "hat": "x"})).json()["id"]
        f = next(o for o in (await c.get("/api/outfits", headers=h)).json() if o["id"] == fid)
        assert (f["kind"], f["face"], f["hat"]) == ("face", "return null;", "")  # a piece keeps only its own slot
        await c.delete(f"/api/outfits/{fid}", headers=h)
        assert (await c.delete(f"/api/outfits/{oid}", headers=h)).json() == {"ok": True}
        assert (await c.delete(f"/api/outfits/{oid}", headers=h)).status_code == 404
        assert (await c.get("/api/outfits", headers=h)).json() == []
        # a single piece keeps only its own slot
        await c.post("/api/outfits", headers=h, json={"kind": "hat", "name": "Cap", "hat": "H", "bottom": "B"})
        assert (await c.post("/api/outfits", headers=h, json={"kind": "bottom", "hat": "H"})).status_code == 400
        [cap] = (await c.get("/api/outfits", headers=h)).json()
        assert (cap["kind"], cap["hat"], cap["bottom"]) == ("hat", "H", "")
    await mgr.store.close()


async def test_collection_holds_ten_per_kind(tmp_path):
    app, mgr, user, token, run = await make(tmp_path, FakeProvider())
    h = {"Authorization": f"Bearer {token}"}
    piece = {"kind": "hat", "name": "h", "description": "", "hat": "return null;", "bottom": ""}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        for _ in range(10):
            assert (await c.post("/api/outfits", headers=h, json=piece)).status_code == 200
        r = await c.post("/api/outfits", headers=h, json=piece)
        assert r.status_code == 400 and "full" in r.text
        # the limit is per kind: hats being full does not block a bottom
        bottom = {**piece, "kind": "bottom", "hat": "", "bottom": "return null;"}
        assert (await c.post("/api/outfits", headers=h, json=bottom)).status_code == 200
    await mgr.store.close()
